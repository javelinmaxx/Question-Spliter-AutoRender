from io import BytesIO
import json
import sqlite3

import fitz
import pytest

import app as application
import physics
from app import create_app
from analysis_storage import rules_hash
from test_workflow import sample_pdf, save


def post_pdf(client, data, auto=True, name='Physics_HL_Paper2_2025.pdf'):
    return client.post('/api/documents',data=dict(file=(BytesIO(data),name),auto_import='1' if auto else '0'))


def no_ocr(*args,**kwargs):
    pytest.fail('Saved page data must be reused without OCR/extraction/model inference.')


def altered_pdf(data, diagram=False):
    with fitz.open(stream=data,filetype='pdf') as pdf:
        pdf[0].insert_text((350,40),'Different source session header')
        if diagram:
            pdf[0].draw_rect(fitz.Rect(250,300,300,350),color=(0,0,0))
        return pdf.tobytes()


def test_identical_pdf_reuses_saved_analysis_across_restart_and_can_auto_import(tmp_path,monkeypatch):
    data=sample_pdf();client=create_app(tmp_path).test_client()
    first=post_pdf(client,data,auto=False).json
    assert client.get('/api/questions').json == []
    monkeypatch.setattr(application,'extract',no_ocr)
    monkeypatch.setattr(application,'review_disagreement',no_ocr)
    restarted=create_app(tmp_path).test_client()
    repeated=post_pdf(restarted,data)
    assert repeated.status_code == 200 and repeated.json['duplicate_document']
    assert repeated.json['analysis']['auto_import'] is True
    assert repeated.json['id'] == first['id'] and repeated.json['text_pages'] == first['text_pages']
    assert repeated.json['import_result']['imported'] == 2
    again=post_pdf(restarted,data)
    assert again.json['import_result']['imported'] == 0
    assert len(again.json['import_result']['skipped_numbers']) == 2
    assert len(restarted.get('/api/documents').json) == 1
    assert len(restarted.get('/api/questions').json) == 2
    assert len(list((tmp_path/'documents').glob('*.pdf'))) == 1


def test_identical_question_pixels_and_text_are_skipped_across_different_source_pdfs(tmp_path):
    client=create_app(tmp_path).test_client();data=sample_pdf()
    assert post_pdf(client,data).json['import_result']['imported'] == 2
    second=post_pdf(client,altered_pdf(data),name='another_source.pdf')
    assert second.status_code == 201
    assert second.json['import_result']['imported'] == 0
    assert len(second.json['import_result']['duplicate_questions']) == 2
    assert len(client.get('/api/questions').json) == 2
    # Explicit save cannot create another exact copy either.
    q=second.json['questions'][0]
    response=client.post('/api/questions',json=dict(q,document_id=second.json['id']))
    assert response.status_code == 400 and 'already exists' in response.json['error']


def test_matching_wording_with_different_diagram_is_flagged_but_not_discarded(tmp_path):
    client=create_app(tmp_path).test_client();data=sample_pdf()
    first=post_pdf(client,data).json
    response=post_pdf(client,altered_pdf(data,diagram=True),name='different_diagram.pdf')
    assert response.status_code == 201
    assert response.json['import_result']['imported'] == 1
    questions=client.get('/api/questions').json
    assert len(questions) == 3
    added=next(q for q in questions if q['document_id'] == response.json['id'])
    assert added['possible_duplicate_ids']
    assert all(q['id'] not in q.get('possible_duplicate_ids',[]) for q in questions)


def test_reanalysis_uses_saved_pages_updates_imports_and_preserves_manual_reviews(tmp_path,monkeypatch):
    client=create_app(tmp_path).test_client()
    original=post_pdf(client,sample_pdf()).json
    doc=client.get('/api/documents/'+original['id']).json
    manual=save(client,doc,tags=['teacher choice'],difficulty='Hard')
    second=next(q for q in client.get('/api/questions').json if q['number'] == 2)
    with sqlite3.connect(tmp_path/'bank.sqlite3') as conn:
        row=json.loads(conn.execute('SELECT data FROM documents WHERE id=?',(doc['id'],)).fetchone()[0])
        row['analysis']['rules_hash']='old-rules'
        conn.execute('UPDATE documents SET data=? WHERE id=?',(json.dumps(row),doc['id']))
    assert client.get('/api/documents/'+doc['id']).json['rules_changed']
    real_suggest=physics.suggest
    def changed_rule(text,*args,**kwargs):
        result=real_suggest(text,*args,**kwargs)
        if 'resistance' in text.lower():
            result['topics']=['A.0',*result['topics']]
            result['tags']=physics.custom_tags(text,result['topics'])
        return result
    monkeypatch.setattr(physics,'suggest',changed_rule)
    monkeypatch.setattr(physics,'read_pages',no_ocr)
    monkeypatch.setattr(application,'review_disagreement',no_ocr)
    result=client.post(f"/api/documents/{doc['id']}/reanalyse",json={})
    assert result.status_code == 200,result.json
    assert result.json['updated_question_ids'] == [second['id']]
    assert result.json['preserved_reviewed_ids'] == [manual['id']]
    after=client.get('/api/documents/'+doc['id']).json
    assert after['text_pages'] == original['text_pages']
    assert after['analysis']['rules_hash'] == rules_hash() and not after['rules_changed']
    saved={q['id']:q for q in client.get('/api/questions').json}
    assert saved[manual['id']]['tags'] == ['teacher choice'] and saved[manual['id']]['difficulty'] == 'Hard'
    assert 'A.0' in saved[second['id']]['topics']
    assert len(saved) == 2
    restarted=create_app(tmp_path).test_client()
    assert restarted.get('/api/documents/'+doc['id']).json['analysis']['reused_page_data']


def test_reanalysis_without_saved_pages_requires_one_upload_upgrade(tmp_path):
    data=sample_pdf();client=create_app(tmp_path).test_client();doc=post_pdf(client,data,auto=False).json
    with sqlite3.connect(tmp_path/'bank.sqlite3') as conn:
        raw=json.loads(conn.execute('SELECT data FROM documents WHERE id=?',(doc['id'],)).fetchone()[0]);raw.pop('text_pages')
        conn.execute('UPDATE documents SET data=? WHERE id=?',(json.dumps(raw),doc['id']))
    assert client.post(f"/api/documents/{doc['id']}/reanalyse",json={}).status_code == 400
    upgraded=post_pdf(client,data,auto=False)
    assert upgraded.status_code == 201 and upgraded.json['text_pages']
    repeated=post_pdf(client,data,auto=False)
    assert repeated.status_code == 200 and repeated.json['id'] == upgraded.json['id']


def test_reanalysis_auto_imports_newly_detected_groups_when_original_upload_opted_in(tmp_path,monkeypatch):
    client=create_app(tmp_path).test_client();doc=post_pdf(client,sample_pdf()).json
    with sqlite3.connect(tmp_path/'bank.sqlite3') as conn:
        rows=conn.execute('SELECT id,data FROM questions').fetchall()
        removed=next(qid for qid,data in rows if json.loads(data)['number']==2)
        conn.execute('DELETE FROM questions WHERE id=?',(removed,))
    monkeypatch.setattr(physics,'read_pages',no_ocr)
    result=client.post(f"/api/documents/{doc['id']}/reanalyse",json={})
    assert result.status_code == 200,result.json
    assert len(result.json['new_question_ids']) == 1 and len(result.json['updated_question_ids']) == 1
    assert len(client.get('/api/questions').json) == 2


def test_removed_automatic_candidates_are_retained_but_excluded_until_review(tmp_path,monkeypatch):
    client=create_app(tmp_path).test_client();doc=post_pdf(client,sample_pdf()).json
    original=application.extract
    def changed_boundaries(*args,**kwargs):
        result=original(*args,**kwargs);result['questions']=result['questions'][:1];return result
    monkeypatch.setattr(application,'extract',changed_boundaries)
    monkeypatch.setattr(physics,'read_pages',no_ocr)
    result=client.post(f"/api/documents/{doc['id']}/reanalyse",json={})
    assert result.status_code == 200 and result.json['outdated_numbers'] == [2]
    bank=client.get('/api/questions').json
    assert len(bank) == 2 and next(q for q in bank if q['number']==2)['analysis_outdated']
    paper=client.post('/api/papers',json=dict(level='HL',minutes=30,topics=[]))
    assert paper.status_code == 201 and paper.json['count'] == 1
    assert any(reason['code']=='analysis_outdated' for reason in paper.json['diagnostics']['exclusions'])
