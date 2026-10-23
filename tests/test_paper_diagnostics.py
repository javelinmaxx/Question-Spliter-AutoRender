import json
import sqlite3

import pytest

from app import create_app
from test_workflow import upload, save
from test_subquestions import saved_parent, approve
from test_topic_scope import motion_energy_question
from topic_scope import scope_decision


@pytest.fixture
def bank(tmp_path):
    return create_app(tmp_path).test_client(), tmp_path


def build(client, **changes):
    value = dict(level='HL', syllabus='2025', minutes=30, topics=[])
    value.update(changes)
    return client.post('/api/papers', json=value)


def reasons(response):
    return {r['code']: r for r in response.json['diagnostics']['exclusions']}


def test_empty_bank_and_analyzed_but_unimported_are_distinguished(bank):
    client, _ = bank
    result = build(client)
    assert result.status_code == 400 and 'empty' in result.json['error']
    assert result.json['diagnostics']['uploaded_documents'] == 0
    doc = upload(client)
    result = build(client)
    assert result.status_code == 400
    assert result.json['diagnostics']['analyzed_not_imported'] == len(doc['questions'])
    assert 'Confirm import' in result.json['error']


@pytest.mark.parametrize('filters,code', [
    (dict(syllabus='Legacy'),'syllabus'),(dict(paper='Paper 1A'),'paper')])
def test_filter_failures_include_counts_actual_metadata_and_examples(bank, filters, code):
    client, _ = bank
    doc = upload(client)
    save(client, doc);save(client, doc, 1)
    result = build(client, **filters)
    assert result.status_code == 400
    report = result.json['diagnostics']
    assert report['bank_syllabuses'] == {'2025':2} and report['bank_levels'] == {'HL':2}
    assert reasons(result)[code]['count'] == 2
    assert reasons(result)[code]['examples'][0]['filename'] == doc['filename']
    assert reasons(result)[code]['action']


def test_topic_filter_explains_missing_review_and_unrelated_questions(bank):
    client, _ = bank
    doc = upload(client)
    save(client, doc);save(client, doc, 1)
    result = build(client, topics=['A.1'])
    assert result.status_code == 400
    assert reasons(result)['topic_review']['count'] == 1
    assert reasons(result)['topic_target']['count'] == 1
    assert result.json['diagnostics']['fitting_budget'] == 0


def test_duration_error_reports_the_shortest_usable_version(bank):
    client, _ = bank
    doc = upload(client)
    save(client,doc);save(client,doc,1)
    result = build(client, minutes=1)
    assert result.status_code == 400 and 'shortest valid version needs 8.3 minutes' in result.json['error']
    assert result.json['diagnostics']['matching_filters'] == 2
    assert reasons(result)['duration']['count'] == 2
    assert result.json['diagnostics']['shortest_valid_minutes'] == 8.3


def test_short_diagnostics_use_dependency_safe_variants_not_parent_time(bank):
    client, _ = bank
    q = saved_parent(client);approve(client,q)
    full = build(client, minutes=5)
    assert full.status_code == 400 and full.json['diagnostics']['shortest_valid_minutes'] == 10
    short = build(client, minutes=5, render_mode='short')
    assert short.status_code == 201,short.json
    assert short.json['diagnostics']['shortest_valid_minutes'] == 5
    assert short.json['actual_minutes'] == 5


@pytest.mark.parametrize('target,expected',[(100,'below the 100-minute target'),(10,'selected combination leaves 3 minutes')])
def test_partial_paper_still_downloads_and_explains_shortfall(bank, target, expected):
    client, root = bank
    doc = upload(client)
    save(client,doc,minutes=7);save(client,doc,1,minutes=6)
    result = build(client,minutes=target)
    assert result.status_code == 201,result.json
    report = result.json['diagnostics']
    assert expected in report['summary']
    assert report['shortfall_minutes'] == result.json['shortfall_minutes'] > 0
    assert client.get(f"/api/papers/{result.json['id']}/download").mimetype == 'application/pdf'
    with sqlite3.connect(root / 'bank.sqlite3') as conn:
        stored=json.loads(conn.execute('SELECT data FROM papers WHERE id=?',(result.json['id'],)).fetchone()[0])
    assert stored['diagnostics'] == report


def test_missing_source_and_sl_conflicts_have_specific_reasons(bank):
    client,root = bank
    doc=upload(client);q=save(client,doc,level='Both')
    with sqlite3.connect(root/'bank.sqlite3') as conn:
        value=json.loads(conn.execute('SELECT data FROM questions WHERE id=?',(q['id'],)).fetchone()[0])
        value['level_conflicts']=['A.4']
        conn.execute('UPDATE questions SET data=? WHERE id=?',(json.dumps(value),q['id']))
    result=build(client,level='SL')
    assert result.status_code == 400 and reasons(result)['sl_content']['count'] == 1
    (root/'documents'/(doc['id']+'.pdf')).unlink()
    result=build(client)
    assert result.status_code == 400 and reasons(result)['source']['count'] == 1


def test_precise_scope_reasons_share_the_actual_scope_rules():
    q=motion_energy_question()
    parts=q['subquestions']['parts']
    parts[0]['topics']=['A.3']
    assert scope_decision(q,['A.1'])[1] == 'topic_context'
    parts[0]['topics']=[]
    parts[1]['requires']=['stem','b'];parts[2]['requires']=['stem'];parts[3]['requires']=['stem','a']
    assert scope_decision(q,['A.1'])[1] == 'topic_dependency'
    parts[1]['requires']=['stem'];parts[3]['requires']=['stem']
    parts[1]['topics']=['A.1','A.3'];parts[3]['topics']=['A.3']
    assert scope_decision(q,['A.1'])[1] == 'topic_inseparable'
