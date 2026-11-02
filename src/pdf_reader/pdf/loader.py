"""Load a PDF with PyMuPDF and extract its text with layout information."""

import logging
from pathlib import Path
from typing import Any

import pymupdf

from pdf_reader.pdf.errors import CorruptPdfError, EncryptedPdfError, NoTextError, PdfNotFoundError
from pdf_reader.pdf.models import BBox, Document, Page, TextBlock, TextLine

log = logging.getLogger(__name__)

# Keep whitespace as-is (the text pipeline normalizes it), expand ligatures such as
# "fi" into plain letters, and ignore text outside the visible page area.
_TEXT_FLAGS = pymupdf.TEXT_PRESERVE_WHITESPACE | pymupdf.TEXT_MEDIABOX_CLIP


def load_pdf(path: Path) -> Document:
    """Open a PDF and extract all text page by page in reading order.

    This is blocking and can take a while for large files; call it off the UI thread.

    Args:
        path: The PDF file to read.

    Returns:
        The extracted document.

    Raises:
        PdfNotFoundError: The file does not exist or cannot be read.
        EncryptedPdfError: The PDF requires a password.
        CorruptPdfError: The file is damaged or not a PDF.
        NoTextError: The PDF contains no extractable text.
    """
    if not path.is_file():
        raise PdfNotFoundError(path)
    try:
        pdf = pymupdf.open(path, filetype="pdf")
    except (pymupdf.FileDataError, pymupdf.EmptyFileError) as exc:
        log.warning("Corrupt PDF %s: %s", path, exc)
        raise CorruptPdfError(path) from exc
    except OSError as exc:
        log.warning("Cannot open %s: %s", path, exc)
        raise PdfNotFoundError(path) from exc
    except Exception as exc:  # PyMuPDF raises plain RuntimeError/ValueError for odd files.
        log.warning("Failed to open %s", path, exc_info=True)
        raise CorruptPdfError(path) from exc

    with pdf:
        if pdf.needs_pass:
            raise EncryptedPdfError(path)
        if pdf.page_count == 0:
            raise CorruptPdfError(path)
        try:
            pages = tuple(_extract_page(page) for page in pdf)
            title = _title(pdf.metadata, path)
        except Exception as exc:
            log.warning("Failed to extract text from %s", path, exc_info=True)
            raise CorruptPdfError(path) from exc

    document = Document(path=path, title=title, pages=pages)
    if not document.has_text:
        raise NoTextError(path)
    log.info("Loaded %s: %d pages", path, document.page_count)
    return document


def _title(metadata: dict[str, Any] | None, path: Path) -> str:
    title = (metadata or {}).get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    return path.stem


def _extract_page(page: pymupdf.Page) -> Page:
    # sort=True orders blocks top-to-bottom, then left-to-right.
    data = page.get_text("dict", flags=_TEXT_FLAGS, sort=True)
    blocks: list[TextBlock] = []
    for raw_block in data.get("blocks", []):
        if raw_block.get("type") != 0:  # 0 = text, 1 = image
            continue
        lines = tuple(
            line for raw_line in raw_block.get("lines", []) if (line := _make_line(raw_line))
        )
        if lines:
            blocks.append(TextBlock(lines=lines, bbox=_bbox(raw_block["bbox"])))
    rect = page.rect
    return Page(number=page.number + 1, width=rect.width, height=rect.height, blocks=tuple(blocks))


def _make_line(raw_line: dict[str, Any]) -> TextLine | None:
    spans = raw_line.get("spans", [])
    text = "".join(span.get("text", "") for span in spans)
    if not text.strip():
        return None
    font_size = max((float(span.get("size", 0.0)) for span in spans), default=0.0)
    return TextLine(text=text, bbox=_bbox(raw_line["bbox"]), font_size=font_size)


def _bbox(values: Any) -> BBox:
    x0, y0, x1, y1 = (float(v) for v in values)
    return (x0, y0, x1, y1)
