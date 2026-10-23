import hashlib
from io import BytesIO
import json

import pytest

from tools import download_model


def remote(monkeypatch, correct=True):
    weights = b'GGUF test bytes, not an inference model'
    info = dict(sha='a' * 40, siblings=[dict(rfilename=download_model.FILENAME,
                 lfs=dict(sha256=hashlib.sha256(weights).hexdigest(), size=len(weights)))])
    urls = []
    def open_url(url, timeout):
        urls.append(url)
        if '/api/models/' in url:
            return BytesIO(json.dumps(info).encode())
        return BytesIO(weights if correct else b'incorrect download')
    monkeypatch.setattr(download_model, 'urlopen', open_url)
    return weights, urls


def test_model_download_pins_revision_and_verifies_bytes(tmp_path, monkeypatch):
    weights, urls = remote(monkeypatch)
    download_model.download(tmp_path)
    path = tmp_path / download_model.FILENAME
    assert path.read_bytes() == weights
    metadata = json.loads(path.with_suffix('.gguf.json').read_text())
    assert metadata['sha256'] == hashlib.sha256(weights).hexdigest()
    assert '/resolve/' + 'a' * 40 + '/' in urls[1]


def test_corrupt_model_is_not_published(tmp_path, monkeypatch):
    remote(monkeypatch, correct=False)
    with pytest.raises(ValueError, match='verification'):
        download_model.download(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_existing_partial_file_is_preserved(tmp_path, monkeypatch):
    remote(monkeypatch)
    partial = (tmp_path / download_model.FILENAME).with_suffix('.gguf.part')
    partial.write_bytes(b'pre-existing partial data')
    with pytest.raises(ValueError, match='partial'):
        download_model.download(tmp_path)
    assert partial.read_bytes() == b'pre-existing partial data'


def test_existing_different_model_is_preserved(tmp_path, monkeypatch):
    remote(monkeypatch)
    path = tmp_path / download_model.FILENAME
    path.write_bytes(b'existing model')
    with pytest.raises(ValueError, match='different checksum'):
        download_model.download(tmp_path)
    assert path.read_bytes() == b'existing model'
