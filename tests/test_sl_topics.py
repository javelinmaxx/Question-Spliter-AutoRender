from io import BytesIO
import json
import sqlite3

import fitz
import pytest

from app import create_app
from physics import HL_ONLY_TOPICS, suggest
from test_workflow import upload, save


@pytest.mark.parametrize('code,text', [
    ('A.4','Calculate the torque and moment of inertia of the rotating flywheel.'),
    ('A.5','Explain length contraction and time dilation using special relativity.'),
    ('B.4','Explain entropy changes in this Carnot heat engine.'),
    ('D.4','Determine the induced emf from the changing magnetic flux.'),
    ('E.2','Explain the photoelectric effect and de Broglie wavelength.')])
def test_sl_analysis_excludes_hl_only_labels_but_preserves_conflict(code, text):
    assert code in suggest(text, 'Paper 2', 'HL')['topics']
    sl = suggest(text, 'Paper 2', 'SL')
    assert code not in sl['topics'] and code in sl['level_conflicts']
    assert not set(sl['topics']) & HL_ONLY_TOPICS


@pytest.mark.parametrize('code', sorted(HL_ONLY_TOPICS))
def test_hl_only_topics_are_rejected_by_sl_builder_and_sl_both_saves(tmp_path, code):
    client = create_app(tmp_path).test_client()
    doc = upload(client)
    for mode in ('full', 'short'):
        result = client.post('/api/papers', json=dict(level='SL', minutes=30, topics=[code], render_mode=mode))
        assert result.status_code == 400 and 'HL-only' in result.json['error']
    for level in ('SL', 'Both'):
        result = client.post('/api/questions', json=dict(doc['questions'][0], document_id=doc['id'], level=level, topics=[code]))
        assert result.status_code == 400 and 'HL-only' in result.json['error']
    # HL retains access to each of the five topics.
    save(client, doc, topics=[code])
    result = client.post('/api/papers', json=dict(level='HL', minutes=30, topics=[code]))
    assert result.status_code == 201, result.json
    assert client.get('/api/questions?level=SL&topic='+code).status_code == 400


def test_sl_auto_import_retains_conflict_and_builder_cannot_select_it(tmp_path):
    client = create_app(tmp_path).test_client()
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((50,45),'IB Physics Standard level Paper 2 2025')
        page.insert_text((50,100),'1. Calculate the torque and moment of inertia of this rotating flywheel. [4]')
        data = pdf.tobytes()
    result = client.post('/api/documents', data=dict(file=(BytesIO(data),'Physics_SL_2025.pdf'), ocr_mode='off',auto_import='1'))
    assert result.status_code == 201, result.json
    assert result.json['import_result']['imported'] == 1
    saved = client.get('/api/questions').json[0]
    assert saved['level'] == 'SL' and 'A.4' in saved['level_conflicts']
    assert 'A.4' not in saved['topics']
    restarted = create_app(tmp_path).test_client()
    assert restarted.get('/api/questions').json[0]['level_conflicts'] == saved['level_conflicts']
    for mode in ('full','short'):
        result = restarted.post('/api/papers', json=dict(level='SL',minutes=30,topics=[],render_mode=mode))
        assert result.status_code == 400


@pytest.mark.parametrize('unsafe', ['parent', 'part', 'conflict'])
def test_sl_builder_excludes_incompatible_existing_both_records_even_without_topic_filter(tmp_path, unsafe):
    client = create_app(tmp_path).test_client()
    doc = upload(client)
    bad = save(client, doc, level='Both')
    good = save(client, doc, 1, level='Both')
    with sqlite3.connect(tmp_path / 'bank.sqlite3') as conn:
        value = json.loads(conn.execute('SELECT data FROM questions WHERE id=?',(bad['id'],)).fetchone()[0])
        if unsafe == 'parent': value['topics'] = ['A.4']
        if unsafe == 'part': value['subquestions'] = dict(parts=[dict(id='a',topics=['D.4'])])
        if unsafe == 'conflict': value['level_conflicts'] = ['E.2']
        conn.execute('UPDATE questions SET data=? WHERE id=?',(json.dumps(value),bad['id']))
    for mode in ('full','short'):
        result = client.post('/api/papers', json=dict(level='SL',minutes=30,topics=[],render_mode=mode))
        assert result.status_code == 201,result.json
        assert result.json['question_ids'] == [good['id']]
    assert [q['id'] for q in client.get('/api/questions?level=SL').json] == [good['id']]


def test_shared_topics_remain_available_to_sl_and_catalog_matches_roadmap(tmp_path):
    client = create_app(tmp_path).test_client()
    catalog = client.get('/api/catalog').json
    assert set(catalog['hl_only_topics']) == HL_ONLY_TOPICS == set(catalog['prerequisite_policy']['level_scope']['HL_only'])
    doc = upload(client)
    save(client, doc, level='SL',topics=['D.1'])
    result = client.post('/api/papers', json=dict(level='SL',minutes=30,topics=['D.1']))
    assert result.status_code == 201, result.json
