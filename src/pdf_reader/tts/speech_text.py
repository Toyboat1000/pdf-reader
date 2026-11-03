"""Rewrite written shorthand into what a person would say, just before speaking.

Only the spoken text changes; what's shown on screen stays exactly as written.
"""

import re

_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\be\.\s?g\.,?", re.IGNORECASE), "for example,"),
    (re.compile(r"\bi\.\s?e\.,?", re.IGNORECASE), "that is,"),
    (re.compile(r"\bcf\.", re.IGNORECASE), "compare"),
    (re.compile(r"\betc\.(?=\s*[a-z])"), "etcetera,"),
    (re.compile(r"\betc\."), "etcetera."),
    (re.compile(r"\bvs\.?(?=\s)", re.IGNORECASE), "versus"),
    (re.compile(r"\bapprox\.", re.IGNORECASE), "approximately"),
    (re.compile(r"\bet al\.", re.IGNORECASE), "and colleagues"),
    (re.compile(r"\bFigs?\.\s*(?=\d)"), "Figure "),
    (re.compile(r"\bEqs?\.\s*(?=\d)"), "Equation "),
    (re.compile(r"\bCh\.\s*(?=\d)"), "Chapter "),
    (re.compile(r"\bVol\.\s*(?=\d)"), "Volume "),
    (re.compile(r"\bNo\.\s*(?=\d)"), "Number "),
    (re.compile(r"\bpp\.\s*(?=\d)"), "pages "),
    (re.compile(r"\bp\.\s*(?=\d)"), "page "),
    (re.compile(r"\s&\s"), " and "),
    (re.compile(r"\bw/\s?(?=\w)"), "with "),
    # A dash between numbers is a range: "1990\u20132000" is "1990 to 2000".
    (re.compile(r"(?<=\d)\s*[\u2013-]\s*(?=\d)"), " to "),
    # Dashes between words are spoken as a short pause.
    (re.compile(r"\s*[\u2014\u2013]\s*|\s+-\s+"), ", "),
    # Bullets and stray symbols that would be read out or mumbled.
    (re.compile(r"[\u2022\u25aa\u25cf\u25e6\u2023\u2043]"), " "),
]
_SPACES = re.compile(r"\s{2,}")


def speech_text(text: str) -> str:
    """Return ``text`` rewritten for natural speech."""
    for pattern, replacement in _RULES:
        text = pattern.sub(replacement, text)
    return _SPACES.sub(" ", text).strip(" ,")
