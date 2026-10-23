"""Reviewed subquestion layouts and directed prerequisite constraints."""
import hashlib
import json
import math
import re

from ocr import region_text
from physics import TOPICS, suggest

VERSION = 1


def question_hash(question):
    return hashlib.sha256(json.dumps({key: question[key] for key in ('regions', 'text', 'minutes', 'paper')}, sort_keys=True).encode()).hexdigest()


def propose_parts(question, records):
    """Suggest top-level lettered parts; retain roman-numbered parts inside them."""
    starts = []
    expected = 'a'
    for index, region in enumerate(question['regions']):
        record = records[region['page']]
        lines = record['native_lines'] if len(record['native'].strip()) >= 50 else record['lines']
        for line in sorted(lines, key=lambda line: (line['bbox'][1], line['bbox'][0])):
            box = line['bbox']
            match = re.match(r'^\(([a-z])\)(?:\s|$)', line['text'].strip())
            if (match and match[1] == expected and region['rect'][0] <= box[0] <= record['width'] * .30
                    and region['rect'][1] <= (box[1] + box[3]) / 2 <= region['rect'][3]):
                top = max(region['rect'][1], box[1] - 3)
                # Do not manufacture a tiny stem crop when (a) shares the first line.
                if not starts and top - region['rect'][1] < 5:
                    top = region['rect'][1]
                starts.append((index, top, expected))
                expected = chr(ord(expected) + 1)
    if len(starts) < 2:
        return None

    def slice_regions(start, end):
        result = []
        for index in range(start[0], min(end[0] + 1, len(question['regions']))):
            source = question['regions'][index]
            left, top, right, bottom = source['rect']
            if index == start[0]:
                top = start[1]
            if index == end[0]:
                bottom = end[1]
            if bottom - top >= 5:
                result.append(dict(page=source['page'], rect=[left, top, right, bottom]))
        return result

    first = question['regions'][0]
    end = (len(question['regions']), 0)
    parts = [dict(id='stem', label='Shared stem (always retained)', requires=[], minutes=0,
                  regions=slice_regions((0, first['rect'][1]), starts[0][:2]))]
    each = max(.1, math.floor(question['minutes'] * 10 / len(starts)) / 10)
    for i, (index, top, label) in enumerate(starts):
        regions = slice_regions((index, top), starts[i + 1][:2] if i + 1 < len(starts) else end)
        parts.append(dict(id=label, label=f'({label})', regions=regions, minutes=each,
                          requires=['stem', *[p['id'] for p in parts if p['id'] != 'stem']]))
    for part in parts:
        part['text'] = region_text(records, part['regions'])
        part['topics'] = suggest(part['text'], question['paper'], question.get('level'))['topics']
    return dict(version=VERSION, source_hash=question_hash(question), status='draft', parts=parts,
                model_review=None, reason='Review every boundary and dependency. Unknown dependencies initially retain all earlier parts.')


def validate_layout(question, parts):
    """Require a lossless full-width partition so omitted crops cannot hide shared text."""
    if not isinstance(parts, list) or not 3 <= len(parts) <= 33:
        raise ValueError('A layout needs a shared stem and 2–32 subquestion groups.')
    ids = [p.get('id') for p in parts]
    if ids[0] != 'stem' or len(set(ids)) != len(ids) or any(not isinstance(i, str) or not re.fullmatch(r'[a-z][a-z0-9_.-]{0,31}', i) for i in ids):
        raise ValueError('Use unique part IDs; the first part must be stem.')
    intervals = [[] for _ in question['regions']]
    for part in parts:
        if not isinstance(part.get('topics', []), list) or any(code not in TOPICS for code in part.get('topics', [])):
            raise ValueError('Part topics must be valid syllabus topic codes.')
        if not isinstance(part.get('label'), str) or not 1 <= len(part['label']) <= 80:
            raise ValueError('Each part needs a short label.')
        minutes = float(part['minutes'])
        if not math.isfinite(minutes) or (minutes < 0 if part['id'] == 'stem' else minutes <= 0):
            raise ValueError('Subquestion times must be positive; stem time may be zero.')
        if not isinstance(part.get('regions'), list) or (not part['regions'] and part['id'] != 'stem'):
            raise ValueError('Each subquestion needs at least one crop.')
        for crop in part['regions']:
            coordinates = crop['rect']
            if len(coordinates) != 4 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in coordinates):
                raise ValueError('Invalid crop coordinates.')
            left, top, right, bottom = coordinates
            matches = [i for i, parent in enumerate(question['regions']) if crop['page'] == parent['page']
                       and abs(left - parent['rect'][0]) < .01 and abs(right - parent['rect'][2]) < .01
                       and top >= parent['rect'][1] - .01 and bottom <= parent['rect'][3] + .01]
            if len(matches) != 1 or bottom - top < 5:
                raise ValueError('Part crops must be full-width slices of exactly one parent crop, at least 5 points high.')
            intervals[matches[0]].append((top, bottom))
    for parent, slices in zip(question['regions'], intervals):
        cursor = parent['rect'][1]
        for top, bottom in sorted(slices):
            if abs(top - cursor) > .01:
                raise ValueError('Part crops must cover the entire parent without gaps or overlaps.')
            cursor = bottom
        if abs(cursor - parent['rect'][3]) > .01:
            raise ValueError('Part crops must cover the entire parent.')
    if sum(float(p['minutes']) for p in parts) > question['minutes'] + .001:
        raise ValueError('Part times exceed the parent estimate. Adjust the parts or save a higher parent estimate first.')


def validate_graph(parts):
    ids = {p['id'] for p in parts}
    graph = {}
    for part in parts:
        requires = part.get('requires')
        if not isinstance(requires, list) or len(requires) != len(set(requires)) or any(r not in ids or r == part['id'] for r in requires):
            raise ValueError('Prerequisites must name other existing parts without duplicates.')
        if (part['id'] == 'stem' and requires) or (part['id'] != 'stem' and 'stem' not in requires):
            raise ValueError('Every subquestion requires its parent stem; the stem has no prerequisites.')
        graph[part['id']] = requires
    visiting, done = set(), set()
    def visit(node):
        if node in visiting:
            raise ValueError('Circular subquestion dependencies are not allowed.')
        if node in done:
            return
        visiting.add(node)
        for dependency in graph[node]:
            visit(dependency)
        visiting.remove(node)
        done.add(node)
    for node in graph:
        visit(node)


def approved_map(question):
    mapping = question.get('subquestions')
    if not mapping or mapping.get('status') != 'approved' or mapping.get('source_hash') != question_hash(question):
        return None
    try:
        validate_layout(question, mapping['parts'])
        validate_graph(mapping['parts'])
    except (ValueError, KeyError, TypeError):
        return None
    return mapping


def render_variant(question, omitted=()):
    mapping = approved_map(question)
    if not mapping:
        if omitted:
            raise ValueError('Approve a current subquestion layout and dependency map before omitting parts.')
        return dict(question, omitted_parts=[], kept_parts=[], dependent_omissions=0, render_mode='full', dependency_approved=False)
    parts = mapping['parts']
    omitted = set(omitted)
    ids = {p['id'] for p in parts}
    if 'stem' in omitted or not omitted.issubset(ids) or len(ids - omitted) < 2:
        raise ValueError('Retain the parent stem and at least one subquestion.')
    for part in parts:
        if part['id'] not in omitted and set(part['requires']) & omitted:
            raise ValueError(f"Cannot omit a prerequisite of retained part {part['id']}.")
    if not omitted:
        return dict(question, omitted_parts=[], kept_parts=[p['id'] for p in parts], dependent_omissions=0, render_mode='full', dependency_approved=True)
    regions = [r for p in parts if p['id'] not in omitted for r in p['regions']]
    def source_order(region):
        index = next(i for i, parent in enumerate(question['regions']) if parent['page'] == region['page']
                     and abs(parent['rect'][0] - region['rect'][0]) < .01 and abs(parent['rect'][2] - region['rect'][2]) < .01
                     and parent['rect'][1] - .01 <= region['rect'][1] and parent['rect'][3] + .01 >= region['rect'][3])
        return index, region['rect'][1]
    regions.sort(key=source_order)
    # Unallocated reading time remains attached to the stem.
    minutes = question['minutes'] - sum(float(p['minutes']) for p in parts if p['id'] in omitted)
    return dict(question, regions=regions, minutes=round(minutes, 6), marks=None, original_marks=question.get('marks'), render_mode='short', dependency_approved=True,
                omitted_parts=[p['id'] for p in parts if p['id'] in omitted],
                kept_parts=[p['id'] for p in parts if p['id'] not in omitted],
                dependent_omissions=sum(p['id'] in omitted and len(p['requires']) > 1 for p in parts))


def short_variants(question, required_omissions=(), focus_topics=()):
    mapping = approved_map(question)
    if not mapping:
        return [render_variant(question)]
    parts = mapping['parts']
    omitted = set(required_omissions)
    render_variant(question, omitted)  # Validate mandatory topic omissions first.
    def removable(independent_only):
        kept = [p for p in parts if p['id'] != 'stem' and p['id'] not in omitted]
        if len(kept) < 2:
            return []
        required = {r for p in kept for r in p['requires']}
        return [p for p in reversed(kept) if p['id'] not in required and (not independent_only or p['requires'] == ['stem'])
                and (not focus_topics or any(other['id'] != p['id'] and set(other.get('topics', [])) & set(focus_topics) for other in kept))]
    # Short always prefers pruning independent terminal parts, even if Full fits.
    while removable(True):
        omitted.add(removable(True)[0]['id'])
    variants = [render_variant(question, omitted)]
    # If necessary, dependent terminal parts may go next, but never their retained prerequisites.
    while removable(False):
        omitted.add(removable(False)[0]['id'])
        variants.append(render_variant(question, omitted))
    return variants


def choose_short(questions, target, selected_topics=()):
    limit = math.floor(target * 10 + 1e-8)
    states = {0: ([], 0)}
    for question in questions:
        if selected_topics:
            from topic_scope import scoped_question
            scoped = scoped_question(question, selected_topics)
            if scoped is None:
                continue
            forced = scoped.get('omitted_parts', [])
        else:
            forced = []
        previous = dict(states)
        for variant in short_variants(question, forced, selected_topics):
            variant['topic_omitted_parts'] = list(forced)
            mapping = approved_map(question)
            if mapping and all(p.get('topics') for p in mapping['parts'] if p['id'] != 'stem' and p['id'] in variant['kept_parts']):
                variant['topics'] = sorted({c for p in mapping['parts'] if p['id'] in variant['kept_parts'] for c in p.get('topics', [])})
            cost = max(1, math.ceil(variant['minutes'] * 10 - 1e-8))
            for duration, (chosen, omissions) in previous.items():
                total = duration + cost
                if total > limit:
                    continue
                candidate = (chosen + [variant], omissions + variant['dependent_omissions'])
                existing = states.get(total)
                if existing is None or (len(candidate[0]), -candidate[1]) > (len(existing[0]), -existing[1]):
                    states[total] = candidate
    return states[max(states)][0]
