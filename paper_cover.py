"""Original practice-paper cover using familiar examination page conventions."""
import fitz


BLACK = (0.08, 0.08, 0.08)
GRAY = (0.40, 0.40, 0.40)


def duration_label(minutes):
    hours = int(minutes // 60)
    remainder = round(minutes - hours * 60, 1)
    pieces = []
    if hours:
        pieces.append(f'{hours} hour' + ('s' if hours != 1 else ''))
    if remainder or not pieces:
        pieces.append(f'{remainder:g} minute' + ('s' if remainder != 1 else ''))
    return ' '.join(pieces)


def add_practice_cover(pdf, *, level, syllabus, target, chosen, mode):
    page = pdf.new_page(width=595, height=842)
    paper_types = sorted({q['paper'] for q in chosen})
    paper_label = paper_types[0] if len(paper_types) == 1 else 'Mixed-paper practice'
    subject = {'HL':'Higher level','SL':'Standard level','SL_from_HL':'Standard level - questions from HL papers','Any':'Mixed levels'}[level]
    page.insert_text((56, 83), 'Physics', fontname='hebo', fontsize=14, color=BLACK)
    page.insert_text((56, 101), subject, fontname='hebo', fontsize=12, color=BLACK)
    page.insert_text((56, 119), paper_label, fontname='hebo', fontsize=12, color=BLACK)
    page.insert_textbox(fitz.Rect(325, 50, 539, 85), 'PRACTICE ASSESSMENT\nIB DP Physics question bank',
                        fontname='hebo', fontsize=9, align=2, color=GRAY)
    page.insert_text((56, 151), 'Date: ____________________', fontsize=10, color=BLACK)
    page.insert_text((56, 173), 'Name: ______________________________', fontsize=10, color=BLACK)
    page.insert_textbox(fitz.Rect(339, 165, 539, 181), 'Candidate number (optional)', fontsize=9, align=1, color=BLACK)
    for index in range(10):
        left = 339 + index * 20
        page.draw_rect(fitz.Rect(left, 185, left + 20, 205), color=GRAY, width=.6)
    page.insert_text((56, 204), 'Time allowed: ' + duration_label(target), fontsize=11, color=BLACK)
    page.draw_line((56, 216), (539, 216), color=BLACK, width=.8)
    page.insert_text((56, 238), 'Instructions to candidates', fontname='hebo', fontsize=11, color=BLACK)
    all_mcq = all(q['paper'] in ('Paper 1', 'Paper 1A') for q in chosen)
    instructions = [
        'Answer all questions included in this practice paper.',
        'Record your answers clearly on separate paper.' if all_mcq else 'Write your answers on separate paper; show calculations and units where appropriate.',
        'Use the calculator and data booklet arrangements specified by your teacher.',
        'Questions are numbered consecutively; original subquestion labels are retained.'
    ]
    marks = [q.get('marks') for q in chosen]
    if all(isinstance(mark, (int, float)) and mark > 0 for mark in marks):
        instructions.append(f'The maximum mark for this practice paper is [{sum(marks):g} marks].')
    else:
        instructions.append('Total marks are not confirmed; follow the mark labels on the included parts.')
    y = 260
    for text in instructions:
        page.insert_text((58, y), '\u2022', fontsize=10, color=BLACK)
        height = 32 if len(text) > 90 else 26
        remaining = page.insert_textbox(fitz.Rect(72, y - 11, 539, y + height), text, fontsize=10, lineheight=1.35, color=BLACK)
        if remaining < 0:
            raise ValueError('Candidate instructions do not fit the cover page.')
        y += height
    top = max(420, y + 24)
    page.draw_line((56, top), (539, top), color=(.72,.72,.72), width=.5)
    syllabus_label = 'First assessment 2025' if syllabus == '2025' else 'Legacy syllabus'
    actual = round(sum(q['minutes'] for q in chosen), 1)
    page.insert_text((56, top + 23), 'Practice-paper details', fontname='hebo', fontsize=10, color=BLACK)
    details = [f'Syllabus: {syllabus_label}', f'Question groups: {len(chosen)}',
               f'Estimated question time: {duration_label(actual)}', f'Rendering: {mode.title()}']
    if actual < target:
        details.append(f'The selected questions are {target - actual:g} estimated minutes below the requested length.')
    page.insert_textbox(fitz.Rect(56, top + 34, 539, top + 150), '\n'.join(details), fontsize=10, lineheight=1.5, color=GRAY)
    page.insert_textbox(fitz.Rect(56, 734, 539, 777),
                        'Generated practice material. Not an official IB examination.\nTime estimates are approximate. This application is not affiliated with the International Baccalaureate.',
                        fontsize=8, lineheight=1.4, color=GRAY)
    pdf.set_metadata({'title': f'Physics {level} - {paper_label} - Practice assessment',
                      'author': 'Physics Question Bank', 'subject': 'Generated IB DP Physics practice material'})


def finalize_practice_cover(pdf):
    page = pdf[0]
    page.insert_text((56, 798), f'{len(pdf)} pages', fontsize=9, color=GRAY)
    page.insert_text((470, 798), 'Practice paper', fontsize=9, color=GRAY)
