"""Find when each written word is spoken, for word-by-word highlighting.

Engines report timings for what they actually said, which is not always word for
word what is written: "e.g." is spoken as "for example", "1990" as "nineteen
ninety". :func:`align_word_starts` matches written words to spoken words by length
(a short dynamic-programming alignment), so one written word can stand for several
spoken ones and the other way round. :func:`estimate_word_starts` is the fallback
for engines without timings.

Words are the whitespace-separated pieces of the text (``text.split()``); their
indexes are what the views highlight.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

from pdf_reader.tts.speech_text import speech_text

_DIGIT_WEIGHT = 3.0  # A digit is spoken as about three sounds ("seven", "twenty").
_SYMBOL_WEIGHT = 3.0  # "&", "%", "+" and the like are spoken as a short word.
_SYMBOLS = frozenset("&%+=$\u20ac\u00a3@#\u00b0")
_GROUP_PENALTY = 0.35  # Cost of each extra word in a one-to-many match.
_MAX_SPOKEN_PER_WORD = 6  # "1,234,567" can become many spoken words.
_MAX_WORDS_PER_SPOKEN = 3
_BAND = 6  # Alignments stray at most this far (plus the length difference) from the diagonal.


@dataclass(frozen=True, slots=True)
class SpokenWord:
    """A word as the engine spoke it.

    Attributes:
        length: How many sounds (phonemes or letters) it has; only relative sizes
            matter.
        start: When it starts, in seconds.
        end: When it ends, in seconds.
    """

    length: int
    start: float
    end: float


def word_weight(word: str) -> float:
    """Return roughly how many sounds a written word is spoken with."""
    spoken = speech_text(word) if any(c in word for c in ".&/") else word
    weight = 0.0
    for char in spoken:
        if char.isalpha():
            weight += 1.0
        elif char.isdigit():
            weight += _DIGIT_WEIGHT
        elif char in _SYMBOLS:
            weight += _SYMBOL_WEIGHT
    return weight


def estimate_word_starts(text: str, duration: float) -> tuple[float, ...]:
    """Spread the words of ``text`` over ``duration`` seconds by their length."""
    words = text.split()
    if not words:
        return ()
    weights = [max(word_weight(w), 0.5) + 1.0 for w in words]  # +1: the gap after it.
    total = sum(weights)
    starts: list[float] = []
    elapsed = 0.0
    for weight in weights:
        starts.append(duration * elapsed / total)
        elapsed += weight
    return tuple(starts)


def align_word_starts(text: str, spoken: Sequence[SpokenWord]) -> tuple[float, ...]:
    """Return the start time of every word of ``text``, from the spoken words.

    Args:
        text: The written text; its words are ``text.split()``.
        spoken: The words as spoken, in order, with their timings.

    Returns:
        One non-decreasing start time per written word. Words that were not spoken
        (a lone dash, say) share the start of the next spoken word.
    """
    words = text.split()
    if not words:
        return ()
    if not spoken:
        return tuple(0.0 for _ in words)
    weights = [word_weight(w) for w in words]
    total_written = sum(weights)
    total_spoken = sum(s.length for s in spoken)
    scale = total_spoken / total_written if total_written > 0 else 1.0
    expected = [w * scale for w in weights]
    groups = _align(expected, [float(s.length) for s in spoken])

    starts: list[float | None] = [None] * len(words)
    for (i0, i1), (j0, j1) in groups:
        if i1 == i0 or j1 == j0:
            continue  # Unspoken written word, or an extra spoken one: no start of its own.
        begin, end = spoken[j0].start, spoken[j1 - 1].end
        if i1 - i0 == 1:
            starts[i0] = begin
            continue
        # Several written words spoken as one: share its time by their lengths.
        share = [max(expected[i], 0.5) for i in range(i0, i1)]
        elapsed = 0.0
        for offset, part in enumerate(share):
            starts[i0 + offset] = begin + (end - begin) * elapsed / sum(share)
            elapsed += part

    result: list[float] = [0.0] * len(words)
    following = spoken[-1].end
    for i in range(len(words) - 1, -1, -1):
        value = starts[i]
        if value is not None:
            following = value
        result[i] = following
    # Never decreasing, so a binary search finds the word at any moment.
    for i in range(1, len(result)):
        result[i] = max(result[i], result[i - 1])
    return tuple(result)


type _Group = tuple[tuple[int, int], tuple[int, int]]


def _align(written: list[float], spoken: list[float]) -> list[_Group]:
    """Pair runs of written words with runs of spoken words, minimizing the mismatch.

    Returns ``((i0, i1), (j0, j1))`` groups covering both sequences in order; one
    side of a group may be empty.
    """
    n, m = len(written), len(spoken)
    inf = math.inf
    cost = [[inf] * (m + 1) for _ in range(n + 1)]
    step: list[list[tuple[int, int]]] = [[(0, 0)] * (m + 1) for _ in range(n + 1)]
    cost[0][0] = 0.0
    written_sum = [0.0]
    for value in written:
        written_sum.append(written_sum[-1] + value)
    spoken_sum = [0.0]
    for value in spoken:
        spoken_sum.append(spoken_sum[-1] + value)

    def mismatch(a: float, b: float) -> float:
        return abs(math.log((a + 1.0) / (b + 1.0)))

    # Only cells near the diagonal are explored, which keeps long sentences fast.
    band = abs(n - m) + _BAND

    def window(i: int) -> range:
        centre = i * m // max(n, 1)
        return range(max(0, centre - band), min(m, centre + band) + 1)

    def inside(i: int, j: int) -> bool:
        return abs(j - i * m // max(n, 1)) <= band

    moves = [(1, k) for k in range(1, _MAX_SPOKEN_PER_WORD + 1)]
    moves += [(k, 1) for k in range(2, _MAX_WORDS_PER_SPOKEN + 1)]
    for i in range(n + 1):
        for j in window(i):
            here = cost[i][j]
            if here == inf:
                continue
            for di, dj in moves:
                ni, nj = i + di, j + dj
                if ni > n or nj > m or not inside(ni, nj):
                    continue
                a = written_sum[ni] - written_sum[i]
                b = spoken_sum[nj] - spoken_sum[j]
                value = here + mismatch(a, b) + _GROUP_PENALTY * (di + dj - 2)
                if value < cost[ni][nj]:
                    cost[ni][nj], step[ni][nj] = value, (di, dj)
            if i < n:  # A written word that wasn't spoken (punctuation, symbols).
                value = here + (0.1 if written[i] == 0 else 1.0 + mismatch(written[i], 0))
                if value < cost[i + 1][j]:
                    cost[i + 1][j], step[i + 1][j] = value, (1, 0)
            if j < m:  # A spoken word with no written counterpart.
                value = here + 1.0 + 0.5 * mismatch(spoken[j], 0)
                if value < cost[i][j + 1]:
                    cost[i][j + 1], step[i][j + 1] = value, (0, 1)

    groups: list[_Group] = []
    i, j = n, m
    while i > 0 or j > 0:
        di, dj = step[i][j]
        groups.append(((i - di, i), (j - dj, j)))
        i, j = i - di, j - dj
    groups.reverse()
    return groups
