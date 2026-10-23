from copy import deepcopy

import fitz
import pytest

from app import create_app
from subquestions import choose_short, question_hash
from topic_scope import POLICY, scoped_question, topic_closure
from test_subquestions import mapped_question, saved_parent, approve


def motion_energy_question():
    q = mapped_question()
    q['topics'] = ['A.1', 'A.3']
    for p in q['subquestions']['parts']:
        p['topics'] = [] if p['id'] == 'stem' else ['A.3'] if p['id'] == 'b' else ['A.1']
    return q


def test_curriculum_prerequisites_are_directional_and_conservative():
    assert {'D.1', 'A.1', 'A.2', 'A.3'} == topic_closure(['D.1'])
    assert topic_closure(['A.2']) == {'A.1', 'A.2'}
    assert 'D.1' not in topic_closure(['A.2'])
    assert topic_closure(['C.3']) == {'C.3', 'C.2', 'C.1', 'A.3', 'A.2', 'A.1'}
    assert 'B.1' not in topic_closure(['C.3'])  # No alphabetical/theme-wide order.
    gravity = dict(id='g', minutes=10, topics=['D.1', 'A.2'], paper='Paper 2', text='gravity and circular motion', regions=[])
    assert scoped_question(gravity, ['D.1']) is not None
    assert scoped_question(gravity, ['A.2']) is None
    gravity['topics'] = ['A.2']
    assert scoped_question(gravity, ['D.1']) is None  # Earlier-only questions are not gravity targets.


def test_optional_energy_extension_is_removed_for_motion():
    q = motion_energy_question()
    result = scoped_question(q, ['A.1'])
    assert result['kept_parts'] == ['stem', 'a', 'c']
    assert result['omitted_parts'] == ['b'] and result['minutes'] == 7
    assert result['topics'] == ['A.1'] and result['marks'] is None
    assert q['regions'] == mapped_question()['regions']
    result = scoped_question(q, ['A.1', 'A.3'])
    assert result['omitted_parts'] == []


def test_dependency_on_out_of_scope_content_cannot_be_hidden():
    q = motion_energy_question()
    parts = q['subquestions']['parts']
    parts[1]['requires'] = ['stem', 'b']
    parts[2]['requires'] = ['stem']
    parts[3]['requires'] = ['stem', 'a']
    assert scoped_question(q, ['A.1']) is None
    parts[0]['topics'] = ['A.3']
    assert scoped_question(q, ['A.1']) is None  # The shared stem cannot be dropped.


def test_multi_topic_inseparable_part_needs_all_topics_in_scope():
    q = motion_energy_question()
    q['subquestions']['parts'][1]['topics'] = ['A.1', 'A.3']
    q['subquestions']['parts'][3]['topics'] = ['A.3']
    assert scoped_question(q, ['A.1']) is None
    assert scoped_question(q, ['A.3']) is not None  # Energy allows its earlier motion foundation.


def test_unknown_or_stale_annotations_do_not_enable_topic_cropping():
    q = motion_energy_question()
    q['subquestions']['parts'][2]['topics'] = []
    assert scoped_question(q, ['A.1']) is None
    q = motion_energy_question()
    q['minutes'] = 11
    assert scoped_question(q, ['A.1']) is None


def test_short_keeps_a_target_topic_not_just_its_prerequisites():
    q = motion_energy_question()
    q['topics'] = ['D.1', 'A.2']
    parts = q['subquestions']['parts']
    parts[1]['topics'] = ['D.1']
    parts[2]['topics'] = ['A.2']
    parts[3]['topics'] = ['A.2']
    parts[2]['requires'] = ['stem']
    results = choose_short([q], 10, ['D.1'])
    assert len(results) == 1 and 'a' in results[0]['kept_parts']
    assert 'stem' in results[0]['kept_parts']
    assert results[0]['kept_parts'] == ['stem', 'a']


def test_invalid_curriculum_policy_is_rejected(monkeypatch):
    monkeypatch.setitem(POLICY['requires'], 'A.1', ['D.1'])
    with pytest.raises(ValueError, match='Circular'):
        topic_closure(['D.1'])


def test_search_png_and_full_topic_paper_use_same_scoped_parts(tmp_path):
    client = create_app(tmp_path).test_client()
    q = saved_parent(client)
    parts = approve(client, q)
    for p in parts:
        p['topics'] = [] if p['id'] == 'stem' else ['A.3'] if p['id'] == 'b' else ['A.1']
    result = client.post(f"/api/questions/{q['id']}/subquestions/approve", json=dict(parts=parts, confirmed=True))
    assert result.status_code == 200, result.json
    matches = client.get('/api/questions?topic=A.1').json
    assert len(matches) == 1 and matches[0]['omitted_parts'] == ['b']
    assert 'BETA_ENERGY' not in matches[0]['text']
    assert client.get(f"/api/questions/{q['id']}/image?topic=A.1").mimetype == 'image/png'
    # Full retains all in-scope tasks but still excludes optional later-topic material.
    generated = client.post('/api/papers', json=dict(level='HL', minutes=10, topics=['A.1']))
    assert generated.status_code == 201, generated.json
    assert generated.json['render_mode'] == 'full'
    assert generated.json['selections'][0]['topic_omitted_parts'] == ['b']
    output = client.get(f"/api/papers/{generated.json['id']}/download")
    with fitz.open(stream=output.data, filetype='pdf') as pdf:
        text = '\n'.join(page.get_text() for page in pdf)
    assert 'ALPHA_SPEED' in text and 'GAMMA_UNIT' in text and 'BETA_ENERGY' not in text
    combined = client.get('/api/questions?topic=A.1&topic=A.3').json
    assert len(combined) == 1 and combined[0]['omitted_parts'] == []
    original = client.get('/api/documents/' + q['document_id']).json['questions'][0]
    assert original['regions'] == q['regions'] and 'BETA_ENERGY' in original['text']


def test_all_24_content_deductions_are_consistent_and_acyclic():
    from physics import TOPICS
    assert set(POLICY['requires']) == set(TOPICS) == set(POLICY['topic_analysis'])
    assert 'example_sl_route' not in POLICY
    for code, detail in POLICY['topic_analysis'].items():
        assert detail['core_prerequisites'] == POLICY['requires'][code]
        assert detail['summary'] and detail['deduction'] and detail['printed_pages']
        assert set(detail['conditional_links']).issubset(TOPICS)
        assert code not in detail['core_prerequisites']
        assert code in topic_closure([code])  # Traverses and rejects cycles/unknown codes.
    assert 'B.4' not in topic_closure(['E.4'])  # A power-plant extension is conditional.
    assert 'D.1' not in topic_closure(['D.2'])  # A gravitational analogy is not a prerequisite.
    assert 'A.5' not in topic_closure(['C.5'])  # Relativistic Doppler is conditional.
    assert topic_closure(['A.5']) == {'A.5', 'A.1'}
    assert {'D.2', 'B.5', 'A.3'} <= topic_closure(['D.4'])
