"""Deterministic markscheme extraction and selected-question PDF rendering.

This module performs local PDF/OCR processing only. It deliberately has no
language-model dependency or callback.
"""
import re

import fitz


def _line_records(page):
    """Group PDF words into visual lines, including table cells at the same height."""
    words = page.get_text("words", sort=True)
    groups = []
    for word in words:
        x0, y0, x1, y1, text = word[:5]
        match = next((line for line in groups if abs(line["y0"] - y0) <= 1.8), None)
        if match is None:
            match = {"y0": y0, "y1": y1, "words": []}
            groups.append(match)
        match["y0"] = min(match["y0"], y0)
        match["y1"] = max(match["y1"], y1)
        match["words"].append((x0, text))
    for line in groups:
        line["words"].sort(key=lambda item: item[0])
        line["text"] = " ".join(word for _, word in line["words"]).strip()
        line["x0"] = min(x for x, _ in line["words"])
    return sorted(groups, key=lambda line: (line["y0"], line["x0"]))


def extract_markscheme_regions(pdf, paper):
    """Locate exact question-row bands on structured markscheme pages."""
    if paper in ("Paper 1", "Paper 1A", "Paper 1B"):
        return {}
    regions = {}
    for page_index in range(3, len(pdf)):
        page = pdf[page_index]
        page_text = page.get_text("text")
        continuation = re.search(r"\(Question\s+(\d+)\s+continued\)", page_text, re.I)
        current = int(continuation.group(1)) if continuation else None
        page_bands = {}
        for line in _line_records(page):
            row = re.match(r"^(\d{1,2})\.\s+", line["text"])
            if row and line["x0"] < 150:
                current = int(row.group(1))
            if current is None:
                continue
            band = page_bands.setdefault(current, [line["y0"], line["y1"]])
            band[0] = min(band[0], line["y0"])
            band[1] = max(band[1], line["y1"])
        for number, (top, bottom) in page_bands.items():
            if bottom > top:
                regions.setdefault(number, []).append({
                    "page": page_index,
                    "rect": [0, max(0, top - 3), page.rect.width, min(page.rect.height, bottom + 3)],
                })
    return regions


def extract_markscheme_entries(page_texts, paper, regions=None):
    """Return parent-question entries keyed by question number."""
    pages = list(page_texts or [])
    if paper in ("Paper 1", "Paper 1A", "Paper 1B"):
        text = "\n".join(pages)
        entries = {}
        for number, answer in re.findall(r"(?<!\d)(\d{1,2})\s*[.)]\s*([A-D])\b", text, re.I):
            entries[int(number)] = {"lines": [f"Answer: {answer.upper()}"], "regions": []}
        return entries

    entries = {}
    current = None
    # First three pages are the cover, copyright notice and marking instructions.
    for page_text in pages[3:]:
        continuation = re.search(r"\(Question\s+(\d+)\s+continued\)", page_text, re.I)
        if continuation:
            current = int(continuation.group(1))
        for raw_line in page_text.splitlines():
            line = raw_line.strip()
            if not line or re.fullmatch(r"\(Question\s+\d+\s+continued\)", line, re.I):
                continue
            row = re.match(r"^(\d{1,2})\.\s+(.+)$", line)
            if row:
                current = int(row.group(1))
            if current is not None:
                entries.setdefault(current, []).append(line)
    return {
        number: {"lines": lines, "regions": (regions or {}).get(number, [])}
        for number, lines in entries.items() if lines
    }


def render_selected_markscheme(path, selected_entries, *, title="Generated Physics markscheme"):
    """Create a separate markscheme containing only selected question entries."""
    with fitz.open() as output:
        for item in selected_entries:
            regions = list(item.get("regions") or [])
            source_path = item.get("source_path")
            if regions and source_path:
                with fitz.open(source_path) as source:
                    for region_index, region in enumerate(regions, 1):
                        page = output.new_page(width=595, height=842)
                        label = f"Question {item['number']}"
                        if len(regions) > 1:
                            label += f" (continued {region_index}/{len(regions)})"
                        page.insert_text((48, 48), title, fontname="hebo", fontsize=12)
                        page.insert_text((48, 68), label, fontname="hebo", fontsize=10)
                        page.insert_text((48, 84),
                                         f"Source: {item.get('source_filename', 'Imported markscheme')} · "
                                         f"{item.get('year')} · {item.get('paper')} · {item.get('timezone')}",
                                         fontsize=7, color=(0.35, 0.35, 0.35))
                        page.show_pdf_page(
                            fitz.Rect(24, 100, 571, 790), source, region["page"],
                            clip=fitz.Rect(region["rect"]),
                        )
                continue

            lines = list(item.get("lines") or [])
            if not lines:
                continue
            text = "\n".join(lines).encode("cp1252", "replace").decode("cp1252")
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
                page.insert_text((48, 84),
                                 f"Source: {item.get('source_filename', 'Imported markscheme')} · "
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
