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
