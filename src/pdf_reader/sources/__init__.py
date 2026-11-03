"""Documents that are read as flowing text: Word files, web pages, and plain text.

Paged formats (PDF, EPUB, and other e-books) are handled by :mod:`pdf_reader.pdf`.
Everything here produces a :class:`TextSource`: a title and paragraphs of text.
"""

from pdf_reader.sources.files import TEXT_SUFFIXES, read_text_document
from pdf_reader.sources.models import SourceError, TextSource
from pdf_reader.sources.web import FetchResult, fetch, is_web_address, normalize_address

__all__ = [
    "TEXT_SUFFIXES",
    "FetchResult",
    "SourceError",
    "TextSource",
    "fetch",
    "is_web_address",
    "normalize_address",
    "read_text_document",
]
