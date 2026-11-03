"""Scanned PDFs: word-to-sentence mapping, OCR loading, and the clickable page view."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt
from pytestqt.qtbot import QtBot

from pdf_reader.core.word_map import build_word_map
from pdf_reader.pdf import load_pdf
from pdf_reader.pdf.models import Document, OcrWord, Page
from pdf_reader.pdf.ocr import ocr_available
from pdf_reader.text import Segment, TextPipeline
from pdf_reader.ui.main_window import MainWindow
from scripts.make_sample_pdf import build_scanned_sample
from tests.test_ui import make_window


def ocr_page(number: int, words: list[str]) -> Page:
    boxes = tuple(OcrWord(w, (10.0 * i, 0.0, 10.0 * i + 8, 10.0)) for i, w in enumerate(words))
    return Page(number, 100, 100, (), words=boxes)


def test_word_map_aligns_sentences_and_skips_removed_words() -> None:
    document = Document(
        Path("x.pdf"), "x", (ocr_page(1, ["Hello", "world.", "Good-", "bye", "now.", "12"]),)
    )
    sentences = [Segment("Hello world.", 1, 0), Segment("Goodbye now.", 1, 1)]
    word_map = build_word_map(document, sentences)
    assert word_map is not None
    assert [w.sentence for w in word_map.by_page[1]] == [0, 0, 1, 1, 1, 1]
    # The page number ("12") is clickable but not part of the highlight.
    assert [w.spoken for w in word_map.by_page[1]][-1] is False
    assert len(word_map.sentence_boxes(1)) == 3  # "Good-", "bye", "now."
    assert word_map.sentence_at(1, 41, 5) == 1  # On "bye".
    assert word_map.sentence_at(1, 5, 50) == 0  # Below "Hello": nearest word.
    assert word_map.sentence_at(2, 0, 0) is None


def test_no_word_map_for_text_pdfs() -> None:
    document = Document(Path("x.pdf"), "x", (Page(1, 100, 100, ()),))
    assert build_word_map(document, []) is None


needs_ocr = pytest.mark.skipif(not ocr_available(), reason="Windows OCR is not available")


@pytest.fixture(scope="module")
def scanned_pdf(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("scan") / "scanned.pdf"
    build_scanned_sample(path)
    return path


@needs_ocr
def test_scanned_pdf_is_read_with_ocr(scanned_pdf: Path) -> None:
    progress: list[tuple[int, int]] = []
    document = load_pdf(scanned_pdf, progress=lambda done, total: progress.append((done, total)))
    assert document.is_scanned
    assert progress == [(0, 3), (1, 3), (2, 3)]
    texts = [s.text for s in TextPipeline().process_document(document)]
    assert texts[0] == "A Short Guide to Listening"
    assert "Reading aloud is one of the oldest ways of sharing a text." in texts
    assert not any(t in {"1", "2", "3"} for t in texts)  # Page numbers removed.
    assert texts[-1].startswith("If you can hear this final sentence clearly")


@pytest.fixture
def window(qtbot: QtBot, tmp_path: Path) -> Iterator[MainWindow]:
    win = make_window(qtbot, tmp_path)
    win.resize(900, 700)
    yield win
    win.close()


@needs_ocr
def test_page_view_shows_scans_and_clicks_start_reading(
    qtbot: QtBot, window: MainWindow, scanned_pdf: Path
) -> None:
    window.open_file(scanned_pdf)
    qtbot.waitUntil(lambda: window._document is not None, timeout=15000)
    assert window._views.currentWidget() is window._page_view
    assert window._page_images_action.isEnabled()
    assert window._page_images_action.isChecked()

    document = window._document
    assert document is not None and document.word_map is not None
    # Click the middle of the first word of sentence 2.
    target = document.word_map.sentence_boxes(2)[0]
    view = window._page_view
    rect = view._page_rect(target.page - 1)
    x0, y0, x1, y1 = target.bbox
    point = QPoint(
        int(rect.left() + (x0 + x1) / 2 * view._zoom), int(rect.top() + (y0 + y1) / 2 * view._zoom)
    )
    qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    qtbot.waitUntil(lambda: window._session.position == 2)

    window._page_images_action.trigger()  # Switch to the recognized text.
    assert window._views.currentWidget() is window._view
