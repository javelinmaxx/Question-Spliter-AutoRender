# Separation and tag results

6 papers · 141 question PNGs · 1400-pixel canvas width.

These are saved automatic outputs from the six-paper validation run, not an approved question bank. Topic anchors check selected labels only. Review the original images and text before using a question.

| Paper | Questions | Separation | Tags | Spreadsheet |
| --- | --- | --- | --- | --- |
| Physics_paper_1A_TZ3_HL.pdf | 40 | [Crops and coordinates](<Physics_paper_1A_TZ3_HL/separation.json>) | [JSON](<Physics_paper_1A_TZ3_HL/tags.json>) | [CSV](<Physics_paper_1A_TZ3_HL/tags.csv>) |
| Physics_paper_1A_TZ1_HL.pdf | 40 | [Crops and coordinates](<Physics_paper_1A_TZ1_HL/separation.json>) | [JSON](<Physics_paper_1A_TZ1_HL/tags.json>) | [CSV](<Physics_paper_1A_TZ1_HL/tags.csv>) |
| Physics HL Paper 1A TZC.pdf | 40 | [Crops and coordinates](<Physics HL Paper 1A TZC/separation.json>) | [JSON](<Physics HL Paper 1A TZC/tags.json>) | [CSV](<Physics HL Paper 1A TZC/tags.csv>) |
| Physics_paper_2_TZ3_HL.pdf | 10 | [Crops and coordinates](<Physics_paper_2_TZ3_HL/separation.json>) | [JSON](<Physics_paper_2_TZ3_HL/tags.json>) | [CSV](<Physics_paper_2_TZ3_HL/tags.csv>) |
| Physics HL Paper 2 TZC (1).pdf | 9 | [Crops and coordinates](<Physics HL Paper 2 TZC (1)/separation.json>) | [JSON](<Physics HL Paper 2 TZC (1)/tags.json>) | [CSV](<Physics HL Paper 2 TZC (1)/tags.csv>) |
| Physics HL Paper 1B TZC.pdf | 2 | [Crops and coordinates](<Physics HL Paper 1B TZC/separation.json>) | [JSON](<Physics HL Paper 1B TZC/tags.json>) | [CSV](<Physics HL Paper 1B TZC/tags.csv>) |

Use [tags.csv](tags.csv) to search all 141 records. Per-paper tags.json files include topic names, matched evidence, command terms, year/level/paper/syllabus, marks, estimated minutes, difficulty, both text sources, diagnostic anchor checks and OCR disagreement status. separation.json links each image to ordered source pages/crops and its SHA-256.

Mark mismatches: Physics HL Paper 2 TZC (1).pdf: 61 / 90 marks; Physics HL Paper 1B TZC.pdf: 18 / 20 marks. Review those marks before using time estimates. Difficulty is unrated.

4 of 4 evaluated OCR/PDF disagreements remain unresolved. See [language-review.json](language-review.json) for decisions and model availability. These are recorded results, not a claim that all tags are correct. See [validation-report.md](validation-report.md).

Regenerate outside the checkout, then export without overwriting changed files:

```sh
.venv/bin/python tools/validate_papers.py --output /tmp/physics-validation-new
.venv/bin/python tools/export_sample_results.py --validation /tmp/physics-validation-new
```
