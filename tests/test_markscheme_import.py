from io import BytesIO
from pathlib import Path
import json
import sqlite3

import fitz
import pytest

import app as application
from app import create_app
from exam_identity import match_question_to_markscheme

ROOT = Path(__file__).resolve().parents[1] / "TEST SAMPLES"


def post_pdf(client, endpoint, path):
    return client.post(endpoint, data={
        "file": (BytesIO(path.read_bytes()), path.name),
        "ocr_mode": "off",
    })


def test_legacy_2000_markscheme_import_preserves_sections_and_unknown_timezone(tmp_path):
    client = create_app(tmp_path).test_client()
    path = ROOT / 'Physics HL - May 2000 - P2 MS.pdf'
    response = post_pdf(client, '/api/markschemes', path)
    assert response.status_code == 201, response.json
    data = response.json
    assert (data['identity']['year'], data['identity']['session'], data['identity']['level'],
            data['identity']['paper'], data['identity']['timezone']) == (2000, 'May', 'HL', 'Paper 2', None)
    assert data['question_numbers'] == ['A1', 'A2', 'A3', 'A4', 'B1', 'B2', 'B3', 'B4']
    assert [r['page'] for r in data['entries']['A1']['regions']] == [1, 2]
    assert [r['page'] for r in data['entries']['B4']['regions']] == [15, 16, 17]
    question = dict(year=2000, paper='Paper 2', timezone='TZ1', number=1)
    assert not match_question_to_markscheme(question, data['identity'], data['question_numbers'])['matched']
    legacy_q = dict(question, exam_identifier='M00/430/H(2)', source_label='B1')
    assert match_question_to_markscheme(legacy_q, data['identity'], data['question_numbers'])['matched']
    assert not match_question_to_markscheme(dict(legacy_q, exam_identifier='N00/430/H(2)'), data['identity'], data['question_numbers'])['matched']


def test_legacy_paper_section_labels_are_retained_for_matching(tmp_path):
    client = create_app(tmp_path).test_client()
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((50, 40), 'M00/430/H(2) Physics Higher Level Paper 2 May 2000')
        page.insert_text((50, 100), 'A1. Calculate the momentum of the moving object.')
        page.insert_text((50, 200), 'A2. Explain the effect of the net force.')
        page.insert_text((50, 300), 'B1. Determine the energy of the moving object.')
        data = pdf.tobytes()
    response = client.post('/api/documents', data={'file': (BytesIO(data), 'physics.pdf'), 'ocr_mode': 'off'})
    assert response.status_code == 201, response.json
    doc = response.json
    assert [q['source_label'] for q in doc['questions']] == ['A1', 'A2', 'B1']
    assert client.post(f"/api/documents/{doc['id']}/confirm-import", json={}).status_code == 200
    questions = client.get('/api/questions').json
    assert {q['source_label'] for q in questions} == {'A1', 'A2', 'B1'}
    assert all(q['exam_identifier'] == 'M00/430/H(2)' for q in questions)
    assert post_pdf(client, '/api/markschemes', ROOT / 'Physics HL - May 2000 - P2 MS.pdf').status_code == 201
    b1 = next(q for q in questions if q['source_label'] == 'B1')
    result = client.post('/api/papers', json=dict(level='HL', syllabus='Legacy', minutes=100,
                         topics=[], question_ids=[b1['id']]))
    assert result.status_code == 201, result.json
    assert result.json['markscheme']['matched_questions'] == 1
    assert result.json['markscheme']['generated']
    with fitz.open(tmp_path / 'papers' / (result.json['id'] + '-markscheme.pdf')) as marked:
        assert 'source QB1' in marked[0].get_text()


def test_restart_fills_missing_saved_question_timezone_from_source(tmp_path):
    client = create_app(tmp_path).test_client()
    paper = post_pdf(client, '/api/documents', ROOT / 'Physics_paper_1__TZ1_HL.pdf').json
    assert client.post(f"/api/documents/{paper['id']}/confirm-import", json={}).status_code == 200
    with sqlite3.connect(tmp_path / 'bank.sqlite3') as conn:
        rows = conn.execute('SELECT id, data FROM questions').fetchall()
        for qid, raw in rows:
            q = json.loads(raw)
            q['timezone'] = None
            conn.execute('UPDATE questions SET data=? WHERE id=?', (json.dumps(q), qid))
    reopened = create_app(tmp_path).test_client()
    assert all(q['timezone'] == 'TZ1' for q in reopened.get('/api/questions').json)


def test_markscheme_import_indexes_ocr_after_native_text(tmp_path, monkeypatch):
    client = create_app(tmp_path).test_client()
    def read(pdf, *args):
        return ([dict(text='1. A\n2. C', native=pdf[0].get_text())], [])
    monkeypatch.setattr(application, 'read_pages', read)
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((50, 90), 'Markscheme May 2024 Physics Higher level Paper 1 TZ1')
        payload = pdf.tobytes()
    result = client.post('/api/markschemes', data={'file': (BytesIO(payload), 'physics_markscheme.pdf')})
    assert result.status_code == 201, result.json
    assert result.json['question_numbers'] == [1, 2]


def test_ambiguous_markschemes_can_be_reviewed_and_resolved_without_new_paper(tmp_path):
    client = create_app(tmp_path).test_client()
    paper = post_pdf(client, '/api/documents', ROOT / 'Physics_paper_1__TZ1_HL.pdf').json
    assert client.post(f"/api/documents/{paper['id']}/confirm-import", json={}).status_code == 200
    question = next(q for q in client.get('/api/questions').json if q['number'] == 3)
    original = ROOT / 'Physics_paper_1__TZ1_HL_markscheme.pdf'
    first = post_pdf(client, '/api/markschemes', original).json
    with fitz.open(original) as source:
        source.set_metadata(dict(source.metadata, title='Alternative copy'))
        copy = source.tobytes()
    second = client.post('/api/markschemes', data={'file': (BytesIO(copy), 'alternative_markscheme.pdf'), 'ocr_mode': 'off'}).json
    generated = client.post('/api/papers', json=dict(level='HL', syllabus='Legacy', minutes=45, topics=[], question_ids=[question['id']]))
    assert generated.status_code == 201, generated.json
    paper_id = generated.json['id']
    ambiguous = generated.json['markscheme']['ambiguous_questions']
    assert len(ambiguous) == 1
    assert {c['id'] for c in ambiguous[0]['candidates']} == {first['id'], second['id']}
    assert client.get(f"/api/markschemes/{second['id']}/source").status_code == 200
    endpoint = f'/api/papers/{paper_id}/markscheme/resolve'
    assert client.post(endpoint, json={'choices': {question['id']: 'invalid'}}).status_code == 400
    with sqlite3.connect(tmp_path / 'bank.sqlite3') as conn:
        raw = conn.execute('SELECT data FROM questions WHERE id=?', (question['id'],)).fetchone()[0]
        modified = json.loads(raw)
        modified['year'] = 2020
        conn.execute('UPDATE questions SET data=? WHERE id=?', (json.dumps(modified), question['id']))
    result = client.post(endpoint, json={'choices': {question['id']: second['id']}})
    assert result.status_code == 200, result.json
    assert result.json['matched_questions'] == 1 and not result.json['ambiguous_questions']
    assert result.json['choices'] == {question['id']: second['id']}
    saved_question = next(q for q in client.get('/api/questions').json if q['id'] == question['id'])
    assert saved_question['markscheme_link'] == {'markscheme_id': second['id'], 'entry_key': '3'}
    with sqlite3.connect(tmp_path / 'bank.sqlite3') as conn:
        assert conn.execute('SELECT count(*) FROM papers').fetchone()[0] == 1
    future = client.post('/api/papers', json=dict(level='HL', syllabus='Legacy', minutes=45, topics=[], question_ids=[question['id']]))
    assert future.status_code == 201 and future.json['markscheme']['matched_questions'] == 1
    assert client.get(f'/api/papers/{paper_id}/markscheme').status_code == 200


def test_missing_matches_can_be_manually_selected_per_paper(tmp_path):
    from test_workflow import upload, save
    client = create_app(tmp_path).test_client()
    doc = upload(client)
    first = save(client, doc, minutes=7)
    second = save(client, doc, 1, minutes=6)
    marks = post_pdf(client, '/api/markschemes', ROOT / 'Physics_paper_1__TZ1_HL_markscheme.pdf').json
    generated = client.post('/api/papers', json=dict(level='HL', minutes=20, topics=[], question_ids=[first['id'], second['id']]))
    assert generated.status_code == 201 and len(generated.json['markscheme']['missing_questions']) == 2
    paper_id = generated.json['id']
    endpoint = f'/api/papers/{paper_id}/markscheme/resolve'
    assert client.post(endpoint, json={'manual_choices': {first['id']: {'markscheme_id': marks['id'], 'entry_key':'999'}}}).status_code == 400
    assert client.post(endpoint, json={'manual_choices': {'unknown': {'markscheme_id': marks['id'], 'entry_key':'1'}}}).status_code == 400
    for question, key, remaining in [(first, '3', 1), (second, '4', 0)]:
        response = client.post(endpoint, json={'manual_choices': {question['id']: {'markscheme_id': marks['id'], 'entry_key':key}}})
        assert response.status_code == 200, response.json
        assert len(response.json['missing_questions']) == remaining
    assert len(response.json['manual_choices']) == 2
    with fitz.open(tmp_path/'papers'/(paper_id+'-markscheme.pdf')) as output:
        assert len(output) == 2
        assert 'Question 1' in output[0].get_text() and 'source Q3' in output[0].get_text()
        assert 'Question 2' in output[1].get_text() and 'source Q4' in output[1].get_text()
    assert client.get(f'/api/papers/{paper_id}/markscheme').status_code == 200
    with sqlite3.connect(tmp_path/'bank.sqlite3') as conn:
        assert conn.execute('SELECT count(*) FROM papers').fetchone()[0] == 1
    bank = {q['id']: q for q in client.get('/api/questions').json}
    assert bank[first['id']]['markscheme_link'] == {'markscheme_id': marks['id'], 'entry_key':'3'}
    assert bank[second['id']]['markscheme_link'] == {'markscheme_id': marks['id'], 'entry_key':'4'}
    future = client.post('/api/papers', json=dict(level='HL', minutes=20, topics=[], question_ids=[first['id'], second['id']]))
    assert future.status_code == 201 and future.json['markscheme']['matched_questions'] == 2


def test_manual_choice_after_importing_an_exact_match(tmp_path):
    client = create_app(tmp_path).test_client()
    paper = post_pdf(client, '/api/documents', ROOT / 'Physics_paper_1__TZ1_HL.pdf').json
    client.post(f"/api/documents/{paper['id']}/confirm-import", json={})
    q = next(q for q in client.get('/api/questions').json if q['number'] == 3)
    q2 = next(q for q in client.get('/api/questions').json if q['number'] == 4)
    generated = client.post('/api/papers', json=dict(level='HL', syllabus='Legacy', minutes=45, topics=[], question_ids=[q['id'], q2['id']])).json
    assert len(generated['markscheme']['missing_questions']) == 2
    marks = post_pdf(client, '/api/markschemes', ROOT / 'Physics_paper_1__TZ1_HL_markscheme.pdf').json
    result = client.post(f"/api/papers/{generated['id']}/markscheme/resolve", json={'manual_choices': {q['id']: {'markscheme_id': marks['id'], 'entry_key': '3'}}})
    assert result.status_code == 200 and result.json['matched_questions'] == 2
    result = client.post(f"/api/papers/{generated['id']}/markscheme/resolve", json={'manual_choices': {q2['id']: {'markscheme_id': marks['id'], 'entry_key': '4'}}})
    assert result.status_code == 200 and len(result.json['manual_choices']) == 2


def test_markscheme_workspace_saves_valid_choice_for_future_generation(tmp_path):
    client = create_app(tmp_path).test_client()
    paper = post_pdf(client, '/api/documents', ROOT / 'Physics_paper_1__TZ1_HL.pdf').json
    assert client.post(f"/api/documents/{paper['id']}/confirm-import", json={}).status_code == 200
    question = next(q for q in client.get('/api/questions').json if q['number'] == 3)
    original = ROOT / 'Physics_paper_1__TZ1_HL_markscheme.pdf'
    first = post_pdf(client, '/api/markschemes', original).json
    with fitz.open(original) as source:
        source.set_metadata(dict(source.metadata, title='Alternative markscheme'))
        alternative = source.tobytes()
    second = client.post('/api/markschemes', data={'file': (BytesIO(alternative), 'alternative_markscheme.pdf'), 'ocr_mode': 'off'}).json
    overview = client.get('/api/markscheme-matches')
    assert overview.status_code == 200, overview.json
    row = next(q for q in overview.json if q['id'] == question['id'])
    assert row['status'] == 'ambiguous' and {c['id'] for c in row['candidates']} == {first['id'], second['id']}
    picker = client.post('/api/papers/markscheme-status', json={'question_ids':[question['id']]})
    assert picker.status_code == 200 and picker.json[0]['status'] == 'ambiguous'
    assert {c['id'] for c in picker.json[0]['candidates']} == {first['id'], second['id']}
    endpoint = f"/api/questions/{question['id']}/markscheme-choice"
    assert client.post(endpoint, json={'markscheme_id':'invalid'}).status_code == 400
    assert client.post(endpoint, json={'markscheme_id':second['id']}).status_code == 200
    reopened = create_app(tmp_path).test_client()
    row = next(q for q in reopened.get('/api/markscheme-matches').json if q['id'] == question['id'])
    assert row['status'] == 'matched' and row['markscheme_id'] == second['id'] and len(row['candidates']) == 2
    edited = dict(next(q for q in reopened.get('/api/questions').json if q['id'] == question['id']), topics=['A.1'])
    saved = reopened.post('/api/questions', json=edited)
    assert saved.status_code == 201 and saved.json['markscheme_choice'] == second['id']
    result = reopened.post('/api/papers', json=dict(level='HL', syllabus='Legacy', minutes=45, topics=[], question_ids=[question['id']]))
    assert result.status_code == 201 and result.json['markscheme']['matched_questions'] == 1
    assert not result.json['markscheme']['ambiguous_questions']
    assert reopened.post('/api/papers/markscheme-status', json={'question_ids':[question['id']]}).json[0]['status'] == 'matched'
    assert reopened.post(endpoint, json={'markscheme_id':None}).status_code == 200
    assert next(q for q in reopened.get('/api/markscheme-matches').json if q['id'] == question['id'])['status'] == 'ambiguous'


def test_picker_manual_markscheme_link_is_saved_before_generation(tmp_path):
    from test_workflow import upload, save
    client = create_app(tmp_path).test_client()
    doc = upload(client)
    question = save(client, doc)
    marks = post_pdf(client, '/api/markschemes', ROOT / 'Physics_paper_1__TZ1_HL_markscheme.pdf').json
    status = client.post('/api/papers/markscheme-status', json={'question_ids':[question['id']]}).json[0]
    assert status['status'] == 'missing'
    endpoint = f"/api/questions/{question['id']}/markscheme-link"
    assert client.post(endpoint, json={'markscheme_id': marks['id'], 'entry_key':'999'}).status_code == 400
    linked = client.post(endpoint, json={'markscheme_id': marks['id'], 'entry_key':'3'})
    assert linked.status_code == 200, linked.json
    reopened = create_app(tmp_path).test_client()
    status = reopened.post('/api/papers/markscheme-status', json={'question_ids':[question['id']]}).json[0]
    assert status['status'] == 'matched' and status['match_method'] == 'manual'
    assert status['markscheme_id'] == marks['id'] and status['entry_key'] == '3'
    edited = dict(next(q for q in reopened.get('/api/questions').json if q['id'] == question['id']), topics=['A.1'])
    saved = reopened.post('/api/questions', json=edited)
    assert saved.status_code == 201 and saved.json['markscheme_link'] == {'markscheme_id': marks['id'], 'entry_key':'3'}
    generated = reopened.post('/api/papers', json=dict(level='HL',minutes=45,topics=[],question_ids=[question['id']]))
    assert generated.status_code == 201, generated.json
    assert generated.json['markscheme']['matched_questions'] == 1
    assert generated.json['markscheme']['generated'] is True
    assert reopened.get(f"/api/papers/{generated.json['id']}/markscheme").status_code == 200
    assert reopened.post(endpoint, json={'markscheme_id':None}).status_code == 200
    assert reopened.post('/api/papers/markscheme-status', json={'question_ids':[question['id']]}).json[0]['status'] == 'missing'


def test_imported_markscheme_is_stored_without_language_model_review(tmp_path, monkeypatch):
    client = create_app(tmp_path).test_client()
    path = ROOT / "Physics_paper_1__TZ1_HL_markscheme.pdf"
    monkeypatch.setattr(
        application, "review_disagreement",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Markscheme must not be sent to the language model")),
    )
    response = post_pdf(client, "/api/markschemes", path)
    assert response.status_code == 201, response.json
    assert response.json["identity"]["year"] == 2019
    assert response.json["identity"]["paper"] == "Paper 1"
    assert response.json["identity"]["timezone"] == "TZ1"
    assert response.json["question_numbers"] == list(range(1, 41))
    assert response.json["language_model_review"] == "not_run"
    assert client.get("/api/documents").json == []
    assert client.get("/api/questions").json == []
    listed = client.get("/api/markschemes").json
    assert len(listed) == 1 and listed[0]["identity"]["timezone"] == "TZ1"


def test_real_paper_question_matches_imported_markscheme_and_generates_answer_pdf(tmp_path, monkeypatch):
    client = create_app(tmp_path).test_client()
    monkeypatch.setattr(
        application, "review_disagreement",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("This text-based sample should not need model review")),
    )

    paper_path = ROOT / "Physics_paper_1__TZ1_HL.pdf"
    paper_response = post_pdf(client, "/api/documents", paper_path)
    assert paper_response.status_code == 201, paper_response.json
    assert paper_response.json["metadata"]["year"] == 2019
    assert paper_response.json["metadata"]["paper"] == "Paper 1"
    assert paper_response.json["metadata"]["timezone"] == "TZ1"

    imported = client.post(f"/api/documents/{paper_response.json['id']}/confirm-import", json={})
    assert imported.status_code == 200, imported.json
    questions = [q for q in client.get("/api/questions").json
                 if q["document_id"] == paper_response.json["id"]]
    assert questions
    question = next((q for q in questions if q["number"] == 3), questions[0])
    assert question["year"] == 2019 and question["paper"] == "Paper 1"
    assert question["timezone"] == "TZ1"

    marks_path = ROOT / "Physics_paper_1__TZ1_HL_markscheme.pdf"
    marks_response = post_pdf(client, "/api/markschemes", marks_path)
    assert marks_response.status_code == 201, marks_response.json
    assert post_pdf(client, "/api/markschemes", marks_path).status_code == 201
    markscheme = client.get("/api/markschemes").json[0]
    direct_match = match_question_to_markscheme(
        question, markscheme["identity"], markscheme["question_numbers"])
    assert direct_match["matched"], direct_match

    generated = client.post("/api/papers", json={
        "level": "HL", "syllabus": "Legacy", "minutes": 45, "topics": [],
        "paper": "Paper 1", "year_min": 2019, "year_max": 2019,
        "question_ids": [question["id"]],
    })
    assert generated.status_code == 201, generated.json
    assert generated.json["markscheme"]["generated"] is True, generated.json["markscheme"]
    assert generated.json["markscheme"]["matched_questions"] == 1
    assert generated.json["markscheme"]["missing_questions"] == []
    assert generated.json["markscheme"]["ambiguous_questions"] == []

    original_path = tmp_path / "papers" / (generated.json["id"] + "-markscheme.pdf")
    with fitz.open(original_path) as mark_pdf:
        mark_text = "\n".join(page.get_text() for page in mark_pdf)
        assert 'Question 1' in mark_text
        assert f"source Q{question['number']}" in mark_text
        assert "Answer:" in mark_text

    download = client.get(f"/api/papers/{generated.json['id']}/markscheme")
    assert download.status_code == 200 and download.mimetype == "application/pdf"
    with fitz.open(stream=download.data, filetype="pdf") as print_pdf:
        assert len(print_pdf) >= 1
        assert all(len(page.get_images(full=True)) == 1 for page in print_pdf)



@pytest.mark.parametrize(
    "filename,paper,expected_count",
    [
        ("Physics_paper_2__TZ1_HL_markscheme.pdf", "Paper 2", 8),
        ("Physics_paper_3__TZ1_HL_markscheme.pdf", "Paper 3", 20),
    ],
)
def test_structured_sample_markschemes_store_question_specific_page_regions(tmp_path, monkeypatch, filename, paper, expected_count):
    client = create_app(tmp_path).test_client()
    monkeypatch.setattr(
        application, "review_disagreement",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Markscheme OCR must not be sent to the language model")),
    )
    response = post_pdf(client, "/api/markschemes", ROOT / filename)
    assert response.status_code == 201, response.json
    assert response.json["identity"]["paper"] == paper
    assert set(range(1, expected_count + 1)).issubset(set(response.json["question_numbers"]))
    with fitz.open(tmp_path / "markschemes" / (response.json["id"] + ".pdf")) as source:
        entries = response.json["entries"]
        for number in range(1, expected_count + 1):
            assert entries[str(number)]["regions"], f"Question {number} has no source-page crop"
            assert all(0 <= region["page"] < len(source) for region in entries[str(number)]["regions"])



def test_structured_paper_two_markscheme_export_uses_original_source_rows(tmp_path, monkeypatch):
    client = create_app(tmp_path).test_client()
    monkeypatch.setattr(
        application, "review_disagreement",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Markscheme import must not invoke language-model review")),
    )
    paper_path = ROOT / "Physics_paper_2__TZ1_HL.pdf"
    paper_response = post_pdf(client, "/api/documents", paper_path)
    assert paper_response.status_code == 201, paper_response.json
    assert paper_response.json["metadata"]["timezone"] == "TZ1"
    imported = client.post(f"/api/documents/{paper_response.json['id']}/confirm-import", json={})
    assert imported.status_code == 200, imported.json
    question = next(q for q in client.get("/api/questions").json
                    if q["document_id"] == paper_response.json["id"] and q["number"] == 1)
    assert question["timezone"] == "TZ1"

    marks_path = ROOT / "Physics_paper_2__TZ1_HL_markscheme.pdf"
    marks_response = post_pdf(client, "/api/markschemes", marks_path)
    assert marks_response.status_code == 201, marks_response.json
    entry = marks_response.json["entries"]["1"]
    assert entry["regions"], "Question 1 should retain its original markscheme page regions"

    generated = client.post("/api/papers", json={
        "level": "HL", "syllabus": "Legacy", "minutes": 45, "topics": [],
        "paper": "Paper 2", "year_min": 2019, "year_max": 2019,
        "question_ids": [question["id"]],
    })
    assert generated.status_code == 201, generated.json
    assert generated.json["markscheme"]["generated"] is True, generated.json["markscheme"]
    assert generated.json["markscheme"]["matched_questions"] == 1
    original_path = tmp_path / "papers" / (generated.json["id"] + "-markscheme.pdf")
    with fitz.open(original_path) as mark_pdf:
        text = "\n".join(page.get_text() for page in mark_pdf)
        assert "Question 1" in text
        assert len(mark_pdf) == len(entry["regions"])
