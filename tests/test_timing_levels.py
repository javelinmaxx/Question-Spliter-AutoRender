from io import BytesIO
import json
import sqlite3

import fitz
import pytest

from app import create_app
from assessment_timing import estimate
from test_workflow import upload, save


@pytest.mark.parametrize('level,paper,marks,minutes',[
    ('HL','Paper 1A',1,2),('SL','Paper 1A',1,2),('HL','Paper 1B',20,40),
    ('SL','Paper 1B',20,40),('HL','Paper 2',90,150),('SL','Paper 2',50,90),
])
def test_official_paper_rates(level,paper,marks,minutes):
    value=estimate(marks,paper,level,'2025')
    assert value['minutes']==minutes
    assert value['minutes_per_mark']==value['paper_minutes']/value['paper_marks']
    assert value['method']=='ib_mark_rate'


def test_legacy_rates_and_unknown_fallback():
    assert estimate(1,'Paper 1','HL','Legacy')['minutes']==1.5
    assert estimate(50,'Paper 2','SL','Legacy')['minutes']==75
    assert estimate(95,'Paper 2','HL','Legacy')['minutes']==135
    assert estimate(None,'Paper 2','HL')['minutes']==5
    assert estimate(5,'Paper 2','Unknown')['method']=='fallback'


def test_startup_reestimates_old_defaults_without_ocr_and_preserves_teacher_override(tmp_path,monkeypatch):
    client=create_app(tmp_path).test_client();doc=upload(client)
    first=save(client,doc);second=save(client,doc,1,minutes=17)
    with sqlite3.connect(tmp_path/'bank.sqlite3') as conn:
        raw=conn.execute('SELECT data FROM questions WHERE id=?',(first['id'],)).fetchone()[0]
        q=json.loads(raw);q.pop('timing',None);q['minutes']=12.6
        conn.execute('UPDATE questions SET data=? WHERE id=?',(json.dumps(q),first['id']))
    monkeypatch.setattr('physics.read_pages',lambda *args:pytest.fail('No OCR during timing migration'))
    reopened=create_app(tmp_path).test_client()
    bank={q['id']:q for q in reopened.get('/api/questions').json}
    assert bank[first['id']]['minutes']==11.7
    assert bank[first['id']]['timing']['mode']=='automatic'
    assert bank[second['id']]['minutes']==17 and bank[second['id']]['timing']['mode']=='manual'
    assert create_app(tmp_path).test_client().get('/api/questions').status_code==200


@pytest.fixture
def mixed(tmp_path):
    client=create_app(tmp_path).test_client();saved={}
    for level,tasks in [('HL',[
        ('Calculate the force on a cart.','A.2'),
        ('Calculate the gravitational force between two masses.','D.1'),
        ('Calculate the moment of inertia of the flywheel.','A.4'),
        ('Determine the escape speed from the planet.','A.2')]),('SL',[
        ('Calculate the acceleration of the cart.','A.1'),
        ('Calculate the gravitational field strength.','D.1')])]:
        with fitz.open() as pdf:
            page=pdf.new_page();page.insert_text((50,45),f'IB Physics {level} Paper 2 2025')
            for index,(text,topic) in enumerate(tasks):page.insert_text((50,100+150*index),f'{index+1}. {text} [3]')
            result=client.post('/api/documents',data=dict(file=(BytesIO(pdf.tobytes()),f'Physics_{level}_2025_Paper2.pdf'),ocr_mode='off'))
            assert result.status_code==201,result.json
            doc=result.json
        saved[level]=[dict(save(client,doc,i,topics=[topic]),document_id=doc['id']) for i,(_,topic) in enumerate(tasks)]
    return client,saved


def test_four_level_modes_use_source_and_content_checks(mixed):
    client,qs=mixed
    expected={'HL':{q['id'] for q in qs['HL']},'SL':{qs['HL'][0]['id'],*[q['id'] for q in qs['SL']]},
              'SL_from_HL':{qs['HL'][0]['id']},'Any':{q['id'] for group in qs.values() for q in group}}
    for level,ids in expected.items():
        assert {q['id'] for q in client.get('/api/questions',query_string={'level':level}).json}==ids
        result=client.post('/api/papers',json=dict(level=level,minutes=100,topics=[]))
        assert result.status_code==201,result.json
        assert set(result.json['question_ids'])==ids
        downloaded=client.get(f"/api/papers/{result.json['id']}/download")
        with fitz.open(stream=downloaded.data,filetype='pdf') as pdf:
            assert ('Mixed levels' if level=='Any' else 'Standard level' if level in ('SL','SL_from_HL') else 'Higher level') in pdf[0].get_text()


def test_mixed_depth_hl_question_needs_explicit_review_and_confirmation_persists(mixed):
    client,qs=mixed;q=qs['HL'][1]
    result=client.post('/api/papers/preview',json=dict(level='SL_from_HL',minutes=100,topics=[]))
    assert any(e['code']=='sl_review' for e in result.json['diagnostics']['exclusions'])
    reviewed=client.post('/api/questions',json=dict(q,sl_suitability='sl_suitable'))
    assert reviewed.status_code==201,reviewed.json
    ids={q['id'] for q in client.get('/api/questions?level=SL_from_HL').json}
    assert ids=={qs['HL'][0]['id'],q['id']}
    assert reviewed.json['source_level']=='HL' and reviewed.json['level']=='HL'
    root=client.application.extensions['model_backfill'].root
    reopened=create_app(root).test_client()
    assert {q['id'] for q in reopened.get('/api/questions?level=SL_from_HL').json}==ids
    for unsafe in [qs['HL'][2],qs['HL'][3]]:
        invalid=client.post('/api/questions',json=dict(unsafe,sl_suitability='sl_suitable'))
        assert invalid.status_code==400 and 'HL-only' in invalid.json['error']
    assert client.post('/api/papers',json=dict(level='SL_from_HL',minutes=100,topics=['A.4'])).status_code==400


def test_old_unmarked_mcq_and_approved_time_allocation():
    from assessment_timing import refresh
    mcq=dict(marks=None,minutes=5,level='HL',syllabus='Legacy',paper='Paper 1')
    refresh(mcq)
    assert mcq['marks']==1 and mcq['minutes']==1.5
    approved=dict(marks=6,minutes=10.8,level='HL',syllabus='2025',paper='Paper 2',subquestions=dict(status='approved',parts=[dict(minutes=10.8)]))
    refresh(approved)
    assert approved['minutes']==10.8 and approved['timing']['minutes']==10
    assert approved['subquestions']['parts'][0]['minutes']==10.8
