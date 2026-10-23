"""Export existing validation crops and tags into a reviewable results folder."""
import argparse
import csv
import hashlib
from io import BytesIO, StringIO
import json
from pathlib import Path
import sys

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ocr import region_text
from physics import TOPICS


def encode(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode()


def csv_bytes(rows):
    stream = StringIO(newline='')
    writer = csv.DictWriter(stream, lineterminator='\n', fieldnames=['paper_file', 'question', 'year', 'level', 'paper',
                            'syllabus', 'topics', 'topic_names', 'command_terms', 'marks',
                            'estimated_minutes', 'difficulty', 'ocr_status', 'language_review_status',
                            'anchor_check', 'review_status', 'image'])
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode()


def export_results(validation, output, language_report=None):
    manifest = json.loads((ROOT / 'tests/fixtures/physics_papers.json').read_text())
    report_bytes = (validation / 'report.json').read_bytes()
    report = json.loads(report_bytes)
    if report['failures']:
        raise ValueError('Resolve validation failures before exporting this result set.')
    language = json.loads(language_report.read_text()) if language_report else None
    reviews = {(r['source_case'], r['question']): r['review'] for r in language['cases']} if language else {}
    artifacts, papers, all_rows = {}, [], []
    for case in manifest['papers']:
        source = ROOT / case['path']
        if hashlib.sha256(source.read_bytes()).hexdigest() != case['sha256']:
            raise ValueError(f"Source paper checksum mismatch: {source}")
        observed = next(p for p in report['papers'] if p['sha256'] == case['sha256'])
        folder = validation / case['sha256'][:12]
        data = json.loads((folder / 'extraction.json').read_text())
        if len(data['questions']) != case['questions'] or not all(observed['checks'].values()):
            raise ValueError(f"Incomplete validation: {case['filename']}")
        destination = Path(source.stem)
        separation, tags, rows = [], [], []
        anchors = {a['number']: a for a in case['anchors']}
        for q in data['questions']:
            image_path = Path('questions') / f"question-{q['number']:02d}.png"
            png = (folder / image_path.name).read_bytes()
            with Image.open(BytesIO(png)) as image:
                width, height = image.size
                if image.format != 'PNG' or width != 1400:
                    raise ValueError(f'Unexpected crop image: {image_path}')
            artifacts[destination / image_path] = png
            separation.append(dict(number=q['number'], image=image_path.as_posix(),
                                   image_sha256=hashlib.sha256(png).hexdigest(), width=width, height=height,
                                   source_pages=[r['page'] + 1 for r in q['regions']], regions=q['regions']))
            anchor = anchors.get(q['number'])
            anchor_check = None
            if anchor:
                missing = sorted(set(anchor['required_topics']) - set(q['topics']))
                forbidden = sorted(set(anchor['forbidden_topics']) & set(q['topics']))
                if missing or forbidden:
                    raise ValueError('Stored topic results no longer satisfy their diagnostic anchors.')
                anchor_check = dict(**anchor, status='passed', scope='specified required/forbidden topics only')
            review = reviews.get((case['sha256'][:12], q['number'])) or q.get('language_review')
            record = {k: q[k] for k in ('number', 'year', 'level', 'paper', 'syllabus', 'topics',
                                        'commands', 'marks', 'minutes', 'difficulty', 'text_source',
                                        'topic_evidence', 'ocr_comparison')}
            record.update(image=image_path.as_posix(), review_status='automatic_suggestion',
                          topic_names={code: TOPICS[code] for code in q['topics']},
                          language_review=review, anchor_check=anchor_check,
                          source_texts=dict(pdf=region_text(data['text_pages'], q['regions'], 'native'),
                                            ocr=region_text(data['text_pages'], q['regions'], 'ocr')))
            tags.append(record)
            row = dict(paper_file=case['filename'], question=q['number'], year=q['year'], level=q['level'],
                       paper=q['paper'], syllabus=q['syllabus'], topics='; '.join(q['topics']),
                       topic_names='; '.join(TOPICS[c] for c in q['topics']), command_terms='; '.join(q['commands']),
                       marks=q['marks'], estimated_minutes=q['minutes'], difficulty=q['difficulty'],
                       ocr_status=q['ocr_comparison']['status'], language_review_status=review['status'] if review else 'not_run',
                       anchor_check='passed_partial' if anchor_check else 'not_checked',
                       review_status='automatic_suggestion', image=image_path.as_posix())
            rows.append(row)
            all_rows.append(dict(row, image=(destination / image_path).as_posix()))
        provenance = dict(source_file=case['filename'], source_sha256=case['sha256'],
                          source_pages=len(data['pages']), metadata=data['metadata'],
                          mark_audit=data['mark_audit'], warnings=data['warnings'])
        artifacts[destination / 'separation.json'] = encode(dict(**provenance,
            coordinate_system='PDF points; page indices in regions are zero-based; source_pages are one-based', questions=separation))
        artifacts[destination / 'tags.json'] = encode(dict(**provenance, questions=tags))
        artifacts[destination / 'tags.csv'] = csv_bytes(rows)
        papers.append(dict(filename=case['filename'], source_sha256=case['sha256'], folder=destination.as_posix(),
                           questions=len(tags), separation=(destination / 'separation.json').as_posix(),
                           tags=(destination / 'tags.json').as_posix(), csv=(destination / 'tags.csv').as_posix(),
                           mark_audit=data['mark_audit'], warnings=data['warnings']))
    artifacts[Path('tags.csv')] = csv_bytes(all_rows)
    disagreements = sum(row['ocr_status'] == 'disagreement' for row in all_rows)
    index = dict(schema=1, validation_report_sha256=hashlib.sha256(report_bytes).hexdigest(), papers=papers,
                 total_questions=sum(p['questions'] for p in papers),
                 limitations=report['limitations'], language_review_summary=dict(
                     resolved=language['resolved'], remaining=language['remaining'], model=language['model']) if language else None)
    portable_report = dict(report, papers=[dict(p, artifacts=next(r['folder'] for r in papers if r['source_sha256'] == p['sha256'])) for p in report['papers']])
    artifacts[Path('validation-report.json')] = encode(portable_report)
    index['source_validation_report_sha256'] = index['validation_report_sha256']
    index['validation_report_sha256'] = hashlib.sha256(artifacts[Path('validation-report.json')]).hexdigest()
    artifacts[Path('index.json')] = encode(index)
    artifacts[Path('validation-report.md')] = (validation / 'report.md').read_bytes()
    if language:
        artifacts[Path('language-review.json')] = encode(language)
    lines = ['# Separation and tag results', '',
             f"{len(papers)} papers · {index['total_questions']} question PNGs · 1400-pixel canvas width.", '',
             'These are saved automatic outputs from the six-paper validation run, not an approved question bank. '
             'Topic anchors check selected labels only. Review the original images and text before using a question.', '',
             '| Paper | Questions | Separation | Tags | Spreadsheet |', '| --- | --- | --- | --- | --- |']
    for p in papers:
        lines.append(f"| {p['filename']} | {p['questions']} | [Crops and coordinates](<{p['separation']}>) | [JSON](<{p['tags']}>) | [CSV](<{p['csv']}>) |")
    language_note = (f"{language['remaining']} of {len(language['cases'])} evaluated OCR/PDF disagreements remain unresolved. "
                     'See [language-review.json](language-review.json) for decisions and model availability. '
                     if language else f'{disagreements} source disagreements are recorded. No language-model report was supplied for this export. ')
    mismatches = [f"{p['filename']}: {p['mark_audit']['detected']} / {p['mark_audit']['expected']} marks" for p in papers if p['mark_audit']['status'] == 'mismatch']
    lines += ['', f"Use [tags.csv](tags.csv) to search all {index['total_questions']} records. Per-paper tags.json files include topic names, "
              'matched evidence, command terms, year/level/paper/syllabus, marks, estimated minutes, difficulty, '
              'both text sources, diagnostic anchor checks and OCR disagreement status. '
              'separation.json links each image to ordered source pages/crops and its SHA-256.', '',
              ('Mark mismatches: ' + '; '.join(mismatches) + '. Review those marks before using time estimates.' if mismatches else 'No document-level mark mismatches were found; individual marks still require review.') + ' Difficulty is unrated.', '',
              language_note + 'These are recorded results, not a claim that all tags are correct. See [validation-report.md](validation-report.md).', '',
              'Regenerate outside the checkout, then export without overwriting changed files:', '', '```sh',
              '.venv/bin/python tools/validate_papers.py --output /tmp/physics-validation-new',
              '.venv/bin/python tools/export_sample_results.py --validation /tmp/physics-validation-new', '```', '']
    artifacts[Path('README.md')] = '\n'.join(lines).encode()
    # Preflight every file so a conflicting existing export cannot be partially overwritten.
    for relative, content in artifacts.items():
        path = output / relative
        if path.exists() and path.read_bytes() != content:
            raise ValueError(f'Preserving changed output: {path}. Export to a fresh --output directory.')
    for relative, content in artifacts.items():
        path = output / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(content)
    return index


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--validation', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'TEST SAMPLES/results')
    parser.add_argument('--language-report', type=Path)
    args = parser.parse_args()
    try:
        result = export_results(args.validation.resolve(), args.output.resolve(), args.language_report)
    except (ValueError, KeyError, OSError, StopIteration) as error:
        parser.exit(1, 'Export failed: ' + str(error) + '\n')
    print(f"Exported {len(result['papers'])} papers and {result['total_questions']} questions to {args.output}")
