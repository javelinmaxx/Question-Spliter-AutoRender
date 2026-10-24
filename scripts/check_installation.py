"""Check the local runtime without running tests, installing or loading Qwen."""
import importlib.metadata
import hashlib
import http.client
import json
import os
from pathlib import Path
import sys
import webbrowser

ROOT = Path(__file__).resolve().parents[1]


def open_existing_server(root=ROOT):
    """Reopen only this app and data directory, never an unrelated local service."""
    try:
        port = int(os.environ.get('PORT', '5001'))
        data_root = Path(os.environ.get('QUESTION_BANK_DATA', root / 'instance')).resolve()
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=1)
        try:
            connection.request('GET', '/api/health')
            response = connection.getresponse()
            value = json.loads(response.read(8192)) if response.status == 200 else {}
        finally:
            connection.close()
        if not isinstance(value, dict) or value.get('service') != 'ibdp-physics-question-bank' or value.get('data_id') != hashlib.sha256(str(data_root).encode()).hexdigest():
            return False
        url = f'http://127.0.0.1:{port}'
        try:
            if os.environ.get('QUESTION_BANK_OPEN_BROWSER', 'auto') != '0':
                webbrowser.open(url, new=2)
        except (OSError, webbrowser.Error):
            pass
        print(f'Question bank already running. Open {url} in your browser.')
        return True
    except (OSError, ValueError, http.client.HTTPException):
        return False


def installation_issues(root=ROOT):
    issues = []
    if sys.version_info[:2] != (3, 12):
        issues.append('Python 3.12 is required by the Mac installer.')
    for requirement in (root / 'requirements.txt').read_text().splitlines():
        if '==' not in requirement or requirement.lstrip().startswith('#'):
            continue
        name, expected = requirement.strip().split('==', 1)
        try:
            actual = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            actual = 'missing'
        if actual != expected:
            issues.append(f'{name}: expected {expected}, found {actual}.')
    try:
        import flask
        import fitz
        from PIL import Image
        if not (Path(fitz.get_tessdata()) / 'eng.traineddata').is_file():
            issues.append('English Tesseract OCR data is missing.')
    except (ImportError, RuntimeError, OSError) as error:
        issues.append('Runtime check failed: ' + str(error))
    return issues


if __name__ == '__main__':
    if sys.argv[1:] == ['--open-existing']:
        sys.exit(0 if open_existing_server() else 1)
    issues = installation_issues()
    print('\n'.join(issues) if issues else 'Installation ready; skipping setup.')
    sys.exit(bool(issues))
