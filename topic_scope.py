"""Directional curriculum scope and dependency-safe topic cropping."""
import json
from pathlib import Path

from physics import TOPICS
from subquestions import approved_map, render_variant

POLICY = json.loads((Path(__file__).parent / 'curriculum_prerequisites.json').read_text())


def topic_closure(selected):
    if not isinstance(selected, (list, tuple)) or any(code not in TOPICS for code in selected):
        raise ValueError('Select valid syllabus topics.')
    allowed, visiting = set(), set()
    def visit(code):
        if code in visiting:
            raise ValueError('Circular curriculum prerequisite policy.')
        if code in allowed:
            return
        if code not in TOPICS:
            raise ValueError('Unknown topic in curriculum prerequisite policy.')
        visiting.add(code)
        for prerequisite in POLICY['requires'].get(code, []):
            visit(prerequisite)
        visiting.remove(code)
        allowed.add(code)
    for code in selected:
        visit(code)
    return allowed


def effective_topics(question, kept):
    mapping = approved_map(question)
    if mapping:
        return sorted({code for p in mapping['parts'] if p['id'] in kept for code in p.get('topics', [])})
    return question['topics']


def scoped_question(question, selected):
    if not selected:
        return render_variant(question)
    selected = set(selected)
    allowed = topic_closure(list(selected))
    mapping = approved_map(question)
    whole_matches = bool(selected & set(question['topics'])) and set(question['topics']).issubset(allowed)
    # Unknown part topics never justify removing content from a mixed parent.
    if not mapping or any(not p.get('topics') for p in mapping['parts'] if p['id'] != 'stem'):
        return render_variant(question) if whole_matches else None
    parts = mapping['parts']
    if not set(parts[0].get('topics', [])).issubset(allowed):
        return None  # Shared context cannot be removed to make a question fit.
    keep = {'stem'} | {p['id'] for p in parts[1:] if set(p['topics']).issubset(allowed)}
    changed = True
    while changed:
        invalid = {p['id'] for p in parts if p['id'] in keep and not set(p['requires']).issubset(keep)}
        changed = bool(invalid)
        keep -= invalid
    if not any(p['id'] in keep and selected & set(p.get('topics', [])) for p in parts[1:]):
        return None  # Prerequisite-only material is not a match for the target topic.
    result = render_variant(question, [p['id'] for p in parts if p['id'] not in keep])
    result['topics'] = effective_topics(question, result['kept_parts'])
    result['topic_omitted_parts'] = result['omitted_parts']
    result['topic_scope'] = dict(requested=sorted(selected), allowed=sorted(allowed), policy_version=POLICY['version'])
    if result['omitted_parts']:
        result['render_mode'] = 'topic_filtered'
        result['text'] = '\n'.join(p['text'] for p in parts if p['id'] in keep)
    return result
