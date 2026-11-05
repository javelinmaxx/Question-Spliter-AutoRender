"""Stable, content-addressed identifiers for editable paper selections."""
import hashlib
import json


OPTION_KEYS = ('level', 'origin', 'syllabus', 'render_mode', 'year_min', 'year_max',
               'minutes', 'paper', 'topics', 'document_ids')
DEFAULTS = dict(level='HL', origin='', syllabus='2025', render_mode='full',
                year_min='', year_max='', minutes=45, paper='', topics=[], document_ids=[])


def selection_snapshot(value, question_ids):
    if not isinstance(value, dict):
        raise ValueError('Paper settings must be an object.')
    if not isinstance(question_ids, list) or not question_ids or any(not isinstance(i, str) or not i for i in question_ids) or len(set(question_ids)) != len(question_ids):
        raise ValueError('Select at least one unique question before saving a paper ID.')
    options = {key: value.get(key, DEFAULTS[key]) for key in OPTION_KEYS}
    for key in ('topics', 'document_ids'):
        if not isinstance(options[key], list) or any(not isinstance(i, str) for i in options[key]):
            raise ValueError(f'{key} must be a list of names.')
        options[key] = sorted(set(options[key]))
    for key in ('year_min', 'year_max'):
        options[key] = '' if options[key] in (None, '') else str(int(options[key]))
    options['minutes'] = float(options['minutes'])
    for key in ('level', 'origin', 'syllabus', 'render_mode', 'paper'):
        if not isinstance(options[key], str):
            raise ValueError(f'{key} must be text.')
    return dict(version=1, options=options, question_ids=list(question_ids))


def selection_hash(snapshot):
    encoded = json.dumps(snapshot, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()
    return hashlib.sha256(encoded).hexdigest()
