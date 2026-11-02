from pathlib import Path

import pytest

from pdf_reader.core.document import ReadingDocument, text_title
from pdf_reader.pdf.models import Document, Page
from pdf_reader.text.segment import Segment


@pytest.mark.parametrize(
    ("text", "title"),
    [
        ("Short title\nBody", "Short title"),
        ("\n\n   Spaced    out   \n", "Spaced out"),
        ("", "Untitled text"),
        (
            "A very long first line that goes on well past the fifty character limit",
            "A very long first line that goes on well past the\u2026",
        ),
        ("x" * 80, "x" * 50 + "\u2026"),
    ],
)
def test_text_title(text: str, title: str) -> None:
    assert text_title(text) == title


def test_text_document() -> None:
    sentences = (Segment("One.", 1, 0), Segment("Two.", 1, 1))
    doc = ReadingDocument.from_text("One.\n\nTwo.", sentences)
    assert doc.title == "One."
    assert doc.display_name == "One."
    assert not doc.is_paginated
    assert doc.page_count == 1
    assert doc.text == "One.\n\nTwo."
    assert doc.path is None


def test_pdf_document() -> None:
    pdf = Document(
        path=Path("C:/docs/paper.pdf"),
        title="A Paper",
        pages=tuple(Page(n, 595, 842, ()) for n in (1, 2, 3)),
    )
    sentences = (Segment("One.", 1, 0), Segment("Three.", 3, 1))
    doc = ReadingDocument.from_pdf(pdf, sentences)
    assert doc.is_paginated
    assert doc.display_name == "paper.pdf"
    assert doc.page_count == 3
    assert doc.page_of(1) == 3
    assert doc.first_sentence_on_or_after_page(2) == 1
    assert doc.first_sentence_on_or_after_page(4) is None
