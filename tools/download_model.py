"""Download official Qwen GGUF weights, pinned to a resolved revision and checksum."""
import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import quote
from urllib.request import urlopen

REPOSITORY = 'Qwen/Qwen2.5-1.5B-Instruct-GGUF'
FILENAME = 'qwen2.5-1.5b-instruct-q4_k_m.gguf'


def download(destination):
    api = 'https://huggingface.co/api/models/' + REPOSITORY + '?blobs=true'
    with urlopen(api, timeout=30) as response:
        info = json.load(response)
    revision = info['sha']
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('Model host did not return a valid immutable revision.')
    artifact = next(item for item in info['siblings'] if item['rfilename'] == FILENAME)
    checksum = artifact['lfs']['sha256']
    size = artifact['lfs']['size']
    if not re.fullmatch(r'[0-9a-f]{64}', checksum) or not isinstance(size, int) or not 0 < size < 2_000_000_000:
        raise ValueError('Model host did not provide a valid artifact checksum and size.')
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / FILENAME
    if target.exists():
        with target.open('rb') as file:
            if hashlib.file_digest(file, 'sha256').hexdigest() != checksum:
                raise ValueError('An existing model file has a different checksum; preserve it and choose another destination.')
    else:
        partial = target.with_suffix('.gguf.part')
        if partial.exists():
            raise ValueError('A partial model download already exists; preserve it and choose another destination.')
        url = f'https://huggingface.co/{REPOSITORY}/resolve/{revision}/{quote(FILENAME)}'
        digest, received = hashlib.sha256(), 0
        try:
            with urlopen(url, timeout=30) as response, partial.open('xb') as file:
                while chunk := response.read(1024 * 1024):
                    received += len(chunk)
                    if received > size:
                        raise ValueError('Model download exceeded its declared size.')
                    digest.update(chunk)
                    file.write(chunk)
            if received != size or digest.hexdigest() != checksum:
                raise ValueError('Model artifact checksum or size verification failed.')
            partial.replace(target)
        finally:
            partial.unlink(missing_ok=True)
    manifest = dict(repository=REPOSITORY, revision=revision, filename=FILENAME, sha256=checksum, size=size)
    target.with_suffix('.gguf.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(str(target))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, default=Path('/workspace/models/qwen-physics'))
    args = parser.parse_args()
    try:
        download(args.destination)
    except Exception as error:
        parser.exit(1, 'Model download failed: ' + str(error) + '\n')
