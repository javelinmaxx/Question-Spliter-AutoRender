"""Conservative filename and cover-heading detection for IB markschemes."""
import re

NAME_PATTERN = re.compile(r'\b(?:mark\s*schemes?|marking\s+(?:schemes?|notes)|ms)\b')
DIRECTORIES = {'markscheme', 'markschemes', 'mark scheme', 'mark schemes',
               'marking scheme', 'marking schemes', 'marking notes', 'ms'}
HEADING_PATTERN = re.compile(r'^\s*(?:physics\s*[-:]?\s*)?(?:mark\s*schemes?|marking\s+(?:schemes?|notes))\s*$', re.I | re.M)


def normalized_name(value):
    return re.sub(r'[^a-z0-9]+', ' ', value.lower()).strip()


def markscheme_name(path):
    parts = str(path or '').replace('\\', '/').split('/')
    if any(normalized_name(part) in DIRECTORIES for part in parts[:-1]):
        return True
    name = parts[-1].rsplit('.', 1)[0]
    return bool(NAME_PATTERN.search(normalized_name(name)))


def markscheme_heading(text):
    # A standalone title is evidence; an exam question mentioning markschemes is not.
    return bool(HEADING_PATTERN.search(text))
