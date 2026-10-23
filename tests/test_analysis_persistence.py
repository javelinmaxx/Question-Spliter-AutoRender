"""Verify restart recovery without invoking extraction or optional inference again."""
from io import BytesIO
import json
import subprocess
import sys

import pytest

import app as application
from app import create_app
from language_review import context_hash
from test_workflow import sample_pdf
from test_subquestions import saved_parent, approve


def no_reanalysis(*args, **kwargs):
    pytest.fail('Reopening saved analysis must not run extraction or model inference.')


def test_auto_import_analysis_survives_a_fresh_python_process(tmp_path):
    client = create_app(tmp_path).test_client()
    response = client.post('/api/documents', data=dict(
        file=(BytesIO(sample_pdf()), 'Physics_HL_Paper2_2025.pdf'), auto_import='1'))
    assert response.status_code == 201
    doc = response.json
    assert doc['analysis']['status'] == doc['analysis']['language_review_status'] == 'complete'
    assert doc['analysis']['completed_at'] and doc['text_pages']
    saved = client.get('/api/questions').json
    # A separate interpreter cannot rely on objects or caches from this process.
    script = '''
import json, sys
import app
app.extract = lambda *a, **kw: (_ for _ in ()).throw(AssertionError('Unexpected extraction'))
app.review_disagreement = lambda *a, **kw: (_ for _ in ()).throw(AssertionError('Unexpected inference'))
client = app.create_app(sys.argv[1]).test_client()
doc = client.get('/api/documents/' + sys.argv[2]).json
questions = client.get('/api/questions').json
assert all(client.get('/api/questions/' + q['id'] + '/image').mimetype == 'image/png' for q in questions)
print(json.dumps(dict(document=doc, questions=questions)))
'''
    result = subprocess.run([sys.executable, '-c', script, str(tmp_path), doc['id']], check=True,
                            capture_output=True, text=True, timeout=15)
    restored = json.loads(result.stdout)
    assert restored['document']['analysis'] == doc['analysis']
    assert restored['document']['text_pages'] == doc['text_pages']
    assert restored['questions'] == saved
    assert {q['number'] for q in restored['document']['questions']} == {1, 2}


def test_interruption_during_model_review_keeps_extraction_and_completed_reviews(tmp_path, monkeypatch):
    original_extract = application.extract
    def extract_with_disagreements(*args, **kwargs):
        doc = original_extract(*args, **kwargs)
        for q in doc['questions']:
            q['ocr_comparison']['status'] = 'disagreement'
        return doc
    calls = []
    def interrupted_review(*args, **kwargs):
        calls.append(args)
        if len(calls) == 2:
            raise KeyboardInterrupt('Simulated stop during the second model call')
        return dict(status='needs_review', input_hash=context_hash(*args[:5]),
                    reason='Completed first check; teacher review required.', topics=[], evidence=[])
    monkeypatch.setattr(application, 'extract', extract_with_disagreements)
    monkeypatch.setattr(application, 'review_disagreement', interrupted_review)
    app = create_app(tmp_path)
    app.config['TESTING'] = True
    with pytest.raises(KeyboardInterrupt):
        app.test_client().post('/api/documents', data=dict(file=(BytesIO(sample_pdf()), 'Physics_HL_Paper2_2025.pdf')))
    monkeypatch.setattr(application, 'extract', no_reanalysis)
    monkeypatch.setattr(application, 'review_disagreement', no_reanalysis)
    reopened = create_app(tmp_path).test_client()
    documents = reopened.get('/api/documents').json
    assert len(documents) == 1
    doc = reopened.get('/api/documents/' + documents[0]['id']).json
    assert len(doc['questions']) == 2 and doc['text_pages']
    assert doc['analysis']['status'] == 'complete'
    assert doc['analysis']['language_review_status'] == 'pending'
    assert doc['questions'][0]['language_review']['reason'].startswith('Completed first check')
    assert (tmp_path / 'documents' / (doc['id'] + '.pdf')).exists()
    # The saved extraction can be imported after restart despite the interrupted check.
    result = reopened.post(f"/api/documents/{doc['id']}/confirm-import", json={}).json
    assert result['imported'] == 2 and result['failed'] == []


def test_dependency_analysis_and_approval_survive_restart(tmp_path, monkeypatch):
    client = create_app(tmp_path).test_client()
    q = saved_parent(client)
    monkeypatch.setattr(application, 'analyze_dependencies', lambda parts: dict(
        status='needs_review', parts=parts, evidence=[], reason='Persist this completed diagnostic.'))
    analyzed = client.post(f"/api/questions/{q['id']}/subquestions/analyze", json={})
    assert analyzed.status_code == 200
    monkeypatch.setattr(application, 'extract', no_reanalysis)
    monkeypatch.setattr(application, 'analyze_dependencies', no_reanalysis)
    reopened = create_app(tmp_path).test_client()
    mapping = reopened.get(f"/api/questions/{q['id']}/subquestions").json['mapping']
    assert mapping == analyzed.json and mapping['status'] == 'draft'
    approve(reopened, q)
    approved = reopened.get(f"/api/questions/{q['id']}/subquestions").json['mapping']
    restarted = create_app(tmp_path).test_client()
    assert restarted.get(f"/api/questions/{q['id']}/subquestions").json['mapping'] == approved
    assert restarted.get(f"/api/questions/{q['id']}/image?mode=short").mimetype == 'image/png'
