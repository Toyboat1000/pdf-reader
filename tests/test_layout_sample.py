"""End-to-end layout cleanup on the generated two-column sample PDF."""

from pathlib import Path

import pytest

from pdf_reader.pdf import load_pdf
from pdf_reader.text import Segment, TextPipeline
from scripts.make_sample_pdf import LAYOUT_HEADER, build, build_layout_sample


@pytest.fixture(scope="module")
def spoken(tmp_path_factory: pytest.TempPathFactory) -> list[Segment]:
    path = tmp_path_factory.mktemp("layout") / "layout.pdf"
    build_layout_sample(path)
    return TextPipeline().process_document(load_pdf(path))


def all_text(segments: list[Segment]) -> str:
    return " ".join(s.text for s in segments)


def test_header_footer_and_page_numbers_removed(spoken: list[Segment]) -> None:
    text = all_text(spoken)
    assert "Journal of Listening Studies" not in text
    assert LAYOUT_HEADER not in text
    assert "Page 1 of 3" not in text
    assert "of 3" not in text


def test_footnotes_and_markers_removed(spoken: list[Segment]) -> None:
    text = all_text(spoken)
    assert "Mixing sentences from two columns" not in text
    assert "tedious to hear" not in text
    assert "matters as much as sentence order" not in text
    assert "mixing up the sentences." in text
    assert "challenge." in text
    assert "within each column." in text
    assert "sentences1" not in text
    assert "challenge2" not in text


def test_columns_and_continued_sentences(spoken: list[Segment]) -> None:
    texts = [s.text for s in spoken]
    assert texts[:4] == [
        "On Reading Aloud: A Two-Column Example",
        "This sample shows the layouts that a text-to-speech reader has to handle.",
        "It has a running header, page numbers, footnotes, and two columns of text that "
        "continue across columns and pages.",
        "Most academic papers are printed in two columns.",
    ]
    assert (
        "To read such a page correctly, the program first finds the gap between the "
        "columns and then reads each column from top to bottom, so that the listener can "
        "follow the argument without confusion."
    ) in texts
    assert (
        "This paragraph ends with a word that is split across the page, an example of "
        "hyphenation that the reader repairs."
    ) in texts
    assert texts[-3:] == [
        "This is the end of the sentence that began on the previous page.",
        "Thank you for listening to this two-column sample.",
        "The right column of the last page is short.",
    ]


def test_sentences_keep_their_own_page(spoken: list[Segment]) -> None:
    pages = {s.text: s.page for s in spoken}
    assert pages["This sentence started at the bottom of the left column."] == 1
    assert (
        pages[
            "The rest of this column is ordinary text, written to fill the space "
            "with a few more sentences."
        ]
        == 2
    )
    assert pages["This is the end of the sentence that began on the previous page."] == 3


def test_simple_sample_loses_only_page_numbers(tmp_path: Path) -> None:
    path = tmp_path / "simple.pdf"
    build(path)
    texts = [s.text for s in TextPipeline().process_document(load_pdf(path))]
    assert texts[0] == "A Short Guide to Listening"
    assert texts[-1].startswith("If you can hear this final sentence clearly")
    assert not any(t in {"1", "2", "3"} for t in texts)
    assert len(texts) == 23
