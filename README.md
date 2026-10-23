# IB DP Physics Question Splitter

A local question bank for IB DP Physics HL and SL, using the syllabus first assessed in 2025. Older papers are kept under a separate Legacy syllabus label.

## Run

Requires Python 3.12 (tested on Linux). No API key, external database, or Node build is required.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python app.py
```

The development server listens on port 5000, on the local machine only. Use `PORT` to change the port. This is a single-user development application without authentication; add authentication and a production server before exposing it publicly.

## Workflow

1. **Import & review:** Upload a PDF (40 MB / 150 pages maximum). Text-based PDFs receive suggested sequential parent-question boundaries, year, level, paper, topics and command terms. The original document is retained.
2. **Review each question:** Check the year, level, syllabus, topics, marks, time and difficulty. Edit crop coordinates in PDF points, add continuation pages in source order, and preview the combined image. A Paper 2 stem and all its subquestions must be one question group. Save only after checking every boundary.
3. **Question library:** Search reviewed questions by text, custom tags or command terms, and filter by year, level, syllabus, paper, difficulty and topic. Open the PNG or edit the review. Saving the same source document and question number updates the record.
4. **Build a paper:** Choose HL/SL, syllabus, optional paper type, topics and a time budget. Download a PDF containing complete question groups, source references and an estimated total time. Multi-page groups remain consecutive. No subquestion is selected independently.

Generated PNGs use a 1400-pixel white canvas with 60-pixel padding and consistent gaps between page crops. Generation uses whole-question subset selection to fill the requested time without exceeding the stored estimates, at a conservative tenth-minute resolution. It reports any unfilled time. Mixed-topic questions qualify only when all their topics are selected. Questions tagged `Both` qualify for either level; otherwise HL and SL are matched strictly.

## What is automated, and what needs review

- **Text extraction and numbering:** Local PyMuPDF extraction; sequential Arabic parent question numbers starting at 1. Unusual layouts, repeated numbering, columns, headers and diagrams can produce incorrect boundaries. Edit them manually. PDFs with no detected questions still support manual crop creation.
- **Metadata:** Year, HL/SL and paper are inferred from readable text and the filename. Syllabus defaults to 2025 for papers dated 2025 onward and Legacy for earlier papers; this is an editable suggestion, not syllabus-content recognition. Legacy questions can be manually mapped to the available 2025 topics, but are excluded from 2025 generation until explicitly reviewed and reclassified.
- **Topics and command terms:** Keyword-based suggestions across the 24 syllabus subtopics, not an AI classifier. Check missing topics, false matches and HL-only content. There is no external syllabus verification or automatic HL/SL content mapping.
- **Time:** Initially 1.8 minutes per detected mark, or 5 minutes when marks cannot be found. Marks are extracted from bracketed values or explicit total marks. These estimates are editable heuristics, not official examination timing.
- **Difficulty:** Starts as **Unrated**; set Easy, Medium or Hard during review. Automatic calibrated difficulty scoring is not implemented.
- **Scans:** OCR is not included. Scanned PDFs can be cropped manually and tagged, but receive no reliable text-based suggestions. Password-protected PDFs must be unlocked first.
- **Paper output:** Preserves selected crop order and content, including multi-page groups. Very tall crops may be tiled across consecutive pages. It does not synthesize new questions, create markschemes, balance assessment objectives, or insert standardized answer spaces.

Import documents you have permission to use. No past papers are bundled or downloaded by the application.

## Data and tests

SQLite metadata, source PDFs, PNGs and generated papers are stored in ignored `instance/`. Override with `QUESTION_BANK_DATA=/absolute/path` to use another location. Back up that entire directory together; a code checkout alone does not contain your question bank. Restarting the server preserves saved data.

```sh
.venv/bin/python -m pytest -q
```

Tests use synthetic papers and temporary databases to exercise imports, multi-page grouping, crop validation, PNG rendering, metadata updates, search, persistence, topic/level restrictions, time budgets, scanned-paper manual review and generated PDF content. Real IB papers have not yet been validated; test representative papers before relying on unattended extraction.

The application is not affiliated with or endorsed by the International Baccalaureate.
