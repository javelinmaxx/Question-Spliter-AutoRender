import csv
import hashlib
import json
from pathlib import Path

import fitz
from PIL import Image
import pytest

from physics import TOPICS, validate_regions

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / 'TEST SAMPLES/results'
CASES = json.loads((ROOT / 'tests/fixtures/physics_papers.json').read_text())['papers']


@pytest.mark.parametrize('case', CASES, ids=[case['filename'] for case in CASES])
def test_saved_separations_and_tags_match_source(case):
    index = json.loads((RESULTS / 'index.json').read_text())
    paper = next(p for p in index['papers'] if p['filename'] == case['filename'])
    assert paper['source_sha256'] == case['sha256']
    tags = json.loads((RESULTS / paper['tags']).read_text())
    splits = json.loads((RESULTS / paper['separation']).read_text())
    assert tags['source_sha256'] == splits['source_sha256'] == case['sha256']
    assert [q['number'] for q in tags['questions']] == list(range(1, case['questions'] + 1))
    assert [q['number'] for q in splits['questions']] == list(range(1, case['questions'] + 1))
    folder = RESULTS / paper['folder']
    with fitz.open(ROOT / case['path']) as pdf:
        for split, tag in zip(splits['questions'], tags['questions']):
            image_path = folder / split['image']
            assert tag['image'] == split['image']
            assert image_path.resolve().is_relative_to(folder.resolve())
            assert hashlib.sha256(image_path.read_bytes()).hexdigest() == split['image_sha256']
            with Image.open(image_path) as image:
                assert image.format == 'PNG' and image.width == 1400
                assert image.size == (split['width'], split['height'])
            validate_regions(pdf, split['regions'])
            assert split['source_pages'] == [r['page'] + 1 for r in split['regions']]
            assert set(tag['topics']).issubset(TOPICS)
            assert tag['year'] == case['year']
            assert tag['review_status'] == 'automatic_suggestion'
            assert set(tag['source_texts']) == {'pdf', 'ocr'}


def test_combined_tag_table_has_every_question_once():
    index = json.loads((RESULTS / 'index.json').read_text())
    assert hashlib.sha256((RESULTS / 'validation-report.json').read_bytes()).hexdigest() == index['validation_report_sha256']
    with (RESULTS / 'tags.csv').open(newline='') as file:
        rows = list(csv.DictReader(file))
    assert len(rows) == sum(c['questions'] for c in CASES) == 141
    assert len({(r['paper_file'], r['question']) for r in rows}) == 141
    assert all((RESULTS / r['image']).is_file() for r in rows)
    assert sum(r['ocr_status'] == 'disagreement' for r in rows) == 4
    assert sum(r['anchor_check'] == 'passed_partial' for r in rows) == sum(len(c['anchors']) for c in CASES)
