from io import BytesIO
import json
import sqlite3

import fitz
import pytest

from app import create_app
from test_workflow import sample_pdf, save, upload


@pytest.fixture
def bank(tmp_path):
    app = create_app(tmp_path)
    app.config['TESTING'] = True
    return app.test_client(), tmp_path


def test_confirm_import_saves_full_groups_tags_and_pngs(bank):
    client, root = bank
    doc = upload(client)
    assert client.get('/api/questions').json == []
    response = client.post(f"/api/documents/{doc['id']}/confirm-import", json={})
    assert response.status_code == 200, response.json
    assert response.json['imported'] == 2 and response.json['failed'] == []
    saved = client.get('/api/questions').json
    first = next(q for q in saved if q['number'] == 1)
    assert first['review_status'] == 'imported'
    assert first['subquestions'] is None  # Bulk import does not approve dependency pruning.
    assert first['regions'] == doc['questions'][0]['regions']
    assert '(a)' in first['text'] and '(b)' in first['text']
    assert {'calculate', 'state', 'explain'} <= set(first['commands'])
    assert {'mechanics', 'kinematics', 'projectile'} <= set(first['tags'])
    assert client.get(f"/api/questions/{first['id']}/image").mimetype == 'image/png'
    assert len(create_app(root).test_client().get('/api/questions').json) == 2
    generated = client.post('/api/papers', json=dict(level='HL', topics=[], minutes=30))
    assert generated.status_code == 201, generated.json
    assert generated.json['count'] == 2


def test_repeat_confirm_preserves_reviewed_questions_and_is_idempotent(bank):
    client, _ = bank
    doc = upload(client)
    reviewed = save(client, doc, tags=['my custom tag'], commands=[], difficulty='Hard')
    url = f"/api/documents/{doc['id']}/confirm-import"
    result = client.post(url, json={}).json
    assert result['imported'] == 1 and result['skipped_numbers'] == [1]
    result = client.post(url, json={}).json
    assert result['imported'] == 0 and sorted(result['skipped_numbers']) == [1, 2]
    first = next(q for q in client.get('/api/questions').json if q['id'] == reviewed['id'])
    assert first['review_status'] == 'reviewed' and first['difficulty'] == 'Hard'
    assert first['tags'] == ['my custom tag'] and first['commands'] == []


def test_unknown_metadata_and_no_topic_can_be_imported_without_invention(bank):
    client, _ = bank
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((50, 90), '1. State the meaning of this observation in the experiment described below.')
        data = pdf.tobytes()
    doc = client.post('/api/documents', data=dict(file=(BytesIO(data), 'unknown.pdf'), ocr_mode='off')).json
    assert len(doc['questions']) == 1
    result = client.post(f"/api/documents/{doc['id']}/confirm-import", json={}).json
    assert result['imported'] == 1 and result['failed'] == []
    saved = client.get('/api/questions').json[0]
    assert saved['year'] is None and saved['level'] == saved['syllabus'] == saved['paper'] == 'Unknown'
    assert saved['topics'] == saved['tags'] == [] and saved['commands'] == ['state']
    assert client.post('/api/papers', json=dict(level='HL', minutes=30, topics=[])).status_code == 400


def test_invalid_candidate_is_reported_without_losing_other_imports(bank):
    client, root = bank
    doc = upload(client)
    with sqlite3.connect(root / 'bank.sqlite3') as conn:
        raw = json.loads(conn.execute('SELECT data FROM documents WHERE id=?', (doc['id'],)).fetchone()[0])
        raw['questions'][0]['regions'][0]['rect'] = [100, 100, 0, 0]
        conn.execute('UPDATE documents SET data=? WHERE id=?', (json.dumps(raw), doc['id']))
    result = client.post(f"/api/documents/{doc['id']}/confirm-import", json={}).json
    assert result['imported'] == 1 and result['failed'][0]['number'] == 1
    assert [q['number'] for q in client.get('/api/questions').json] == [2]
    assert client.post('/api/documents/missing/confirm-import', json={}).status_code == 400


def test_auto_fill_uses_current_crops_and_topics_without_saving(bank):
    client, _ = bank
    doc = upload(client)
    payload = dict(regions=doc['questions'][1]['regions'], paper='Paper 2', topics=['B.5'])
    result = client.post(f"/api/documents/{doc['id']}/suggest-tags", json=payload)
    assert result.status_code == 200
    assert result.json['commands'] == ['determine']
    assert 'current and circuits' in result.json['tags'] and 'resistance' in result.json['tags']
    assert 'mechanics' not in result.json['tags']
    payload['paper'] = 'Paper 1A'
    assert client.post(f"/api/documents/{doc['id']}/suggest-tags", json=payload).json['commands'] == []
    payload['topics'] = ['invalid']
    assert client.post(f"/api/documents/{doc['id']}/suggest-tags", json=payload).status_code == 400
    assert client.get('/api/questions').json == []


def test_opt_in_auto_import_saves_during_upload_with_no_extra_confirmation(bank):
    client, _ = bank
    response = client.post('/api/documents', data=dict(
        file=(BytesIO(sample_pdf()), 'Physics_HL_Paper2_2025.pdf'), auto_import='1'))
    assert response.status_code == 201, response.json
    result = response.json['import_result']
    assert result['imported'] == 2 and result['failed'] == []
    saved = client.get('/api/questions').json
    assert len(saved) == 2 and all(q['review_status'] == 'imported' for q in saved)
    assert all(q['tags'] and q['commands'] and q['subquestions'] is None for q in saved)
    assert client.post('/api/documents', data=dict(file=(BytesIO(b'not a PDF'), 'broken.pdf'), auto_import='1')).status_code == 400
    assert len(client.get('/api/questions').json) == 2
