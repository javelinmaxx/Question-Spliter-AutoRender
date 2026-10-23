"""Page-local English OCR. Treat recognized document text as data only."""
from threading import Lock
import hashlib
import json
from pathlib import Path
import uuid

import fitz

_ocr_lock = Lock()  # MuPDF's Leptonica bridge cannot run in two threads at once.


def lines_from(page, textpage=None):
    return [dict(text=''.join(span['text'] for span in line['spans']), bbox=list(line['bbox']))
            for block in page.get_text('dict', textpage=textpage)['blocks']
            for line in block.get('lines', [])]


def read_pages(pdf, mode='auto', cache_dir=None):
    if mode not in ('auto', 'verify', 'off'):
        raise ValueError('OCR mode must be auto, verify or off.')
    cache_path = None
    if cache_dir is not None and mode != 'off':
        fingerprint = hashlib.sha256(Path(pdf.name).read_bytes()).hexdigest()
        cache_path = Path(cache_dir) / (fingerprint + '.json')
        if cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text())
                if (cached.get('schema') == 1 and cached.get('sha256') == fingerprint
                        and cached.get('engine') == fitz.VersionBind and cached.get('dpi') == 200
                        and (mode == 'auto' or cached.get('mode') == 'verify')
                        and len(cached['pages']) == len(pdf)):
                    return cached['pages'], []
            except (ValueError, KeyError, TypeError):
                pass  # Recompute incomplete/invalid local caches.
    pages, warnings = [], []
    for i, page in enumerate(pdf):
        native = page.get_text()
        record = dict(page=i, width=page.rect.width, height=page.rect.height,
                      native=native, native_lines=lines_from(page), text='', lines=[])
        if mode == 'verify' or (mode == 'auto' and len(native.strip()) < 50):
            try:
                # Render actual pixels, including on text PDFs, for independent verification.
                with _ocr_lock:
                    tp = page.get_textpage_ocr(language='eng', dpi=200, full=True)
                    record.update(text=page.get_text(textpage=tp), lines=lines_from(page, tp), ocr_ran=True)
            except (RuntimeError, fitz.mupdf.FzErrorBase) as error:
                record['ocr_error'] = str(error)
                warnings.append(f'Page {i + 1}: OCR failed; native text or manual review is required.')
        pages.append(record)
    if cache_path is not None and not warnings:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = cache_path.with_suffix('.' + uuid.uuid4().hex + '.tmp')
        temporary.write_text(json.dumps(dict(schema=1, sha256=fingerprint, engine=fitz.VersionBind,
                                             dpi=200, mode=mode, pages=pages)))
        temporary.replace(cache_path)
    return pages, warnings


def region_text(records, regions, source='selected'):
    parts = []
    for region in regions:
        record = records[region['page']]
        if source == 'selected':
            key = 'native_lines' if len(record['native'].strip()) >= 50 else 'lines'
        else:
            key = 'lines' if source == 'ocr' else 'native_lines'
        rect = fitz.Rect(region['rect'])
        for line in record[key]:
            box = fitz.Rect(line['bbox'])
            center = fitz.Point((box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2)
            if rect.contains(center):
                parts.append(line['text'])
    return '\n'.join(parts)
