"""Page-local English OCR. Treat recognized document text as data only."""
from threading import Lock
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import uuid

import fitz
from cpu_runtime import cpu_setting
from paper_labels import obsolete_option_indices

_ocr_lock = Lock()  # MuPDF's Leptonica bridge cannot run in two threads at once.
_pool_lock = Lock()
_pool = None


def _initialize_worker():
    # Each process handles one page. Nested Tesseract OpenMP threads would
    # otherwise multiply the CPU budget by the number of page workers.
    os.environ['OMP_THREAD_LIMIT'] = '1'
    os.environ['OMP_NUM_THREADS'] = '1'


def _process_pool():
    global _pool
    with _pool_lock:
        if _pool is None:
            # Spawn avoids forking Flask threads or a loaded llama.cpp context.
            _pool = ProcessPoolExecutor(max_workers=cpu_setting('QUESTION_BANK_OCR_WORKERS'),
                mp_context=multiprocessing.get_context('spawn'), initializer=_initialize_worker)
        return _pool


def _discard_broken_pool(pool):
    global _pool
    with _pool_lock:
        if _pool is pool:
            _pool = None
    pool.shutdown(wait=False, cancel_futures=True)


def _recognize(page):
    try:
        with _ocr_lock:
            tp = page.get_textpage_ocr(language='eng', dpi=200, full=True)
            return dict(text=page.get_text(textpage=tp), lines=lines_from(page, tp), ocr_ran=True)
    except (RuntimeError, fitz.mupdf.FzErrorBase) as error:
        return dict(ocr_error=str(error))


def _recognize_file(path, index):
    # No Document / Page object crosses a process boundary.
    with fitz.open(path) as pdf:
        return _recognize(pdf[index])


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
    pages, warnings, pending = [], [], []
    for i, page in enumerate(pdf):
        native = page.get_text()
        record = dict(page=i, width=page.rect.width, height=page.rect.height,
                      native=native, native_lines=lines_from(page), text='', lines=[])
        if mode == 'verify' or (mode == 'auto' and len(native.strip()) < 50):
            pending.append(i)
        pages.append(record)
    if len(pending) > 1 and cpu_setting('QUESTION_BANK_OCR_WORKERS') > 1:
        # Snapshot includes unsaved PDF changes and supports in-memory inputs.
        # Workers share a file path instead of copying a whole PDF per page.
        with TemporaryDirectory(prefix='physics-ocr-') as directory:
            snapshot = str(Path(directory) / 'pages.pdf')
            pdf.save(snapshot)
            futures, pool = [], None
            try:
                pool = _process_pool()
                for i in pending:
                    futures.append((i, pool.submit(_recognize_file, snapshot, i)))
                for i, future in futures:
                    pages[i].update(future.result())
            except (RuntimeError, OSError) as error:
                # Restricted process creation / failed worker: finish safely in
                # the caller, without discarding native text or cached results.
                for i, future in futures:
                    if not future.done():
                        future.cancel()
                if isinstance(error, BrokenProcessPool) and pool is not None:
                    _discard_broken_pool(pool)
                for i in pending:
                    if not pages[i].get('ocr_ran') and 'ocr_error' not in pages[i]:
                        pages[i].update(_recognize(pdf[i]))
            finally:
                # Keep the snapshot until even uncancellable tasks have stopped.
                for _, future in futures:
                    try:
                        future.result()
                    except Exception:
                        pass
    else:
        for i in pending:
            pages[i].update(_recognize(pdf[i]))
    for record in pages:
        if 'ocr_error' in record:
            warnings.append(f"Page {record['page'] + 1}: OCR failed; native text or manual review is required.")
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
        ignored = obsolete_option_indices([line['text'] for line in record[key]])
        for index, line in enumerate(record[key]):
            box = fitz.Rect(line['bbox'])
            center = fitz.Point((box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2)
            if rect.contains(center):
                if index not in ignored:
                    parts.append(line['text'])
    return '\n'.join(parts)
