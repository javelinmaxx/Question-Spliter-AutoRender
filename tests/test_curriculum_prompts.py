"""Verify curriculum delivery and evidence boundaries, not model intelligence."""
import json

import pytest

from curriculum_context import curriculum_context, OCR_PROMPT_VERSION, DEPENDENCY_PROMPT_VERSION
from dependency_review import analyze_dependencies
from language_review import review_disagreement, validate_response
from physics import TOPICS
from test_language_review import PDF, OCR, model_response
from test_subquestions import mapped_question, model_output
from test_model_backfill import setup_disagreement


def test_curriculum_guidance_covers_catalogue_without_adding_prerequisite_tags():
    context=curriculum_context(TOPICS)
    assert set(context['topic_guidance'])==set(TOPICS)
    assert all(row['assesses'] for row in context['topic_guidance'].values())
    context=curriculum_context(['D.1'])
    assert set(context['topic_guidance'])=={'D.1'}
    assert 'A.2' in context['topic_guidance']['D.1']['earlier_foundations']
    assert any('centripetal' in text and 'gravitational' in text for text in context['distinctions'])
    assert 'not an official' in curriculum_context(['A.0'])['distinctions'][0]


def test_topic_review_includes_focused_definitions_and_unmodified_sources():
    def completion(**kwargs):
        system=kwargs['messages'][0]['content']
        payload=json.loads(kwargs['messages'][1]['content'])
        guidance=payload['curriculum_context']['topic_guidance']
        assert set(guidance)=={'C.5'}
        assert 'observer' in guidance['C.5']['assesses'].lower()
        assert payload['untrusted_document_sources']==dict(pdf=PDF,ocr=OCR)
        assert 'never invent' in system.lower()
        assert 'prerequisite' in system and 'abstain' in system
        return dict(choices=[dict(finish_reason='stop',message=dict(content=json.dumps(model_response())))])
    result=review_disagreement(PDF,OCR,'Paper 1A',['C.5'],[],TOPICS,completion=completion)
    assert result['status']=='resolved' and result['prompt_version']==OCR_PROMPT_VERSION


def test_curriculum_definition_is_not_accepted_as_source_evidence():
    definition=curriculum_context(['C.5'])['topic_guidance']['C.5']['assesses']
    with pytest.raises(ValueError,match='not found'):
        validate_response(model_response(evidence=[dict(topic='C.5',source='pdf',quote=definition)]),PDF,OCR,['C.5'])


def test_dependency_prompt_keeps_all_topic_choices_and_source_parts():
    parts=mapped_question()['subquestions']['parts']
    def completion(system,payload,schema):
        assert payload['topic_catalog']==TOPICS
        assert 'curriculum_context' in payload
        assert 'A.2' in payload['curriculum_context']['topic_guidance']
        assert [p['text'] for p in payload['untrusted_parts']]==[p['text'] for p in parts]
        assert 'does NOT require' in system and 'Sharing a topic alone' in system
        assert 'Do not add prerequisite topics' in system
        return model_output(parts),{'model':'stand-in'}
    result=analyze_dependencies(parts,completion=completion)
    assert result['status']=='proposed' and result['prompt_version']==DEPENDENCY_PROMPT_VERSION


def test_backfill_refreshes_old_prompt_once_using_saved_text(tmp_path,monkeypatch):
    _,client,doc,job=setup_disagreement(tmp_path,monkeypatch)
    from language_review import context_hash
    calls=[]
    def review(*args):
        calls.append(1)
        return dict(status='needs_review',input_hash=context_hash(*args),model='qwen',reason='Check manually')
    job.review=review
    job.run_once()
    with job.connection() as conn:
        data=json.loads(conn.execute('SELECT data FROM documents WHERE id=?',(doc['id'],)).fetchone()[0])
        data['questions'][0]['language_review']['prompt_version']='physics-ocr-v1'
        conn.execute('UPDATE documents SET data=? WHERE id=?',(json.dumps(data),doc['id']))
    monkeypatch.setattr('physics.read_pages',lambda *args:pytest.fail('OCR must not repeat'))
    job.run_once();job.run_once()
    assert len(calls)==2
    assert client.get('/api/documents/'+doc['id']).json['questions'][0]['language_review']['prompt_version']==OCR_PROMPT_VERSION


def test_old_dependency_prompt_is_refreshed_but_approved_map_is_not(tmp_path):
    from app import create_app
    from test_subquestions import saved_parent, approve
    app=create_app(tmp_path);client=app.test_client();saved_parent(client)
    job=app.extensions['model_backfill'];job.availability=lambda:dict(available=True)
    calls=[]
    def review(parts):
        calls.append(1)
        return dict(status='needs_review',parts=parts,reason='Review this draft')
    job.dependencies=review;job.run_once()
    with job.connection() as conn:
        qid,raw=conn.execute('SELECT id,data FROM questions').fetchone()
        q=json.loads(raw)
        q['subquestions']['model_review']['prompt_version']='old'
        conn.execute('UPDATE questions SET data=? WHERE id=?',(json.dumps(q),qid))
    job.run_once();job.run_once()
    assert len(calls)==2
    q=client.get('/api/questions').json[0]
    approve(client,q)
    with job.connection() as conn:
        raw=conn.execute('SELECT data FROM questions WHERE id=?',(qid,)).fetchone()[0]
        q=json.loads(raw);q['subquestions']['model_review']['prompt_version']='old'
        conn.execute('UPDATE questions SET data=? WHERE id=?',(json.dumps(q),qid))
    job.run_once()
    assert len(calls)==2
    assert client.get('/api/questions').json[0]['subquestions']['status']=='approved'
