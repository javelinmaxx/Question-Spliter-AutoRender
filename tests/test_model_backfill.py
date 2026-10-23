import json
from copy import deepcopy
from io import BytesIO
from threading import Event

from app import create_app
from test_language_review import disagreement_pdf
from test_subquestions import saved_parent, approve


def setup_disagreement(tmp_path, monkeypatch):
    data, record=disagreement_pdf()
    monkeypatch.setattr('physics.read_pages',lambda *args:([record],[]))
    app=create_app(tmp_path);client=app.test_client()
    doc=client.post('/api/documents',data={'file':(BytesIO(data),'paper.pdf'),'ocr_mode':'verify'}).json
    job=app.extensions['model_backfill']
    job.availability=lambda:dict(available=True)
    return app,client,doc,job


def test_backfill_saved_text_persists_and_does_not_repeat_after_restart(tmp_path,monkeypatch):
    app,client,doc,job=setup_disagreement(tmp_path,monkeypatch)
    calls=[]
    def review(*args):
        from language_review import context_hash
        calls.append(args)
        return dict(status='needs_review',input_hash=context_hash(*args),model='qwen',topics=[],evidence=[],reason='Uncertain')
    job.review=review
    monkeypatch.setattr('physics.read_pages',lambda *args: (_ for _ in ()).throw(AssertionError('OCR must not run')))
    job.run_once();job.run_once()
    assert len(calls)==1
    data=client.get('/api/documents/'+doc['id']).json
    assert data['questions'][0]['language_review']['model']=='qwen'
    restarted=create_app(tmp_path).extensions['model_backfill']
    restarted.availability=lambda:dict(available=True)
    restarted.review=lambda *args:(_ for _ in ()).throw(AssertionError('Already reviewed'))
    restarted.run_once()
    assert restarted.state['errors']==0


def test_disappearing_model_does_not_mark_check_done(tmp_path,monkeypatch):
    _,client,doc,job=setup_disagreement(tmp_path,monkeypatch)
    job.review=lambda *args:dict(status='unavailable')
    job.run_once()
    review=client.get('/api/documents/'+doc['id']).json['questions'][0]['language_review']
    assert review['status']=='unavailable' and 'automatic_context' not in review


def test_model_failure_is_saved_once_without_repeated_inference(tmp_path,monkeypatch):
    _,client,doc,job=setup_disagreement(tmp_path,monkeypatch)
    calls=[]
    def fail(*args):
        calls.append(1);raise RuntimeError('Invalid model output')
    job.review=fail
    job.run_once();job.run_once()
    review=client.get('/api/documents/'+doc['id']).json['questions'][0]['language_review']
    assert len(calls)==1 and review['status']=='needs_review'
    assert 'Invalid model output' in review['reason']


def test_dependency_proposals_are_saved_but_never_approved_and_teacher_map_preserved(tmp_path):
    app=create_app(tmp_path);client=app.test_client();q=saved_parent(client)
    job=app.extensions['model_backfill'];job.availability=lambda:dict(available=True)
    calls=[]
    def dependencies(parts):
        calls.append(1)
        return dict(status='proposed',parts=deepcopy(parts),model='qwen',reason='Check proposal')
    job.dependencies=dependencies
    job.run_once();job.run_once()
    saved=client.get('/api/questions').json[0]
    assert len(calls)==1
    assert saved['subquestions']['status']=='draft'
    assert saved['topics']==q['topics'] and saved['regions']==q['regions']
    approve(client,saved)
    job.run_once()
    assert len(calls)==1
    assert client.get('/api/questions').json[0]['subquestions']['status']=='approved'


def test_background_worker_does_not_block_request_and_avoids_duplicate_worker(tmp_path,monkeypatch):
    _,client,doc,job=setup_disagreement(tmp_path,monkeypatch)
    entered,release,finished=Event(),Event(),Event()
    def review(*args):
        entered.set();assert release.wait(5)
        from language_review import context_hash
        return dict(status='needs_review',input_hash=context_hash(*args),model='qwen',reason='Uncertain')
    job.review=review
    original=job.run_once
    def run():
        try:original()
        finally:finished.set()
    job.run_once=run
    job.kick(force=True)
    assert entered.wait(5)
    assert client.get('/api/catalog').status_code==200
    assert client.get('/api/model/status').json['backfill']['running']
    job.kick(force=True)
    release.set();assert finished.wait(5)
    assert job.state['updated']==1


def test_concurrent_teacher_change_is_not_overwritten(tmp_path,monkeypatch):
    _,_,doc,job=setup_disagreement(tmp_path,monkeypatch)
    def review(*args):
        with job.connection() as conn:
            data=json.loads(conn.execute('SELECT data FROM documents WHERE id=?',(doc['id'],)).fetchone()[0])
            data['questions'][0]['tags']=['teacher edit']
            conn.execute('UPDATE documents SET data=? WHERE id=?',(json.dumps(data),doc['id']))
        from language_review import context_hash
        return dict(status='resolved',input_hash=context_hash(*args),model='qwen',topics=['C.5'])
    job.review=review;job.run_once()
    with job.connection() as conn:
        data=json.loads(conn.execute('SELECT data FROM documents WHERE id=?',(doc['id'],)).fetchone()[0])
    assert data['questions'][0]['tags']==['teacher edit']
    assert data['questions'][0]['language_review']['status']=='unavailable'
