from io import BytesIO
import json
from pathlib import Path
import sqlite3

import fitz
import pytest

from app import create_app
from physics import document_metadata, extract
from paper_layout import PaperLayout
from paper_numbering import erase_source_numbers


@pytest.fixture
def bank(tmp_path):
    client=create_app(tmp_path).test_client()
    saved={}
    for paper in (1,2,3):
        with fitz.open() as pdf:
            page=pdf.new_page()
            page.insert_text((50,45),f'Physics HL Paper {paper} 2024')
            page.insert_text((50,80),'Option A - Relativity')
            page.insert_text((50,120),f'1. Calculate the velocity of cart {paper}. [3]')
            doc=client.post('/api/documents',data=dict(file=(BytesIO(pdf.tobytes()),f'Physics_HL_Paper_{paper}_2024.pdf'),ocr_mode='off')).json
        assert doc['metadata']['paper']==f'Paper {paper}'
        question=doc['questions'][0]
        result=client.post('/api/questions',json=dict(question,document_id=doc['id'],syllabus='2025',topics=['A.1'],minutes=5))
        assert result.status_code==201,result.json
        saved[paper]=dict(result.json,document_id=doc['id'])
    return client,saved,tmp_path


def test_paper_three_filter_is_explicit_but_included_with_paper_two(bank):
    client,qs,_=bank
    assert {q['id'] for q in client.get('/api/questions?paper=Paper+2').json}=={qs[2]['id'],qs[3]['id']}
    assert [q['id'] for q in client.get('/api/questions?paper=Paper+3').json]==[qs[3]['id']]
    assert [q['id'] for q in client.get('/api/questions?paper=Paper+1').json]==[qs[1]['id']]
    for paper,expected in [('Paper 2',{qs[2]['id'],qs[3]['id']}),('Paper 3',{qs[3]['id']})]:
        options=dict(level='HL',syllabus='2025',paper=paper,minutes=10,topics=[],auto_select=True)
        plan=client.post('/api/papers/preview',json=options)
        assert plan.status_code==200,plan.json
        assert set(plan.json['selected_question_ids'])==expected
        generated=client.post('/api/papers',json=options)
        assert generated.status_code==201,generated.json
        assert set(generated.json['question_ids'])==expected
    assert qs[3]['paper']=='Paper 3'


def test_paper_three_forms_a_separate_render_group_and_option_labels_are_removed(bank):
    client,qs,_=bank
    result=client.post('/api/papers',json=dict(level='HL',syllabus='2025',minutes=15,topics=[],question_ids=[qs[3]['id'],qs[2]['id'],qs[1]['id']]))
    assert result.status_code==201,result.json
    assert result.json['question_ids']==[qs[1]['id'],qs[2]['id'],qs[3]['id']]
    response=client.get(f"/api/papers/{result.json['id']}/download")
    with fitz.open(stream=response.data,filetype='pdf') as pdf:
        assert len(pdf)==4
        for index in (1,2,3):
            text=pdf[index].get_text()
            assert f'cart {index}' in text and f'Question {index}' in text
            assert 'Option A' not in text


def test_paper_three_unknown_records_are_upgraded_without_changing_teacher_overrides(bank):
    client,qs,root=bank
    doc_id=qs[3]['document_id']
    with sqlite3.connect(root/'bank.sqlite3') as conn:
        data=json.loads(conn.execute('SELECT data FROM documents WHERE id=?',(doc_id,)).fetchone()[0])
        data['metadata']['paper']='Unknown'
        data['questions'][0]['paper']='Unknown'
        conn.execute('UPDATE documents SET data=? WHERE id=?',(json.dumps(data),doc_id))
        q=json.loads(conn.execute('SELECT data FROM questions WHERE id=?',(qs[3]['id'],)).fetchone()[0])
        q['paper']='Unknown'
        conn.execute('UPDATE questions SET data=? WHERE id=?',(json.dumps(q),qs[3]['id']))
    restarted=create_app(root).test_client()
    recovered={q['id']:q for q in restarted.get('/api/questions').json}
    assert recovered[qs[3]['id']]['paper']=='Paper 3'
    assert recovered[qs[2]['id']]['paper']=='Paper 2'
    assert restarted.get('/api/documents/'+doc_id).json['metadata']['paper']=='Paper 3'


@pytest.mark.parametrize('filename,paper', [('Physics_HL_Paper_3_2024.pdf','Paper 3'),('Physics Paper 3 astrophysics 2024.pdf','Paper 3'),('Physics_Paper_1A_HL_2025.pdf','Paper 1A'),('Physics Paper 2 atomic physics 2025.pdf','Paper 2')])
def test_metadata_distinguishes_paper_number_from_option_title(filename,paper):
    assert document_metadata('',filename)['paper']==paper


def test_real_2020_paper_three_retains_all_questions_and_removes_option_residue():
    path=Path(__file__).resolve().parents[1]/'TEST SAMPLES'/'Physics_paper_3__HL.pdf'
    result=extract(path,path.name,ocr_mode='off')
    assert result['metadata']['paper']=='Paper 3' and result['metadata']['year']==2020
    assert [q['number'] for q in result['questions']]==list(range(1,25))
    assert not any('option' in q['text'].lower() for q in result['questions'])
    with fitz.open() as output:
        layout=PaperLayout(output)
        for number,source_number in enumerate((4,12,22),1):
            question=dict(result['questions'][source_number-1],filename=path.name,document_id='2020-paper-three')
            with fitz.open(path) as source:
                report=erase_source_numbers(source,question,{})
                assert report['erased_administrative']>0
                assert layout.add_question(source,question,number)>0
        text='\n'.join(page.get_text() for page in output)
        assert 'Option ' not in text and 'End of Option' not in text
        assert all(f'Question {number}' in text for number in (1,2,3))
