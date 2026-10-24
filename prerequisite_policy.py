"""Validated, request-local prerequisite overrides; the bundled guide stays intact."""
from contextvars import ContextVar
from copy import deepcopy
import hashlib
import json
from pathlib import Path

DEFAULT_POLICY = json.loads((Path(__file__).parent / 'curriculum_prerequisites.json').read_text())
active_policy = ContextVar('prerequisite_policy', default=None)


def current_policy():
    return active_policy.get() or DEFAULT_POLICY


def revision(requires):
    normalized = {code: sorted(earlier) for code, earlier in requires.items()}
    return hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest()


def validate_requires(requires):
    codes = list(DEFAULT_POLICY['requires'])
    if not isinstance(requires, dict) or set(requires) != set(codes):
        raise ValueError('Provide prerequisite lists for every topic, using valid topic codes.')
    for code, earlier in requires.items():
        if (not isinstance(earlier, list) or any(not isinstance(p, str) or p not in codes for p in earlier)
                or len(earlier) != len(set(earlier))):
            raise ValueError(f'{code}: select unique, valid prerequisite topics.')
        if code in earlier:
            raise ValueError(f'{code} cannot require itself.')
    visited, path = set(), []
    def visit(code):
        if code in path:
            raise ValueError('Circular prerequisites: ' + ' → '.join(path[path.index(code):] + [code]))
        if code in visited:
            return
        path.append(code)
        for prerequisite in requires[code]:
            visit(prerequisite)
        path.pop(); visited.add(code)
    for code in codes:
        visit(code)
    return {code: [p for p in codes if p in requires[code]] for code in codes}


def effective_policy(saved=None):
    policy = deepcopy(DEFAULT_POLICY)
    if saved:
        policy['requires'] = saved['requires']
        policy['updated_at'] = saved.get('updated_at')
    policy['revision'] = revision(policy['requires'])
    policy['customized'] = policy['revision'] != revision(DEFAULT_POLICY['requires'])
    for code, earlier in policy['requires'].items():
        policy['topic_analysis'][code]['core_prerequisites'] = earlier
    return policy
