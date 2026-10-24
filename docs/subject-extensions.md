# Adding another subject

The running application remains an **IB DP Physics bank**. This change provides executable Python ports, a reusable PDF engine, subject identity guards and discovery APIs for developing additional subjects. Registering an adapter makes it available to the validation pipeline and catalog API; it does **not** automatically enable another subject in the current Physics user interface. The remaining integration work is listed below.

## Architecture and ports (version 1)

`subjects/ports.py` defines four structural Python protocols and the `SubjectAdapter` descriptor. `subjects/physics.py` wraps the production Physics implementation. The application uses its analysis, tagging, PNG rendering, cover and source-cleanup entry points. `subjects/registry.py` validates explicit registrations and rejects duplicate IDs, invalid catalogs and cyclic prerequisites. No API request can load Python code or supply a plugin path.

| Port | Required operations | Responsibility |
| --- | --- | --- |
| Analysis | `extract`, `suggest`, `custom_tags` | Parent-question boundaries; subject-specific topics, command terms, marks, timing and evidence |
| Curriculum | `prerequisites`, `context`, `model_prompts` | Complete directional prerequisite map; bounded model context; versioned prompts or explicit unavailable model tasks |
| Assessment | `estimate`, `level_exclusion`, `paper_matches` | Paper duration/mark rates; suitability rules; asymmetric paper filters |
| Rendering | `render_question`, `add_cover`, `clean_source` | Subject branding, source labels and numbering, diagrams and crop images |

An adapter has a stable slug (for example `ibdp-physics`), a display name, an adapter version and a callable `catalog()`. The catalog contains `schema_version: 1`, `id`, `name`, `qualification`, `topics` (code → title), `levels`, `syllabuses`, `paper_types` and `hl_only_topics`. The last field can be empty. Topic codes belong to their subject; `A.1` in two subjects does not imply the same content.

Do not use Physics keyword rules, SL/HL concept checks, rates, option-label cleanup or model prompts as defaults for an unrelated subject. Supply actual curriculum content and explicit format rules. Preserve unresolved metadata and missing OCR evidence rather than inventing classifications.

## Reuse the PDF/OCR engine

`pdf_extraction.extract_pdf` accepts subject callbacks:

```python
from pdf_extraction import extract_pdf

class MyAnalysis:
    def extract(self, path, filename, ocr_mode='auto', ocr_cache=None,
                page_records=None):
        return extract_pdf(
            path, filename,
            metadata_fn=self.document_metadata,
            suggest_fn=self.suggest,
            ocr_mode=ocr_mode, ocr_cache=ocr_cache,
            page_records=page_records,
        )
```

`document_metadata(text, filename)` returns `year`, `level`, `syllabus` and `paper`. `suggest(text, paper, level, syllabus)` returns `topics`, `commands`, `tags`, `topic_evidence`, `level_conflicts`, `marks`, `minutes`, `timing` and `difficulty`. Use the full Physics adapter as a signature reference, not as the new subject's curriculum implementation.

The shared engine recognizes sequential `1.`, `2.`, etc. parents and preserves multi-page crops. It does not implement arbitrary section numbering, essays without numeric labels, multilingual OCR or every exam layout. An adapter with a different layout should implement its own `extract` while retaining the result contract. `ocr.read_pages` supports saved OCR/native text, CPU-aware page workers and content-hash caches. `page_records` must bypass OCR during reanalysis.

## Analysis result contract

`subjects.pipeline.analyze(adapter, path, filename, **options)` validates the catalog, identities, topic codes, levels/formats, unique positive parent numbers and finite positive time estimates. It supplies the adapter's `subject_id` on the document and questions. Existing consumers still validate crop coordinates before rendering/importing; this contract checker is not a complete semantic or layout validator.

A result has the existing fields:

```json
{
  "subject_id": "ibdp-physics",
  "metadata": {"year": 2025, "level": "HL", "syllabus": "2025", "paper": "Paper 2"},
  "pages": [{"width": 595, "height": 842}],
  "text_pages": [],
  "warnings": [],
  "questions": [{
    "subject_id": "ibdp-physics",
    "number": 1, "text": "Full parent question text",
    "year": 2025, "level": "HL", "syllabus": "2025", "paper": "Paper 2",
    "topics": ["A.1"], "commands": ["calculate"], "tags": ["kinematics"],
    "topic_evidence": {}, "level_conflicts": [],
    "marks": 3, "minutes": 5, "difficulty": "Unrated",
    "regions": [{"page": 0, "rect": [30, 75, 565, 300]}]
  }]
}
```

Regions use zero-based source page indices and PDF points from the top-left. Keep the shared stem, diagrams and every dependent subquestion. Unknown levels/formats can use `Unknown`; unknown marks/year can be null. Save native/OCR line bounding boxes, OCR errors and provenance so reanalysis and exact-source quote checks remain possible.

Source origin is independent of the subject and paper format: `ib_official`, `self_made`, or `unknown`. Importers should retain explicit teacher labels and source evidence. They must not infer "official" merely from a filename or a familiar layout.

## Register and check an adapter

Implement the four ports, construct `SubjectAdapter`, then explicitly register it in `subjects/registry.py` after the existing Physics registration. Separate objects may implement each port. The test-only fixture in `tests/test_subject_ports.py` demonstrates an independent topic namespace; it is not a real subject or a validated IB curriculum.

```python
from subjects.ports import SubjectAdapter

# Objects below must implement the protocols in subjects/ports.py.
registry.register(SubjectAdapter(
    id='my-subject', name='My subject', version='1',
    analysis=analysis_rules, curriculum=curriculum_rules,
    assessment=assessment_rules, rendering=rendering_rules,
    catalog=subject_catalog,
))
```

Run the same checker against Physics or a newly registered adapter:

```sh
.venv/bin/python tools/check_subject_adapter.py --subject ibdp-physics \
  --sample 'TEST SAMPLES/Physics_paper_3__HL.pdf' \
  --ocr-mode verify --output /tmp/subject-validation.json
```

Omit `--sample` for catalog/port checks only. A sample run records analysis and detected origin evidence; it never imports into the production bank. Use a disposable output path because the requested report is overwritten. A passing contract test does not establish tagging accuracy. Add real, permitted subject samples and expected topic/level anchors; inspect equation-heavy OCR, long parent groups, prerequisites, duplicate handling and generated output.

## Discovery APIs

- `GET /api/subjects`: API version, active bank subject, registered IDs/names/versions, port names and `bank_enabled`.
- `GET /api/subjects/<id>/catalog`: adapter catalog; unknown IDs return 404.
- `GET /api/catalog`: existing Physics UI catalog plus `subject` and `subject_api_version`.

Documents/questions store `subject_id`. Existing records migrate to `ibdp-physics`. Each data directory is stamped in SQLite `application_settings.bank_subject`; mismatched subject records/directories are rejected. Keep `(subject_id, topic_code)` together in future exports and migrations. Do not reinterpret existing Physics tags as another subject's taxonomy.

## Enabling another interactive bank: remaining integration checklist

1. Bind a selected adapter per application/data directory. `create_app` currently explicitly permits Physics only; do not remove that guard before the remaining steps are complete.
2. Replace Physics-specific calls in `topic_scope.py`, `prerequisite_policy.py`, `subquestions.py`, `dependency_review.py`, `level_filter.py` and `assessment_timing.py` with the selected curriculum/assessment/analysis ports. Keep request-local prerequisite policies and per-bank saved overrides.
3. Bind the local model's task schemas, prompt versions, context hashes and background backfill to the adapter. Fail unavailable tasks conservatively; do not reuse Physics reviews for another subject.
4. Drive UI branding, syllabus/level/paper choices and topic widgets from that adapter's catalog. Bind cover branding and format grouping as well as source cleanup. Preserve existing generic selection, ordering and time-budget guarantees.
5. Namespace OCR-analysis/model caches and rule versions by subject and adapter version where interpretation differs. Content-only OCR can still be shared if the OCR engine/language/render parameters match.
6. Run all existing Physics regressions plus independent subject tests before enabling `bank_enabled`. Add a reviewed subject chooser only after mixed-subject requests are rejected or properly partitioned.

For multiple local processes, `PORT` selects the HTTP listening port and `QUESTION_BANK_DATA` selects the bank directory. The server binds `127.0.0.1` (default port 5001). Give each instance a distinct directory and port. There is no new network service per Python port, and no remote inference requirement. Do not invent a `QUESTION_BANK_SUBJECT` setting: another interactive subject is not enabled by an environment variable in this version.
