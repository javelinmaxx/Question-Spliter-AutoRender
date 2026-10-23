"""Versioned rule identity and conservative duplicate fingerprints."""
import hashlib
from io import BytesIO
from pathlib import Path
import re
import unicodedata

from PIL import Image


def rules_hash():
    root = Path(__file__).parent
    digest = hashlib.sha256()
    for name in ('physics.py', 'curriculum_prerequisites.json', 'assessment_timing.py', 'level_filter.py'):
        digest.update((root / name).read_bytes())
    return digest.hexdigest()


def source_hash(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def text_fingerprint(text):
    normalized = unicodedata.normalize('NFKC', text).lower()
    normalized = re.sub(r'^\s*\d+[.)]\s*', '', normalized)
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    return hashlib.sha256(normalized.encode()).hexdigest()


def question_fingerprint(text, png):
    # Require matching pixels too: identical wording can accompany different diagrams.
    with Image.open(BytesIO(png)) as image:
        image = image.convert('RGB')
        digest = hashlib.sha256(str(image.size).encode() + image.tobytes())
    return hashlib.sha256((text_fingerprint(text) + digest.hexdigest()).encode()).hexdigest()
