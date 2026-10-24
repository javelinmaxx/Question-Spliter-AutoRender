"""Reusable sequential-question PDF/OCR engine with injected subject rules."""
import re
import fitz
from ocr import read_pages, region_text


def extract_pdf(path, filename, *, metadata_fn, suggest_fn, ocr_mode='auto', page_records=None, ocr_cache=None, page_reader=read_pages):
    with fitz.open(path) as pdf:
        if pdf.needs_pass:
            raise ValueError('Password-protected PDFs are not supported. Upload an unlocked copy.')
        if len(pdf) > 150:
            raise ValueError('Upload a paper with at most 150 pages.')
        if not len(pdf):
            raise ValueError('PDF contains no pages.')
        records, ocr_warnings = page_reader(pdf, ocr_mode, ocr_cache) if page_records is None else (page_records, [])
        text = '\n'.join(r['native'] if len(r['native'].strip()) >= 50 else r['text'] for r in records)
        metadata = metadata_fn(text, filename)
        labels, starts, numbering_warnings = [], [], []
        for index, record in enumerate(records):
            page = pdf[index]
            selected_lines = record['native_lines'] if len(record['native'].strip()) >= 50 else record['lines']
            for line in sorted(selected_lines, key=lambda l: (round(l['bbox'][1] / 3), l['bbox'][0])):
                match = re.match(r'^(\d{1,2})[.)](?:\s|$)', line['text'].strip())
                if (match and page.rect.width * .05 <= line['bbox'][0] <= page.rect.width * .20
                        and 50 < line['bbox'][1] < page.rect.height - 45):
                    labels.append((index, max(40, line['bbox'][1] - 5), int(match[1]), len(record['native'].strip()) < 50))
        expected = 1
        for i, (page_no, top, detected, is_ocr) in enumerate(labels):
            following = labels[i + 1][2] if i + 1 < len(labels) else None
            inferred = (is_ocr and detected != expected and str(detected).replace('4', '1') == str(expected)
                        and following == expected + 1)
            if detected == expected or inferred:
                if inferred:
                    numbering_warnings.append(f'Page {page_no + 1}: OCR read question {detected}; proposed {expected} from adjacent numbering. Confirm the image.')
                starts.append((page_no, top, expected))
                expected += 1
        candidates = []
        for i, (page_no, top, number) in enumerate(starts):
            end_page, end_y, _ = starts[i + 1] if i + 1 < len(starts) else (len(pdf) - 1, pdf[-1].rect.height - 30, 0)
            regions = []
            for n in range(page_no, end_page + 1):
                page = pdf[n]
                page_body = records[n]['native'] or records[n]['text']
                if re.search(r'(?im)^\s*(Disclaimer:|References:|Please do not write on this page)', page_body):
                    continue
                bottom = end_y if n == end_page else page.rect.height - 45
                y = top if n == page_no else 50
                if bottom <= y:
                    continue
                rect = [30, y, page.rect.width - 30, bottom]
                regions.append(dict(page=n, rect=rect))
            body = region_text(records, regions)
            ocr_text = region_text(records, regions, 'ocr')
            suggestions = suggest_fn(body, metadata['paper'], metadata['level'],metadata['syllabus'])
            ocr_suggestions = suggest_fn(ocr_text, metadata['paper'], metadata['level'],metadata['syllabus']) if ocr_text.strip() else None
            sources = ['native' if len(records[r['page']]['native'].strip()) >= 50 else 'ocr' for r in regions]
            comparison = dict(status='not_run', topics=[], commands=[])
            if ocr_suggestions:
                comparison = dict(status='agreement' if set(suggestions['topics']) == set(ocr_suggestions['topics']) else 'disagreement',
                                  topics=ocr_suggestions['topics'], commands=ocr_suggestions['commands'])
                if all(source == 'ocr' for source in sources):
                    comparison['status'] = 'ocr_only'
            candidates.append(dict(number=number, regions=regions, text=body, text_source='mixed' if len(set(sources)) > 1 else sources[0],
                                   ocr_comparison=comparison, **metadata, **suggestions))
        pages = [dict(width=round(p.rect.width, 2), height=round(p.rect.height, 2)) for p in pdf]
        warnings = ['Automatic crops and tags are suggestions. Review diagrams, continuations and boundaries before saving.', *ocr_warnings, *numbering_warnings]
        if len(text.strip()) < 50:
            warnings.append('No readable text found after extraction/OCR; create crops and enter metadata manually.')
        if not starts:
            warnings.append('No sequential question numbers detected. Add questions manually using page crops.')
        maximum = re.search(r'maximum mark.{0,100}?[\[(]?(\d{2,3})\s*marks?', re.sub(r'\s+', ' ', text[:10000]), re.I)
        expected_marks = int(maximum[1]) if maximum else None
        detected_marks = sum(q['marks'] or 0 for q in candidates)
        mark_audit = dict(expected=expected_marks, detected=detected_marks,
                          status='matched' if expected_marks == detected_marks else 'mismatch' if expected_marks else 'unknown')
        if mark_audit['status'] == 'mismatch':
            warnings.append(f'Detected {detected_marks} marks, but the cover states {expected_marks}. Review question marks and timing; OCR may omit mark brackets.')
        return dict(metadata=metadata, pages=pages, questions=candidates, warnings=warnings, text_pages=records,
                    mark_audit=mark_audit, ocr_pages=sum(bool(r.get('ocr_ran') or r['lines']) for r in records))

