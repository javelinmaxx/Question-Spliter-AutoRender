"""Deterministic markscheme extraction and selected-question PDF rendering.

This module performs local PDF/OCR processing only. It deliberately has no
language-model dependency or callback.
"""
import re

import fitz


def extract_markscheme_entries(page_texts, paper):
    """Return parent-question entries keyed by question number."""
    pages = list(page_texts or [])
    if paper in ("Paper 1", "Paper 1A", "Paper 1B"):
        text = "\n".join(pages)
        entries = {}
        for number, answer in re.findall(r"(?<!\d)(\d{1,2})\s*[.)]\s*([A-D])\b", text, re.I):
            entries[int(number)] = [f"Answer: {answer.upper()}"]
        return entries

    entries = {}
    current = None
    # IB structured markschemes begin their marking tables after the cover,
    # copyright page and marking instructions.
    for page_text in pages[3:]:
        continuation = re.search(r"\(Question\s+(\d+)\s+continued\)", page_text, re.I)
        if continuation:
            current = int(continuation.group(1))
        for raw_line in page_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if re.fullmatch(r"\(Question\s+\d+\s+continued\)", line, re.I):
                continue
            row = re.match(r"^(\d{1,2})\.\s+(.+)$", line)
            if row:
                current = int(row.group(1))
            if current is not None:
                entries.setdefault(current, []).append(line)
    return {number: lines for number, lines in entries.items() if lines}


def render_selected_markscheme(path, selected_entries, *, title="Generated Physics markscheme"):
    """Create a separate markscheme containing only selected question entries."""
    with fitz.open() as output:
        for item in selected_entries:
            lines = list(item.get("lines") or [])
            if not lines:
                continue
            # Standard PDF base fonts use WinAnsi. Keep common physics symbols
            # where possible and replace unsupported glyphs rather than failing
            # the whole generated paper.
            text = "\n".join(lines)
            text = text.encode("cp1252", "replace").decode("cp1252")
            chunks = []
            current, size = [], 0
            for line in text.splitlines():
                if size + len(line) > 2600 and current:
                    chunks.append("\n".join(current))
                    current, size = [], 0
                current.append(line)
                size += len(line) + 1
            if current:
                chunks.append("\n".join(current))
            for part_index, chunk in enumerate(chunks, 1):
                page = output.new_page(width=595, height=842)
                label = f"Question {item['number']}"
                if len(chunks) > 1:
                    label += f" (continued {part_index}/{len(chunks)})"
                page.insert_text((48, 48), title, fontname="hebo", fontsize=12)
                page.insert_text((48, 68), label, fontname="hebo", fontsize=10)
                page.insert_text((48, 84), f"Source: {item.get('source_filename', 'Imported markscheme')} · "
                                  f"{item.get('year')} · {item.get('paper')} · {item.get('timezone')}",
                                  fontsize=7, color=(0.35, 0.35, 0.35))
                remaining = page.insert_textbox(
                    fitz.Rect(48, 100, 547, 790), chunk,
                    fontname="cour", fontsize=8, lineheight=1.15,
                )
                if remaining < 0:
                    raise ValueError(f"Markscheme text for question {item['number']} does not fit on the generated page.")
        if not len(output):
            raise ValueError("No matching markscheme entries were available to generate.")
        total = len(output)
        for index, page in enumerate(output, 1):
            page.insert_text((260, 820), f"Page {index} of {total}", fontsize=8)
        output.set_metadata({
            "title": title,
            "author": "Physics Question Bank",
            "subject": "Selected markscheme entries matched by year, paper, time zone and question number",
        })
        output.save(path, garbage=4, deflate=True, clean=True)
    return len(selected_entries)
