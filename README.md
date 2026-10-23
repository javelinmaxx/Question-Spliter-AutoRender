# IB DP Physics Question Splitter

A local question bank for IB DP Physics HL and SL, using the syllabus first assessed in 2025. Older papers are kept under a separate Legacy syllabus label.

## Run

Requires Python 3.12 (tested on Linux) and Tesseract with English language data. On Debian/Ubuntu, the OCR system packages are `tesseract-ocr` and `tesseract-ocr-eng`. No API key, external database, or Node build is required.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python app.py
```

The development server listens on port 5000, on the local machine only. Use `PORT` to change the port. This is a single-user development application without authentication; add authentication and a production server before exposing it publicly.

## Workflow

1. **Import & review:** Upload a PDF (40 MB / 150 pages maximum). Scanned pages are read with local English OCR automatically. Select **OCR every page to cross-check tags** to independently read even text-based PDFs. Long papers may take several minutes. The original document is retained, along with suggested parent-question boundaries, year, level, paper, topics and command terms.
2. **Review each question:** Check the year, level, syllabus, topics, marks, time and difficulty. Edit crop coordinates in PDF points, add continuation pages in source order, and preview the combined image. A Paper 2 stem and all its subquestions must be one question group. Save only after checking every boundary.
3. **Question library:** Search reviewed questions by text, custom tags or command terms, and filter by year, level, syllabus, paper, difficulty and topic. Open the PNG or edit the review. Saving the same source document and question number updates the record.
4. **Build a paper:** Choose HL/SL, syllabus, optional paper type, topics and a time budget. Download a PDF containing complete question groups, source references and an estimated total time. Multi-page groups remain consecutive. No subquestion is selected independently.

Generated PNGs use a 1400-pixel white canvas with 60-pixel padding and consistent gaps between page crops. Generation uses whole-question subset selection to fill the requested time without exceeding the stored estimates, at a conservative tenth-minute resolution. It reports any unfilled time. Mixed-topic questions qualify only when all their topics are selected. Questions tagged `Both` qualify for either level; otherwise HL and SL are matched strictly.

## What is automated, and what needs review

- **Text extraction and numbering:** Local PyMuPDF extraction plus 200-DPI English Tesseract OCR. Sequential parent numbers must carry punctuation (e.g. `1.`); bare numbers in equations are ignored. A narrowly supported OCR confusion (`4` for `1`) is proposed only with adjacent sequential evidence and always produces a review warning. Unusual layouts, columns, headers and diagrams can still produce incorrect boundaries. Edit them manually. Reference/disclaimer pages and explicitly blank answer pages are excluded.
- **Metadata:** Year, HL/SL and paper are inferred from readable text and the filename. Syllabus defaults to 2025 for papers dated 2025 onward and Legacy for earlier papers; this is an editable suggestion, not syllabus-content recognition. Legacy questions can be manually mapped to the available 2025 topics, but are excluded from 2025 generation until explicitly reviewed and reclassified.
- **Topics and command terms:** Contextual, rule-based suggestions across the 24 syllabus subtopics, with visible matched evidence. Checks distinguish air resistance from circuits, latent heat of fusion from nuclear fusion, angular widths from rotation, and relativistic travel from stellar physics. MCQ wording is not labeled with imperative command terms. OCR/PDF topic agreement and disagreement are shown separately; agreement does **not** establish semantic correctness. Check missing topics, false matches and HL-only content. There is no automatic calibrated classifier or official syllabus verification.
- **Time:** Initially 1.8 minutes per detected mark, or 5 minutes when marks cannot be found. Paper 1A questions receive one mark each. Structured-paper marks are extracted from brackets or explicit totals. A cover-total audit warns when the question marks do not add up; OCR can omit or misread brackets. Review marks before trusting time budgets. These are editable heuristics, not official examination timing.
- **Difficulty:** Starts as **Unrated**; set Easy, Medium or Hard during review. Automatic calibrated difficulty scoring is not implemented.
- **Scans:** OCR text is saved and remains searchable after crop review and application restart. Equations, superscripts, tiny mark brackets and diagrams may be recognized incorrectly. If English OCR data is missing or OCR fails, a page-specific warning is shown; manual crops and tags remain available. Password-protected PDFs must be unlocked first. OCR is serialized within the application because the native Leptonica bridge cannot run concurrently in multiple threads.
- **Paper output:** Preserves selected crop order and content, including multi-page groups. Very tall crops may be tiled across consecutive pages. It does not synthesize new questions, create markschemes, balance assessment objectives, or insert standardized answer spaces.

Import documents you have permission to use. No past papers are bundled or downloaded by the application.

## Data and tests

SQLite metadata, source PDFs, PNGs and generated papers are stored in ignored `instance/`. Override with `QUESTION_BANK_DATA=/absolute/path` to use another location. Content-hash OCR caches are also stored there and reused across matching uploads. Back up that entire directory together; a code checkout alone does not contain your question bank. Restarting the server preserves saved data.

```sh
.venv/bin/python -m pytest -q
```

Tests use synthetic papers and temporary databases to exercise imports, multi-page grouping, crop validation, PNG rendering, metadata updates, search, persistence, topic/level restrictions, time budgets, scanned-paper manual review and generated PDF content. Six user-supplied papers (2025 and 2026, HL Papers 1A/1B/2) are recorded by content hash in `tests/fixtures/physics_papers.json`. PDFs and OCR text are not bundled. The manifest specifies question counts and 51 manually reviewed required/forbidden topic anchors. These anchors were used during development; they are regression checks, not a held-out accuracy benchmark.

The application is not affiliated with or endorsed by the International Baccalaureate.

## Validate the supplied papers

```sh
.venv/bin/python tools/validate_papers.py --papers /path/to/supplied/pdfs --output /path/to/fresh/results
```

The runner reads all pages with OCR, checks file hashes, years, page/question counts and topic anchors, renders every question to a PNG, and runs isolated import/save/search/PDF-generation checks for each paper. It writes `report.md`, `report.json`, crop PNGs and six generated PDFs outside the checkout. Use a fresh output directory for each integration run. OCR results cached in `output/bank/ocr-cache` can be copied to a new output directory to avoid repeating recognition. Scanned-paper mark mismatches are recorded explicitly and do not count as timing verification. Generated papers use a manually checked representative question from each source; the test does not automatically approve the whole question bank.
