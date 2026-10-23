"""Explain the exact filtering and duration rules used for paper selection."""
from collections import Counter
import math

from physics import sl_compatible
from subquestions import short_variants
from topic_scope import scope_decision

REASONS = {
    'level': ('Level does not match', 'Choose the matching level, or correct the question level in its review.'),
    'syllabus': ('Syllabus does not match', 'Older papers are tagged Legacy. Select Legacy, or review and remap them before changing their syllabus.'),
    'paper': ('Paper type does not match', 'Choose Any paper or the paper type available in your bank.'),
    'sl_content': ('HL-only content conflicts with SL', 'Review the flagged content and level. HL-only topics cannot be used in an SL paper.'),
    'source': ('Original source PDF is missing', 'Restore the source PDF from your data backup or upload the paper again.'),
    'topic_target': ('No selected target topic', 'Select a topic assessed by these questions, or leave topics empty. Earlier-prerequisite-only questions are not target matches.'),
    'topic_review': ('Mixed topics need a reviewed part map', 'Approve the subquestion boundaries, topic tags and dependencies, or include the additional topics. Whole questions cannot hide out-of-scope extensions.'),
    'topic_context': ('Shared context is outside the topic scope', 'Include the required context topics or choose another question; the shared stem cannot be removed.'),
    'topic_dependency': ('Target tasks depend on out-of-scope parts', 'Include the prerequisite topics or review the dependency map. Required context cannot be dropped.'),
    'topic_inseparable': ('Target tasks include inseparable extra topics', 'Select the extra topics or choose another question. A multi-topic task cannot be split inside its text.'),
    'duration': ('Shortest valid version exceeds the time budget', 'Increase the duration, or approve a dependency map and choose Short. Check inflated mark/time estimates in question review.'),
}


def diagnose_selection(bank, documents, *, level, syllabus, paper, topics, mode, target, source_ids):
    """Return fitting original parents and a mutually exclusive exclusion breakdown."""
    fitting, excluded, matching_minutes, minimums = [], {}, [], []
    allowed_budget = math.floor(target * 10 + 1e-8) / 10

    def exclude(question, code):
        group = excluded.setdefault(code, dict(code=code, reason=REASONS[code][0], action=REASONS[code][1], count=0, examples=[]))
        group['count'] += 1
        if len(group['examples']) < 3:
            group['examples'].append(dict(question_id=question['id'], document_id=question['document_id'],
                                         filename=question['filename'], number=question['number'],
                                         level=question['level'], syllabus=question['syllabus'], paper=question['paper'],
                                         topics=question['topics'], minutes=question['minutes']))

    for q in bank:
        code = ('level' if q['level'] not in (level, 'Both') else
                'syllabus' if q['syllabus'] != syllabus else
                'paper' if paper and q['paper'] != paper else
                'sl_content' if level == 'SL' and not sl_compatible(q) else
                'source' if q['document_id'] not in source_ids else None)
        if code:
            exclude(q, code)
            continue
        scoped, code = scope_decision(q, topics)
        if scoped is None:
            exclude(q, code)
            continue
        variants = short_variants(q, scoped.get('omitted_parts', []), topics) if mode == 'short' else [scoped]
        matching_minutes.append(variants[0]['minutes'])
        minimum = min(max(.1, math.ceil(v['minutes'] * 10 - 1e-8) / 10) for v in variants)
        minimums.append(minimum)
        if minimum > allowed_budget:
            exclude(q, 'duration')
        else:
            fitting.append(q)

    saved = {(q['document_id'], q['number']) for q in bank}
    unsaved = sum((d['id'], q['number']) not in saved for d in documents for q in d['questions'])
    shortest = min(minimums, default=None)
    if not bank:
        summary = (f'{unsaved} analyzed question groups have not been added to the bank. Use Confirm import or enable Auto-import.'
                   if unsaved else 'The question bank is empty. Upload PDFs and add their detected questions to the bank.')
    elif not minimums:
        summary = 'No saved questions match these filters. See the exclusion reasons and available bank metadata below.'
    elif not fitting:
        summary = f'{len(minimums)} questions match the filters, but the shortest valid version needs {shortest:g} minutes; the budget is {target:g} minutes.'
    else:
        summary = f'{len(fitting)} saved question groups have at least one valid version within the time budget.'
    report = dict(summary=summary, total_saved=len(bank), uploaded_documents=len(documents),
                  analyzed_not_imported=unsaved, matching_filters=len(minimums), fitting_budget=len(fitting),
                  shortest_valid_minutes=shortest, available_minutes=round(sum(matching_minutes), 2),
                  requested=dict(level=level, syllabus=syllabus, paper=paper or 'Any', topics=topics, render_mode=mode, minutes=target),
                  bank_levels=dict(Counter(q['level'] for q in bank)), bank_syllabuses=dict(Counter(q['syllabus'] for q in bank)),
                  bank_papers=dict(Counter(q['paper'] for q in bank)), exclusions=list(excluded.values()))
    return fitting, report


def finish_diagnostics(report, chosen, target):
    actual = round(sum(q['minutes'] for q in chosen), 1)
    report = dict(report, selected_questions=len(chosen), selected_minutes=actual,
                  shortfall_minutes=round(target - actual, 1))
    if actual < target:
        if report['available_minutes'] < target:
            report['summary'] = (f"Matching questions provide at most {report['available_minutes']:g} estimated minutes "
                                 f"in {report['requested']['render_mode'].title()} mode, below the {target:g}-minute target. "
                                 'Add matching questions or broaden the filters; Full may provide more content than Short.')
        else:
            report['summary'] = (f'The selected combination leaves {target - actual:g} minutes unfilled. '
                                 'Question groups, time estimates and prerequisite rules limit which combinations fit without exceeding the budget.')
    else:
        report['summary'] = 'The selected questions fill the requested estimated duration.'
    return report
