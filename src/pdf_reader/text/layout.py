"""Layout-aware cleanup steps that use page positions and fonts.

They remove page numbers, running headers and footers, and footnotes; put
multi-column pages in reading order; and join paragraphs that continue across
blocks or pages. These steps use the page position, font size, and span information that the PDF
loader keeps on each :class:`Segment`. Segments without that information (for
example, pasted text) are passed through untouched. Every step errs on the side of
keeping text: reading a stray page number is better than skipping a real sentence.
They run first in the pipeline, while each segment still holds exactly one PDF text
block.
"""

import logging
import re
from collections import Counter, defaultdict
from dataclasses import replace
from itertools import groupby, pairwise

from pdf_reader.pdf.models import BBox
from pdf_reader.text.segment import Segment
from pdf_reader.text.sentences import first_sentence_end

log = logging.getLogger(__name__)

MARGIN_FRACTION = 0.12
"""Top and bottom share of the page height where headers, footers, and page numbers
are looked for."""

FOOTNOTE_ZONE_FRACTION = 0.45
"""Footnotes are only looked for in this bottom share of the page."""

SMALL_FONT_RATIO = 0.92
"""Text smaller than this fraction of the body font size counts as small print."""

WIDE_BLOCK_RATIO = 0.55
"""Blocks wider than this fraction of the page's text width span all columns."""

MIN_GUTTER = 10.0
"""Narrowest horizontal gap (points) between two columns."""

# ------------------------------------------------------------------ helpers


def _band(segment: Segment) -> str | None:
    """Return "top" or "bottom" if the segment lies within a page margin band."""
    if segment.bbox is None or segment.page_size is None:
        return None
    height = segment.page_size[1]
    _, y0, _, y1 = segment.bbox
    if y1 <= height * MARGIN_FRACTION:
        return "top"
    if y0 >= height * (1 - MARGIN_FRACTION):
        return "bottom"
    return None


def _box(segment: Segment) -> BBox:
    """Return the bounding box of a segment already known to have one."""
    if segment.bbox is None:
        raise ValueError("segment has no bounding box")
    return segment.bbox


def _font_size(segment: Segment) -> float | None:
    if segment.source is None or not segment.source.lines:
        return None
    return max(line.font_size for line in segment.source.lines)


def body_font_size(segments: list[Segment]) -> float | None:
    """Return the most common font size, weighted by amount of text, if known."""
    sizes: Counter[float] = Counter()
    for segment in segments:
        if segment.source is None:
            continue
        for line in segment.source.lines:
            sizes[round(line.font_size * 2) / 2] += len(line.text.strip())
    return sizes.most_common(1)[0][0] if sizes else None


def _log_removed(step: str, before: int, after: int) -> None:
    if before != after:
        log.info("%s removed %d block(s)", step, before - after)


# ------------------------------------------------------------- page numbers

_ROMAN = r"(?=[ivxlcdm]+$)m{0,3}(?:cm|cd|d?c{0,3})(?:xc|xl|l?x{0,3})(?:ix|iv|v?i{0,3})"
_PAGE_NUMBER = re.compile(
    rf"^(?:page\s+)?(?:\d{{1,4}}|{_ROMAN})(?:\s*(?:of|/)\s*\d{{1,4}})?$", re.IGNORECASE
)
_DASHED_NUMBER = re.compile(r"^[-\u2013\u2014]\s*\d{1,4}\s*[-\u2013\u2014]$")


def is_page_number(text: str) -> bool:
    """Return whether ``text`` looks like a page number ("12", "- 4 -", "Page 3 of 9", "iv")."""
    compact = " ".join(text.split())
    return bool(compact) and bool(_PAGE_NUMBER.match(compact) or _DASHED_NUMBER.match(compact))


def remove_page_numbers(segments: list[Segment]) -> list[Segment]:
    """Remove blocks in the top or bottom margin that contain only a page number."""
    kept = [s for s in segments if not (_band(s) and is_page_number(s.text))]
    _log_removed("remove_page_numbers", len(segments), len(kept))
    return kept


# ------------------------------------------------- running headers and footers


def _signature(text: str) -> str:
    """Normalize text so headers that differ only in numbers compare equal."""
    return re.sub(r"\d+", "#", " ".join(text.lower().split()))


def remove_running_headers_footers(segments: list[Segment]) -> list[Segment]:
    """Remove margin blocks whose text repeats on several pages.

    A block in the top or bottom margin is a running header or footer when the same
    text (ignoring numbers) appears in the same margin on at least 3 pages, or 2
    pages for documents of up to 4 pages.
    """
    pages = {s.page for s in segments}
    threshold = 2 if len(pages) <= 4 else 3
    seen: defaultdict[tuple[str, str], set[int]] = defaultdict(set)
    for segment in segments:
        if band := _band(segment):
            seen[(band, _signature(segment.text))].add(segment.page)
    repeated = {key for key, on_pages in seen.items() if len(on_pages) >= threshold}
    kept = [
        s for s in segments if not ((band := _band(s)) and (band, _signature(s.text)) in repeated)
    ]
    _log_removed("remove_running_headers_footers", len(segments), len(kept))
    return kept


# ---------------------------------------------------------------- footnotes

_FOOTNOTE_START = re.compile(
    r"^\s*(?:[\d\u00b9\u00b2\u00b3\u2070-\u2079]{1,3}|[*\u2020\u2021\u00a7\u00b6]{1,3})"
    r"[.)]?\s*[\"'\u201c(]?[A-Za-z]"
)


def remove_footnotes(segments: list[Segment]) -> list[Segment]:
    """Remove footnote text at the bottom of pages.

    A footnote starts with a marker ("1", "*", "\u2020", ...), is in small print
    compared with the body text, and sits in the lower part of the page. Everything
    in small print below the first footnote on a page (continuation lines, further
    footnotes) is removed too.
    """
    body = body_font_size(segments)
    if body is None:
        return segments

    def small(segment: Segment) -> bool:
        size = _font_size(segment)
        return size is not None and size < body * SMALL_FONT_RATIO

    footnote_top: dict[int, float] = {}
    for segment in segments:
        if segment.bbox is None or segment.page_size is None or not small(segment):
            continue
        in_zone = segment.bbox[1] >= segment.page_size[1] * (1 - FOOTNOTE_ZONE_FRACTION)
        if in_zone and _FOOTNOTE_START.match(segment.text):
            top = footnote_top.get(segment.page)
            footnote_top[segment.page] = (
                segment.bbox[1] if top is None else min(top, segment.bbox[1])
            )

    def is_footnote(segment: Segment) -> bool:
        top = footnote_top.get(segment.page)
        return (
            top is not None
            and segment.bbox is not None
            and segment.bbox[1] >= top - 1
            and small(segment)
        )

    kept = [s for s in segments if not is_footnote(s)]
    _log_removed("remove_footnotes", len(segments), len(kept))
    return kept


# Superscript text that is only a footnote reference: "1", "12", "3,4", "*", "†".
_MARKER_TEXT = re.compile(r"^[\s\d,*\u2020\u2021\u00a7\u00b6\u2013-]*[\d*\u2020\u2021\u00a7\u00b6]")
# A marker follows a word of 3+ letters or closing punctuation. "x²" and "mc²"
# (maths) are left alone.
_AFTER_WORD = re.compile(r"(?:[A-Za-z]{3}|[.,;:)\]\"'\u201d\u2019])$")


def remove_footnote_markers(segments: list[Segment]) -> list[Segment]:
    """Drop superscript footnote references ("word\u00b9") from the text."""
    result: list[Segment] = []
    removed = 0
    for segment in segments:
        if segment.source is None:
            result.append(segment)
            continue
        lines: list[str] = []
        changed = False
        for line in segment.source.lines:
            if not line.spans:
                lines.append(line.text)
                continue
            text = ""
            for span in line.spans:
                if (
                    span.superscript
                    and _MARKER_TEXT.match(span.text)
                    and _AFTER_WORD.search(text.rstrip())
                    and text.rstrip() == text  # Attached to the word, not after a space.
                ):
                    changed = True
                    removed += 1
                    continue
                text += span.text
            lines.append(text)
        result.append(replace(segment, text="\n".join(lines)) if changed else segment)
    if removed:
        log.info("remove_footnote_markers removed %d marker(s)", removed)
    return result


# ------------------------------------------------- sidebars, captions, labels

_CAPTION = re.compile(
    r"^\s*(?:figure|fig\.?|table|chart|graph|diagram|exhibit|map|photo(?:graph)?|image|"
    r"illustration|plate|box|source|credit)\s*[\dIVXivx]*(?:[.\-\u2013]\d+)*\s*[:.|\u2014\u2013-]",
    re.IGNORECASE,
)
_MIN_MAIN_CHARS = 60  # A block must be at least this long to define the main column.


def _chars(segment: Segment) -> int:
    return len(segment.text.strip())


def _lines(segment: Segment) -> int:
    return len(segment.source.lines) if segment.source is not None else 1


def is_caption(segment: Segment, body: float) -> bool:
    """Return whether a block looks like a figure or table caption ("Figure 2.1: ...")."""
    if not _CAPTION.match(segment.text):
        return False
    size = _font_size(segment)
    return _lines(segment) <= 4 or (size is not None and size < body * SMALL_FONT_RATIO)


def remove_asides(segments: list[Segment]) -> list[Segment]:
    """Keep the main reading flow; skip sidebars, margin boxes, captions, and labels.

    For each page, the main text column(s) are the columns holding most of the
    body-size text. Blocks lying mostly outside them (margin sidebars, pull quotes,
    "Key terms" boxes) are skipped, as are figure and table captions and short
    small-print fragments inside the main area (labels inside diagrams and charts).
    Headings and body text in the main column are always kept.
    """
    body = body_font_size(segments)
    if body is None:
        return segments
    result: list[Segment] = []
    for _, group in groupby(segments, key=lambda s: s.page):
        result.extend(_main_flow(list(group), body))
    _log_removed("remove_asides", len(segments), len(result))
    return result


def _main_flow(page: list[Segment], body: float) -> list[Segment]:
    laid_out = [s for s in page if s.bbox is not None and s.source is not None]
    body_blocks = [
        s
        for s in laid_out
        if (size := _font_size(s)) is not None
        and 0.8 * body <= size <= 1.25 * body
        and _chars(s) >= _MIN_MAIN_CHARS
    ]
    # Group body blocks into columns by horizontal overlap; weigh them by text.
    columns: list[list[float]] = []  # [x0, x1, chars]
    for segment in sorted(body_blocks, key=lambda s: _box(s)[0]):
        x0, _, x1, _ = _box(segment)
        if columns and x0 < columns[-1][1] + MIN_GUTTER:
            columns[-1][1] = max(columns[-1][1], x1)
            columns[-1][2] += _chars(segment)
        else:
            columns.append([x0, x1, float(_chars(segment))])
    heaviest = max((c[2] for c in columns), default=0.0)
    main = [(c[0], c[1]) for c in columns if c[2] >= 0.3 * heaviest]
    main_width = max((m1 - m0 for m0, m1 in main), default=0.0)

    def in_main(segment: Segment) -> bool:
        x0, _, x1, _ = _box(segment)
        width = max(x1 - x0, 1.0)
        covered = sum(max(0.0, min(x1, m1) - max(x0, m0)) for m0, m1 in main)
        return covered >= 0.5 * width

    kept = []
    for segment in page:
        if segment.bbox is None or segment.source is None:
            kept.append(segment)
            continue
        size = _font_size(segment) or body
        if is_caption(segment, body):
            continue
        if main and not in_main(segment):
            # Outside the main text. It is a sidebar or margin box if it is also set
            # in smaller print or is much narrower; otherwise (say, a short second
            # column) it is kept.
            x0, _, x1, _ = _box(segment)
            if size < body * SMALL_FONT_RATIO or (x1 - x0) < 0.6 * main_width:
                continue
        if size < 0.85 * body and len(segment.text.split()) < 6:
            continue  # A label inside a figure, chart, or diagram.
        kept.append(segment)
    return kept


# ----------------------------------------------------------------- columns


def order_columns(segments: list[Segment]) -> list[Segment]:
    """Put each page's blocks in reading order, handling multi-column layouts.

    Blocks wider than :data:`WIDE_BLOCK_RATIO` of the text width (titles, full-width
    paragraphs) divide the page into horizontal bands. Within a band, blocks
    separated by a vertical gutter that overlap vertically are columns, read left to
    right, each top to bottom. Pages without layout data keep their order.
    """
    result: list[Segment] = []
    for _, group in groupby(segments, key=lambda s: s.page):
        result.extend(_order_page(list(group)))
    return result


def _order_page(segments: list[Segment]) -> list[Segment]:
    if len(segments) < 3 or any(s.bbox is None for s in segments):
        return segments
    left = min(_box(s)[0] for s in segments)
    right = max(_box(s)[2] for s in segments)
    width = right - left
    if width <= 0:
        return segments

    def is_wide(segment: Segment) -> bool:
        x0, _, x1, _ = _box(segment)
        return x1 - x0 > width * WIDE_BLOCK_RATIO

    ordered: list[Segment] = []
    band: list[Segment] = []
    for segment in sorted(segments, key=lambda s: (_box(s)[1], _box(s)[0])):
        if is_wide(segment):
            ordered.extend(_order_band(band))
            band = []
            ordered.append(segment)
        else:
            band.append(segment)
    ordered.extend(_order_band(band))
    return ordered


def _order_band(band: list[Segment]) -> list[Segment]:
    """Order blocks of one band: column by column if it has columns, else top-down."""
    if len(band) < 2:
        return band
    # Group blocks into columns: x-ranges closer than MIN_GUTTER belong together.
    columns: list[list[Segment]] = []
    spans: list[list[float]] = []
    for segment in sorted(band, key=lambda s: _box(s)[0]):
        x0, _, x1, _ = _box(segment)
        if spans and x0 < spans[-1][1] + MIN_GUTTER:
            spans[-1][1] = max(spans[-1][1], x1)
            columns[-1].append(segment)
        else:
            spans.append([x0, x1])
            columns.append([segment])
    if len(columns) < 2 or not _columns_side_by_side(columns):
        return band
    log.debug("Page %d: reading %d columns", band[0].page, len(columns))
    return [s for column in columns for s in sorted(column, key=lambda s: _box(s)[1])]


def _columns_side_by_side(columns: list[list[Segment]]) -> bool:
    """Return whether neighbouring column groups overlap vertically (real columns).

    A narrow title above a narrow author line doesn't overlap vertically, so it is
    not mistaken for two columns.
    """
    ranges = [(min(_box(s)[1] for s in col), max(_box(s)[3] for s in col)) for col in columns]
    for (a0, a1), (b0, b1) in pairwise(ranges):
        overlap = min(a1, b1) - max(a0, b0)
        shorter = min(a1 - a0, b1 - b0)
        if shorter <= 0 or overlap < 0.3 * shorter:
            return False
    return True


# ------------------------------------------------- continued paragraphs

_ENDS_SENTENCE = re.compile(r"[.!?:\u2026][\"'\u201d\u2019)\]]*$")
_STARTS_LOWERCASE = re.compile(r"^[\"'\u201c\u2018(]?[a-z]")


def join_continued_blocks(segments: list[Segment]) -> list[Segment]:
    """Finish a sentence that runs from one block into the next.

    This happens at page breaks and column breaks: the previous block ends without
    sentence-ending punctuation (or with a hyphen) and the next one starts with a
    lowercase letter. The next block's text up to the end of its first sentence is
    moved onto the previous block, joined with a line break so the later hyphenation
    step can rejoin a word split across the break. The rest of the next block stays
    where it is, so its sentences keep their own page.
    """
    result: list[Segment] = []
    joined = 0
    for segment in segments:
        if not (result and _continues(result[-1].text, segment.text)):
            result.append(segment)
            continue
        end = first_sentence_end(segment.text)
        head, tail = (segment.text, "") if end is None else (segment.text[:end], segment.text[end:])
        previous = result[-1]
        result[-1] = replace(
            previous,
            text=f"{previous.text.rstrip()}\n{head.strip()}",
            source=None,  # The text now spans more than one PDF block.
        )
        if tail.strip():
            result.append(replace(segment, text=tail.strip(), source=None))
        joined += 1
    if joined:
        log.info("join_continued_blocks joined %d block(s)", joined)
    return result


def _continues(previous: str, following: str) -> bool:
    previous = previous.rstrip()
    return (
        bool(previous)
        and not _ENDS_SENTENCE.search(previous)
        and bool(_STARTS_LOWERCASE.match(following.lstrip()))
    )
