# IB DP Physics Question Splitter

A local question bank for IB DP Physics HL and SL, using the syllabus first assessed in 2025. Older papers are kept under a separate Legacy syllabus label.

## Run

### macOS

Install [Homebrew](https://brew.sh) and Xcode Command Line Tools (`xcode-select --install`), then run from the repository root:

```sh
./scripts/setup_macos.sh
```

The script installs Homebrew Python 3.12 and Tesseract, creates or reuses `.venv`, configures English OCR locally, installs dependencies, and runs the tests. After successful setup it starts the app and opens your default browser at **http://127.0.0.1:5001** (or your chosen `PORT`). Keep the Terminal open while using the app; press Ctrl+C to stop. It supports Apple Silicon and Intel Macs, including repository paths containing spaces, and leaves shell profiles unchanged.

Optional flags:

```sh
./scripts/setup_macos.sh --no-start              # Install and test without starting
./scripts/setup_macos.sh --with-model            # Also install the local model runtime
./scripts/setup_macos.sh --download-model        # Also download verified weights and start
```

Apple Silicon model builds enable Metal; Intel builds use CPU inference. Weights are saved in ignored `instance/models/`. Model downloads require access to Hugging Face and its artifact hosts. Use `source .venv/physics-env.sh` in each new terminal to restore OCR and any configured model path. Existing incompatible virtual environments or custom environment helper files are preserved and reported for you to resolve.

To start an already installed app without running setup again:

```sh
source .venv/physics-env.sh
python app.py
```

### Manual setup

Requires Python 3.12 (tested on Linux) and Tesseract with English language data. On Debian/Ubuntu, the OCR system packages are `tesseract-ocr` and `tesseract-ocr-eng`. No API key, external database, or Node build is required.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python app.py
```

The development server listens at **http://127.0.0.1:5001**, on the local machine only, and opens your default browser when a desktop is available. Port 5001 avoids the common macOS AirPlay conflict on port 5000. Use `PORT=5002 python app.py` to choose another port; the browser opens the corresponding address. Set `QUESTION_BANK_OPEN_BROWSER=0` to disable browser launch, or `1` to request it explicitly. Headless sessions print the address without launching a browser. This also applies when the macOS setup script starts the app. This is a single-user development application without authentication; add authentication and a production server before exposing it publicly.

## Workflow

1. **Import papers:** Choose **PDF files** (one or several) or click **Choose folder** to open a native directory picker. Folder selection recursively includes PDFs at every nested subfolder depth, including uppercase `.PDF` extensions. The selection summary counts PDFs and the progress list shows relative paths. Each PDF has a 40 MB / 150-page limit; non-PDF files are skipped. PDFs are processed sequentially, and a failed file does not stop the remaining files. Enable **Auto-import after successful analysis** to save detected questions immediately without a confirmation step. Leave it off to inspect suggestions first or click **Confirm import** to add all detected questions from the latest successful upload batch. Selecting a paper under **Resume an import** scopes Confirm import to that paper. Scanned pages are read with local English OCR automatically. Select **OCR every page to cross-check tags** to independently read even text-based PDFs. Long papers may take several minutes. The original document is retained, along with suggested parent-question boundaries, year, level, paper, topics, command terms and editable custom tags.
2. **Review each question:** Check the year, level, syllabus, topics, marks, time and difficulty. Edit crop coordinates in PDF points, add continuation pages in source order, and preview the combined image. A Paper 2 stem and all its subquestions stay in one question group. Command terms and custom tags are filled automatically from the text and topics; **Auto-fill command terms & tags** regenerates those fields from the current crops and selected topics. You can edit both fields before saving.
3. **Question library:** Search saved questions by text, custom tags or command terms, and filter by year range, level, syllabus, paper, difficulty and topic. From year and To year are inclusive; leave either end blank for an open range, or both blank for any year. Unknown years appear only when no year range is set. Open the PNG or edit the review. Saving the same source document and question number updates the record.
4. **Build a paper:** Choose HL/SL, syllabus, optional year range/paper type/source papers, topics, time budget and Full (default) or Short. Click **Show filtered questions** to select questions manually. Enable **Fill paper** to keep those selections and add other matching questions to the remaining time. Full keeps complete question groups without a topic filter; with topics selected, it keeps all in-scope tasks. Short uses approved subquestion dependency maps to omit optional parts while preserving stems and prerequisites. Multi-page content remains consecutive, with source references and an estimated total time.

Topic controls use clickable toggles throughout the library, paper builder, question review and subquestion review. Click again to deselect; use Find a topic to narrow the buttons and Clear topics to reset. No Shift, Ctrl or Command is needed. Keyboard users can use Tab and Space/Enter. HL-only topics stay disabled for SL. A question’s own Year field remains its single source year. The search API accepts inclusive `year_min`/`year_max` (and the older exact `year` parameter); paper preview/generation accept the same range fields. Paper diagnostics explain exclusions for out-of-range or unknown years, and Fill paper respects the range.

Markschemes are ignored during both file and recursive folder uploads. Detection recognizes names such as `markscheme`, `mark scheme`, `marking notes` and standalone `MS`, as well as files under explicitly named markscheme/MS folders. Unlabelled PDFs are also skipped when a standalone markscheme heading is readable on one of the first four pages, including OCR output when enabled. A question merely mentioning a markscheme is not treated as one. The progress list and final summary report skips; remaining papers continue normally. The upload API returns HTTP 200 with `status: "skipped"` and `reason: "markscheme"` for these files, without creating document or question records. Folder clients send `relative_path` for directory-name detection.

Bulk and auto-imported questions are marked **Imported · not individually reviewed** and remain editable. Neither action approves subquestion dependency maps. Existing saved questions for the same uploaded document and question number are skipped, preserving manual edits; uploading the same PDF again reuses its existing analysis and stored OCR/native page data. Missing metadata or topic tags remain unknown rather than being invented. Unknown level/syllabus records are saved in the bank but do not match specific generator filters; choose **All syllabuses** to find them and edit their metadata. Question-level import failures are listed and can be retried with Confirm import.

The upload API accepts multipart `auto_import=1` and returns an `import_result` containing saved IDs and question-level failures. `POST /api/documents/<id>/confirm-import` adds the remaining extracted questions from a stored document. Folder selection is handled in the browser, submitting one PDF per upload request. `POST /api/documents/<id>/suggest-tags` accepts current `regions`, `paper` and `topics` and returns editable command/tag suggestions without saving anything.

Generated PNGs use a 1400-pixel white canvas with 60-pixel padding and consistent gaps between page crops. Generation uses whole-question subset selection to fill the requested time without exceeding the stored estimates, at a conservative tenth-minute resolution. It reports any unfilled time and explains the available content and selection limits. Mixed-topic content qualifies only when every retained topic is selected or is a permitted earlier foundation. Approved part maps allow optional out-of-scope extensions to be cropped. Questions tagged `Both` qualify for either level; otherwise HL and SL are matched strictly.

Generated papers fill pages from the top, trim empty margins, and skip blank crop residue. Short questions share a page at the existing readable scale; a complete question moves to the next page if it cannot fit in the remaining space. Multi-page parents stay consecutive, and continuation headers appear only across actual page breaks. Mixed papers group Paper 1/1A/1B questions together before Paper 2, preserving selected order within each family. Paper 2 starts on a fresh page. These rules also apply to automatic selection and Fill paper. Source references appear below each question or continuation segment. Source continuation notices, page identifiers and recognized footer barcodes are removed. New headers use the generated question number, with `(continued)` only on subsequent rendered pages of that question. Diagram-only crops are preserved; a wholly empty question produces a crop-review error. Original PDFs and bank images are unchanged. Scanned-label cleanup depends on OCR recognition; inspect numbering warnings in the generation result.

## Saved OCR data, reanalysis and duplicates

When Qwen is configured, the app automatically checks saved imports for missing model reviews at startup and periodically while the app is in use. It reviews unresolved PDF/OCR topic disagreements and drafts dependency/topic maps for saved bank questions with identifiable subquestions. This runs in the background using saved text, without repeating OCR. Each result is saved immediately and reused after restart; failed or uncertain attempts remain for manual review instead of being retried continuously. Existing model reviews, teacher tags/crops and approved dependency maps are preserved. Proposals still require review before applying tags or approving a dependency map. The Qwen status line shows background activity; reopen a question to view completed proposals.


Each paper analysis stores its OCR/native text, line positions and page geometry in the local database; OCR caches are retained in `instance/ocr-cache/`. Rule fingerprints indicate when saved analysis was produced by older rules. Under **Resume an import**, open a paper and click **Reanalyse saved text (no OCR)**. This reruns splitting and tagging against the saved page records without calling OCR or the language model. Valid previous model proposals are retained only when their source hash still matches.

Reanalysis updates auto-imported bank entries while preserving manually reviewed crops, tags, time and difficulty. If the original upload opted into Auto-import, newly detected groups are added too. Imported groups that current rules no longer detect are retained but marked for review and excluded from generation until explicitly reviewed and saved. Old imports with no stored page data need one upload to upgrade. Back up the entire data directory, including the original PDFs needed for rendering.

Exact duplicate PDF uploads reuse the existing document instead of repeating OCR or creating a second document. Exact question duplicates across different PDFs require matching normalized text **and source crop pixels**; imports skip these and explicit saves report the existing question. Matching wording with differing images is flagged for comparison, not discarded, because diagrams may differ. Legacy banks are upgraded with fingerprints at startup, and exact duplicate copies are not counted twice in generator availability. These are conservative exact/potential duplicate checks, not a semantic equivalence classifier.

API: `POST /api/documents/<id>/reanalyse` returns updated/new IDs, preserved manual reviews, duplicates and older groups requiring review. Upload responses identify reused PDFs with `duplicate_document: true`; import results include `duplicate_questions`.

## Teacher question selection and Fill paper

Use **Source papers** to narrow the pool, then **Show filtered questions** to inspect question previews and tick the desired groups. **Select all** and **Clear selection** work within the current filtered list. Changing filters or reanalysing data requires refreshing the list. Full selection includes every chosen question, preserving the displayed order within each paper family (Paper 1 before Paper 2); Short may choose a smaller dependency-safe version, but cannot drop a chosen parent. If the selected groups cannot fit, the builder reports their minimum required time.

With **Fill paper** enabled, the selected groups are kept and other eligible, nonduplicate questions are added within the remaining time. An empty manual selection with Fill enabled uses the whole filtered pool. Without manual selection, generation continues to fill the budget automatically. Original parent-number glyphs are erased on generation copies (including scanned number pixels), and new consecutive **Question 1, Question 2, …** headings are added. Continuation pages keep the same new number; subquestion labels remain intact. Original PDFs and bank PNGs remain unchanged. Any OCR numbering-verification failure is reported for inspection.

API: `POST /api/papers/preview` uses the same filters as generation, including optional `document_ids`. `/api/papers` accepts ordered `question_ids` and boolean `fill_paper`; responses record selected/filled IDs, new/source numbers, omissions and numbering diagnostics. Server-side checks revalidate filters, SL restrictions, dependencies and time budgets for every manual selection.

## Generator diagnostics and PDF cover

When no questions fit, the builder shows an availability report instead of a generic failure. It distinguishes an empty bank from analyzed-but-not-imported groups, reports actual level/syllabus/paper distributions, and counts exclusions for level, syllabus, paper type, SL content conflicts, missing source PDFs, topic scope, unreviewed part maps, shared context, dependencies and time limits. Each reason includes example questions and a suggested fix; exclusion counts do not overlap. Time failures report the shortest valid version, including approved Short variants.

When a shorter paper can be built, its download remains available. The report explains whether the matching content is below the requested duration or whether the permitted combinations leave a gap. Diagnostics are returned with both failed and successful `/api/papers` responses and saved with successful paper records.

The A4 title page uses an examination-style layout inspired by the uploaded IB paper covers: subject/level/paper heading, date/name fields, candidate-number boxes, time allowed, a horizontal divider and candidate instructions. It includes the actual PDF page count and total marks only when every retained question has a known mark total. Shortened questions with unknown remaining marks are labelled accordingly. Mixed paper types receive a mixed-paper label; syllabus, estimated content duration and rendering mode are shown separately. The cover is clearly marked as generated practice material and does not use an IB logo or official session identifiers.

## Subquestion dependencies and Short rendering

In the library, open **Dependencies & Short** for a saved question. The application suggests top-level `(a)`, `(b)`, etc. groups, keeping nested roman-numbered parts together. Check each crop and estimated time. The **shared stem** is always retained; when context lives inside another part, list that part as a prerequisite too.

Use **Check dependencies with language model** to request a local model proposal. The model examines the complete grouped text, including implicit references to definitions, shared data and previous answers, and cites source quotations. It cannot inspect diagrams or reliably prove the absence of a dependency. Its output requires manual approval. If weights are unavailable, OCR is ambiguous, output is invalid, or the complete question exceeds the model context budget, the conservative draft is retained and Full remains available.

The direction is **X requires A**: retaining X requires A (and A's prerequisites), but retaining A does not require X. Circular or unknown prerequisites are rejected. After reviewing shared diagrams, all boundaries and dependencies, tick the confirmation and approve the map. Part crops must form a lossless full-width partition of the parent; gaps and overlaps are rejected. You may redistribute page slices using the crop fields. A part's reviewed minutes represent removable time; any unallocated parent time stays with the shared stem. Part times cannot exceed the parent's saved estimate.

**Full is the default** for PNG and PDF output. Without topic filters it preserves every original crop; with topic filters it preserves all in-scope tasks after mandatory topic omissions. **Short** first removes independent terminal groups (parts that require only the stem and are not needed by another retained part), retaining at least one task. If more trimming is needed to fit the time budget, it may remove dependent terminal groups next, but never a prerequisite still needed by a retained part. Original part labels and source order are preserved. A parent is selected at most once. Questions without a current approved map stay whole; the generator reports these fallbacks.

Use **Preview Short PNG** to inspect the shortened result. Optional custom omission checkboxes let you choose a subset for preview; requests that would leave orphaned parts are rejected. Generator selection details record every retained and omitted ID and the adjusted time estimate. Original full PNGs, source PDFs and library tags remain unchanged. Topic-filtered results use the union of retained reviewed part tags; a part can carry multiple topics. Source library tags remain intact. Changing parent crops, source text, paper type or timing invalidates the map and requires renewed review.

The API exposes `GET /api/questions/<id>/subquestions`, `POST .../subquestions/analyze`, and `POST .../subquestions/approve` (`parts` plus `confirmed: true`). Use `POST /api/questions/<id>/render` with `{"mode":"short","omitted_parts":["b"]}` for an explicit PNG subset; omission lists are checked against the directed graph. `GET .../image?mode=short` previews the preferred Short variant. Set `render_mode` to `short` in `/api/papers`; omitting it preserves Full behavior. Manual layouts can also be submitted through the approval API for nonstandard part labels, with unique IDs, full-width source slices, times and prerequisites.

Dependency and rendering tests exercise directionality, transitive prerequisites, cycles, exact crop coverage, stale approvals, independent-first pruning, duration limits, persistence and actual PDF content. Language-model response tests use deterministic stand-ins. Actual CPU inference was also attempted: the small model produced invalid dependency proposals, which were rejected. It has not demonstrated reliable semantic dependency classification; human review remains necessary.

## A.0 Measurements and uncertainties

A.0 is an added application topic available to SL and HL, including review, search, part tags and the paper builder. It covers measurements, uncertainty/error analysis, accuracy/precision, significant figures, error bars and best-fit lines, instrument readings/resolution, unit conversion and dimensional analysis. Suggestions retain the matched source evidence and can carry A.0 alongside physical-content topics. Numerical values or an incidental measured speed alone do not trigger A.0.

The prerequisite policy treats A.0 as an earlier skills foundation. Later-topic queries permit this measurement content; A.0 alone does not authorize later physics knowledge. Existing saved tags are preserved: use Reanalyse saved text to update auto-imported questions, or add A.0 manually in question/part review for existing manual reviews. The roadmap identifies A.0 as a user-requested category for cross-cutting skills, rather than an official 2025 IB subtopic code.

## SL and HL topic availability

For SL and questions marked Both, **A.4 Rigid body mechanics, A.5 Galilean and special relativity, B.4 Thermodynamics, D.4 Induction and E.2 Quantum physics** are disabled in topic selectors. Switching from HL clears those selections. The same rule applies to review, search, dependency-part tags and the paper builder, and API requests cannot bypass it.

SL automatic analysis excludes these labels from selectable suggestions while preserving detected conflicts and the original source evidence. Auto-import still saves the record, but flagged content is excluded from SL papers. Full and Short SL generation also exclude older SL/Both records with HL-only parent or part tags, even without a topic filter. Review the source and correct the level/content before using such questions for SL.

Topics with both SL and additional HL content (including gravity, waves and atomic/nuclear structure) remain selectable. Topic-level checks do not classify every additional-HL concept within those shared topics; source review is still needed. Availability comes from the same versioned curriculum policy used by the roadmap.

## Content-based prerequisite roadmap and topic scope

[IB Physics Prerequisite Roadmap.pdf](<IB Physics Prerequisite Roadmap.pdf>) is saved in the repository root. It summarizes all five themes, 24 syllabus subtopics and the added A.0 skills category, deduces core prerequisites and separates conditional extensions. It does **not** use the IB example teaching route. Rebuild it with `python tools/build_roadmap.py`; PyMuPDF is already a project dependency.

The uploaded *Physics teacher support material*, first assessment 2025 (updated November 2024), supplies the content overview and conceptual examples, printed pp. 2–17. This is support material rather than an exhaustive subject guide. The PDF identifies details inferred from standard physics when the source is brief. The inferred graph is an application policy, not an official IB prerequisite specification. Source identity, content summaries and edge rationales are recorded in `curriculum_prerequisites.json`.

Search accepts multiple targets. Allowed knowledge is the selected targets plus their transitive **core** foundations; conditional links do not expand scope. D.1 gravity therefore permits A.2 circular motion, A.3 energy and A.1 kinematics, while an A.2 forces query excludes D.1. A.1 motion excludes an A.3 energy extension. At least one retained task must concern a selected target; prerequisite-only questions do not qualify.

For an approved, fully tagged part map, topic filtering removes tasks containing out-of-scope content and then removes tasks that require those omitted parts. It excludes a parent with out-of-scope shared context or no surviving target task. Inseparable multi-topic parts require every tag to fit. Without a current reviewed map, a mixed-topic parent can qualify only as a whole when every parent tag fits. Short applies optional trimming after topic omissions. Unfiltered Full remains unchanged. HL/SL checks remain separate: a mixed-depth topic code does not by itself certify that a task is suitable for SL.

## What is automated, and what needs review

- **Text extraction and numbering:** Local PyMuPDF extraction plus 200-DPI English Tesseract OCR. Sequential parent numbers must carry punctuation (e.g. `1.`); bare numbers in equations are ignored. A narrowly supported OCR confusion (`4` for `1`) is proposed only with adjacent sequential evidence and always produces a review warning. Unusual layouts, columns, headers and diagrams can still produce incorrect boundaries. Edit them manually. Reference/disclaimer pages and explicitly blank answer pages are excluded.
- **Metadata:** Year, HL/SL and paper are inferred from readable text and the filename. Syllabus defaults to 2025 for papers dated 2025 onward and Legacy for earlier papers; this is an editable suggestion, not syllabus-content recognition. Legacy questions can be manually mapped to the available 2025 topics, but are excluded from 2025 generation until explicitly reviewed and reclassified.
- **Topics, command terms and custom tags:** Custom tags combine the assigned topic/theme labels with literal matched concepts in the extracted text. MCQ command terms remain empty when no imperative prompt is identified. Contextual, rule-based topic suggestions across the 24 syllabus subtopics plus A.0, with visible matched evidence. Checks distinguish air resistance from circuits, latent heat of fusion from nuclear fusion, angular widths from rotation, and relativistic travel from stellar physics. MCQ wording is not labeled with imperative command terms. OCR/PDF topic agreement and disagreement are shown separately; agreement does **not** establish semantic correctness. Check missing topics, false matches and HL-only content. There is no automatic calibrated classifier or official syllabus verification.
- **Time:** Initially 1.8 minutes per detected mark, or 5 minutes when marks cannot be found. Paper 1A questions receive one mark each. Structured-paper marks are extracted from brackets or explicit totals. A cover-total audit warns when the question marks do not add up; OCR can omit or misread brackets. Review marks before trusting time budgets. These are editable heuristics, not official examination timing.
- **Difficulty:** Starts as **Unrated**; set Easy, Medium or Hard during review. Automatic calibrated difficulty scoring is not implemented.
- **Scans:** OCR text is saved and remains searchable after crop review and application restart. Equations, superscripts, tiny mark brackets and diagrams may be recognized incorrectly. If English OCR data is missing or OCR fails, a page-specific warning is shown; manual crops and tags remain available. Password-protected PDFs must be unlocked first. OCR is serialized within the application because the native Leptonica bridge cannot run concurrently in multiple threads.
- **Paper output:** Preserves selected crop order and content, including multi-page groups. Very tall crops may be tiled across consecutive pages. It does not synthesize new questions, create markschemes, balance assessment objectives, or insert standardized answer spaces.

The application imports local PDFs rather than downloading papers. User-supplied regression PDFs are included in `TEST SAMPLES/`.

## Data and tests

SQLite metadata, source PDFs, PNGs and generated papers are stored in ignored `instance/`. Override with `QUESTION_BANK_DATA=/absolute/path` to use another location. Content-hash OCR caches are also stored there and reused across matching uploads. Back up that entire directory together; a code checkout alone does not contain your question bank. Restarting the server preserves saved data. Completed extraction analysis is committed to disk before optional language-model checks, and each model result is saved as it finishes. This includes OCR/native page text, boundaries, suggested topics, command terms and custom tags, even before questions are added to the bank. Saved dependency diagnostics and approved maps also survive restarts. On the next startup, choose the paper under **Resume an import** to load these results without rerunning extraction or inference. A saved-analysis timestamp is shown; interrupted optional checks are identified separately. Unfinished extraction and unsaved manual form edits are not restored.

```sh
.venv/bin/python -m pytest -q
```

Tests use synthetic papers and temporary databases to exercise imports, multi-page grouping, crop validation, PNG rendering, metadata updates, search, persistence, topic/level restrictions, time budgets, scanned-paper manual review and generated PDF content. Six user-supplied papers (2025 and 2026, HL Papers 1A/1B/2) are recorded by content hash in `tests/fixtures/physics_papers.json`. The six original PDFs are preserved under `TEST SAMPLES/`; the manifest includes their repository paths. OCR text and caches are generated locally. The manifest specifies question counts and 51 manually reviewed required/forbidden topic anchors. These anchors were used during development; they are regression checks, not a held-out accuracy benchmark.

The application is not affiliated with or endorsed by the International Baccalaureate.

## Lightweight language-model review

Disagreements between PDF and OCR topic suggestions can be adjudicated by a local **Qwen2.5 1.5B Instruct, Q4_K_M** model using `llama-cpp-python`. This is an optional CPU inference dependency; the standard splitter does not require model weights. Paper text is not sent to an external inference service.

```sh
# Linux build tools: GCC/G++, with CMake provided by the package build if needed.
CC=gcc CXX=g++ CMAKE_BUILD_PARALLEL_LEVEL=2 \
  CMAKE_ARGS='-DGGML_NATIVE=OFF -DGGML_BLAS=OFF -DLLAMA_CURL=OFF' \
  .venv/bin/python -m pip install -r requirements-model.txt
.venv/bin/python tools/download_model.py --destination /workspace/models/qwen-physics
QUESTION_BANK_MODEL_PATH=/workspace/models/qwen-physics/qwen2.5-1.5b-instruct-q4_k_m.gguf \
  .venv/bin/python app.py
```

The downloader reads the official Qwen repository metadata over verified HTTPS, resolves an immutable revision, and checks the artifact's declared size and SHA-256 before publishing the file. A matching `.gguf.json` checksum manifest is required beside the model file. Loading rechecks its checksum. Downloads need access to `huggingface.co` and any artifact storage destination to which it redirects; a proxy denial must be resolved in environment network settings. Existing files are preserved on checksum conflicts.

Select **OCR every page to cross-check tags** when importing. If the local model is configured, only questions with differing PDF/OCR topics receive automatic model review. Existing imports have a **Review disagreement with language model** button. The model receives the full two text versions, candidate topic names, and relevant curriculum summaries with topic boundaries and prerequisite context; schema-constrained JSON must contain a high-confidence decision and exact source quotations for each topic. Unsupported labels, invented citations, incomplete output, uncertain decisions, absent OCR, and over-budget parent questions leave manual review necessary. Quotes are checked against source text; they do not prove the model's physics judgment is correct.

The editable prompts are [OCR topic review](prompts/physics_ocr.md) and [subquestion dependencies](prompts/physics_dependencies.md). [curriculum_context.py](curriculum_context.py) retrieves relevant content summaries from the existing teacher-support-material analysis rather than filling the small model context with the whole guide. The prompts distinguish assessed content from incidental words or prerequisite knowledge, explain common OCR symbol errors, and require exact exam quotations. A.0 is identified as an application skills category. Long questions still abstain rather than having their text truncated. Prompt versions invalidate cached model reviews; background checks refresh older unapproved reviews using saved text, preserving teacher tags and approved maps.

A live smoke check of the curriculum prompt on two synthetic noisy-text cases produced one correct Doppler proposal and one invalid circular-motion response retained for manual review. These examples overlap the prompt guidance and are not an accuracy benchmark. Full inputs and recorded outputs are in [the smoke report](TEST%20SAMPLES/results/qwen-curriculum-prompt-smoke.json).

A resolved model output is a **proposal**. Apply its topics to the review form and save only after checking the source. It never silently replaces saved tags. Source edits invalidate the proposal. Both original text versions, the original disagreement, model identity, cited evidence and qualitative confidence remain available. Model confidence is not a calibrated probability. Responses are cached against source content, model checksum and prompt version.

To evaluate actual inference against the four previously flagged cases, first generate the real-paper validation outputs and then run:

```sh
QUESTION_BANK_MODEL_PATH=/workspace/models/qwen-physics/qwen2.5-1.5b-instruct-q4_k_m.gguf \
  .venv/bin/python tools/review_disagreements.py \
  --validation /path/to/validation-results --output /tmp/language-review/report.json
```

The command exits nonzero while any case remains unresolved. The runtime and verified weights were installed in the current cloud instance and actual CPU inference with the earlier v1 prompt was run on all four disagreements: **0 resolved, 4 still require review**. This is a historical result, not an evaluation of the current curriculum prompt. Three outputs failed exact-source quotation validation; one abstained with low confidence. See `TEST SAMPLES/results/language-review-live.json`. Unit/integration tests use clearly identified deterministic model stand-ins; they validate response handling, grounding, uncertainty, stale-proposal rejection and persistence, not model intelligence.

## Validate the supplied papers

```sh
.venv/bin/python tools/validate_papers.py --output /path/to/fresh/results
```

The runner uses `TEST SAMPLES/` by default (`--papers /another/path` overrides it), verifies that the six originals match their saved hashes, and reads all pages with OCR. It checks years, page/question counts and topic anchors, renders every question to a PNG, and runs isolated import/save/search/PDF-generation checks for each paper. It writes `report.md`, `report.json`, crop PNGs and six generated PDFs outside the checkout. Use a fresh output directory for each integration run. OCR results cached in `output/bank/ocr-cache` can be copied to a new output directory to avoid repeating recognition. Scanned-paper mark mismatches are recorded explicitly and do not count as timing verification. Generated papers use a manually checked representative question from each source; the test does not automatically approve the whole question bank.

The saved baseline is in [`TEST SAMPLES/results/`](<TEST SAMPLES/results/README.md>): all 141 question PNGs, crop coordinates, per-paper JSON/CSV tag results, a combined [`tags.csv`](<TEST SAMPLES/results/tags.csv>), source text/evidence and validation/review reports. These are automatic suggestions with explicit unresolved flags, not approved tags. Tests verify source links, PNG checksums, crop bounds and tag-table completeness.

```sh
.venv/bin/python tools/export_sample_results.py --validation /path/to/validation-results --output /tmp/physics-results-new
```

Omit `--output` to target `TEST SAMPLES/results/`. Existing changed files are preserved; regenerate into a fresh directory to review changes. Add `--language-report /path/to/language-report.json` to include actual recorded model-review results. Full-page OCR caches, working databases and generated practice PDFs are not copied into the committed baseline.
