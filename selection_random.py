"""Seeded, usage-aware ordering for automatic question selection."""
import math


def usage_count(question, usage_counts=None):
    """Return a safe non-negative historical usage count for a question."""
    try:
        return max(0, int((usage_counts or {}).get(question.get('id'), 0)))
    except (TypeError, ValueError):
        return 0


def weighted_question_order(questions, usage_counts, rng):
    """Return a seeded weighted permutation that puts less-used questions first."""
    ranked = []
    for index, question in enumerate(questions):
        weight = 1.0 / (1 + usage_count(question, usage_counts))
        # Exponential-race sampling gives each question a weighted random priority.
        priority = -math.log(max(rng.random(), 1e-15)) / weight
        ranked.append((priority, index, question))
    ranked.sort(key=lambda item: (item[0], item[1]))
    return [question for _, _, question in ranked]
