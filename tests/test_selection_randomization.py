from physics import choose_questions
from subquestions import choose_short


def test_automatic_selection_prefers_less_used_questions():
    questions = [
        dict(id='frequent', minutes=5),
        dict(id='rare', minutes=5),
    ]
    selected = choose_questions(questions, 5, usage_counts={'frequent': 12, 'rare': 1}, seed=41)
    assert selected == ('rare',)


def test_automatic_selection_is_reproducible_and_seed_breaks_ties():
    questions = [dict(id=code, minutes=5) for code in ('a', 'b', 'c')]
    first = choose_questions(questions, 5, usage_counts={}, seed=90210)
    repeated = choose_questions(questions, 5, usage_counts={}, seed=90210)
    assert first == repeated
    assert len({choose_questions(questions, 5, usage_counts={}, seed=seed) for seed in range(30)}) > 1


def test_short_selection_also_balances_usage_and_reuses_seed():
    questions = [
        dict(id='frequent', minutes=5),
        dict(id='rare', minutes=5),
    ]
    counts = {'frequent': 8, 'rare': 0}
    first = choose_short(questions, 5, usage_counts=counts, seed=77)
    repeated = choose_short(questions, 5, usage_counts=counts, seed=77)
    assert [q['id'] for q in first] == ['rare']
    assert [q['id'] for q in repeated] == ['rare']


def test_short_selection_random_state_changes_equal_usage_tie_breaks():
    questions = [dict(id=code, minutes=5) for code in ('a', 'b', 'c')]
    outcomes = {choose_short(questions, 5, usage_counts={}, seed=seed)[0]['id'] for seed in range(30)}
    assert len(outcomes) > 1
