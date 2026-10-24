"""Trim empty crop residue and paginate visible content at a fixed top edge."""
from io import BytesIO

import fitz
from PIL import Image
from source_origin import origin_label
from crop_display import display_regions


def paper_family(question):
    return 'Paper 1' if question.get('paper') in ('Paper 1', 'Paper 1A', 'Paper 1B') else question.get('paper', 'Unknown')


def group_questions(questions):
    """Stable grouping: preserve teacher/fill order inside each paper family."""
    return sorted(questions, key=lambda q: {'Paper 1': 0, 'Paper 2': 1, 'Paper 3': 2}.get(paper_family(q), 3))


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


def question_clips(source, regions, max_output_height=710, *, paper='Unknown', parent_regions=None):
    """Suppress empty regions/tiles, keeping source and subquestion order."""
    for region in display_regions(regions, paper, parent_regions):
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
        max_height = max_output_height * rect.width / 495
        top = rect.y0
        while top < rect.y1:
            tile = fitz.Rect(rect.x0, top, rect.x1, min(rect.y1, top + max_height))
            visible = content_bounds(page, tile)
            if visible is not None:
                yield region['page'], visible
            top += max_height


class PaperLayout:
    """Flow complete question groups into remaining space at a readable scale."""
    TOP, BOTTOM = 35, 780
    HEADING, REFERENCE, QUESTION_GAP, CROP_GAP = 25, 14, 18, 6
    MIN_SCALE = .85  # At most 15% reduction; retain readable exam text/diagrams.

    def __init__(self, pdf):
        self.pdf = pdf
        self.page_index = None  # The cover is never a question-content page.
        self.cursor = self.TOP
        self.family = None

    def new_page(self):
        self.pdf.new_page()
        self.page_index = len(self.pdf) - 1
        self.cursor = self.TOP

    def reference(self, question):
        filename = question['filename'][:55].encode('ascii', 'replace').decode()
        suffix = f" | {question['year']} | {question['paper']} | {origin_label(question)}"
        while filename and fitz.get_text_length('Source: ' + filename + suffix, fontsize=8) > 495:
            filename = filename[:-1]
        text = 'Source: ' + filename + suffix
        self.pdf[self.page_index].insert_text((50, self.cursor + 10), text, fontsize=8)
        self.cursor += self.REFERENCE

    def add_question(self, source, question, number, *, parent_regions=None):
        capacity = self.BOTTOM - self.TOP - self.HEADING - self.REFERENCE
        clips = list(question_clips(source, question['regions'], capacity,
                                    paper=question.get('paper'), parent_regions=parent_regions))
        if not clips:
            return 0
        heights = [clip.height * 495 / clip.width for _, clip in clips]
        body_height = sum(heights)
        overhead = self.HEADING + self.CROP_GAP * (len(clips) - 1) + self.REFERENCE
        scale = 1.
        # Reserve the inter-question gap when sizing a half-page group. Size
        # the first group too, so two slightly oversized halves can both fit.
        half_page = (self.BOTTOM - self.TOP - self.QUESTION_GAP) / 2
        half_scale = (half_page - overhead) / body_height
        if self.MIN_SCALE <= half_scale < 1:
            scale = half_scale
        family = paper_family(question)
        if self.page_index is not None and self.family == family:
            remaining_scale = (self.BOTTOM - self.cursor - overhead) / body_height
            if self.MIN_SCALE <= remaining_scale < scale:
                scale = remaining_scale
        heights = [height * scale for height in heights]
        total = overhead + sum(heights)
        # If a whole parent will fit on a fresh page, do not split it simply
        # because another question has already used some of the current page.
        # Larger parents also start fresh, keeping their continuations together.
        if self.page_index is None or self.family != family or self.cursor + total > self.BOTTOM + .01:
            self.new_page()
        self.family = family
        used_pages = set()
        continued = False
        needs_heading = True
        for (page_number, clip), height in zip(clips, heights):
            overhead = self.HEADING if needs_heading else self.CROP_GAP
            if self.cursor + overhead + height + self.REFERENCE > self.BOTTOM + .01:
                if not needs_heading:
                    self.reference(question)
                self.new_page()
                continued, needs_heading = True, True
            page = self.pdf[self.page_index]
            if needs_heading:
                label = f'Question {number}' + (' (continued)' if continued else '')
                page.insert_text((50, self.cursor), label, fontsize=12)
                self.cursor += self.HEADING
                needs_heading = False
            else:
                self.cursor += self.CROP_GAP
            page.show_pdf_page(fitz.Rect(50, self.cursor, 50 + 495 * scale, self.cursor + height),
                               source, page_number, clip=clip)
            self.cursor += height
            used_pages.add(self.page_index)
        self.reference(question)
        self.cursor += self.QUESTION_GAP
        return len(used_pages)


def add_question_pages(pdf, source, question, number, layout=None, *, parent_regions=None):
    return (layout if layout is not None else PaperLayout(pdf)).add_question(
        source, question, number, parent_regions=parent_regions)
