from io import BytesIO
import shutil

import fitz
import pytest

from app import create_app
from physics import extract, suggest
from ocr import read_pages


def scanned_question(tmp_path):
    with fitz.open() as original:
        page = original.new_page()
        page.insert_text((50, 45), 'Physics Higher level Paper 1A 2026', fontsize=13)
        page.insert_text((50, 100), '1. Calculate the velocity of a projectile.', fontsize=16)
        page.insert_text((75, 150), 'A. 10 m/s    B. 20 m/s    C. 30 m/s    D. 40 m/s', fontsize=12)
        png = page.get_pixmap(matrix=fitz.Matrix(2, 2)).tobytes('png')
        rect = page.rect
    path = tmp_path / 'scan.pdf'
    with fitz.open() as pdf:
        page = pdf.new_page(width=rect.width, height=rect.height)
        page.insert_image(rect, stream=png)
        pdf.save(path)
    return path


@pytest.mark.skipif(not shutil.which('tesseract'), reason='Requires Tesseract English OCR runtime')
def test_scanned_import_save_search_and_cached_ocr(tmp_path, monkeypatch):
    path = scanned_question(tmp_path)
    bank = tmp_path / 'bank'
    first = extract(path, path.name, ocr_cache=bank / 'ocr-cache')
    assert first['ocr_pages'] == 1 and len(first['questions']) == 1
    q = first['questions'][0]
    assert 'A.1' in q['topics'] and q['marks'] == 1 and q['year'] == 2026
    assert q['ocr_comparison']['status'] == 'ocr_only'
    def fail(*args, **kwargs):
        raise AssertionError('Valid content-hash OCR cache was not reused')
    monkeypatch.setattr(fitz.Page, 'get_textpage_ocr', fail)
    # Auto results can be reused for auto import; verify mode must recompute.
    client = create_app(bank).test_client()
    result = client.post('/api/documents', data={'file': (BytesIO(path.read_bytes()), path.name)})
    assert result.status_code == 201
    saved = client.post('/api/questions', json=dict(q, document_id=result.json['id']))
    assert saved.status_code == 201, saved.json
    assert 'projectile' in saved.json['text'].lower()
    assert len(client.get('/api/questions?q=projectile').json) == 1


def test_ocr_failure_is_visible_and_keeps_native_text(tmp_path, monkeypatch):
    path = scanned_question(tmp_path)
    def fail(*args, **kwargs):
        raise RuntimeError('English traineddata is missing')
    monkeypatch.setattr(fitz.Page, 'get_textpage_ocr', fail)
    data = extract(path, path.name)
    assert data['ocr_pages'] == 0
    assert any('OCR failed' in message for message in data['warnings'])
    assert not data['questions']


def test_number_repair_requires_adjacent_evidence(tmp_path):
    path = tmp_path / 'numbering.pdf'
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((50, 80), '4. Calculate velocity.')
        page.insert_text((50, 180), '2. Calculate acceleration.')
        pdf.save(path)
    with fitz.open(path) as pdf:
        records, _ = read_pages(pdf, 'off')
    for record in records:
        record['text'], record['lines'] = record['native'], record['native_lines']
        record['native'], record['native_lines'] = '', []
    data = extract(path, path.name, page_records=records)
    assert [q['number'] for q in data['questions']] == [1, 2]
    assert any('proposed 1' in warning for warning in data['warnings'])
    records[0]['lines'][1]['text'] = '3. Calculate acceleration.'
    assert extract(path, path.name, page_records=records)['questions'] == []


@pytest.mark.parametrize('text,required,forbidden', [
    ('A projectile moves through the air. Air resistance is negligible.', 'A.1', 'B.5'),
    ('Ice melts. Calculate the specific latent heat of fusion.', 'B.1', 'E.5'),
    ('Calculate the angular width in a diffraction grating.', 'C.3', 'A.4'),
    ('A spaceship travels at 0.8c towards a star.', 'A.5', 'E.5'),
    ('A muon has a proper lifetime and a relativistic speed.', 'A.5', 'A.1'),
    ('A photon scatters from an electron in Compton scattering.', 'E.2', 'A.3'),
    ('A heavily damped oscillator is driven by a periodic force.', 'C.4', 'A.2'),
])
def test_contextual_tags(text, required, forbidden):
    result = suggest(text, 'Paper 1A')
    assert required in result['topics'] and forbidden not in result['topics']
    assert result['topic_evidence'][required]
    assert result['commands'] == []
