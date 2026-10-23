"""Trim empty crop residue and paginate visible content at a fixed top edge."""
from io import BytesIO

import fitz
from PIL import Image


def content_bounds(page, rect):
    # Inspect pixels so scanned diagrams count even when no text was recognized.
    pix = page.get_pixmap(clip=rect, matrix=fitz.Matrix(1, 1), alpha=False)
    ink = Image.open(BytesIO(pix.tobytes('png'))).convert('L').point(lambda p: 255 if p < 210 else 0)
    box = ink.getbbox()
    if box is None:
        return None
    # A few isolated scan specks do not justify a new page. Keep small actual
    # symbols and diagram-only crops; do not require readable prose.
    if ink.histogram()[255] < 5:
        return None
    scale_y = rect.height / pix.height
    return fitz.Rect(rect.x0, max(rect.y0, rect.y0 + box[1] * scale_y - 3),
                     rect.x1, min(rect.y1, rect.y0 + box[3] * scale_y + 3))


def question_clips(source, regions):
    """Suppress empty regions/tiles, keeping source and subquestion order."""
    for region in regions:
        page = source[region['page']]
        area = fitz.Rect(region['rect'])
        # IB registration barcodes are vector bars in the bottom margin, not
        # question diagrams. Their top can intrude above an automatic crop's end.
        bars = [d['rect'] for d in page.get_drawings()
                if 0 < d['rect'].width < 4 and d['rect'].height > 12
                and d['rect'].y0 > page.rect.height - 70
                and abs(d['rect'].x0 - page.rect.width / 2) < 60]
        if len(bars) >= 10:
            area.y1 = min(area.y1, min(b.y0 for b in bars) - 3)
        if area.is_empty:
            continue
        rect = content_bounds(page, area)
        if rect is None:
            continue
        max_height = 710 * rect.width / 495
        top = rect.y0
        while top < rect.y1:
            tile = fitz.Rect(rect.x0, top, rect.x1, min(rect.y1, top + max_height))
            visible = content_bounds(page, tile)
            if visible is not None:
                yield region['page'], visible
            top += max_height


def add_question_pages(pdf, source, question, number):
    count = 0
    for page_number, clip in question_clips(source, question['regions']):
        page = pdf.new_page()
        label = f'Question {number}' + (' (continued)' if count else '')
        page.insert_text((50, 35), label, fontsize=12)
        # show_pdf_page centres by default. A box with the crop's actual aspect
        # ratio makes its top coincide with y=60 for short and tall crops alike.
        height = min(710, clip.height * 495 / clip.width)
        page.show_pdf_page(fitz.Rect(50, 60, 545, 60 + height), source, page_number, clip=clip)
        page.insert_text((50, 805), f"Source: {question['filename'][:55].encode('ascii', 'replace').decode()} | {question['year']} | {question['paper']}", fontsize=8)
        count += 1
    return count
