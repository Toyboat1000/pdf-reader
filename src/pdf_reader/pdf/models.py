"""Immutable data model for an extracted PDF document.

Position data (bounding boxes in PDF points, origin top-left) and font sizes are kept
so later processing steps can detect headers, footers, page numbers, and columns.
"""

from dataclasses import dataclass
from pathlib import Path

type BBox = tuple[float, float, float, float]
"""Bounding box as ``(x0, y0, x1, y1)`` in PDF points, origin at the top-left."""


@dataclass(frozen=True, slots=True)
class TextLine:
    """One line of text as laid out on the page.

    Attributes:
        text: The line's text, spans concatenated.
        bbox: The line's bounding box.
        font_size: Largest font size used on the line, in points.
    """

    text: str
    bbox: BBox
    font_size: float


@dataclass(frozen=True, slots=True)
class TextBlock:
    """A block of lines, usually a paragraph, heading, or caption.

    Attributes:
        lines: Lines in reading order.
        bbox: The block's bounding box.
    """

    lines: tuple[TextLine, ...]
    bbox: BBox

    @property
    def text(self) -> str:
        """Return the block's lines joined with newlines."""
        return "\n".join(line.text for line in self.lines)


@dataclass(frozen=True, slots=True)
class Page:
    """A single page of extracted text.

    Attributes:
        number: 1-based page number.
        width: Page width in points.
        height: Page height in points.
        blocks: Text blocks in reading order.
    """

    number: int
    width: float
    height: float
    blocks: tuple[TextBlock, ...]

    @property
    def text(self) -> str:
        """Return the page text, blocks separated by blank lines."""
        return "\n\n".join(block.text for block in self.blocks)


@dataclass(frozen=True, slots=True)
class Document:
    """A loaded PDF document.

    Attributes:
        path: File the document was loaded from.
        title: Title from the PDF metadata, or the file name if there is none.
        pages: All pages, including ones without text.
    """

    path: Path
    title: str
    pages: tuple[Page, ...]

    @property
    def page_count(self) -> int:
        """Return the number of pages."""
        return len(self.pages)

    @property
    def has_text(self) -> bool:
        """Return whether any page contains non-whitespace text."""
        return any(
            line.text.strip()
            for page in self.pages
            for block in page.blocks
            for line in block.lines
        )
