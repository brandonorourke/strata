import re

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_SPACE_RE = re.compile(r"\s+")

_CORP_SUFFIXES = {
    "inc",
    "incorporated",
    "corp",
    "corporation",
    "co",
    "company",
    "llc",
    "l.l.c",
    "ltd",
    "limited",
    "lp",
    "l.p",
    "llp",
    "l.l.p",
    "plc",
    "p.l.c",
}


def _basic_normalize(name: str) -> str:
    text = name.strip().lower()
    text = _NON_ALNUM_RE.sub(" ", text)
    text = _SPACE_RE.sub(" ", text).strip()
    return text


def normalize_legal_name(name: str) -> str:
    return _basic_normalize(name)


def normalize_loose_name(name: str) -> str:
    text = _basic_normalize(name)
    parts = [p for p in text.split(" ") if p and p not in _CORP_SUFFIXES]
    return " ".join(parts)
