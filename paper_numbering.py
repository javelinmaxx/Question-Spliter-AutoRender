"""Erase source parent-number glyphs on generation copies; keep part labels."""
import re

import fitz
from ocr import _ocr_lock


def number_boxes(raw, region, number, ocr=False):
    area = fitz.Rect(region['rect'])
    found = []
    for block in raw['blocks']:
        for line in block.get('lines', []):
            chars = [char for span in line['spans'] for char in span.get('chars', [])]
            text = ''.join(char['c'] for char in chars)
            match = re.match(r'^\s*(\d{1,3})[.)](?=\s|\(|$)', text)
            if not match:
                continue
            detected = int(match[1])
            if detected != number and not (ocr and match[1].replace('4', '1') == str(number)):
                continue
            rect = fitz.Rect(line['bbox'])
            if not (area.x0 - 1 <= rect.x0 <= min(area.x0 + 80, 130) and area.y0 - 1 <= rect.y0 <= area.y0 + 35):
                continue
            glyphs = chars[match.start(1):match.end()]
            box = fitz.Rect(glyphs[0]['bbox'])
            for char in glyphs[1:]:
                box |= fitz.Rect(char['bbox'])
            found.append(box)
    return found


def erase_source_numbers(source, question, cache):
    erased = 0
    warnings = []
    seen = set()
    for region in question['regions']:
        page_number = region['page']
        key = (page_number, tuple(region['rect']))
        if key in seen:
            continue
        seen.add(key)
        page = source[page_number]
        identity = (question['document_id'], page_number)
        native_key = (*identity, 'native')
        if native_key not in cache:
            cache[native_key] = page.get_text('rawdict', flags=fitz.TEXTFLAGS_RAWDICT & ~fitz.TEXT_PRESERVE_IMAGES)
        boxes = number_boxes(cache[native_key], region, question['number'])
        band = fitz.Rect(region['rect']); band.y1 = min(band.y1, band.y0 + 35)
        if not boxes and not page.get_text(clip=band).strip():
            ocr_key = (*identity, 'ocr')
            if ocr_key not in cache:
                try:
                    with _ocr_lock:
                        textpage = page.get_textpage_ocr(language='eng', dpi=200, full=True)
                        cache[ocr_key] = page.get_text('rawdict', textpage=textpage)
                except (RuntimeError, fitz.mupdf.FzErrorBase):
                    cache[ocr_key] = None
            if cache[ocr_key] is not None:
                boxes = number_boxes(cache[ocr_key], region, question['number'], ocr=True)
            else:
                warnings.append('Could not verify the original number on a scanned page; inspect this question in the generated PDF.')
        for box in boxes:
            page.add_redact_annot(box, fill=(1, 1, 1))
        if boxes:
            # Raster number pixels are erased too, while diagrams and part labels stay.
            page.apply_redactions(images=2, graphics=0, text=0)
            erased += len(boxes)
    return dict(erased_labels=erased, warnings=warnings)
