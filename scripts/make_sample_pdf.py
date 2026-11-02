"""Generate a multi-page sample PDF for trying out and manually testing the app.

Usage::

    uv run python scripts/make_sample_pdf.py [output.pdf]

The text is original and exercises the text pipeline: paragraphs, abbreviations,
quotes, numbers, a word hyphenated across a line break, and a very long sentence.
"""

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
    """Write the sample document to ``output``."""
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


def main() -> None:
    """Build the sample PDF at the path given on the command line."""
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("sample.pdf")
    build(output)
    sys.stdout.write(f"Wrote {output.resolve()}\n")


if __name__ == "__main__":
    main()
