from pathlib import Path
import re
import fitz

ROOT = Path("TEST SAMPLES")
FILES = [
    "Physics_paper_1__TZ1_HL.pdf",
    "Physics_paper_1__TZ1_HL_markscheme.pdf",
    "Physics_paper_2__TZ1_HL.pdf",
    "Physics_paper_2__TZ1_HL_markscheme.pdf",
    "Physics_paper_3__TZ1_HL.pdf",
    "Physics_paper_3__TZ1_HL_markscheme.pdf",
]

for name in FILES:
    path = ROOT / name
    print(f"\\n===== {name} =====")
    with fitz.open(path) as pdf:
        print(f"pages={len(pdf)} version={pdf.metadata.get('format')} title={pdf.metadata.get('title')!r}")
        all_text = "\\n".join(page.get_text(sort=True) for page in pdf)
        print("metadata_candidates:", {
            "years": sorted(set(re.findall(r"\\b20\\d{2}\\b", all_text))),
            "timezones": sorted(set(re.findall(r"\\bTZ\\s*([0-3])\\b", all_text, re.I))),
            "paper_labels": sorted(set(re.findall(r"\\bPaper\\s*[123][AB]?\\b", all_text, re.I))),
        })
        for index, page in enumerate(pdf[:3]):
            lines = [line.strip() for line in page.get_text(sort=True).splitlines() if line.strip()]
            print(f"-- page {index + 1} --")
            for line in lines[:35]:
                print(line[:220])
        if "marks" in name.lower() or "scheme" in name.lower():
            question_heads = []
            for line in all_text.splitlines():
                value = line.strip()
                if re.match(r"^(?:Question\\s*)?\\d{1,2}\\s*[.)]?(?:\\s|$)", value, re.I):
                    question_heads.append(value)
            print("question_heading_candidates:", question_heads[:80])
