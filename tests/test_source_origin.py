from copy import deepcopy
from io import BytesIO
import json
import sqlite3
import pytest

from app import create_app
from source_origin import analyze_origin
from test_workflow import sample_pdf,upload,save


def saved_text(text,native=''):
    return [dict(page=0,text=text,native=native)]


@pytest.mark.parametrize('text,expected',[
    ('© International Baccalaureate Organization 2020','ib_official'),
    ('International Baccalaureate\nN20/4/PHYSI/HP3/ENG/TZ0/XX','ib_official'),
    ('Teacher-made physics paper for revision','self_made'),
    ('Physics HL Paper 2 2025','unknown'),
    ('A teacher-made apparatus measures velocity.','unknown'),
    ('Teacher-made paper\n© International Baccalaureate Organization 2020','unknown')])
def test_source_classification_needs_explicit_evidence(text,expected):
    assert analyze_origin(saved_text(text))['origin']==expected


def test_upload_filters_reanalysis_and_generation_preserve_source_labels(tmp_path):
    client=create_app(tmp_path).test_client()
    doc=upload(client)
    first=save(client,doc,origin='self_made');second=save(client,doc,1,origin='ib_official')
    assert [q['id'] for q in client.get('/api/questions?origin=self_made').json]==[first['id']]
    options=dict(level='HL',minutes=40,topics=[],origin='ib_official')
    preview=client.post('/api/papers/preview',json=options)
    assert [q['id'] for q in preview.json['questions']]==[second['id']]
    assert client.post('/api/papers',json=dict(options,question_ids=[first['id']])).status_code==400
    result=client.post('/api/papers',json=options)
    assert result.status_code==201 and result.json['question_ids']==[second['id']]
    import fitz
    downloaded=client.get(f"/api/papers/{result.json['id']}/download")
    with fitz.open(stream=downloaded.data,filetype='pdf') as pdf:
        assert 'Question sources: Official IB' in pdf[0].get_text()
        assert any('Official IB' in page.get_text() for page in list(pdf)[1:])
    assert client.post('/api/documents/'+doc['id']+'/reanalyse',json={}).status_code==200
    assert {q['id']:q['origin'] for q in client.get('/api/questions').json}=={first['id']:'self_made',second['id']:'ib_official'}
    bulk=client.post('/api/documents/'+doc['id']+'/origin',json=dict(origin='ib_official'))
    assert bulk.json['preserved']==2 and bulk.json['updated']==0


def test_startup_forces_saved_ocr_source_reanalysis_without_running_ocr(tmp_path,monkeypatch):
    client=create_app(tmp_path).test_client();doc=upload(client)
    inherited=save(client,doc,origin='inherit');manual=save(client,doc,1,origin='self_made')
    with sqlite3.connect(tmp_path/'bank.sqlite3') as conn:
        raw=json.loads(conn.execute('SELECT data FROM documents WHERE id=?',(doc['id'],)).fetchone()[0])
        raw['text_pages'][0]['text']='© International Baccalaureate Organization 2020'
        raw['origin_analysis']={'version':'old','origin':'self_made'}
        conn.execute('UPDATE documents SET data=? WHERE id=?',(json.dumps(raw),doc['id']))
    monkeypatch.setattr('physics.read_pages',lambda *a,**kw:pytest.fail('Startup source checks must not run OCR/extraction'))
    restarted=create_app(tmp_path).test_client()
    q={q['id']:q for q in restarted.get('/api/questions').json}
    assert q[inherited['id']]['origin']=='ib_official' and q[manual['id']]['origin']=='self_made'
    data=restarted.get('/api/documents/'+doc['id']).json
    assert data['origin_analysis']['evidence'][0]['source']=='ocr'
    previous=data['origin_analysis']['analyzed_at']
    assert create_app(tmp_path).test_client().get('/api/documents/'+doc['id']).json['origin_analysis']['analyzed_at']!=previous
    assert q[manual['id']]['topics']==manual['topics']


def test_explicit_document_label_survives_startup_but_automatic_can_be_restored(tmp_path):
    client=create_app(tmp_path).test_client()
    response=client.post('/api/documents',data=dict(file=(BytesIO(sample_pdf()),'teacher.pdf'),origin='self_made',auto_import='1'))
    assert response.status_code==201,response.json
    doc=response.json
    restarted=create_app(tmp_path).test_client()
    assert restarted.get('/api/documents/'+doc['id']).json['origin']=='self_made'
    restored=restarted.post('/api/documents/'+doc['id']+'/origin',json=dict(origin='auto'))
    assert restored.status_code==200 and restored.json['origin']=='unknown'
    assert all(q['origin']=='unknown' for q in restarted.get('/api/questions').json)
