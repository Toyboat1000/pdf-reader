"""Textbook reading order, parentheses option, word positions for text PDFs, copy."""

from pathlib import Path

import pytest

from pdf_reader.core.word_map import WordBox, build_word_map
from pdf_reader.pdf import load_pdf
from pdf_reader.pdf.ocr import ocr_available
from pdf_reader.text import Segment, TextPipeline
from pdf_reader.text.pipeline import build_pipeline
from pdf_reader.text.steps import remove_parentheticals
from pdf_reader.ui.page_view import words_to_text
from scripts.make_sample_pdf import build_layout_sample, build_textbook_sample

EXPECTED_TEXTBOOK = [
    "2.1 How Ecosystems Work",
    "An ecosystem is a community of living things together with the place where they live.",
]


def spoken(path: Path, **options: bool) -> list[str]:
    return [s.text for s in build_pipeline(**options).process_document(load_pdf(path))]


def assert_main_flow_only(texts: list[str]) -> None:
    assert texts[:2] == EXPECTED_TEXTBOOK
    joined = " ".join(texts)
    for aside in ("KEY TERMS", "Producer:", "Grass", "Rabbit", "Fox", "Figure 2.1", "Chapter 2"):
        assert aside not in joined
    assert (
        "At each step along the food chain, most of the energy is used up, which is why "
        "there are far fewer predators than plants in any healthy habitat."
    ) in texts
    assert texts[-1] == "Thank you for reading this textbook sample to the end."


def test_textbook_pdf_reads_main_flow_only(tmp_path: Path) -> None:
    path = tmp_path / "textbook.pdf"
    build_textbook_sample(path, scanned=False)
    assert_main_flow_only(spoken(path))


@pytest.mark.skipif(not ocr_available(), reason="Windows OCR is not available")
def test_scanned_textbook_reads_main_flow_only(tmp_path: Path) -> None:
    path = tmp_path / "textbook.pdf"
    build_textbook_sample(path, scanned=True)
    assert_main_flow_only(spoken(path))


def test_asides_can_be_kept(tmp_path: Path) -> None:
    path = tmp_path / "textbook.pdf"
    build_textbook_sample(path, scanned=False)
    joined = " ".join(spoken(path, skip_asides=False))
    assert "KEY TERMS" in joined
    assert "Figure 2.1" in joined


def test_short_second_column_is_not_a_sidebar(tmp_path: Path) -> None:
    path = tmp_path / "layout.pdf"
    build_layout_sample(path)
    assert spoken(path)[-1] == "The right column of the last page is short."


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Plants (and some algae) make food (see Fig. 2).", "Plants make food."),
        ("Nested (outer (inner) text) gone.", "Nested gone."),
        ("(Leading aside) Start here.", "Start here."),
        ("An unbalanced ( bracket stays.", "An unbalanced ( bracket stays."),
    ],
)
def test_remove_parentheticals(text: str, expected: str) -> None:
    assert remove_parentheticals([Segment(text, 1, 0)])[0].text == expected


def test_parentheses_option_in_pipeline() -> None:
    segment = Segment("Water (H2O) is wet.", 1, 0)
    assert [s.text for s in TextPipeline().run([segment])] == ["Water (H2O) is wet."]
    reading = build_pipeline(read_parentheses=False).run([segment])
    assert [s.text for s in reading] == ["Water is wet."]


def test_text_pdfs_get_word_positions_in_reading_order(tmp_path: Path) -> None:
    path = tmp_path / "layout.pdf"
    build_layout_sample(path)
    document = load_pdf(path)
    assert document.has_words and not document.is_scanned
    sentences = TextPipeline().process_document(document)
    word_map = build_word_map(document, sentences)
    assert word_map is not None
    for i, sentence in enumerate(sentences):
        assert len(word_map.sentence_boxes(i)) >= 0.8 * len(sentence.text.split())


def test_words_to_text_keeps_lines_and_pages() -> None:
    words = [
        WordBox(1, (0, 0, 10, 10), 0, True, "Hello"),
        WordBox(1, (12, 0, 30, 10), 0, True, "world"),
        WordBox(1, (0, 20, 10, 30), 0, True, "next"),
        WordBox(2, (0, 0, 10, 10), 1, True, "page"),
    ]
    assert words_to_text(words) == "Hello world\nnext\n\npage"
