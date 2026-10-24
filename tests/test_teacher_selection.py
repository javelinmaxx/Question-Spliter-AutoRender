from io import BytesIO
import json
import re
import sqlite3

import fitz
import pytest

from app import create_app
from analysis_storage import source_hash
from paper_numbering import erase_source_numbers
from test_workflow import upload, save
from test_subquestions import saved_parent, approve


@pytest.fixture
def bank(tmp_path):
    client=create_app(tmp_path).test_client()
    doc=upload(client)
    first=save(client,doc,minutes=7);second=save(client,doc,1,minutes=6)
    return client,tmp_path,doc,first,second


def test_preview_and_manual_selection_share_filters_and_preserve_order(bank):
    client,root,doc,first,second=bank
    options=dict(level='HL',minutes=20,topics=[])
    preview=client.post('/api/papers/preview',json=options)
    assert preview.status_code == 200 and len(preview.json['questions']) == 2
    assert 'Calculate the velocity' in next(q['text'] for q in preview.json['questions'] if q['id']==first['id'])
    selected=[second['id'],first['id']]
    generated=client.post('/api/papers',json=dict(options,question_ids=selected))
    assert generated.status_code == 201,generated.json
    assert generated.json['question_ids'] == selected
    assert [s['number'] for s in generated.json['selections']] == [1,2]
    assert [s['source_number'] for s in generated.json['selections']] == [2,1]
    assert 'Enable Fill paper' in generated.json['diagnostics']['summary']
    assert generated.json['numbering'][second['id']]['erased_labels'] == 1
    assert '1.' in fitz.open(root/'documents'/(doc['id']+'.pdf'))[0].get_text()


def test_picker_prefers_saved_ocr_and_falls_back_per_page_without_rerunning_it(bank, monkeypatch):
    client,root,doc,first,second=bank
    with sqlite3.connect(root/'bank.sqlite3') as conn:
        raw=conn.execute('SELECT data FROM documents WHERE id=?',(doc['id'],)).fetchone()[0]
        data=json.loads(raw)
        data['text_pages'][0]['lines']=[dict(line,text='OCR recognized: '+line['text'])
                                      for line in data['text_pages'][0]['native_lines']]
        conn.execute('UPDATE documents SET data=? WHERE id=?',(json.dumps(data),doc['id']))
    monkeypatch.setattr('physics.read_pages',lambda *args:pytest.fail('Picker must use saved recognition data'))
    result=client.post('/api/papers/preview',json=dict(level='HL',minutes=20,topics=[]))
    assert result.status_code==200,result.json
    by_id={q['id']:q for q in result.json['questions']}
    assert 'OCR recognized: 1.' in by_id[first['id']]['text']
    assert '(b) Explain the change in momentum' in by_id[first['id']]['text']
    assert 'resistance' not in by_id[first['id']]['text']
    assert 'Determine the resistance' in by_id[second['id']]['text']


def test_picker_recognition_text_matches_short_preview_parts(tmp_path):
    client=create_app(tmp_path).test_client()
    question=saved_parent(client)
    approve(client,question)
    options=dict(level='HL',minutes=20,topics=[])
    full=client.post('/api/papers/preview',json=dict(options,render_mode='full')).json['questions'][0]
    short=client.post('/api/papers/preview',json=dict(options,render_mode='short')).json['questions'][0]
    assert all(token in full['text'] for token in ('ALPHA_SPEED','BETA_ENERGY','GAMMA_UNIT'))
    assert 'ALPHA_SPEED' in short['text'] and 'BETA_ENERGY' in short['text']
    assert short['omitted_parts']==['c'] and 'GAMMA_UNIT' not in short['text']


def test_manual_over_budget_is_not_silently_reduced(bank):
    client,_,_,first,second=bank
    result=client.post('/api/papers',json=dict(level='HL',minutes=10,topics=[],question_ids=[first['id'],second['id']]))
    assert result.status_code == 400
    assert 'need at least 13' in result.json['error']
    assert client.post('/api/papers',json=dict(level='HL',minutes=10,topics=[],question_ids=[])).status_code == 400


def test_fill_paper_keeps_teacher_questions_and_adds_only_other_matching_questions(bank):
    client,_,doc,first,second=bank
    options=dict(level='HL',minutes=13,topics=[],question_ids=[first['id']])
    without=client.post('/api/papers',json=options)
    assert without.status_code == 201 and without.json['question_ids'] == [first['id']]
    filled=client.post('/api/papers',json=dict(options,fill_paper=True))
    assert filled.status_code == 201,filled.json
    assert filled.json['question_ids'] == [first['id'],second['id']]
    assert filled.json['filled_question_ids'] == [second['id']]
    assert filled.json['shortfall_minutes'] == 0
    assert [s['selection_source'] for s in filled.json['selections']] == ['teacher','filled']
    # Fill cannot use out-of-scope questions or repeat a selected question.
    topic_only=client.post('/api/papers',json=dict(options,topics=['A.2'],fill_paper=True))
    assert topic_only.json['question_ids'] == [first['id']]


def test_manual_selection_cannot_bypass_current_topic_or_sl_filters(bank):
    client,_,doc,first,second=bank
    result=client.post('/api/papers',json=dict(level='HL',minutes=20,topics=['B.5'],question_ids=[first['id']]))
    assert result.status_code == 400 and 'no longer fit' in result.json['error']
    assert client.post('/api/papers/preview',json=dict(level='SL',minutes=20,topics=['A.4'])).status_code == 400
    result=client.post('/api/papers/preview',json=dict(level='HL',minutes=20,topics=[],document_ids=[doc['id']]))
    assert len(result.json['questions']) == 2
    assert client.post('/api/papers/preview',json=dict(level='HL',minutes=20,topics=[],document_ids=['missing'])).status_code == 400


def test_manual_short_keeps_every_selected_parent_and_prerequisites(tmp_path):
    client=create_app(tmp_path).test_client()
    q=saved_parent(client);approve(client,q)
    result=client.post('/api/papers',json=dict(level='HL',minutes=5,topics=[],render_mode='short',question_ids=[q['id']]))
    assert result.status_code == 201,result.json
    assert result.json['selections'][0]['kept_parts'] == ['stem','a']
    assert result.json['selections'][0]['topics'] == ['A.1']


def test_source_parent_numbers_are_erased_but_body_numbers_and_part_labels_survive(tmp_path):
    client=create_app(tmp_path).test_client()
    with fitz.open() as pdf:
        page=pdf.new_page()
        page.insert_text((50,45),'Physics HL Paper 2 2025')
        page.insert_text((50,100),'23. Calculate the velocity after travelling 23 m. [3]')
        page.insert_text((65,150),'(a) Show all working and preserve this subquestion label.')
        raw=pdf.tobytes()
    uploaded=client.post('/api/documents',data=dict(file=(BytesIO(raw),'custom.pdf'),ocr_mode='off')).json
    value=dict(document_id=uploaded['id'],number=23,level='HL',year=2025,syllabus='2025',paper='Paper 2',
               topics=['A.1'],minutes=5,marks=3,difficulty='Unrated',regions=[dict(page=0,rect=[30,75,560,210])])
    saved=client.post('/api/questions',json=value)
    assert saved.status_code == 201,saved.json
    path=tmp_path/'documents'/(uploaded['id']+'.pdf');before=source_hash(path)
    image_before=(tmp_path/'images'/(saved.json['id']+'.png')).read_bytes()
    result=client.post('/api/papers',json=dict(level='HL',minutes=10,topics=[],question_ids=[saved.json['id']]))
    assert result.status_code == 201,result.json
    assert result.json['numbering'][saved.json['id']]['erased_labels'] == 1
    download=client.get(f"/api/papers/{result.json['id']}/download")
    with fitz.open(stream=download.data,filetype='pdf') as pdf:
        text='\n'.join(p.get_text() for p in pdf)
        assert 'Question 1' in text and '(a)' in text and '23 m' in text
        assert not re.search(r'(?m)^23\.',text)
    assert source_hash(path) == before
    assert (tmp_path/'images'/(saved.json['id']+'.png')).read_bytes() == image_before


def test_number_erasure_also_handles_scanned_question_markers(tmp_path):
    with fitz.open() as original:
        page=original.new_page();page.insert_text((50,100),'23. Calculate the velocity after travelling 23 m.',fontsize=14)
        page.insert_text((65,160),'(a) This subquestion must survive.',fontsize=14)
        image=page.get_pixmap(matrix=fitz.Matrix(2,2)).tobytes('png')
    with fitz.open() as scanned:
        page=scanned.new_page();page.insert_image(page.rect,stream=image)
        question=dict(document_id='scan',number=23,regions=[dict(page=0,rect=[30,75,560,210])])
        result=erase_source_numbers(scanned,question,{})
        assert result['erased_labels'] == 1 and result['warnings'] == []
        # OCR again only in this verification: the source marker pixels have gone.
        verified_page=scanned[0]
        tp=verified_page.get_textpage_ocr(language='eng',dpi=200,full=True)
        text=verified_page.get_text(textpage=tp)
        assert not re.search(r'(?m)^23\.',text)
        assert '(a)' in text and '23 m' in text


def test_fill_paper_can_fill_an_empty_manual_selection(bank):
    client,_,_,first,second=bank
    result=client.post('/api/papers',json=dict(level='HL',minutes=13,topics=[],question_ids=[],fill_paper=True))
    assert result.status_code == 201,result.json
    assert set(result.json['question_ids']) == {first['id'],second['id']}
    assert set(result.json['filled_question_ids']) == {first['id'],second['id']}
    assert result.json['actual_minutes'] == 13
