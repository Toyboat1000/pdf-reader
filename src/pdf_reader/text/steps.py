"""Individual text-processing steps.

Every step is a function ``list[Segment] -> list[Segment]``. Steps that only rewrite
each segment's text can be written as ``str -> str`` functions wrapped with
:func:`text_step`. To add a step, write it here and add it to
:func:`pdf_reader.text.pipeline.default_steps`.
"""

import re
import unicodedata
from collections.abc import Callable
from dataclasses import replace

from pdf_reader.text.chunking import DEFAULT_MAX_CHARS, split_long_text
from pdf_reader.text.segment import Segment
from pdf_reader.text.sentences import split_into_sentences

type TextStep = Callable[[list[Segment]], list[Segment]]
"""A pipeline step: takes segments in reading order and returns new ones."""


def text_step(func: Callable[[str], str]) -> TextStep:
    """Turn a ``str -> str`` function into a step applied to every segment's text."""

    def step(segments: list[Segment]) -> list[Segment]:
        return [replace(segment, text=func(segment.text)) for segment in segments]

    step.__name__ = func.__name__
    step.__qualname__ = func.__qualname__
    step.__doc__ = func.__doc__
    return step


# Unicode superscript digits used as footnote references: after a word of 3+ letters
# ("claim¹") or after closing punctuation ("end.²"). "x²" and "mc²" are kept.
_SUPERSCRIPT_MARKER = re.compile(
    r"(?:(?<=[A-Za-z]{3})|(?<=[.,;:)\]\"'\u201d\u2019]))[\u00b9\u00b2\u00b3\u2070\u2074-\u2079]+"
)


@text_step
def strip_superscript_markers(text: str) -> str:
    """Remove footnote references written with Unicode superscript digits.

    Must run before :func:`normalize_unicode`, which would turn "claim\u00b9" into
    "claim1".
    """
    return _SUPERSCRIPT_MARKER.sub("", text)


# Soft hyphens, zero-width spaces/joiners, and the byte-order mark.
_INVISIBLE = re.compile("[\u00ad\u200b\u200c\u200d\u2060\ufeff]")


@text_step
def normalize_unicode(text: str) -> str:
    """Apply NFKC normalization (e.g. ligatures to letters) and drop invisible characters."""
    return _INVISIBLE.sub("", unicodedata.normalize("NFKC", text))


# A word broken across lines with a hyphen: "exam-\nple".
_HYPHEN_BREAK = re.compile(r"(\w)-[ \t]*\n[ \t]*(\w)")


@text_step
def fix_hyphenated_line_breaks(text: str) -> str:
    r"""Rejoin words hyphenated at line ends.

    "exam-\nple" becomes "example". When the next line starts with a capital
    letter or digit ("Jean-\nPaul", "COVID-\n19") the hyphen is kept.
    """

    def join(match: re.Match[str]) -> str:
        before, after = match.group(1), match.group(2)
        if after.islower():
            return before + after
        return f"{before}-{after}"

    return _HYPHEN_BREAK.sub(join, text)


_WHITESPACE = re.compile(r"\s+")


@text_step
def normalize_whitespace(text: str) -> str:
    """Collapse all runs of whitespace, including line breaks, into single spaces."""
    return _WHITESPACE.sub(" ", text).strip()


_PARENTHETICAL = re.compile(r"\s*\([^()]*\)")
_SPACE_BEFORE_PUNCTUATION = re.compile(r"\s+([,.;:!?])")


@text_step
def remove_parentheticals(text: str) -> str:
    """Remove text in (parentheses), including nested ones, and tidy the spacing."""
    previous = None
    while previous != text:
        previous, text = text, _PARENTHETICAL.sub("", text)
    return _SPACE_BEFORE_PUNCTUATION.sub(r"\1", text).strip()


def drop_unspeakable(segments: list[Segment]) -> list[Segment]:
    """Remove segments without any letters or digits (stray bullets, rules, symbols)."""
    return [s for s in segments if any(ch.isalnum() for ch in s.text)]


def split_sentences(segments: list[Segment]) -> list[Segment]:
    """Split each segment into one segment per sentence."""
    return [
        replace(segment, text=sentence, ends_sentence=True, ends_paragraph=i == len(parts) - 1)
        for segment in segments
        for parts in [split_into_sentences(segment.text)]
        for i, sentence in enumerate(parts)
    ]


def split_long_sentences(max_chars: int = DEFAULT_MAX_CHARS) -> TextStep:
    """Create a step that splits segments longer than ``max_chars`` at natural pauses.

    All but the last piece of a split sentence get ``ends_sentence=False``.
    """

    def step(segments: list[Segment]) -> list[Segment]:
        result: list[Segment] = []
        for segment in segments:
            pieces = split_long_text(segment.text, max_chars)
            last = len(pieces) - 1
            result.extend(
                replace(
                    segment,
                    text=piece,
                    ends_sentence=segment.ends_sentence if i == last else False,
                    ends_paragraph=segment.ends_paragraph if i == last else False,
                )
                for i, piece in enumerate(pieces)
            )
        return result

    step.__name__ = step.__qualname__ = "split_long_sentences"
    return step
