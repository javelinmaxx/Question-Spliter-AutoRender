"""Variants for previews and exact teacher-selected question groups."""
import math

from subquestions import short_variants, approved_map
from topic_scope import scoped_question, effective_topics


def question_variants(question, topics, mode):
    scoped = scoped_question(question, topics)
    if scoped is None:
        return []
    if mode == 'full':
        return [scoped]
    variants = short_variants(question, scoped.get('omitted_parts', []), topics)
    for variant in variants:
        variant['topic_omitted_parts'] = scoped.get('omitted_parts', [])
        mapping = approved_map(question)
        if mapping and all(p.get('topics') for p in mapping['parts'] if p['id'] != 'stem' and p['id'] in variant['kept_parts']):
            variant['topics'] = effective_topics(question, variant['kept_parts'])
    return variants


def select_required(questions, target, topics, mode):
    """Choose one safe variant per selected parent, preserving selection order."""
    limit = math.floor(target * 10 + 1e-8)
    states = {0: ([], 0)}
    for question in questions:
        updated = {}
        for variant in question_variants(question, topics, mode):
            cost = max(1, math.ceil(variant['minutes'] * 10 - 1e-8))
            for duration, (chosen, removals) in states.items():
                total = duration + cost
                if total > limit:
                    continue
                candidate = (chosen + [variant], removals + variant['dependent_omissions'])
                if total not in updated or candidate[1] < updated[total][1]:
                    updated[total] = candidate
        states = updated
        if not states:
            return []
    return states[max(states)][0] if states else []
