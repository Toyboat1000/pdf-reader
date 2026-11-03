"""Text recognition (OCR) for scanned pages, using the OCR engine built into Windows.

Windows 10 and 11 include an offline OCR engine with word-level positions, so no model
download is needed. It recognizes the languages installed in Windows (English is
almost always present). Pages are rendered at :data:`OCR_DPI` and the results are
converted back to PDF points, so they line up with the page.
"""

import asyncio
import logging
import os
import statistics
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import pymupdf

from pdf_reader.pdf.formats import open_paged
from pdf_reader.pdf.models import BBox, OcrWord, TextBlock, TextLine

log = logging.getLogger(__name__)

OCR_DPI = 200
"""Rendering resolution for recognition; 200 dpi reads normal print reliably."""

_engine: Any = None
_engine_lock = threading.Lock()
_engine_checked = False


def _get_engine() -> Any:
    """Create the Windows OCR engine once; return None if it is unavailable."""
    global _engine, _engine_checked
    with _engine_lock:
        if not _engine_checked:
            _engine_checked = True
            try:
                from winrt.windows.media.ocr import OcrEngine

                _engine = OcrEngine.try_create_from_user_profile_languages()
            except Exception:
                log.warning("Windows OCR is not available", exc_info=True)
                _engine = None
            if _engine is not None:
                log.info("Windows OCR ready (%s)", _engine.recognizer_language.language_tag)
        return _engine


def ocr_available() -> bool:
    """Return whether scanned pages can be recognized on this computer."""
    return _get_engine() is not None


type RawLine = list[tuple[str, BBox]]
"""One recognized line: its words with positions in PDF points."""

_local = threading.local()


def recognize_pages(
    pdf_bytes: bytes,
    page_numbers: list[int],
    progress: Callable[[int, int], None] | None = None,
    workers: int | None = None,
    filetype: str = "pdf",
) -> dict[int, list[RawLine]]:
    """Recognize several pages in parallel.

    Each worker thread keeps its own copy of the document and its own OCR engine, so
    pages are rendered and recognized at the same time on several cores.

    Args:
        pdf_bytes: The PDF file's contents.
        page_numbers: 1-based pages to recognize.
        progress: Called with ``(pages_done, pages_total)`` as pages finish.
        workers: Thread count; defaults to the number of CPUs (at most 6).
        filetype: The document's PyMuPDF file type (see :mod:`pdf_reader.pdf.formats`).

    Returns:
        The recognized lines of each page. Pages that fail are returned empty.
    """
    if not page_numbers or _get_engine() is None:
        return {}
    workers = workers or max(1, min(6, os.cpu_count() or 2))
    results: dict[int, list[RawLine]] = {}
    done = 0
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ocr") as pool:
        futures = {pool.submit(_recognize_one, pdf_bytes, n, filetype): n for n in page_numbers}
        for future in as_completed(futures):
            number = futures[future]
            try:
                results[number] = future.result()
            except Exception:
                log.warning("OCR failed on page %d", number, exc_info=True)
                results[number] = []
            done += 1
            if progress is not None:
                progress(done, len(page_numbers))
    return results


def _recognize_one(pdf_bytes: bytes, page_number: int, filetype: str = "pdf") -> list[RawLine]:
    """Render and recognize one page with this thread's document and engine."""
    from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage.streams import DataWriter

    if getattr(_local, "pdf", None) is None:
        _local.pdf = open_paged(data=pdf_bytes, filetype=filetype)
        _local.engine = OcrEngine.try_create_from_user_profile_languages()
    page = _local.pdf[page_number - 1]
    zoom = OCR_DPI / 72
    max_side = OcrEngine.max_image_dimension  # A static property in WinRT.
    zoom = min(zoom, max_side / max(page.rect.width, page.rect.height, 1))
    # Grayscale: a quarter of the data of colour, and just as good for reading text.
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csGRAY)
    writer = DataWriter()
    samples = bytes(pix.samples)
    if pix.stride != pix.width:  # Gray8 bitmaps need tightly packed rows.
        samples = b"".join(
            samples[row * pix.stride : row * pix.stride + pix.width] for row in range(pix.height)
        )
    writer.write_bytes(samples)
    bitmap = SoftwareBitmap.create_copy_from_buffer(
        writer.detach_buffer(), BitmapPixelFormat.GRAY8, pix.width, pix.height
    )
    engine = _local.engine

    async def run() -> Any:
        return await engine.recognize_async(bitmap)

    result = asyncio.run(run())
    lines: list[RawLine] = []
    for line in result.lines:
        words = []
        for word in line.words:
            r = word.bounding_rect
            words.append(
                (
                    word.text,
                    (r.x / zoom, r.y / zoom, (r.x + r.width) / zoom, (r.y + r.height) / zoom),
                )
            )
        if words:
            lines.append(words)
    return lines


def build_page_text(lines: list[RawLine]) -> tuple[tuple[TextBlock, ...], tuple[OcrWord, ...]]:
    """Turn recognized lines into paragraph blocks and a flat word list."""
    grouped: list[tuple[str, BBox, list[OcrWord]]] = []
    for line in lines:
        words = [OcrWord(text, (box[0], box[1], box[2], box[3])) for text, box in line]
        if words:
            grouped.append(
                (" ".join(w.text for w in words), _union([w.bbox for w in words]), words)
            )
    blocks = _group_lines(grouped)
    all_words = tuple(w for _, _, words in grouped for w in words)
    return blocks, all_words


def recognize_page(page: pymupdf.Page) -> tuple[tuple[TextBlock, ...], tuple[OcrWord, ...]]:
    """Recognize one page (convenience wrapper around :func:`recognize_pages`)."""
    data = page.parent.tobytes()
    lines = recognize_pages(data, [page.number + 1], workers=1).get(page.number + 1, [])
    return build_page_text(lines)


def _union(boxes: list[BBox]) -> BBox:
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def _group_lines(lines: list[tuple[str, BBox, list[OcrWord]]]) -> tuple[TextBlock, ...]:
    """Group recognized lines into paragraph blocks by position, not by OCR order.

    Lines are taken top to bottom; each joins the paragraph directly above it when
    they are close, aligned in the same column, and of similar size. This keeps a
    margin sidebar and the main text apart even when OCR reports their lines
    interleaved, which matters for textbooks.
    """
    heights = [b[3] - b[1] for _, b, _ in lines]
    typical = statistics.median(heights) if heights else 10.0
    paragraphs: list[list[TextLine]] = []
    for text, box, _words in sorted(lines, key=lambda line: (line[1][1], line[1][0])):
        height = box[3] - box[1]
        # Word boxes are about one font size tall; this keeps sizes comparable.
        line = TextLine(text=text, bbox=box, font_size=round(height, 1))
        best: list[TextLine] | None = None
        best_gap = float("inf")
        for paragraph in paragraphs:
            prev = paragraph[-1].bbox
            prev_height = prev[3] - prev[1]
            gap = box[1] - prev[3]
            size_change = max(height, prev_height) / max(min(height, prev_height), 0.1)
            overlap = min(box[2], prev[2]) - max(box[0], prev[0])
            narrower = max(min(box[2] - box[0], prev[2] - prev[0]), 1.0)
            aligned = overlap >= 0.5 * narrower or (
                overlap > 0 and abs(box[0] - prev[0]) <= 1.5 * max(prev_height, typical)
            )
            if (
                -0.5 * prev_height <= gap <= 0.8 * max(prev_height, typical)
                and aligned
                # Heading versus body. Line heights vary with ascenders and
                # descenders, so only a large change counts.
                and size_change <= 1.6
                and gap < best_gap
            ):
                best, best_gap = paragraph, gap
        if best is None:
            paragraphs.append([line])
        else:
            best.append(line)
    blocks = [TextBlock(tuple(p), _union([ln.bbox for ln in p])) for p in paragraphs]
    return tuple(sorted(blocks, key=lambda b: (b.bbox[1], b.bbox[0])))
