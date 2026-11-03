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

# A standalone year: 1100-1999 or 2010-2099 (2000-2009 read well as "two thousand
# five"), optionally a decade ("1930s") or possessive ("1930's"). Not part of a larger
# number or an amount: no currency sign, digit, comma, or point before it, and no
# digit, thousands group, decimals, percent sign, or unit after it.
_YEAR = re.compile(
    r"(?<![$\u20ac\u00a3\w,.])(1[1-9]\d\d|20[1-9]\d)(s|['\u2019]s)?"
    r"(?!\d|,\d{3}|\.\d|%|\s?(?:kg|km|mi|lbs?|ft|m|g)\b)"
)
_ONES = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
]
_TENS = ["_", "_", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def _two_digits(number: int) -> str:
    if number < 20:
        return _ONES[number]
    tens, ones = divmod(number, 10)
    return _TENS[tens] + (f"-{_ONES[ones]}" if ones else "")


def _plural(word: str) -> str:
    if word.endswith("y"):
        return word[:-1] + "ies"
    return word + ("es" if word.endswith("x") else "s")


def year_words(year: int) -> str:
    """Say a year the usual way: 1930 "nineteen thirty", 1905 "nineteen oh five"."""
    century, rest = divmod(year, 100)
    if rest == 0:
        return f"{_two_digits(century)} hundred"
    if rest < 10:
        return f"{_two_digits(century)} oh {_ONES[rest]}"
    return f"{_two_digits(century)} {_two_digits(rest)}"


def _say_year(match: re.Match[str]) -> str:
    words = year_words(int(match.group(1)))
    suffix = match.group(2)
    if suffix == "s":
        head, _, last = words.rpartition(" ")
        return f"{head} {_plural(last)}"
    return words + (suffix or "")


def speech_text(text: str) -> str:
    """Return ``text`` rewritten for natural speech."""
    for pattern, replacement in _RULES:
        text = pattern.sub(replacement, text)
    # After the rules, so both ends of a range ("1990-2000" -> "1990 to 2000") count.
    text = _YEAR.sub(_say_year, text)
    return _SPACES.sub(" ", text).strip(" ,")
