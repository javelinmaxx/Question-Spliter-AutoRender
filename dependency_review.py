"""SLM proposals for directed subquestion prerequisites; never automatic approval."""
from copy import deepcopy
from pathlib import Path

from curriculum_context import curriculum_context, DEPENDENCY_PROMPT_VERSION

from language_review import local_json_review, normalized
from subquestions import validate_graph
from physics import TOPICS, suggest

PROMPT_VERSION = DEPENDENCY_PROMPT_VERSION
SYSTEM = (Path(__file__).parent / 'prompts' / 'physics_dependencies.md').read_text()


def analyze_dependencies(parts, completion=None):
    ids = [p['id'] for p in parts if p['id'] != 'stem']
    topic_schema = dict(type='array', maxItems=4, items=dict(type='string', enum=list(TOPICS)))
    schema = dict(type='object', additionalProperties=False, required=['parts', 'stem_topics'], properties={
        'stem_topics': topic_schema,
        'parts': dict(type='array', minItems=len(ids), maxItems=len(ids), items=dict(
            type='object', additionalProperties=False, required=['id', 'requires', 'confidence', 'quote', 'reason', 'topics'],
            properties=dict(id=dict(type='string', enum=ids), requires=dict(type='array', maxItems=len(ids)-1, items=dict(type='string', enum=ids)),
                            topics=dict(topic_schema, minItems=1),
                            confidence=dict(type='string', enum=['high', 'medium', 'low']),
                            quote=dict(type='string', minLength=5, maxLength=300), reason=dict(type='string', minLength=1, maxLength=600))))})
    base = dict(prompt_version=PROMPT_VERSION, status='needs_review', parts=deepcopy(parts), evidence=[], reason='Manual dependency review is required.')
    if len(ids) < 2 or len(ids) > 32:
        return dict(base, reason='A dependency review needs 2–32 identified subquestion groups.')
    relevant = {code for part in parts for code in suggest(part['text'], 'Paper 2')['topics']}
    relevant.update(code for part in parts for code in part.get('topics', []))
    payload = dict(topic_catalog=TOPICS, curriculum_context=curriculum_context(relevant), untrusted_parts=[dict(id=p['id'], label=p['label'], text=p['text']) for p in parts])
    if sum(len(p['text']) for p in parts) > 6000:
        return dict(base, reason='The full parent question exceeds the local model context budget; no text was truncated.')
    try:
        value, identity = (completion(SYSTEM, payload, schema) if completion else local_json_review(SYSTEM, payload, schema, max_tokens=1200))
        if not isinstance(value, dict) or set(value) != {'parts', 'stem_topics'} or not isinstance(value['parts'], list) or len(value['parts']) != len(ids):
            raise ValueError('The model must review every subquestion exactly once.')
        def valid_topics(topics):
            return isinstance(topics, list) and len(topics) <= 4 and all(isinstance(c, str) and c in TOPICS for c in topics) and len(topics) == len(set(topics))
        if not valid_topics(value['stem_topics']):
            raise ValueError('The model supplied invalid shared-stem topics.')
        by_id = {p['id']: p for p in base['parts']}
        by_id['stem']['topics'] = value['stem_topics']
        seen = set()
        high = True
        for item in value['parts']:
            if not isinstance(item, dict) or set(item) != {'id', 'requires', 'confidence', 'quote', 'reason', 'topics'}:
                raise ValueError('Invalid dependency response fields.')
            label = item['id']
            if label not in ids or label in seen:
                raise ValueError('Duplicate or unknown subquestion ID.')
            seen.add(label)
            if not isinstance(item['quote'], str) or not 5 <= len(item['quote']) <= 300 or normalized(item['quote']) not in normalized(by_id[label]['text']):
                raise ValueError('A dependency quote was not found in its source part.')
            if item['confidence'] not in ('high', 'medium', 'low') or not isinstance(item['reason'], str) or not 1 <= len(item['reason']) <= 600:
                raise ValueError('Invalid dependency explanation or confidence.')
            requires = item['requires']
            if not isinstance(requires, list) or len(requires) != len(set(requires)) or any(r not in ids or r == label for r in requires):
                raise ValueError('The model supplied invalid prerequisites.')
            by_id[label]['requires'] = ['stem', *requires]
            if not valid_topics(item['topics']) or not item['topics']:
                raise ValueError('Each assessed part needs valid topic tags.')
            by_id[label]['topics'] = item['topics']
            high = high and item['confidence'] == 'high'
        validate_graph(base['parts'])
        if not high:
            # Do not expose a partially trusted graph as an independence proposal.
            return dict(base, parts=deepcopy(parts), evidence=value['parts'], **identity,
                        reason='Some dependency judgments are uncertain. Review manually; all original dependencies were retained.')
        return dict(base, status='proposed', evidence=value['parts'], **identity,
                    reason='Model dependency proposal. Check shared text, diagrams and all prerequisites before approval.')
    except (ValueError, KeyError, IndexError, TypeError, RuntimeError, OSError, ImportError) as error:
        return dict(base, parts=deepcopy(parts), reason='Dependency analysis is unavailable or invalid: ' + str(error)[:250])
