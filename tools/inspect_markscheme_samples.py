from pathlib import Path
import fitz

from exam_identity import parse_exam_identity
from markscheme_data import extract_markscheme_entries, extract_markscheme_regions

ROOT = Path("TEST SAMPLES")
PAIRS = [
    ("Physics_paper_1__TZ1_HL.pdf", "Physics_paper_1__TZ1_HL_markscheme.pdf"),
    ("Physics_paper_2__TZ1_HL.pdf", "Physics_paper_2__TZ1_HL_markscheme.pdf"),
    ("Physics_paper_3__TZ1_HL.pdf", "Physics_paper_3__TZ1_HL_markscheme.pdf"),
]

for paper_name, marks_name in PAIRS:
    paper_path, marks_path = ROOT / paper_name, ROOT / marks_name
    with fitz.open(paper_path) as paper_pdf, fitz.open(marks_path) as marks_pdf:
        paper_text = "\n".join(page.get_text(sort=True) for page in paper_pdf)
        marks_texts = [page.get_text(sort=True) for page in marks_pdf]
        paper_identity = parse_exam_identity(paper_text, paper_name)
        marks_identity = parse_exam_identity("\n".join(marks_texts), marks_name)
        regions = extract_markscheme_regions(marks_pdf, marks_identity["paper"])
        entries = extract_markscheme_entries(marks_texts, marks_identity["paper"], regions)
        print({
            "paper": paper_name,
            "marks": marks_name,
            "identity": (paper_identity["year"], paper_identity["paper"], paper_identity["timezone"]),
            "marks_identity": (marks_identity["year"], marks_identity["paper"], marks_identity["timezone"]),
            "question_numbers": sorted(entries),
            "question_regions": sum(bool(entry["regions"]) for entry in entries.values()),
        })
