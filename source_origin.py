"""Teacher-declared source provenance; independent of subject and paper type."""
from datetime import datetime, timezone
import hashlib
import json
import re

ORIGINS = {'ib_official': 'Official IB', 'self_made': 'Self-made', 'unknown': 'Unspecified'}
VERSION = 'source-origin-v1'


def analyze_origin(records):
    """Recheck saved text only. Explicit conflicting evidence stays unspecified."""
    evidence, sources = [], []
    for record in records[:4]:
        source = 'ocr' if record.get('text', '').strip() else 'pdf_text'
        text = record.get('text', '') if source == 'ocr' else record.get('native', '')
        sources.append(dict(page=record['page'], source=source, text=text))
        patterns = {
            'self_made': r'\b(?:self[- ]made|teacher[- ](?:made|written|created)|school[- ](?:made|written)|locally[- ](?:written|created))\s+(?:[A-Za-z]+\s+)?(?:papers?|questions?|tests?|exams?|assessments?)\b|generated practice material|not an official IB examination',
            'ib_official': r'(?:©|\(c\)|copyright)\s*(?:\d{4}\s*)?International\s+Baccalaureate(?:\s+(?:Organization|Organisation))?(?:\s+\d{4})?',
        }
        for kind, pattern in patterns.items():
            match = re.search(pattern, text, re.I)
            if match:
                evidence.append(dict(page=record['page'], source=source, kind=kind, quote=match.group(0)))
        session = re.search(r'\b[MN]\d{2}\s*/\s*[1-7]\s*/\s*[A-Z]{3,8}\s*/\s*[HS]P[123]', text, re.I)
        if session and re.search(r'International\s+Baccalaureate', text, re.I):
            evidence.append(dict(page=record['page'], source=source, kind='ib_official', quote=session.group(0)))
    kinds = {item['kind'] for item in evidence}
    origin = next(iter(kinds)) if len(kinds) == 1 else 'unknown'
    return dict(version=VERSION, origin=origin, status='detected' if origin != 'unknown' else 'needs_review',
                reason='Conflicting source labels require review.' if len(kinds)>1 else 'Source text provides explicit evidence.' if kinds else 'No explicit source evidence was found.',
                evidence=evidence, text_sha256=hashlib.sha256(json.dumps(sources,sort_keys=True).encode()).hexdigest(),
                analyzed_at=datetime.now(timezone.utc).isoformat())


def validate_origin(value, filtering=False):
    if filtering and value in (None, ''):
        return None
    if not isinstance(value, str) or value not in ORIGINS:
        raise ValueError('Choose Official IB, Self-made or Unspecified as the source origin.')
    return value


def origin_label(question):
    return ORIGINS.get(question.get('origin'), ORIGINS['unknown'])
