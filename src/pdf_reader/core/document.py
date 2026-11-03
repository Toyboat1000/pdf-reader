"""A document prepared for reading: its spoken sentences plus where they came from."""

import bisect
from dataclasses import dataclass, field
from pathlib import Path

from pdf_reader.core.word_map import WordMap
from pdf_reader.pdf.models import Document
from pdf_reader.text.segment import Segment


@dataclass(frozen=True)
class ReadingDocument:
    """Sentences to read aloud, from a PDF file or from pasted text.

    Attributes:
        title: Display title.
        sentences: Spoken chunks in reading order; positions are indexes into this.
        page_count: Number of pages (1 for pasted text).
        path: The file the document was opened from, if any.
        pdf: The extracted PDF with full layout information, for PDF documents.
        text: The original text, for pasted-text documents.
        word_map: Word positions on scanned pages, for showing and clicking page
            images; ``None`` for documents without scanned pages.
        doc_id: Content-based identifier used to remember the reading position and
            bookmarks, or ``None`` if the document is not remembered.
    """

    title: str
    sentences: tuple[Segment, ...]
    page_count: int = 1
    path: Path | None = None
    pdf: Document | None = None
    text: str | None = None
    doc_id: str | None = None
    word_map: WordMap | None = None
    _page_starts: tuple[int, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        starts: list[int] = []
        last_page = None
        for i, sentence in enumerate(self.sentences):
            if sentence.page != last_page:
                starts.append(i)
                last_page = sentence.page
        object.__setattr__(self, "_page_starts", tuple(starts))

    @classmethod
    def from_pdf(
        cls,
        pdf: Document,
        sentences: tuple[Segment, ...],
        doc_id: str | None = None,
        word_map: WordMap | None = None,
    ) -> "ReadingDocument":
        """Create a reading document for an extracted PDF."""
        return cls(
            title=pdf.title,
            sentences=sentences,
            page_count=pdf.page_count,
            path=pdf.path,
            pdf=pdf,
            doc_id=doc_id,
            word_map=word_map,
        )

    @classmethod
    def from_text(cls, text: str, sentences: tuple[Segment, ...]) -> "ReadingDocument":
        """Create a reading document for pasted or typed text."""
        return cls(title=text_title(text), sentences=sentences, text=text)

    @property
    def is_paginated(self) -> bool:
        """Return whether the document has real pages (PDFs do; pasted text doesn't)."""
        return self.pdf is not None

    @property
    def display_name(self) -> str:
        """Return the file name for files, otherwise the title."""
        return self.path.name if self.path is not None else self.title

    @property
    def sentence_count(self) -> int:
        """Return the number of spoken chunks."""
        return len(self.sentences)

    def page_of(self, index: int) -> int:
        """Return the 1-based page number of sentence ``index``."""
        return self.sentences[index].page

    def first_sentence_on_or_after_page(self, page: int) -> int | None:
        """Return the first sentence index on ``page`` or a later page, if any."""
        pages = [self.sentences[i].page for i in self._page_starts]
        pos = bisect.bisect_left(pages, page)
        return self._page_starts[pos] if pos < len(pages) else None


_TITLE_MAX_CHARS = 50


def text_title(text: str) -> str:
    """Make a short title from the first line of ``text``."""
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if not first_line:
        return "Untitled text"
    title = " ".join(first_line.split())
    if len(title) <= _TITLE_MAX_CHARS:
        return title
    cut = title.rfind(" ", 0, _TITLE_MAX_CHARS)
    return title[: cut if cut > 0 else _TITLE_MAX_CHARS].rstrip(",;:") + "\u2026"
