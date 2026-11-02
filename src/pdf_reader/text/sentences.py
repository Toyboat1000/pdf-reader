"""Rule-based English sentence splitting.

The splitter looks for sentence-ending punctuation followed by whitespace and a
capital letter or digit, then rules out the common false positives: abbreviations,
initials, and references such as "No. 5" or "Fig. 3".
"""

import re

# Abbreviations that are (almost) never the end of a sentence.
ABBREVIATIONS: frozenset[str] = frozenset(
    {
        "mr", "mrs", "ms", "mx", "dr", "prof", "sr", "jr", "st", "mt", "ft", "vs", "v",
        "e.g", "i.e", "cf", "viz", "approx", "ca", "al", "esp", "resp",
        "inc", "ltd", "co", "corp", "dept", "univ", "assn", "bros",
        "gen", "gov", "sen", "rep", "rev", "hon", "capt", "col", "lt", "sgt", "cmdr", "adm",
        "ave", "blvd", "rd", "jan", "feb", "apr", "jun", "jul", "aug", "sep", "sept",
        "oct", "nov", "dec", "ed", "eds", "trans", "op",
    }
)  # fmt: skip

# Abbreviations that only precede numbers ("No. 5", "pp. 12-14"). Before anything
# else ("I said no. Then...") the period ends the sentence.
NUMBER_ABBREVIATIONS: frozenset[str] = frozenset(
    {"no", "nos", "p", "pp", "fig", "figs", "eq", "eqs", "vol", "vols", "ch", "sec", "art", "ref"}
)

# Terminal punctuation (including the ellipsis character), optional closing quotes
# or brackets, then whitespace.
_BOUNDARY = re.compile(r"[.!?\u2026]+[\"'\u201d\u2019)\]]*\s+")
# Characters that may open a sentence before its first letter: quotes, brackets, dashes.
_OPENERS = "\"'\u201c\u2018([\u2014\u2013-"
_LAST_TOKEN = re.compile(r"(\S+)$")
_DOTTED_ACRONYM = re.compile(r"^(?:[A-Za-z]\.)+[A-Za-z]$")


def split_into_sentences(text: str) -> list[str]:
    """Split text into sentences.

    Args:
        text: Text with normalized whitespace (single spaces, no newlines needed).

    Returns:
        The sentences, stripped, in order. Text without any sentence boundary is
        returned as a single sentence; empty input returns an empty list.
    """
    sentences: list[str] = []
    start = 0
    for match in _BOUNDARY.finditer(text):
        if _is_boundary(text, match):
            sentence = text[start : match.end()].strip()
            if sentence:
                sentences.append(sentence)
            start = match.end()
    if tail := text[start:].strip():
        sentences.append(tail)
    return sentences


def first_sentence_end(text: str) -> int | None:
    """Return the index just after the first sentence boundary in ``text``, if any.

    Works on raw text with line breaks; the boundary includes the whitespace after
    the sentence-ending punctuation.
    """
    for match in _BOUNDARY.finditer(text):
        if _is_boundary(text, match):
            return match.end()
    return None


def _is_boundary(text: str, match: re.Match[str]) -> bool:
    following = text[match.end() :].lstrip(_OPENERS)
    if not following:
        return False
    next_char = following[0]
    if not (next_char.isupper() or next_char.isdigit()):
        return False

    punctuation = match.group().rstrip()
    if not punctuation.startswith(".") or punctuation.startswith(".."):
        return True  # "!", "?", and ellipses are not used in abbreviations.

    token_match = _LAST_TOKEN.search(text, 0, match.start())
    if token_match is None:
        return True
    token = token_match.group(1).lstrip(_OPENERS)
    word = token.lower()
    if word in ABBREVIATIONS:
        return False
    if word in NUMBER_ABBREVIATIONS and next_char.isdigit():
        return False
    if len(token) == 1 and token.isupper():
        return False  # An initial, as in "J. R. R. Tolkien".
    return not _DOTTED_ACRONYM.match(token)  # "U.S." or "a.m."
