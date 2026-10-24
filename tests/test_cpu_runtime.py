import hashlib
import json
import sys
from types import SimpleNamespace

import cpu_runtime
import language_review


def test_cpu_budget_obeys_affinity_and_container_quota(monkeypatch):
    monkeypatch.setattr(cpu_runtime.os, 'cpu_count', lambda: 16)
    monkeypatch.setattr(cpu_runtime.os, 'sched_getaffinity', lambda _: set(range(8)), raising=False)
    monkeypatch.setattr(cpu_runtime.Path, 'read_text', lambda _: '250000 100000')
    assert cpu_runtime.available_cpus() == 3
    monkeypatch.setenv('QUESTION_BANK_OCR_WORKERS', '20')
    assert cpu_runtime.cpu_setting('QUESTION_BANK_OCR_WORKERS') == 3
    monkeypatch.setenv('QUESTION_BANK_OCR_WORKERS', '2')
    assert cpu_runtime.cpu_setting('QUESTION_BANK_OCR_WORKERS') == 2
    monkeypatch.setenv('QUESTION_BANK_OCR_WORKERS', 'invalid')
    assert cpu_runtime.cpu_setting('QUESTION_BANK_OCR_WORKERS') == 3


def test_cpu_budget_without_linux_interfaces(monkeypatch):
    monkeypatch.setattr(cpu_runtime.os, 'cpu_count', lambda: 12)
    def missing(*args):
        raise OSError('No Linux interface on macOS')
    monkeypatch.setattr(cpu_runtime.os, 'sched_getaffinity', missing, raising=False)
    monkeypatch.setattr(cpu_runtime.Path, 'read_text', missing)
    assert cpu_runtime.available_cpus() == 12


def test_model_uses_full_cpu_budget_for_prompt_and_generation(tmp_path, monkeypatch):
    path = tmp_path / 'model.gguf'
    path.write_bytes(b'test weights')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    path.with_suffix('.gguf.json').write_text(json.dumps(dict(sha256=digest)))
    monkeypatch.setenv('QUESTION_BANK_MODEL_PATH', str(path))
    monkeypatch.delenv('QUESTION_BANK_MODEL_THREADS', raising=False)
    monkeypatch.setattr(cpu_runtime, 'available_cpus', lambda: 12)
    calls = []
    def load(**kwargs):
        calls.append(kwargs)
        return object()
    monkeypatch.setitem(sys.modules, 'llama_cpp', SimpleNamespace(Llama=load))
    monkeypatch.setattr(language_review, '_loaded', None)
    first, _ = language_review.verified_model()
    assert calls[0]['n_threads'] == calls[0]['n_threads_batch'] == 12
    assert language_review.verified_model()[0] is first
    monkeypatch.setenv('QUESTION_BANK_MODEL_THREADS', '3')
    second, _ = language_review.verified_model()
    assert second is not first
    assert calls[-1]['n_threads'] == calls[-1]['n_threads_batch'] == 3
