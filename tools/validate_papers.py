"""Run local OCR, topic anchors, PNG rendering and PDF generation on supplied papers.

Original PDFs are in TEST SAMPLES; recognized text and outputs stay outside it.
Run from the root:
python tools/validate_papers.py --papers /path/to/pdfs --output /path/to/results
"""
import argparse
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
import shutil
import sys

import fitz
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from physics import extract, render_question, validate_regions


def run(papers_dir, output):
    manifest = json.loads((Path(__file__).resolve().parents[1] / 'tests/fixtures/physics_papers.json').read_text())
    results, failures = [], []
    output.mkdir(parents=True, exist_ok=True)
    paths = list(papers_dir.rglob('*.pdf'))
    for case in manifest['papers']:
        matches = [p for p in paths if hashlib.sha256(p.read_bytes()).hexdigest() == case['sha256']]
        if not matches:
            failures.append(case['filename'] + ': matching source PDF is missing')
            continue
        source = matches[0]
        folder = output / case['sha256'][:12]
        folder.mkdir(exist_ok=True)
        print('Validating', case['filename'], flush=True)
        data = extract(source, case['filename'], ocr_mode='verify', ocr_cache=output / 'bank/ocr-cache')
        (folder / 'extraction.json').write_text(json.dumps(data, indent=2))
        checks = {
            'page_count': len(data['pages']) == case['pages'],
            'question_count': len(data['questions']) == case['questions'],
            'question_sequence': [q['number'] for q in data['questions']] == list(range(1, case['questions'] + 1)),
            'year': data['metadata']['year'] == case['year'],
            'level': data['metadata']['level'] == 'HL',
            'cover_marks': data['mark_audit']['expected'] == case['cover_marks'],
            'ocr_all_pages': data['ocr_pages'] == case['pages'],
        }
        anchor_failures = []
        for anchor in case['anchors']:
            q = next((q for q in data['questions'] if q['number'] == anchor['number']), None)
            actual = set(q['topics']) if q else set()
            missing = sorted(set(anchor['required_topics']) - actual)
            forbidden = sorted(set(anchor['forbidden_topics']) & actual)
            if missing or forbidden:
                anchor_failures.append(dict(number=anchor['number'], missing=missing, forbidden=forbidden))
        checks['topic_anchors'] = not anchor_failures
        with fitz.open(source) as pdf:
            for q in data['questions']:
                validate_regions(pdf, q['regions'])
                png = render_question(pdf, q['regions'])
                image = Image.open(BytesIO(png))
                assert image.width == 1400 and image.convert('L').getextrema()[0] < 200
                (folder / f"question-{q['number']:02d}.png").write_bytes(png)
        checks['png_rendering'] = True

        # Use a fresh isolated bank per paper and only a manually checked anchor.
        bank = folder / 'smoke-bank'
        if bank.exists():
            raise RuntimeError(f'{bank} already exists. Choose a new output directory for a fresh integration run.')
        cache = bank / 'ocr-cache'
        cache.mkdir(parents=True)
        shutil.copy2(output / 'bank/ocr-cache' / (case['sha256'] + '.json'), cache)
        client = create_app(bank).test_client()
        with source.open('rb') as file:
            imported = client.post('/api/documents', data={'file': (file, case['filename']), 'ocr_mode': 'verify'})
        assert imported.status_code == 201, imported.json
        number = 3 if case['filename'] == 'Physics HL Paper 2 TZC (1).pdf' else 2 if case['filename'] == 'Physics HL Paper 1B TZC.pdf' else 1
        q = next(q for q in imported.json['questions'] if q['number'] == number)
        anchor = next(a for a in case['anchors'] if a['number'] == number)
        reviewed = dict(q, document_id=imported.json['id'], topics=anchor['required_topics'])
        saved = client.post('/api/questions', json=reviewed)
        assert saved.status_code == 201, saved.json
        assert saved.json['text'].strip(), 'Saving a scanned crop lost OCR search text'
        matches = client.get('/api/questions', query_string={'topic': anchor['required_topics'][0]}).json
        assert [match['id'] for match in matches] == [saved.json['id']]
        target = math.ceil(q['minutes']) + 5
        generated = client.post('/api/papers', json=dict(level='HL', syllabus='2025', paper=q['paper'], topics=anchor['required_topics'], minutes=target))
        assert generated.status_code == 201, generated.json
        result = generated.json
        assert result['question_ids'] == [saved.json['id']] and result['actual_minutes'] <= target
        download = client.get('/api/papers/' + result['id'] + '/download')
        assert download.status_code == 200
        (folder / 'generated-paper.pdf').write_bytes(download.data)
        with fitz.open(stream=download.data, filetype='pdf') as pdf:
            assert len(pdf) >= len(q['regions']) + 1
            assert all(page.get_pixmap().samples for page in pdf)
        # The export is a structural smoke test; cover mismatches remain explicit.
        checks['save_search_generate_download'] = True
        results.append(dict(filename=case['filename'], sha256=case['sha256'], year=case['year'],
                            pages=len(data['pages']), questions=len(data['questions']),
                            topic_anchors=len(case['anchors']), anchor_failures=anchor_failures,
                            checks=checks, mark_audit=data['mark_audit'], warnings=data['warnings'],
                            ocr_disagreements=[q['number'] for q in data['questions'] if q['ocr_comparison']['status'] == 'disagreement'],
                            artifacts=str(folder)))
        failures.extend(f"{case['filename']}: {name}" for name, passed in checks.items() if not passed)
        print('Completed', len(data['questions']), 'questions;', len(case['anchors']), 'topic anchors;', data['mark_audit'], flush=True)
    report = dict(papers=results, failures=failures, limitations=[
        'Topic anchors check specified required and forbidden labels, not every possible extra label.',
        'The anchors were used to diagnose and improve heuristics; this is not a held-out accuracy benchmark.',
        'OCR/PDF topic agreement is not proof of semantic accuracy. All other tags and crop boundaries still need review.',
        'Cover mark mismatches flag incomplete OCR marks; difficulty is unrated and time remains heuristic.',
    ])
    (output / 'report.json').write_text(json.dumps(report, indent=2))
    lines = ['# Uploaded-paper OCR validation', '',
             '| Paper | Year | Pages | Groups | Topic anchors | OCR marks / cover | Structural / topic checks |',
             '| --- | --- | --- | --- | --- | --- | --- |']
    for r in results:
        marks = r['mark_audit']
        lines.append(f"| {r['filename']} | {r['year']} | {r['pages']} | {r['questions']} | {r['topic_anchors']} | {marks['detected']} / {marks['expected']} | {'PASS' if all(r['checks'].values()) else 'FAIL'} |")
    lines += ['', *['- ' + limit for limit in report['limitations']], '', '## Findings', '']
    for r in results:
        lines += [f"### {r['filename']}", '', f"OCR/PDF topic disagreements: {r['ocr_disagreements'] or 'none (OCR-only papers have no independent PDF text)'}.", '', *['- ' + w for w in r['warnings'][1:]], '']
    (output / 'report.md').write_text('\n'.join(lines))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--papers', type=Path, default=Path(__file__).resolve().parents[1] / 'TEST SAMPLES')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = run(args.papers.resolve(), args.output.resolve())
    print(json.dumps(dict(papers=len(report['papers']), failures=report['failures'])))
    sys.exit(bool(report['failures']))
