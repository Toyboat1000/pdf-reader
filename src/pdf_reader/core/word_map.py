"""Link recognized words on scanned pages to the sentences that are read aloud.

The text pipeline cleans and reshapes OCR text (removing page numbers, joining
hyphenated words, ...), so sentences can't be traced back to words directly. Instead,
each page's sentence words are aligned with its OCR words using a sequence diff.
Words that don't match exactly (e.g. halves of a hyphenated word) are attributed to
the surrounding sentence, so every word on the page is clickable.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher

from pdf_reader.pdf.models import BBox, Document
from pdf_reader.text.segment import Segment

_NON_WORD = re.compile(r"[^\w]+")


@dataclass(frozen=True, slots=True)
class WordBox:
    """A recognized word's position and the sentence it belongs to.

    Attributes:
        page: 1-based page number.
        bbox: Position on the page, in PDF points.
        sentence: Index of the sentence the word belongs to.
        spoken: True if the word is part of the sentence's spoken text (it is
            highlighted); False if it was only attributed for clicking (e.g. a
            removed page number next to the sentence).
    """

    page: int
    bbox: BBox
    sentence: int
    spoken: bool


@dataclass(frozen=True)
class WordMap:
    """Word positions for every scanned page, and their sentences."""

    by_page: dict[int, list[WordBox]]

    def sentence_boxes(self, sentence: int) -> list[WordBox]:
        """Return the highlighted words of a sentence, in page order."""
        return [
            w
            for words in self.by_page.values()
            for w in words
            if w.sentence == sentence and w.spoken
        ]

    def sentence_at(self, page: int, x: float, y: float) -> int | None:
        """Return the sentence of the word at (or nearest to) a point on a page."""
        words = self.by_page.get(page)
        if not words:
            return None

        def distance(w: WordBox) -> float:
            x0, y0, x1, y1 = w.bbox
            dx = max(x0 - x, 0.0, x - x1)
            dy = max(y0 - y, 0.0, y - y1)
            return dx * dx + 4 * dy * dy  # Prefer words on the same line.

        return min(words, key=distance).sentence


def _norm(text: str) -> str:
    return _NON_WORD.sub("", text).lower()


def build_word_map(document: Document, sentences: Sequence[Segment]) -> WordMap | None:
    """Align each scanned page's OCR words with its sentences.

    Returns:
        The map, or ``None`` if the document has no scanned pages.
    """
    if not document.is_scanned:
        return None
    by_page: dict[int, list[WordBox]] = {}
    for page in document.pages:
        if not page.is_scanned:
            continue
        tokens: list[tuple[str, int]] = [
            (norm, i)
            for i, s in enumerate(sentences)
            if s.page == page.number
            for word in s.text.split()
            if (norm := _norm(word))
        ]
        ocr = [_norm(w.text) for w in page.words]
        owner: list[int | None] = [None] * len(ocr)
        matcher = SequenceMatcher(None, [t for t, _ in tokens], ocr, autojunk=False)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                for k in range(j2 - j1):
                    owner[j1 + k] = tokens[i1 + k][1]
            elif tag == "replace":
                # OCR and spoken words differ here ("Good- bye" vs "Goodbye"): spread the
                # OCR words over the sentences of the spoken words they stand for.
                for k in range(j2 - j1):
                    owner[j1 + k] = tokens[i1 + k * (i2 - i1) // (j2 - j1)][1]
            # "insert": OCR words that aren't spoken (removed page numbers, headers).
        by_page[page.number] = _attribute(page.number, page.words, owner)
    return WordMap(by_page)


def _attribute(page: int, words: Sequence, owner: list[int | None]) -> list[WordBox]:
    """Give every word a sentence: spoken words keep theirs; others borrow a neighbour's."""
    previous: list[int | None] = []
    last = None
    for o in owner:
        last = o if o is not None else last
        previous.append(last)
    following: list[int | None] = [None] * len(owner)
    nxt = None
    for i in range(len(owner) - 1, -1, -1):
        nxt = owner[i] if owner[i] is not None else nxt
        following[i] = nxt

    boxes: list[WordBox] = []
    for i, word in enumerate(words):
        if owner[i] is not None:
            boxes.append(WordBox(page, word.bbox, owner[i], True))
            continue
        before, after = previous[i], following[i]
        if before is not None and before == after:
            # Inside a sentence (e.g. half of a hyphenated word): highlight it too.
            boxes.append(WordBox(page, word.bbox, before, True))
        elif before is not None or after is not None:
            sentence = before if before is not None else after
            assert sentence is not None
            boxes.append(WordBox(page, word.bbox, sentence, False))
    return boxes
