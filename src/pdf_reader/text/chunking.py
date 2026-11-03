"""Split overly long sentences into speakable chunks at natural pause points."""

import math
import re

DEFAULT_MAX_CHARS = 380
"""Default chunk length limit. Kokoro accepts about 510 phonemes (roughly 400
characters of English). Speaking a whole sentence in one piece keeps its intonation
natural, so only sentences longer than this are split."""

# Preferred split points, best first. A chunk ends right after the matched text.
_DELIMITER_GROUPS: tuple[re.Pattern[str], ...] = (
    re.compile(r"[;:](?=\s)"),
    re.compile(r"\s[\u2014\u2013-](?=\s)|\u2014"),  # Em dash, en dash, or hyphen.
    re.compile(r",(?=\s)"),
    re.compile(r"(?<=\S)\s"),
)


def split_long_text(text: str, max_chars: int = DEFAULT_MAX_CHARS) -> list[str]:
    """Split ``text`` into chunks of at most ``max_chars`` characters.

    Splits at semicolons and colons first, then dashes, then commas, then spaces,
    choosing the split nearest to an even division so chunks have similar lengths.
    A single "word" longer than the limit (for example a URL) is cut hard.

    Args:
        text: The text to split.
        max_chars: Maximum chunk length; must be positive.

    Returns:
        The chunks, stripped and non-empty, in order.
    """
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    chunks: list[str] = []
    rest = text.strip()
    while len(rest) > max_chars:
        cut = _find_cut(rest, max_chars)
        if piece := rest[:cut].strip():
            chunks.append(piece)
        rest = rest[cut:].strip()
    if rest:
        chunks.append(rest)
    return chunks


def _find_cut(text: str, max_chars: int) -> int:
    pieces_needed = math.ceil(len(text) / max_chars)
    ideal = len(text) / pieces_needed
    window = text[: max_chars + 1]
    min_pos = max(1, max_chars // 3)
    for pattern in _DELIMITER_GROUPS:
        cuts = [m.end() for m in pattern.finditer(window) if min_pos <= m.end() <= max_chars]
        if cuts:
            return min(cuts, key=lambda pos: abs(pos - ideal))
    # No good split point after min_pos: take any whitespace, else cut hard.
    space = window.rfind(" ", 1, max_chars + 1)
    return space if space > 0 else max_chars
