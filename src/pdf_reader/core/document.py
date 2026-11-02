"""A document prepared for reading: the extracted PDF plus its spoken sentences."""

import bisect
from dataclasses import dataclass, field

from pdf_reader.pdf.models import Document
from pdf_reader.text.segment import Segment


@dataclass(frozen=True)
class ReadingDocument:
    """An extracted PDF and the sentences that will be read aloud.

    Attributes:
        document: The source document with full layout information.
        sentences: Spoken chunks in reading order; positions are indexes into this.
    """

    document: Document
    sentences: tuple[Segment, ...]
    _page_starts: tuple[int, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        starts: list[int] = []
        last_page = None
        for i, sentence in enumerate(self.sentences):
            if sentence.page != last_page:
                starts.append(i)
                last_page = sentence.page
        object.__setattr__(self, "_page_starts", tuple(starts))

    @property
    def title(self) -> str:
        """Return the document title."""
        return self.document.title

    @property
    def page_count(self) -> int:
        """Return the number of pages in the PDF."""
        return self.document.page_count

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
