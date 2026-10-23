import hashlib
import json
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / 'tests/fixtures/physics_papers.json').read_text())['papers']


@pytest.mark.parametrize('case', CASES, ids=[case['filename'] for case in CASES])
def test_supplied_paper_is_preserved(case):
    path = ROOT / case['path']
    assert path.parent == ROOT / 'TEST SAMPLES'
    with path.open('rb') as file:
        assert hashlib.file_digest(file, 'sha256').hexdigest() == case['sha256']
    with fitz.open(path) as pdf:
        assert len(pdf) == case['pages']
        assert not pdf.needs_pass
