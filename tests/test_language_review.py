from io import BytesIO
import json

import fitz
import pytest

import app as application
from app import create_app
from language_review import review_disagreement, validate_response, context_hash
from ocr import lines_from
from physics import TOPICS

PDF = 'A source of light moves away from a stationary observer. The wavelength increases.'
OCR = 'Asource of light moves away from a stationary observer. The wavelength increases.'


def model_response(**changes):
    value = dict(decision='resolve', confidence='high', reason='The moving source and observed wavelength indicate a Doppler shift.',
                 evidence=[dict(topic='C.5', source='pdf', quote='moves away from a stationary observer')])
    value.update(changes)
    return value


def completion(value=None, **overrides):
    def run(**kwargs):
        assert kwargs['temperature'] == 0
        assert kwargs['response_format']['schema']['properties']['evidence']['items']['properties']['topic']['enum'] == ['C.5']
        assert 'untrusted' in kwargs['messages'][0]['content'].lower()
        assert json.loads(kwargs['messages'][1]['content'])['untrusted_document_sources']['ocr'] == OCR
        return dict(choices=[dict(finish_reason='stop', message=dict(content=json.dumps(value or model_response())))], **overrides)
    return run


def test_model_proposal_has_grounded_quotes_and_source_hash():
    result = review_disagreement(PDF, OCR, 'Paper 1A', ['C.5'], [], TOPICS, completion=completion())
    assert result['status'] == 'resolved' and result['topics'] == ['C.5']
    assert result['input_hash'] == context_hash(PDF, OCR, 'Paper 1A', ['C.5'], [])
    assert result['model'] == 'test-double'


@pytest.mark.parametrize('value', [
    model_response(evidence=[dict(topic='A.1', source='pdf', quote='moves away')]),
    model_response(evidence=[dict(topic='C.5', source='pdf', quote='not present in the paper')]),
    model_response(evidence=[dict(topic='C.5', source='web', quote='moves away')]),
    model_response(evidence=[dict(topic='C.5', source='pdf', quote='moves away'), dict(topic='C.5', source='pdf', quote='moves away')]),
    model_response(reason=''), model_response(confidence='certain'),
    dict(model_response(), executable='rm -rf /'), ['C.5'],
])
def test_invalid_or_unsupported_reviews_are_rejected(value):
    with pytest.raises(ValueError):
        validate_response(value, PDF, OCR, ['C.5'])


@pytest.mark.parametrize('confidence', ['medium', 'low'])
def test_model_uncertainty_does_not_resolve(confidence):
    result = review_disagreement(PDF, OCR, 'Paper 1A', ['C.5'], [], TOPICS,
                                 completion=completion(model_response(confidence=confidence)))
    assert result['status'] == 'needs_review' and result['topics'] == []


def test_missing_model_keeps_disagreement_visible(monkeypatch):
    monkeypatch.delenv('QUESTION_BANK_MODEL_PATH', raising=False)
    result = review_disagreement(PDF, OCR, 'Paper 1A', ['C.5'], [], TOPICS)
    assert result['status'] == 'unavailable' and result['topics'] == []


def test_incomplete_response_and_oversized_question_abstain():
    result = review_disagreement(PDF, OCR, 'Paper 1A', ['C.5'], [], TOPICS,
                                 completion=lambda **kw: {'choices': []})
    assert result['status'] == 'needs_review'
    result = review_disagreement(PDF * 200, OCR, 'Paper 1A', ['C.5'], [], TOPICS,
                                 completion=lambda **kw: pytest.fail('Do not truncate parent questions'))
    assert result['status'] == 'needs_review'


def disagreement_pdf():
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((50, 45), 'Physics Higher level Paper 1A 2025')
        page.insert_text((50, 100), '1. A source moving away from an observer emits light of wavelength L.')
        native = page.get_text()
        lines = lines_from(page)
        ocr_lines = [dict(line, text=line['text'].replace('A source', 'Asource')) for line in lines]
        record = dict(page=0, width=page.rect.width, height=page.rect.height, native=native,
                      native_lines=lines, text=native.replace('A source', 'Asource'), lines=ocr_lines, ocr_ran=True)
        return pdf.tobytes(), record


def test_api_review_is_a_proposal_and_stale_crops_invalidate_it(tmp_path, monkeypatch):
    data, record = disagreement_pdf()
    monkeypatch.setattr('physics.read_pages', lambda *args: ([record], []))
    monkeypatch.delenv('QUESTION_BANK_MODEL_PATH', raising=False)
    client = create_app(tmp_path).test_client()
    imported = client.post('/api/documents', data={'file': (BytesIO(data), 'paper.pdf'), 'ocr_mode': 'verify'})
    assert imported.status_code == 201, imported.json
    doc = imported.json
    assert doc['questions'][0]['language_review']['status'] == 'unavailable'
    # Exercise real parsing/grounding with a deterministic stand-in, not real inference.
    def local_review(*args, **kwargs):
        value = dict(decision='resolve', confidence='high', reason='A moving light source indicates Doppler shift.',
                     evidence=[dict(topic='C.5', source='pdf', quote='moving away from an observer')])
        return review_disagreement(*args, **kwargs, completion=lambda **kw: {
            'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(value)}}]})
    monkeypatch.setattr(application, 'review_disagreement', local_review)
    result = client.post(f"/api/documents/{doc['id']}/questions/1/language-review", json={})
    assert result.status_code == 200 and result.json['status'] == 'resolved'
    assert client.get('/api/questions').json == []  # Resolving is not saving or approving.
    q = client.get('/api/documents/' + doc['id']).json['questions'][0]
    saved = client.post('/api/questions', json=dict(q, document_id=doc['id'], topics=['C.5']))
    assert saved.status_code == 201 and saved.json['language_review']['status'] == 'resolved'
    # A new crop must not inherit a model decision for the old content.
    q['regions'][0]['rect'][1] += 15
    changed = client.post('/api/questions', json=dict(q, document_id=doc['id'], topics=['C.5']))
    assert changed.status_code == 201 and changed.json['language_review'] is None


def test_checksum_failure_never_loads_model(tmp_path, monkeypatch):
    path = tmp_path / 'fake.gguf'
    path.write_bytes(b'not model weights')
    path.with_suffix('.gguf.json').write_text(json.dumps(dict(sha256='0' * 64)))
    monkeypatch.setenv('QUESTION_BANK_MODEL_PATH', str(path))
    monkeypatch.setattr('language_review.status', lambda: {'available': True})
    result = review_disagreement(PDF, OCR, 'Paper 1A', ['C.5'], [], TOPICS)
    assert result['status'] == 'needs_review' and 'checksum' in result['reason']
