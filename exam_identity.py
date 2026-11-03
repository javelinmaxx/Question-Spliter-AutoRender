"""IB examination identity and conservative question-to-markscheme matching."""
import re

IDENTIFIER_RE = re.compile(
    r"(?<![A-Z0-9])(?P<session>[MN])(?P<year>\d{2})/4/PHYSI/"
    r"(?P<paper_code>HPM|SPM|HP[123]|SP[123]|HPA|SPA|HPB|SPB)/"
    r"[A-Z]{3}/TZ(?P<timezone>[0-3])/XX(?P<marksuffix>/M)?(?![A-Z0-9])",
    re.I,
)

PAPER_CODES = {
    "HPM": "Paper 1", "SPM": "Paper 1",
    "HP1": "Paper 1", "SP1": "Paper 1",
    "HP2": "Paper 2", "SP2": "Paper 2",
    "HP3": "Paper 3", "SP3": "Paper 3",
    "HPA": "Paper 1A", "SPA": "Paper 1A",
    "HPB": "Paper 1B", "SPB": "Paper 1B",
}


def normalize_timezone(value):
    if value in (None, ""):
        return None
    match = re.fullmatch(r"(?:TZ)?\s*([0-3])", str(value).strip(), re.I)
    return f"TZ{match.group(1)}" if match else None


def parse_exam_identity(text, filename=""):
    """Read the IB document code first; use visible cover text only as fallback."""
    source = f"{filename}\n{text or ''}"
    match = IDENTIFIER_RE.search(source)
    if match:
        short_year = int(match.group("year"))
        year = (1900 if short_year >= 70 else 2000) + short_year
        code = match.group("paper_code").upper()
        return {
            "year": year,
            "session": "May" if match.group("session").upper() == "M" else "November",
            "paper": PAPER_CODES[code],
            "paper_code": code,
            "level": "HL" if code.startswith("H") else "SL",
            "timezone": f"TZ{match.group('timezone')}",
            "is_markscheme": bool(match.group("marksuffix")),
            "identifier": match.group(0),
            "identity_source": "ib_document_code",
        }

    year_match = re.search(r"\b(?:May|Nov(?:ember)?)\s+(20\d{2})\b", source, re.I)
    paper_match = re.search(r"\bPaper\s*([123])\s*([AB])?\b", source, re.I)
    level_match = re.search(r"\b(HL|higher level|SL|standard level)\b", source, re.I)
    timezone_match = re.search(r"\bTZ\s*([0-3])\b", source, re.I)
    paper = None
    if paper_match:
        paper = f"Paper {paper_match.group(1)}{(paper_match.group(2) or '').upper()}"
    level = None
    if level_match:
        level = "HL" if level_match.group(1).lower() in ("hl", "higher level") else "SL"
    return {
        "year": int(year_match.group(1)) if year_match else None,
        "session": None,
        "paper": paper,
        "paper_code": None,
        "level": level,
        "timezone": normalize_timezone(timezone_match.group(1)) if timezone_match else None,
        "is_markscheme": bool(re.search(r"\b(?:mark\s*scheme|marking\s+scheme|marking\s+notes)\b", source, re.I)),
        "identifier": None,
        "identity_source": "cover_text" if any((year_match, paper_match, level_match, timezone_match)) else "unknown",
    }


def identity_key(identity):
    """The requested exact exam-level key; question number is matched separately."""
    if not isinstance(identity, dict):
        return None
    year, paper, timezone = identity.get("year"), identity.get("paper"), normalize_timezone(identity.get("timezone"))
    if not isinstance(year, int) or not paper or not timezone:
        return None
    return year, paper, timezone


def match_question_to_markscheme(question, markscheme_identity, available_numbers):
    """Return an explicit result; never guess when metadata or the question is absent."""
    question_key = identity_key(question)
    markscheme_key = identity_key(markscheme_identity)
    if not markscheme_identity or not markscheme_identity.get("is_markscheme"):
        return {"matched": False, "reason": "not_a_markscheme"}
    if question_key is None:
        return {"matched": False, "reason": "question_identity_incomplete"}
    if markscheme_key is None:
        return {"matched": False, "reason": "marksheme_identity_incomplete"}
    if question_key != markscheme_key:
        fields = ("year", "paper", "timezone")
        mismatch = [field for field in fields if (
            question.get(field) if field != "timezone" else normalize_timezone(question.get(field))
        ) != (
            markscheme_identity.get(field) if field != "timezone" else normalize_timezone(markscheme_identity.get(field))
        )]
        return {"matched": False, "reason": "exam_identity_mismatch", "mismatched_fields": mismatch}
    try:
        number = int(question.get("number"))
    except (TypeError, ValueError):
        return {"matched": False, "reason": "question_number_missing"}
    if number not in set(available_numbers or []):
        return {"matched": False, "reason": "question_not_in_markscheme"}
    return {"matched": True, "reason": "exact_match", "question_number": number}


def question_numbers_from_markscheme(page_texts, paper):
    """Extract parent question numbers from MCQ answer keys or structured markscheme rows."""
    if paper in ("Paper 1", "Paper 1A", "Paper 1B"):
        text = "\n".join(page_texts or [])
        return {
            int(number) for number, _ in re.findall(r"(?<!\d)(\d{1,2})\s*[.)]\s*([A-D])\b", text, re.I)
        }
    numbers = set()
    # First three pages are the cover, copyright notice and marking instructions
    # in the supplied IB samples; question tables begin on page four.
    for page_text in (page_texts or [])[3:]:
        for line in page_text.splitlines():
            match = re.match(r"^\s*(\d{1,2})\.\s+", line)
            if match:
                numbers.add(int(match.group(1)))
    return numbers
