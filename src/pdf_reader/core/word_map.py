"""Link the words on PDF pages (from the text layer or OCR) to the sentences read aloud.

The text pipeline cleans and reshapes OCR text (removing page numbers, joining
hyphenated words, ...), so sentences can't be traced back to words directly. Instead,
each page's sentence words are aligned with its OCR words using a sequence diff.
Words that don't match exactly (e.g. halves of a hyphenated word) are attributed to
the surrounding sentence, so every word on the page is clickable.
"""

import re
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from pdf_reader.pdf.models import BBox, Document, OcrWord
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
        text: The word as printed on the page (for copying).
    """

    page: int
    bbox: BBox
    sentence: int
    spoken: bool
    text: str = ""


@dataclass(frozen=True)
class WordMap:
    """Word positions for every scanned page, and their sentences."""

    by_page: dict[int, list[WordBox]]
    _lines: dict[int, list[tuple[int, BBox]]] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )

    def sentence_boxes(self, sentence: int) -> list[WordBox]:
        """Return the highlighted words of a sentence, in page order."""
        return [
            w
            for words in self.by_page.values()
            for w in words
            if w.sentence == sentence and w.spoken
        ]

    def sentence_lines(self, sentence: int) -> list[tuple[int, BBox]]:
        """Return one even band per line a sentence covers, as ``(page, bbox)``.

        OCR word boxes differ in height (ascenders, descenders, punctuation), so the
        words on each line are merged into a single band, and every band of the
        sentence gets the same height, centred on its line. This is what the page
        view draws as highlight pills.
        """
        cached = self._lines.get(sentence)
        if cached is not None:
            return cached
        bands = line_bands(self.sentence_boxes(sentence))
        self._lines[sentence] = bands
        return bands

    def sentence_at(
        self, page: int, x: float, y: float, max_distance: float | None = None
    ) -> int | None:
        """Return the sentence of the word at (or nearest to) a point on a page.

        Args:
            page: 1-based page number.
            x: Horizontal position in points.
            y: Vertical position in points.
            max_distance: If given, only words within this many points count.
        """
        words = self.by_page.get(page)
        if not words:
            return None

        def distance(w: WordBox) -> float:
            x0, y0, x1, y1 = w.bbox
            dx = max(x0 - x, 0.0, x - x1)
            dy = max(y0 - y, 0.0, y - y1)
            return dx * dx + 4 * dy * dy  # Prefer words on the same line.

        nearest = min(words, key=distance)
        if max_distance is not None and distance(nearest) > max_distance**2:
            return None
        return nearest.sentence


def line_bands(boxes: Sequence[WordBox]) -> list[tuple[int, BBox]]:
    """Merge words into one even band per line, as ``(page, bbox)`` in reading order.

    Every band gets the same height (the median word height), centred on its line,
    so highlights look uniform even though word boxes differ in height.
    """
    lines: list[list[WordBox]] = []
    for box in boxes:
        last = lines[-1][-1] if lines else None
        if last is not None and _same_line(last, box):
            lines[-1].append(box)
        else:
            lines.append([box])
    height = statistics.median(b.bbox[3] - b.bbox[1] for b in boxes) if boxes else 0.0
    bands: list[tuple[int, BBox]] = []
    for line in lines:
        centre = statistics.median((b.bbox[1] + b.bbox[3]) / 2 for b in line)
        x0 = min(b.bbox[0] for b in line)
        x1 = max(b.bbox[2] for b in line)
        bands.append((line[0].page, (x0, centre - height / 2, x1, centre + height / 2)))
    return bands


def _same_line(previous: WordBox, word: WordBox) -> bool:
    """Return whether ``word`` continues the line ``previous`` is on."""
    if previous.page != word.page:
        return False
    height = previous.bbox[3] - previous.bbox[1]
    centre_gap = abs((previous.bbox[1] + previous.bbox[3]) / 2 - (word.bbox[1] + word.bbox[3]) / 2)
    horizontal_gap = word.bbox[0] - previous.bbox[2]
    return centre_gap < 0.6 * height and -height < horizontal_gap < 3 * height


def _norm(text: str) -> str:
    return _NON_WORD.sub("", text).lower()


def build_word_map(document: Document, sentences: Sequence[Segment]) -> WordMap | None:
    """Align each scanned page's OCR words with its sentences.

    Returns:
        The map, or ``None`` if the document has no scanned pages.
    """
    if not document.has_words:
        return None
    by_page: dict[int, list[WordBox]] = {}
    for page in document.pages:
        if not page.words:
            continue
        on_page = [(i, s) for i, s in enumerate(sentences) if s.page == page.number]
        tokens: list[tuple[str, int]] = [
            (norm, i) for i, s in on_page for word in s.text.split() if (norm := _norm(word))
        ]
        words = _reading_order(page.words, [s.bbox for _, s in on_page])
        ocr = [_norm(w.text) for w in words]
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
        by_page[page.number] = _attribute(page.number, words, owner)
    return WordMap(by_page)


def _reading_order(words: Sequence[OcrWord], block_boxes: list[BBox | None]) -> list[OcrWord]:
    """Put a page's words in the order their blocks are read.

    The pipeline reorders blocks (columns, skipped sidebars), so each word is placed
    with the block that contains it, in the order the sentences use those blocks.
    Words outside every read block (removed headers, captions) go last.
    """
    ranks: list[BBox] = []
    for box in block_boxes:
        if box is not None and box not in ranks:
            ranks.append(box)

    def rank(word: OcrWord) -> int:
        cx = (word.bbox[0] + word.bbox[2]) / 2
        cy = (word.bbox[1] + word.bbox[3]) / 2
        for i, (x0, y0, x1, y1) in enumerate(ranks):
            if x0 - 1 <= cx <= x1 + 1 and y0 - 1 <= cy <= y1 + 1:
                return i
        return len(ranks)

    order = sorted(range(len(words)), key=lambda i: (rank(words[i]), i))
    return [words[i] for i in order]


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
            boxes.append(WordBox(page, word.bbox, owner[i], True, word.text))
            continue
        before, after = previous[i], following[i]
        if before is not None and before == after:
            # Inside a sentence (e.g. half of a hyphenated word): highlight it too.
            boxes.append(WordBox(page, word.bbox, before, True, word.text))
        elif before is not None or after is not None:
            sentence = before if before is not None else after
            assert sentence is not None
            boxes.append(WordBox(page, word.bbox, sentence, False, word.text))
    return boxes
