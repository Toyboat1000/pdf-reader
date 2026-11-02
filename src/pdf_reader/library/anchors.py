"""Creating anchors for sentences and finding them again in a (re)processed document."""

import hashlib
from collections.abc import Sequence
from pathlib import Path

from pdf_reader.library.models import Anchor
from pdf_reader.text.segment import Segment

ANCHOR_TEXT_CHARS = 80
"""How much of a sentence's text an anchor keeps."""

_MIN_PREFIX_CHARS = 10  # Shorter sentences ("1", "Yes.") match too much to be prefixes.


def file_id(path: Path) -> str:
    """Return a SHA-256 hash of a file's contents, used as its document id.

    Identifying documents by content means positions and bookmarks survive moving or
    renaming the file. Blocking; call it off the UI thread.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def make_anchor(sentences: Sequence[Segment], index: int) -> Anchor:
    """Create an anchor for sentence ``index``."""
    sentence = sentences[index]
    return Anchor(index=index, page=sentence.page, text=sentence.text[:ANCHOR_TEXT_CHARS])


def resolve(anchor: Anchor, sentences: Sequence[Segment]) -> int:
    """Find the sentence an anchor refers to.

    In order of preference: the saved index if its text still matches; the matching
    sentence closest to the saved index; the first sentence on the saved page; the
    saved index clamped to the document.

    Args:
        anchor: The saved location.
        sentences: The document's current sentences; must not be empty.

    Returns:
        A valid sentence index.
    """
    count = len(sentences)
    if count == 0:
        raise ValueError("cannot resolve an anchor in an empty document")

    def matches(i: int) -> bool:
        text = sentences[i].text
        # The second case covers a saved sentence that is now split in two.
        return text.startswith(anchor.text) or (
            len(text) >= _MIN_PREFIX_CHARS and anchor.text.startswith(text)
        )

    if 0 <= anchor.index < count and matches(anchor.index):
        return anchor.index
    candidates = [i for i in range(count) if matches(i)]
    if candidates:
        return min(candidates, key=lambda i: abs(i - anchor.index))
    on_page = [i for i in range(count) if sentences[i].page == anchor.page]
    if on_page:
        return on_page[0]
    return max(0, min(anchor.index, count - 1))
