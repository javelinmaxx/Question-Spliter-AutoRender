from pathlib import Path

import fitz
import pytest

from exam_identity import (
    identity_key,
    match_question_to_markscheme,
    parse_exam_identity,
    question_numbers_from_markscheme,
)

ROOT = Path(__file__).resolve().parents[1] / "TEST SAMPLES"
PAIRS = [
    ("Physics_paper_1__TZ1_HL.pdf", "Physics_paper_1__TZ1_HL_markscheme.pdf", "Paper 1", 40),
    ("Physics_paper_2__TZ1_HL.pdf", "Physics_paper_2__TZ1_HL_markscheme.pdf", "Paper 2", 11),
    ("Physics_paper_3__TZ1_HL.pdf", "Physics_paper_3__TZ1_HL_markscheme.pdf", "Paper 3", 20),
]


def pdf_text(path):
    with fitz.open(path) as pdf:
        return [page.get_text(sort=True) for page in pdf]


def question_numbers_from_paper(path):
    import re
    with fitz.open(path) as pdf:
        text = "\n".join(page.get_text(sort=True) for page in pdf[3:])
    return {int(number) for number in re.findall(r"(?m)^\s*(\d{1,2})\.\s+(?=[A-Z(])", text)}


@pytest.mark.parametrize("paper_name,marks_name,paper,expected_count", PAIRS)
def test_newly_pushed_papers_match_their_markschemes(paper_name, marks_name, paper, expected_count):
    paper_pages = pdf_text(ROOT / paper_name)
    marks_pages = pdf_text(ROOT / marks_name)
    paper_identity = parse_exam_identity("\n".join(paper_pages), paper_name)
    marks_identity = parse_exam_identity("\n".join(marks_pages), marks_name)

    assert paper_identity["year"] == marks_identity["year"] == 2019
    assert paper_identity["session"] == marks_identity["session"] == "May"
    assert paper_identity["paper"] == marks_identity["paper"] == paper
    assert paper_identity["timezone"] == marks_identity["timezone"] == "TZ1"
    assert paper_identity["level"] == marks_identity["level"] == "HL"
    assert paper_identity["is_markscheme"] is False
    assert marks_identity["is_markscheme"] is True
    assert identity_key(paper_identity) == identity_key(marks_identity)

    paper_numbers = question_numbers_from_paper(ROOT / paper_name)
    marks_numbers = question_numbers_from_markscheme(marks_pages, paper)
    assert len(paper_numbers) == expected_count
    assert paper_numbers == set(range(1, expected_count + 1))
    assert paper_numbers.issubset(marks_numbers)

    for number in paper_numbers:
        question = dict(paper_identity, number=number)
        result = match_question_to_markscheme(question, marks_identity, marks_numbers)
        assert result == {"matched": True, "reason": "exact_match", "question_number": number}


def test_markscheme_match_rejects_wrong_year_paper_timezone_and_number():
    marks = dict(year=2019, paper="Paper 2", timezone="TZ1", is_markscheme=True)
    available = set(range(1, 12))
    base = dict(year=2019, paper="Paper 2", timezone="TZ1", number=1)
    assert match_question_to_markscheme(base, marks, available)["matched"]
    for change, expected in [
        ({"year": 2020}, "year"),
        ({"paper": "Paper 3"}, "paper"),
        ({"timezone": "TZ2"}, "timezone"),
    ]:
        result = match_question_to_markscheme({**base, **change}, marks, available)
        assert result["reason"] == "exam_identity_mismatch"
        assert expected in result["mismatched_fields"]
    assert match_question_to_markscheme({**base, "number": 12}, marks, available)["reason"] == "question_not_in_markscheme"
    assert match_question_to_markscheme({**base, "timezone": None}, marks, available)["reason"] == "question_identity_incomplete"
