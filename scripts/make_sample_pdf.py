"""Generate sample PDFs for trying out and manually testing the app.

Usage::

    uv run python scripts/make_sample_pdf.py [output.pdf]            # simple sample
    uv run python scripts/make_sample_pdf.py --layout [output.pdf]   # layout sample
    uv run python scripts/make_sample_pdf.py --scanned [output.pdf]  # scanned (OCR) sample

The simple sample exercises the text pipeline: paragraphs, abbreviations, quotes,
numbers, a word hyphenated across a line break, and a very long sentence.

The layout sample exercises layout cleanup: a running header, "Page N of 3"
footers, two columns, footnotes with superscript markers, and sentences that run
across column and page breaks (one with a word hyphenated across pages).

All text is original. The tests import these builders, so changing the text may
require updating ``tests/test_layout_sample.py``.
"""

import argparse
import re
import sys
from pathlib import Path

import pymupdf

PAGES: list[list[str]] = [
    [
        "A Short Guide to Listening",
        "Reading aloud is one of the oldest ways of sharing a text. Long before printed "
        "books were common, a single reader would often read to a whole room. Today, "
        "computers can do the same job, and they never get tired.",
        "This sample document was written to test a text-to-speech reader. It contains "
        "several pages, a few headings, and sentences of very different lengths. Dr. Lee "
        "and Mr. Patel, two fictional researchers, appear in it from time to time.",
        "Listening is different from reading. When you read, your eyes can jump back and "
        "forth; when you listen, the words arrive one after another, in order. Good "
        "narration therefore needs clear pauses at the end of each sentence.",
    ],
    [
        "Why Speed Matters",
        "Most people speak at around 150 words per minute. Many listeners, however, can "
        "follow speech at twice that rate after a little practice. That is why a speed "
        "control is useful: slow it down for difficult material, and speed it up for "
        "familiar topics.",
        "Here is a deliberately long sentence that keeps going, with commas, clauses, and "
        "asides, so that the reader has to split it into smaller pieces; it describes a "
        "walk through a quiet town at dawn, past the bakery where the first loaves are "
        "cooling, past the station where an early train waits with its doors open, and "
        "finally down to the river, where the mist is only beginning to lift.",
        '"Is this working?" asked Dr. Lee. "It seems to be," replied Mr. Patel, who had '
        "been listening carefully for any mistakes in the pronunciation of numbers such "
        "as 3.14, 1,024, and 2026.",
    ],
    [
        "Final Thoughts",
        "A good reading tool should stay out of the way. It should highlight the current "
        "sentence, let you jump to any part of the text with a single click, and remem-\n"
        "ber your preferred voice and speed the next time you open it.",
        "Thank you for listening to this sample. If you can hear this final sentence "
        "clearly, the reader has made it all the way to the end of the document.",
    ],
]


def build(output: Path) -> None:
    """Write the simple sample document to ``output``."""
    doc = pymupdf.open()
    for page_number, paragraphs in enumerate(PAGES, start=1):
        page = doc.new_page(width=595, height=842)  # A4 in points.
        y = 72.0
        for i, paragraph in enumerate(paragraphs):
            heading = i == 0
            size = 18 if heading else 11.5
            rect = pymupdf.Rect(72, y, 523, 770)
            # insert_textbox returns the unused height (negative if the text overflowed).
            spare = page.insert_textbox(
                rect, paragraph, fontsize=size, fontname="helv", lineheight=1.35
            )
            if spare < 0:
                raise RuntimeError(f"Paragraph {i} on page {page_number} does not fit")
            used = rect.height - spare
            y += used + (14 if heading else 10)
        page.insert_text((290, 810), str(page_number), fontsize=9, fontname="helv")
    doc.set_metadata({"title": "A Short Guide to Listening"})
    doc.save(output)
    doc.close()


# ------------------------------------------------------------------- layout sample

LAYOUT_TITLE = "On Reading Aloud: A Two-Column Example"
LAYOUT_HEADER = "Journal of Listening Studies \u2014 Volume 3"

# Each page: (left column paragraphs, right column paragraphs, footnotes).
# "^N" marks a superscript footnote reference.
LAYOUT_PAGES: list[tuple[list[str], list[str], list[str]]] = [
    (
        [
            "Most academic papers are printed in two columns. A reader that simply goes "
            "from the top of the page to the bottom would jump back and forth between "
            "them, mixing up the sentences^1.",
            "To read such a page correctly, the program first finds the gap between the "
            "columns and then reads each column from top to bottom, so that the listener",
        ],
        [
            "can follow the argument without confusion. This sentence started at the "
            "bottom of the left column.",
            "Footnotes are another challenge^2. They are printed in small type at the "
            "bottom of the page, and most listeners prefer to skip them. This paragraph "
            "ends with a word that is split across the page, an exam-",
        ],
        [
            "1 Mixing sentences from two columns makes the text impossible to follow.",
            "2 Footnotes often contain references, which are tedious to hear.",
        ],
    ),
    (
        [
            "ple of hyphenation that the reader repairs. The rest of this column is "
            "ordinary text, written to fill the space with a few more sentences.",
            "Running headers repeat the same words at the top of every page. Page "
            "numbers appear at the bottom. Neither belongs in the spoken text.",
        ],
        [
            "A careful reader also keeps the order of paragraphs within each column^3. "
            "When a sentence runs from the bottom of one page onto the next, the reader "
            "joins the two halves so that it is spoken as one sentence, as the reader moves",
        ],
        ["3 Paragraph order matters as much as sentence order."],
    ),
    (
        [
            "from one page to the next. This is the end of the sentence that began on "
            "the previous page.",
            "Thank you for listening to this two-column sample.",
        ],
        ["The right column of the last page is short."],
        [],
    ),
]

_FONT = "helv"
_PAGE_W, _PAGE_H = 595, 842
_LEFT, _RIGHT, _GUTTER = 72, 523, 21
_BODY_SIZE = 10.5
_MARKER = re.compile(r"(\^\d+)")


def _text_width(text: str, size: float) -> float:
    plain = _MARKER.sub(lambda m: m.group(1)[1:], text)
    return pymupdf.get_text_length(plain, _FONT, size)


def _wrap(text: str, width: float, size: float) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split(" "):
        candidate = f"{current} {word}".strip()
        if current and _text_width(candidate, size) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _draw_line(page: pymupdf.Page, x: float, y: float, line: str, size: float) -> None:
    """Draw a line, rendering "^N" as a small raised footnote reference."""
    for piece in _MARKER.split(line):
        if not piece:
            continue
        if piece.startswith("^"):
            small = size * 0.65
            page.insert_text((x, y - size * 0.35), piece[1:], fontsize=small, fontname=_FONT)
            x += pymupdf.get_text_length(piece[1:], _FONT, small)
        else:
            page.insert_text((x, y), piece, fontsize=size, fontname=_FONT)
            x += pymupdf.get_text_length(piece, _FONT, size)


def _draw_paragraphs(
    page: pymupdf.Page, x: float, y: float, width: float, paragraphs: list[str], size: float
) -> float:
    """Draw paragraphs top-down starting at baseline ``y``; return the next free y."""
    line_height = size * 1.35
    for paragraph in paragraphs:
        for line in _wrap(paragraph, width, size):
            _draw_line(page, x, y, line, size)
            y += line_height
        y += size  # Paragraph gap, so each paragraph becomes its own text block.
    return y


def build_layout_sample(output: Path) -> None:
    """Write the layout sample (headers, footers, columns, footnotes) to ``output``."""
    doc = pymupdf.open()
    column_width = (_RIGHT - _LEFT - _GUTTER) / 2
    for number, (left, right, footnotes) in enumerate(LAYOUT_PAGES, start=1):
        page = doc.new_page(width=_PAGE_W, height=_PAGE_H)
        page.insert_text((_LEFT, 42), LAYOUT_HEADER, fontsize=9, fontname=_FONT)
        top = 80.0
        if number == 1:
            page.insert_text((_LEFT, 92), LAYOUT_TITLE, fontsize=17, fontname=_FONT)
            top = _draw_paragraphs(
                page,
                _LEFT,
                128,
                _RIGHT - _LEFT,
                [
                    "This sample shows the layouts that a text-to-speech reader has to "
                    "handle. It has a running header, page numbers, footnotes, and two "
                    "columns of text that continue across columns and pages."
                ],
                _BODY_SIZE,
            )
        left_end = _draw_paragraphs(page, _LEFT, top + 12, column_width, left, _BODY_SIZE)
        right_x = _LEFT + column_width + _GUTTER
        right_end = _draw_paragraphs(page, right_x, top + 12, column_width, right, _BODY_SIZE)
        if footnotes:
            y = 712.0
            if max(left_end, right_end) > y - 20:
                raise RuntimeError(f"Columns on page {number} run into the footnotes")
            _draw_paragraphs(page, _LEFT, y, _RIGHT - _LEFT, footnotes, 8)
        footer = f"Page {number} of {len(LAYOUT_PAGES)}"
        page.insert_text(
            (_PAGE_W / 2 - pymupdf.get_text_length(footer, _FONT, 9) / 2, 812),
            footer,
            fontsize=9,
            fontname=_FONT,
        )
    doc.set_metadata({"title": LAYOUT_TITLE})
    doc.save(output)
    doc.close()


def build_scanned_sample(output: Path) -> None:
    """Write a scanned-looking copy of the simple sample: page images, no text layer."""
    simple = output.with_suffix(".source.pdf")
    build(simple)
    source = pymupdf.open(simple)
    scanned = pymupdf.open()
    for page in source:
        image = page.get_pixmap(dpi=150, colorspace=pymupdf.csGRAY)
        target = scanned.new_page(width=page.rect.width, height=page.rect.height)
        target.insert_image(target.rect, stream=image.tobytes("png"))
    source.close()
    simple.unlink()
    scanned.save(output)
    scanned.close()


def main() -> None:
    """Build a sample PDF at the path given on the command line."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("output", nargs="?", type=Path, help="where to write the PDF")
    parser.add_argument(
        "--layout", action="store_true", help="build the layout sample (columns, footnotes)"
    )
    parser.add_argument(
        "--scanned", action="store_true", help="build a scanned sample (page images only)"
    )
    args = parser.parse_args()
    if args.scanned:
        output = args.output or Path("scanned-sample.pdf")
        build_scanned_sample(output)
    elif args.layout:
        output = args.output or Path("layout-sample.pdf")
        build_layout_sample(output)
    else:
        output = args.output or Path("sample.pdf")
        build(output)
    sys.stdout.write(f"Wrote {output.resolve()}\n")


if __name__ == "__main__":
    main()
