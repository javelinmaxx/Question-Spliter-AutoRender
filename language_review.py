"""Optional local SLM adjudication. PDF/OCR strings are untrusted document data."""
import hashlib
import json
import os
from pathlib import Path
import re
from threading import Lock

from curriculum_context import curriculum_context, OCR_PROMPT_VERSION
from cpu_runtime import cpu_setting

PROMPT_VERSION = OCR_PROMPT_VERSION
MAX_SOURCE_CHARS = 6000
_lock = Lock()
_loaded = None

SYSTEM = (Path(__file__).parent / 'prompts' / 'physics_ocr.md').read_text()


def normalized(text):
    return re.sub(r'\s+', ' ', text).strip()


def context_hash(native, ocr, paper, pdf_topics, ocr_topics):
    data = dict(pdf=native, ocr=ocr, paper=paper, pdf_topics=sorted(pdf_topics), ocr_topics=sorted(ocr_topics))
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def status():
    configured = os.environ.get('QUESTION_BANK_MODEL_PATH', '')
    if not configured:
        return dict(available=False, reason='Local language model is not configured.')
    path = Path(configured)
    if not path.is_file() or not path.with_suffix(path.suffix + '.json').is_file():
        return dict(available=False, reason='Local model weights or their checksum manifest are missing.')
    try:
        import importlib.util
        if importlib.util.find_spec('llama_cpp') is None:
            return dict(available=False, reason='The optional local model runtime is not installed.')
    except ImportError:
        return dict(available=False, reason='The optional local model runtime is not installed.')
    return dict(available=True, model=path.name, reason='Local model is configured; weights are verified when loaded.')


def verified_model():
    global _loaded
    path = Path(os.environ['QUESTION_BANK_MODEL_PATH']).resolve()
    manifest = json.loads(path.with_suffix(path.suffix + '.json').read_text())
    expected = manifest['sha256']
    if not isinstance(expected, str) or not re.fullmatch(r'[0-9a-f]{64}', expected):
        raise ValueError('Model manifest requires an authoritative SHA-256 checksum.')
    threads = cpu_setting('QUESTION_BANK_MODEL_THREADS')
    identity = (str(path), path.stat().st_size, path.stat().st_mtime_ns, expected, threads)
    if _loaded and _loaded[0] == identity:
        return _loaded[1], expected
    with path.open('rb') as file:
        digest = hashlib.file_digest(file, 'sha256').hexdigest()
    if digest != expected:
        raise ValueError('Local model checksum verification failed.')
    from llama_cpp import Llama
    model = Llama(model_path=str(path), n_ctx=4096, n_threads=threads, n_threads_batch=threads,
                  n_gpu_layers=0, seed=0, verbose=False)
    _loaded = (identity, model)
    return model, expected


def local_json_review(system, payload, schema, max_tokens=1000):
    """Shared local inference transport; callers validate task-specific semantics."""
    availability = status()
    if not availability['available']:
        raise RuntimeError(availability['reason'])
    with _lock:
        model, digest = verified_model()
        messages = [dict(role='system', content=system), dict(role='user', content=json.dumps(payload))]
        if len(model.tokenize(json.dumps(messages).encode())) + max_tokens + 100 > 4096:
            raise ValueError('The complete dependency context exceeds the local model token budget.')
        result = model.create_chat_completion(messages=messages, temperature=0, max_tokens=max_tokens,
                                             response_format=dict(type='json_object', schema=schema))
        if result['choices'][0].get('finish_reason') != 'stop':
            raise ValueError('The language-model dependency response was incomplete.')
        return json.loads(result['choices'][0]['message']['content']), dict(model=Path(os.environ['QUESTION_BANK_MODEL_PATH']).name, model_sha256=digest)


def response_schema(codes):
    return {
        'type': 'object', 'additionalProperties': False,
        'required': ['decision', 'confidence', 'reason', 'evidence'],
        'properties': {
            'decision': {'type': 'string', 'enum': ['resolve', 'abstain']},
            'confidence': {'type': 'string', 'enum': ['high', 'medium', 'low']},
            'reason': {'type': 'string', 'minLength': 1, 'maxLength': 700},
            'evidence': {'type': 'array', 'maxItems': len(codes), 'items': {
                'type': 'object', 'additionalProperties': False,
                'required': ['topic', 'source', 'quote'],
                'properties': {
                    'topic': {'type': 'string', 'enum': codes},
                    'source': {'type': 'string', 'enum': ['pdf', 'ocr']},
                    'quote': {'type': 'string', 'minLength': 5, 'maxLength': 240},
                },
            }},
        },
    }


def validate_response(value, native, ocr, candidates):
    """Reject malformed labels and invented citations even with constrained decoding."""
    if not isinstance(value, dict) or set(value) != {'decision', 'confidence', 'reason', 'evidence'}:
        raise ValueError('The model returned an invalid review object.')
    if value['decision'] not in ('resolve', 'abstain') or value['confidence'] not in ('high', 'medium', 'low'):
        raise ValueError('The model returned an invalid decision or confidence.')
    if not isinstance(value['reason'], str) or not 1 <= len(value['reason']) <= 700:
        raise ValueError('The model returned an invalid explanation.')
    evidence = value['evidence']
    if not isinstance(evidence, list) or len(evidence) > len(candidates):
        raise ValueError('The model returned invalid evidence.')
    topics = []
    for item in evidence:
        if not isinstance(item, dict) or set(item) != {'topic', 'source', 'quote'}:
            raise ValueError('The model returned invalid evidence fields.')
        topic, source, quote = item['topic'], item['source'], item['quote']
        if not isinstance(topic, str) or topic not in candidates or topic in topics:
            raise ValueError('The model returned an unsupported or duplicate topic.')
        if source not in ('pdf', 'ocr') or not isinstance(quote, str) or not 5 <= len(quote) <= 240:
            raise ValueError('The model returned an invalid source quote.')
        actual = native if source == 'pdf' else ocr
        if normalized(quote) not in normalized(actual):
            raise ValueError('The model quote was not found in the cited source.')
        topics.append(topic)
    resolved = value['decision'] == 'resolve' and value['confidence'] == 'high' and bool(topics)
    return dict(status='resolved' if resolved else 'needs_review', topics=topics if resolved else [],
                reason=value['reason'], confidence=value['confidence'], evidence=evidence)


def review_disagreement(native, ocr, paper, pdf_topics, ocr_topics, topic_names,
                        cache_dir=None, completion=None):
    fingerprint = context_hash(native, ocr, paper, pdf_topics, ocr_topics)
    base = dict(input_hash=fingerprint, prompt_version=PROMPT_VERSION, topics=[], evidence=[])
    if not native.strip() or not ocr.strip():
        return dict(base, status='needs_review', reason='Both PDF and OCR text are required for adjudication.')
    if set(pdf_topics) == set(ocr_topics):
        return dict(base, status='not_needed', reason='The source topic suggestions agree.')
    if len(native) + len(ocr) > MAX_SOURCE_CHARS:
        return dict(base, status='needs_review', reason='The complete question exceeds the local review context limit; review it manually.')
    candidates = sorted(set(pdf_topics) | set(ocr_topics))
    if not candidates or any(code not in topic_names for code in candidates):
        return dict(base, status='needs_review', reason='No valid candidate topic set is available.')
    if completion is None and not status()['available']:
        return dict(base, status='unavailable', reason=status()['reason'])
    try:
        with _lock:
            if completion is None:
                model, digest = verified_model()
                complete = model.create_chat_completion
                model_name = Path(os.environ['QUESTION_BANK_MODEL_PATH']).name
            else:
                complete, digest, model_name = completion, 'test-double', 'test-double'
            cache = None
            if cache_dir is not None and completion is None:
                key = hashlib.sha256((PROMPT_VERSION + fingerprint + digest).encode()).hexdigest()
                cache = Path(cache_dir) / (key + '.json')
                if cache.exists():
                    try:
                        cached = json.loads(cache.read_text())
                        checked = validate_response(cached['response'], native, ocr, candidates)
                        return dict(base, **checked, model=model_name, model_sha256=digest, cached=True)
                    except (ValueError, KeyError, TypeError):
                        pass
            payload = dict(paper=paper, candidate_topics={code: topic_names[code] for code in candidates},
                           pdf_suggested_topics=pdf_topics, ocr_suggested_topics=ocr_topics,
                           curriculum_context=curriculum_context(candidates),
                           untrusted_document_sources={'pdf': native, 'ocr': ocr})
            messages = [dict(role='system', content=SYSTEM), dict(role='user', content=json.dumps(payload))]
            # Abstain rather than truncating any part of the parent question.
            if completion is None and len(model.tokenize(json.dumps(messages).encode())) + 600 > 4096:
                return dict(base, status='needs_review', reason='The complete question exceeds the model token budget.')
            result = complete(messages=messages, temperature=0, max_tokens=450,
                              response_format=dict(type='json_object', schema=response_schema(candidates)))
            if result['choices'][0].get('finish_reason') != 'stop':
                raise ValueError('The language-model response was incomplete.')
            value = json.loads(result['choices'][0]['message']['content'])
            checked = validate_response(value, native, ocr, candidates)
            if cache is not None:
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps(dict(response=value, model_sha256=digest)))
            return dict(base, **checked, model=model_name, model_sha256=digest, cached=False)
    except (ValueError, KeyError, IndexError, TypeError, RuntimeError, OSError, ImportError) as error:
        return dict(base, status='needs_review', reason='Local language review could not produce a validated result: ' + str(error)[:250])
