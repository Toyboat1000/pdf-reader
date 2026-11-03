"""Paged document formats that PyMuPDF opens: PDF, EPUB, and other e-books.

E-books have no fixed pages; MuPDF lays them out on pages of :data:`EBOOK_PAGE`.
Every place that opens a document (text extraction, OCR, page rendering, covers)
goes through :func:`open_paged`, so they all see exactly the same pages.
"""

from pathlib import Path

import pymupdf

PAGED_FORMATS: dict[str, str] = {
    ".pdf": "pdf",
    ".epub": "epub",
    ".mobi": "mobi",
    ".fb2": "fb2",
    ".xps": "xps",
    ".oxps": "xps",
    ".cbz": "cbz",
}
"""File suffix -> PyMuPDF file type, for documents shown as pages."""

EBOOK_PAGE = (432.0, 648.0)
"""Width and height in points of an e-book page (6 x 9 inches, a paperback)."""

EBOOK_FONT_SIZE = 11.0
"""Base font size in points for laying out e-books."""


def filetype_of(path: Path) -> str:
    """Return the PyMuPDF file type for ``path`` (PDF unless the suffix says otherwise)."""
    return PAGED_FORMATS.get(path.suffix.lower(), "pdf")


def is_paged(path: Path) -> bool:
    """Return whether ``path`` is a document shown as pages."""
    return path.suffix.lower() in PAGED_FORMATS


def open_paged(
    path: Path | None = None, *, data: bytes | None = None, filetype: str = "pdf"
) -> pymupdf.Document:
    """Open a paged document from a file or from its bytes, laying out e-books.

    Raises whatever PyMuPDF raises for unreadable files.
    """
    if data is not None:
        document = pymupdf.open(stream=data, filetype=filetype)
    else:
        assert path is not None
        document = pymupdf.open(path, filetype=filetype)
    if document.is_reflowable:
        width, height = EBOOK_PAGE
        document.layout(width=width, height=height, fontsize=EBOOK_FONT_SIZE)
    return document
