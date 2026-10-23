"""Build the root roadmap PDF from the versioned filter policy using PyMuPDF."""
from pathlib import Path
import json
import sys

import fitz

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from physics import TOPICS

POLICY = json.loads((ROOT / 'curriculum_prerequisites.json').read_text())
OUTPUT = ROOT / 'IB Physics Prerequisite Roadmap.pdf'
INK = (0.12, 0.18, 0.25)
BLUE = (0.08, 0.30, 0.48)
LIGHT = (0.93, 0.96, 0.98)


def lines(text, width, size=10, font='helv'):
    result = []
    for paragraph in text.split('\n'):
        current = ''
        for word in paragraph.split():
            candidate = (current + ' ' + word).strip()
            if fitz.get_text_length(candidate, fontname=font, fontsize=size) > width and current:
                result.append(current)
                current = word
            else:
                current = candidate
        result.append(current)
    return result


def write(page, x, y, text, width=507, size=10, color=INK, font='helv'):
    for line in lines(text, width, size, font):
        page.insert_text((x, y), line, fontname=font, fontsize=size, color=color)
        y += size * 1.38
    return y


def heading(doc, number, title, subtitle):
    page = doc.new_page(width=595, height=842)
    page.draw_rect(fitz.Rect(0, 0, 595, 12), color=BLUE, fill=BLUE)
    y = write(page, 44, 49, title, size=21, color=BLUE, font='hebo')
    y = write(page, 44, y + 8, subtitle, size=10)
    page.insert_text((44, 815), f'IB DP Physics | First assessment 2025 | Filter policy v{POLICY["version"]}', fontsize=8, color=BLUE)
    page.insert_text((510, 815), f'{number} / 7', fontsize=8, color=BLUE)
    return page, y + 20


def table(page, y, columns, rows, size=9):
    widths = [width for _, width in columns]
    for index, cells in enumerate([[name for name, _ in columns]] + rows):
        wrapped = [lines(str(cell), width - 14, size) for cell, width in zip(cells, widths)]
        height = max(len(value) for value in wrapped) * size * 1.38 + 13
        if y + height > 790:
            raise ValueError('Roadmap table exceeds printable page.')
        page.draw_rect(fitz.Rect(44, y, 551, y + height), color=(0.82, 0.87, 0.90), fill=BLUE if index == 0 else LIGHT if index % 2 else (1, 1, 1), width=.4)
        x = 44
        for value, width in zip(wrapped, widths):
            write(page, x + 7, y + size + 5, '\n'.join(value), width - 14, size, (1, 1, 1) if index == 0 else INK, 'hebo' if index == 0 else 'helv')
            x += width
        y += height
    return y


def build():
    doc = fitz.open()
    p, y = heading(doc, 1, 'Physics prerequisite roadmap', 'A content-based analysis of all five themes and 24 subtopics. No example teaching route is used.')
    y = write(p, 44, y, 'How to read the deductions', size=13, font='hebo')
    y = write(p, 44, y + 4, 'Core foundations are inferred from the physics needed to understand a topic. A core permission allows earlier content in a query; it does not mean every individual question requires the whole foundation topic. Conditional links apply only to specific extensions and never expand a topic query automatically.')
    y = write(p, 44, y + 16, 'Foundation -> dependent topic', size=13, font='hebo')
    # Exact mechanics chain. Arrows point from required foundation to dependent topic.
    y += 12
    for i, (code, name) in enumerate([('A.1', 'Motion'), ('A.2', 'Forces'), ('A.3', 'Energy'), ('D.1', 'Gravity')]):
        x = 44 + i * 132
        p.draw_rect(fitz.Rect(x, y, x + 111, y + 44), color=BLUE, fill=LIGHT)
        write(p, x + 9, y + 16, code + ' / ' + name, width=95, size=10, color=BLUE)
        if i < 3:
            p.draw_line((x + 113, y + 22), (x + 129, y + 22), color=BLUE)
            p.draw_line((x + 129, y + 22), (x + 125, y + 18), color=BLUE)
            p.draw_line((x + 129, y + 22), (x + 125, y + 26), color=BLUE)
    y = write(p, 44, y + 64, 'Gravity may include earlier circular motion and energy. A forces query does not gain permission for gravity. Gravity also has a direct forces foundation; the diagram shows the transitive chain.', size=10)
    y = write(p, 44, y + 16, 'Dependency layers across the whole syllabus', size=13, font='hebo')
    levels = {}
    def level(code):
        if code not in levels:
            levels[code] = 0 if not POLICY['requires'][code] else 1 + max(level(c) for c in POLICY['requires'][code])
        return levels[code]
    for code in TOPICS:
        level(code)
    rows = [[str(i), ', '.join(c for c in TOPICS if levels[c] == i)] for i in range(max(levels.values()) + 1)]
    y = table(p, y + 10, [('Layer', 60), ('Topics with this longest prerequisite depth', 447)], rows, size=9)
    write(p, 44, y + 19, 'Layers are a topological view of the inferred graph, not a prescribed teaching order. Topics in one layer are not prerequisites for one another. Units, algebra, graphs, proportionality and vector skills underpin the map without being separate topic codes.', size=9)

    for number, (theme, data) in enumerate(POLICY['themes'].items(), 2):
        p, y = heading(doc, number, theme + '. ' + data['title'], data['summary'])
        for code, analysis in POLICY['topic_analysis'].items():
            if not code.startswith(theme + '.'):
                continue
            label = 'HL only' if code in POLICY['level_scope']['HL_only'] else 'SL + additional HL' if code in POLICY['level_scope']['SL_and_additional_HL'] else 'SL / HL common'
            y = write(p, 44, y, code + '  ' + TOPICS[code] + '  [' + label + ']', size=11, font='hebo', color=BLUE)
            y = write(p, 44, y + 2, analysis['summary'], size=9.5)
            core = ', '.join(analysis['core_prerequisites']) or 'No earlier topic; foundational skills only'
            optional = ', '.join(analysis['conditional_links']) or 'None assigned'
            y = write(p, 44, y + 3, 'Core: ' + core + '.  Conditional: ' + optional + '.', size=9, font='hebo')
            y = write(p, 44, y + 2, 'Deduction: ' + analysis['deduction'], size=9)
            y = write(p, 44, y + 2, 'Evidence: TSM printed pp. ' + analysis['printed_pages'] + '. ' + analysis['coverage'], size=8, color=(.33, .38, .42))
            p.draw_line((44, y + 5), (551, y + 5), color=(.8, .85, .9), width=.5)
            y += 20
        if y > 798:
            raise ValueError(f'Theme {theme} overflows: {y}')

    p, y = heading(doc, 7, 'Rules for topic-safe selection', 'Use the content prerequisites together with a separately approved subquestion dependency map.')
    examples = [
        ('1. Expand only core foundations', 'Allowed scope = selected targets plus their transitive core foundations. Conditional links are excluded unless selected explicitly or already reached through a core path. Never infer reverse links or all same-theme topics.'),
        ('2. Require a target task', 'At least one retained task must be tagged with a selected target. A mechanics-only question is not a gravity result, even though mechanics is in the gravity knowledge scope.'),
        ('3. Remove out-of-scope extensions', 'For A.1 motion, remove an optional A.3 energy extension. For D.1 gravity, allow A.2 circular motion; for A.2 forces, do not permit D.1. An inseparable multi-topic task needs all its topics in the allowed scope.'),
        ('4. Preserve the dependency direction', 'If X requires A, retaining X always retains A and the shared stem. Retaining A does not force X. When an out-of-scope prerequisite is removed, remove its dependants too. Reject the parent if no target task survives or the shared stem is out of scope.'),
        ('5. Keep approval and level checks', 'Only current, reviewed part crops, topic tags and acyclic dependency maps authorize trimming. Missing or stale maps permit a whole question only if all parent tags fit. HL/SL suitability is a separate check; mixed-depth topic codes do not certify SL content.'),
        ('6. Apply Full and Short consistently', 'Unfiltered Full preserves every crop. Topic-filtered Full keeps every in-scope task. Short may additionally omit optional tasks, preferring independent tasks, while preserving a target task and all required context.')]
    for title, body in examples:
        y = write(p, 44, y, title, size=11, color=BLUE, font='hebo')
        y = write(p, 44, y + 2, body, size=9.3) + 10
    y = write(p, 44, y + 2, 'Source and limits', size=12, font='hebo')
    y = write(p, 44, y + 4, 'IB Physics teacher support material, first assessment 2025; published September 2023, updated July/November 2024. Analysis uses printed pp. 2-17 (PDF pp. 7-22); the sample teaching route is excluded. The uploaded PDF has 116 pages. Full source identity and per-topic rationales are in curriculum_prerequisites.json.', size=8.5)
    y = write(p, 44, y + 5, 'This is a content-based project synthesis, not an official IB prerequisite specification or an exhaustive syllabus checklist. The support material is brief on some topics; the cards label physics deductions where details are inferred. Core versus conditional is an application judgement that can be revised after teacher review.', size=8.5)
    write(p, 44, y + 5, 'Small-model dependency suggestions require human approval. Current real inference has not demonstrated reliable dependency classification; conservative validation rejects invalid graphs.', size=8.5)
    doc.set_metadata({'title':'IB DP Physics Content and Prerequisite Roadmap', 'author':'Question Splitter project', 'subject':'All 24 subtopics: content summaries, deduced prerequisites and conditional links'})
    doc.save(OUTPUT, garbage=4, deflate=True)
    print(OUTPUT)


if __name__ == '__main__':
    build()
