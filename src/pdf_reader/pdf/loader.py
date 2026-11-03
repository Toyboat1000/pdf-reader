"""Load a PDF with PyMuPDF and extract its text with layout information."""

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pymupdf

from pdf_reader.pdf.errors import CorruptPdfError, EncryptedPdfError, NoTextError, PdfNotFoundError
from pdf_reader.pdf.models import BBox, Document, Page, TextBlock, TextLine, TextSpan
from pdf_reader.pdf.ocr import ocr_available, recognize_page

type ProgressCallback = Callable[[int, int], None]

log = logging.getLogger(__name__)

# Keep whitespace as-is (the text pipeline normalizes it), expand ligatures such as
# "fi" into plain letters, and ignore text outside the visible page area.
_TEXT_FLAGS = pymupdf.TEXT_PRESERVE_WHITESPACE | pymupdf.TEXT_MEDIABOX_CLIP


def load_pdf(path: Path, progress: ProgressCallback | None = None) -> Document:
    """Open a PDF and extract all text page by page in reading order.

    This is blocking and can take a while for large files; call it off the UI thread.

    Pages without any text but with images (scanned pages) are run through OCR.

    Args:
        path: The PDF file to read.
        progress: Called with ``(pages_done, page_count)`` while scanned pages are
            being recognized, which can take a moment per page.

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
            pages = tuple(_extract_page(page, progress) for page in pdf)
            title = _title(pdf.metadata, path)
        except Exception as exc:
            log.warning("Failed to extract text from %s", path, exc_info=True)
            raise CorruptPdfError(path) from exc

    document = Document(path=path, title=title, pages=pages)
    if not document.has_text:
        scanned = any(page.blocks == () and page.has_images for page in pages)
        raise NoTextError(path, scanned=scanned, ocr_available=ocr_available())
    log.info("Loaded %s: %d pages", path, document.page_count)
    return document


def _title(metadata: dict[str, Any] | None, path: Path) -> str:
    title = (metadata or {}).get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    return path.stem


def _extract_page(page: pymupdf.Page, progress: ProgressCallback | None = None) -> Page:
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
    if not blocks and page.get_images():
        if progress is not None:
            progress(page.number, page.parent.page_count)
        try:
            ocr_blocks, words = recognize_page(page)
        except Exception:
            log.warning("OCR failed on page %d", page.number + 1, exc_info=True)
            ocr_blocks, words = (), ()
        log.info("OCR page %d: %d words", page.number + 1, len(words))
        return Page(
            number=page.number + 1,
            width=rect.width,
            height=rect.height,
            blocks=ocr_blocks,
            words=words,
            has_images=True,
        )
    return Page(number=page.number + 1, width=rect.width, height=rect.height, blocks=tuple(blocks))


def _make_line(raw_line: dict[str, Any]) -> TextLine | None:
    raw_spans = raw_line.get("spans", [])
    text = "".join(span.get("text", "") for span in raw_spans)
    if not text.strip():
        return None
    font_size = max((float(span.get("size", 0.0)) for span in raw_spans), default=0.0)
    # The baseline of the line's main (largest) text, to spot raised spans.
    main = max(raw_spans, key=lambda span: float(span.get("size", 0.0)))
    baseline = float(main.get("origin", (0.0, 0.0))[1])
    spans = tuple(
        TextSpan(
            text=span.get("text", ""),
            font_size=float(span.get("size", 0.0)),
            superscript=_is_superscript(span, font_size, baseline),
        )
        for span in raw_spans
    )
    return TextLine(text=text, bbox=_bbox(raw_line["bbox"]), font_size=font_size, spans=spans)


def _is_superscript(span: dict[str, Any], line_size: float, baseline: float) -> bool:
    """Return whether a span is superscript: flagged by MuPDF, or small and raised."""
    if int(span.get("flags", 0)) & pymupdf.TEXT_FONT_SUPERSCRIPT:
        return True
    size = float(span.get("size", 0.0))
    origin_y = float(span.get("origin", (0.0, baseline))[1])
    return size <= 0.8 * line_size and origin_y < baseline - 0.15 * line_size


def _bbox(values: Any) -> BBox:
    x0, y0, x1, y1 = (float(v) for v in values)
    return (x0, y0, x1, y1)
