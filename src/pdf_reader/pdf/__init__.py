"""PDF loading and text extraction with page and position information."""

from pdf_reader.pdf.errors import (
    CorruptPdfError,
    EncryptedPdfError,
    NoTextError,
    PdfError,
    PdfNotFoundError,
)
from pdf_reader.pdf.loader import load_pdf
from pdf_reader.pdf.models import BBox, Document, Page, TextBlock, TextLine, TextSpan

__all__ = [
    "BBox",
    "CorruptPdfError",
    "Document",
    "EncryptedPdfError",
    "NoTextError",
    "Page",
    "PdfError",
    "PdfNotFoundError",
    "TextBlock",
    "TextLine",
    "TextSpan",
    "load_pdf",
]
