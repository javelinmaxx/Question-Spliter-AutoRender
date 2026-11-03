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
IDENTITY = re.compile(
    r"\b([MN])(\d{2})/4/PHYSI/(HPM|HP[123]|HPA|HPB)/ENG/TZ([0-3])/XX(?:/M)?\b",
    re.I,
)

for name in FILES:
    path = ROOT / name
    print(f"\n===== {name} =====")
    with fitz.open(path) as pdf:
        texts = [page.get_text(sort=True) for page in pdf]
        all_text = "\n".join(texts)
        identity = IDENTITY.search(all_text)
        print(f"pages={len(pdf)} version={pdf.metadata.get('format')} title={pdf.metadata.get('title')!r}")
        print("identifier:", identity.group(0) if identity else "NOT FOUND")
        if identity:
            print("identity_fields:", {
                "session": "May" if identity.group(1).upper() == "M" else "November",
                "year": 2000 + int(identity.group(2)),
                "paper_code": identity.group(3).upper(),
                "timezone": f"TZ{identity.group(4)}",
                "is_markscheme": bool(re.search(r"/M\b", identity.group(0))),
            })
        page_indices = range(min(len(pdf), 7)) if "markscheme" in name.lower() else range(min(len(pdf), 3))
        for index in page_indices:
            lines = [line.strip() for line in texts[index].splitlines() if line.strip()]
            print(f"-- page {index + 1} --")
            for line in lines[:65]:
                print(line[:220])
        if name == "Physics_paper_2__TZ1_HL.pdf":
            print("paper2_body_text:")
            for page_index in range(2, min(len(pdf), 7)):
                print(f"-- page {page_index + 1} --")
                print(texts[page_index][:1800])
            print("numbered_line_candidates:")
            for page_index, page in enumerate(pdf):
                for block in page.get_text("dict", sort=True)["blocks"]:
                    for line in block.get("lines", []):
                        value = "".join(span["text"] for span in line["spans"]).strip()
                        if re.match(r"^\d{1,2}[.)]\s", value):
                            print(page_index + 1, round(line["bbox"][0], 1), round(line["bbox"][1], 1), value[:100])
        if "markscheme" in name.lower():
            mcq = re.findall(r"(?<!\d)(\d{1,2})\s*[.)]\s*([A-D])\b", all_text)
            structured = []
            for line in all_text.splitlines():
                value = line.strip()
                if re.match(r"^\d{1,2}\s*(?:[.)]|\([a-z]\))", value, re.I):
                    structured.append(value)
            print("mcq_answer_pairs:", mcq[:60])
            print("structured_question_rows:", structured[:100])
