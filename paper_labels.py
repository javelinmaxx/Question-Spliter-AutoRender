"""Recognize obsolete option headings, retaining assessed question prose."""
import re

OPTION_TITLES = (r'(?:relativity(?:\s+and\s+particle\s+physics)?|engineering\s+physics|imaging|astrophysics|'
                 r'sight\s+and\s+wave\s+phenomena|quantum\s+physics(?:\s+and\s+nuclear\s+physics)?|'
                 r'digital\s+technology|communications|electromagnetic\s+waves|biomedical\s+physics|'
                 r'historical\s+physics|mechanics|energy\s+extension|optics)')
OPTION_LINE = re.compile(
    r'(?:options?(?:\s+[A-G](?:\s*[,/&]\s*[A-G])*)?'
    r'(?:\s*[:\-–—]\s*' + OPTION_TITLES + r')?'
    r'(?:\s*\[\s*\d+\s*marks?\s*\])?'
    r'|option\s+[A-G](?:\s*,\s*question\s+\d+)?\s+(?:continued|continues\s+on\s+(?:the\s+)?(?:next|following)\s+page)'
    r'|end\s+of\s+option\s+[A-G]'
    r'|answer\s+all\s+(?:(?:of\s+)?the\s+)?questions\s+(?:from|in)\s+(?:any\s+)?(?:one|two|1|2)\s+(?:of\s+the\s+)?options?\.?'
    r'(?:\s+answers\s+must\s+be\s+written\s+within\s+the\s+answer\s+boxes(?:\s+provided\.?)?)?)\.?', re.I)


def obsolete_option_line(text):
    text = re.sub(r'\s+', ' ', re.sub(r'[\x00-\x1f]', ' ', text)).strip()
    if (text[:1], text[-1:]) in (('(', ')'), ('[', ']')):
        text = text[1:-1].strip()
    return bool(OPTION_LINE.fullmatch(text))


def obsolete_option_indices(texts):
    ignored = {i for i, text in enumerate(texts) if obsolete_option_line(text)}
    for i in list(ignored):
        if (re.search(r'answer\s+boxes\s*$', texts[i], re.I) and i + 1 < len(texts)
                and re.fullmatch(r'provided\.?', texts[i + 1].strip(), re.I)):
            ignored.add(i + 1)
    return ignored
