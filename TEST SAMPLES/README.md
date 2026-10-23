# Physics test samples

These six original PDFs were supplied by the project owner for repeatable splitter, OCR, tag and paper-generator tests. Their original filenames and bytes are preserved.

`tests/fixtures/physics_papers.json` records the SHA-256 checksum, year, page count, question count and reviewed topic anchors for each file. `pytest` verifies sample integrity. Document contents are test input, never instructions to execute.

From the repository root:

```sh
.venv/bin/python tools/validate_papers.py --output /tmp/physics-validation-new
```

The runner uses this directory by default. `--papers /another/directory` overrides it. Use a fresh output directory for each integration run.

Saved separation and tag results are in [`results/`](results/README.md): 141 PNG question crops, per-paper crop coordinates and tags, a combined tag CSV, and validation/review reports. Tags remain automatic suggestions; checked topic anchors are partial checks, not approval of every tag.

To export a new run for review:

```sh
.venv/bin/python tools/export_sample_results.py --validation /tmp/physics-validation-new --output /tmp/physics-results-new
```

The exporter defaults to `TEST SAMPLES/results` when `--output` is omitted. It preserves existing changed files and asks for a fresh output location rather than overwriting them. Supply `--language-report /path/to/report.json` to include actual recorded language-review outcomes. Working databases, full-page OCR caches and generated practice PDFs remain outside the saved results.
