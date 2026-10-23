from copy import deepcopy
from io import BytesIO

import fitz
import pytest

from app import create_app
from dependency_review import analyze_dependencies
from subquestions import approved_map, choose_short, question_hash, render_variant, short_variants, validate_graph, validate_layout


def mapped_question():
    q = dict(id='q1', minutes=10., paper='Paper 2', text='Shared experiment. a speed. b uses a. c independent.',
             regions=[dict(page=0, rect=[30, 60, 560, 450])])
    parts = [dict(id='stem', label='Shared stem', minutes=1, requires=[], regions=[dict(page=0, rect=[30, 60, 560, 130])], text='Shared experiment.'),
             dict(id='a', label='(a)', minutes=3, requires=['stem'], regions=[dict(page=0, rect=[30, 130, 560, 240])], text='Calculate the speed.'),
             dict(id='b', label='(b)', minutes=3, requires=['stem', 'a'], regions=[dict(page=0, rect=[30, 240, 560, 350])], text='Using your answer in (a), calculate force.'),
             dict(id='c', label='(c)', minutes=2, requires=['stem'], regions=[dict(page=0, rect=[30, 350, 560, 450])], text='State an unrelated unit.')]
    q['subquestions'] = dict(version=1, status='approved', source_hash=question_hash(q), parts=parts)
    return q


def test_direction_is_child_requires_parent_not_reverse():
    q = mapped_question()
    assert render_variant(q, ['b'])['kept_parts'] == ['stem', 'a', 'c']
    with pytest.raises(ValueError, match='prerequisite'):
        render_variant(q, ['a'])
    assert render_variant(q, ['b', 'c'])['kept_parts'] == ['stem', 'a']
    for omitted in [['stem'], ['unknown'], ['a', 'b', 'c']]:
        with pytest.raises(ValueError):
            render_variant(q, omitted)


def test_short_prefers_independent_removal_then_safe_dependent_leaves():
    q = mapped_question()
    variants = short_variants(q)
    assert variants[0]['omitted_parts'] == ['c'] and variants[0]['minutes'] == 8
    assert variants[1]['omitted_parts'] == ['b', 'c'] and variants[1]['minutes'] == 5
    assert choose_short([q], 10)[0]['omitted_parts'] == ['c']
    assert choose_short([q], 6)[0]['omitted_parts'] == ['b', 'c']
    assert choose_short([q], 4) == []
    assert len(choose_short([q], 30)) == 1  # Never select the same parent twice.
    assert render_variant(q)['regions'] == q['regions']  # Full is lossless.


def test_transitive_dependencies_and_stale_review():
    q = mapped_question()
    q['subquestions']['parts'][3]['requires'] = ['stem', 'b']
    with pytest.raises(ValueError):
        render_variant(q, ['b'])
    with pytest.raises(ValueError):
        render_variant(q, ['a'])
    assert render_variant(q, ['b', 'c'])['kept_parts'] == ['stem', 'a']
    q['minutes'] = 11
    assert approved_map(q) is None
    assert short_variants(q)[0]['regions'] == q['regions']
    with pytest.raises(ValueError, match='Approve'):
        render_variant(q, ['c'])


def test_cycles_and_missing_stem_edges_are_rejected():
    parts = mapped_question()['subquestions']['parts']
    parts[1]['requires'] = ['stem', 'b']
    with pytest.raises(ValueError, match='Circular'):
        validate_graph(parts)
    parts[1]['requires'] = []
    with pytest.raises(ValueError, match='stem'):
        validate_graph(parts)


@pytest.mark.parametrize('change', ['gap', 'overlap', 'narrow', 'outside', 'excess_time'])
def test_layout_cannot_drop_or_duplicate_shared_context(change):
    q = mapped_question()
    parts = deepcopy(q['subquestions']['parts'])
    if change == 'gap': parts[1]['regions'][0]['rect'][1] += 10
    if change == 'overlap': parts[1]['regions'][0]['rect'][1] -= 10
    if change == 'narrow': parts[1]['regions'][0]['rect'][0] += 10
    if change == 'outside': parts[1]['regions'][0]['rect'][3] = 999
    if change == 'excess_time': parts[1]['minutes'] = 100
    with pytest.raises(ValueError):
        validate_layout(q, parts)


def model_output(parts):
    return dict(stem_topics=[], parts=[dict(id=p['id'], topics=['A.2'], requires=['a'] if p['id'] == 'b' else [], confidence='high',
                           quote=p['text'], reason='This prompt uses (a).' if p['id'] == 'b' else 'Self-contained with the shared stem.')
                       for p in parts if p['id'] != 'stem'])


def test_model_dependency_proposals_are_grounded_and_not_approved():
    parts = mapped_question()['subquestions']['parts']
    result = analyze_dependencies(parts, completion=lambda *args, **kw: (model_output(parts), {'model': 'test-double'}))
    assert result['status'] == 'proposed'
    assert result['parts'][2]['requires'] == ['stem', 'a']
    assert result['parts'][3]['requires'] == ['stem']
    assert parts[2]['requires'] == ['stem', 'a']


@pytest.mark.parametrize('failure', ['unknown', 'cycle', 'quote', 'missing', 'uncertain'])
def test_invalid_or_uncertain_model_result_never_enables_pruning(failure):
    parts = mapped_question()['subquestions']['parts']
    value = model_output(parts)
    if failure == 'unknown': value['parts'][0]['requires'] = ['fake']
    if failure == 'cycle': value['parts'][0]['requires'] = ['b']
    if failure == 'quote': value['parts'][1]['quote'] = 'An invented source quotation.'
    if failure == 'missing': value['parts'].pop()
    if failure == 'uncertain': value['parts'][0]['confidence'] = 'low'
    result = analyze_dependencies(parts, completion=lambda *args, **kw: (value, {'model': 'test-double'}))
    assert result['status'] == 'needs_review' and result['parts'] == parts


def dependency_pdf():
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((50, 45), 'IB Physics Higher level Paper 2 2025')
        page.insert_text((50, 90), '1. Shared experiment: a trolley and its mass.')
        page.insert_text((65, 150), '(a) Calculate ALPHA_SPEED, the average velocity. [2]')
        page.insert_text((65, 250), '(b) Using your answer in (a), calculate BETA_ENERGY, the kinetic energy. [2]')
        page.insert_text((65, 350), '(c) State GAMMA_UNIT for velocity independently. [1]')
        return pdf.tobytes()


def saved_parent(client):
    response = client.post('/api/documents', data={'file': (BytesIO(dependency_pdf()), 'physics.pdf')})
    assert response.status_code == 201, response.json
    doc = response.json
    q = dict(doc['questions'][0], document_id=doc['id'], topics=['A.2'], minutes=10)
    saved = client.post('/api/questions', json=q)
    assert saved.status_code == 201, saved.json
    return dict(saved.json, document_id=doc['id'])


def approve(client, q):
    response = client.get(f"/api/questions/{q['id']}/subquestions")
    assert response.status_code == 200, response.json
    parts = response.json['mapping']['parts']
    assert [p['id'] for p in parts] == ['stem', 'a', 'b', 'c']
    for part in parts:
        part['requires'] = [] if part['id'] == 'stem' else ['stem', 'a'] if part['id'] == 'b' else ['stem']
        part['minutes'] = {'stem': 1, 'a': 3, 'b': 3, 'c': 2}[part['id']]
    response = client.post(f"/api/questions/{q['id']}/subquestions/approve", json=dict(parts=parts, confirmed=True))
    assert response.status_code == 200, response.json
    return parts


def paper(client, mode=None, minutes=10):
    body = dict(level='HL', syllabus='2025', minutes=minutes)
    if mode is not None: body['render_mode'] = mode
    response = client.post('/api/papers', json=body)
    assert response.status_code == 201, response.json
    download = client.get(f"/api/papers/{response.json['id']}/download")
    with fitz.open(stream=download.data, filetype='pdf') as pdf:
        text = '\n'.join(page.get_text() for page in pdf)
    return response.json, text


def test_full_default_short_dependency_closure_and_persistence(tmp_path):
    client = create_app(tmp_path).test_client()
    q = saved_parent(client)
    before, _ = paper(client, 'short')
    assert before['short_fallbacks'] == [q['id']]
    approve(client, q)
    full, text = paper(client)
    assert full['render_mode'] == 'full' and full['actual_minutes'] == 10
    assert all(token in text for token in ('Shared experiment', 'ALPHA_SPEED', 'BETA_ENERGY', 'GAMMA_UNIT'))
    short, text = paper(client, 'short')
    assert short['actual_minutes'] == 8 and short['short_fallbacks'] == []
    assert short['selections'][0]['omitted_parts'] == ['c']
    assert 'Shared experiment' in text and 'ALPHA_SPEED' in text and 'BETA_ENERGY' in text and 'GAMMA_UNIT' not in text
    shorter, text = paper(client, 'short', 6)
    assert shorter['actual_minutes'] == 5 and shorter['selections'][0]['kept_parts'] == ['stem', 'a']
    assert 'ALPHA_SPEED' in text and 'BETA_ENERGY' not in text and 'GAMMA_UNIT' not in text
    assert create_app(tmp_path).test_client().get(f"/api/questions/{q['id']}/subquestions").json['mapping']['status'] == 'approved'


def test_custom_omissions_and_changed_parent_are_checked(tmp_path):
    client = create_app(tmp_path).test_client()
    q = saved_parent(client)
    parts = approve(client, q)
    url = f"/api/questions/{q['id']}/render"
    assert client.post(url, json=dict(mode='short', omitted_parts=['b'])).mimetype == 'image/png'
    assert client.post(url, json=dict(mode='short', omitted_parts=['a'])).status_code == 400
    assert client.post(url, json=dict(mode='full', omitted_parts=['c'])).status_code == 400
    assert client.post(url, json=dict(mode='short', omitted_parts=['stem'])).status_code == 400
    assert client.post(f"/api/questions/{q['id']}/subquestions/approve", json=dict(parts=parts, confirmed=False)).status_code == 400
    changed = client.post('/api/questions', json=dict(q, minutes=11))
    assert changed.status_code == 201 and changed.json['subquestions'] is None
    assert client.post(url, json=dict(mode='short', omitted_parts=['c'])).status_code == 400


def test_model_endpoint_cannot_auto_approve(tmp_path, monkeypatch):
    client = create_app(tmp_path).test_client()
    q = saved_parent(client)
    def proposal(parts):
        return analyze_dependencies(parts, completion=lambda *args, **kw: (model_output(parts), {'model': 'test-double'}))
    monkeypatch.setattr('app.analyze_dependencies', proposal)
    result = client.post(f"/api/questions/{q['id']}/subquestions/analyze", json={})
    assert result.status_code == 200 and result.json['status'] == 'draft'
    assert result.json['model_review']['status'] == 'proposed'
    assert client.post(f"/api/questions/{q['id']}/render", json=dict(mode='short', omitted_parts=['c'])).status_code == 400
