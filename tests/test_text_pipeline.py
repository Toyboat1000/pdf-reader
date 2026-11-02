from pathlib import Path

from pdf_reader.pdf.models import Document, Page, TextBlock, TextLine
from pdf_reader.text import Segment, TextPipeline, default_steps, document_segments, text_step
from pdf_reader.text.pipeline import text_segments
from pdf_reader.text.steps import (
    drop_unspeakable,
    fix_hyphenated_line_breaks,
    normalize_unicode,
    normalize_whitespace,
    split_long_sentences,
    split_sentences,
    strip_superscript_markers,
)


def seg(text: str, page: int = 1, block: int = 0) -> Segment:
    return Segment(text=text, page=page, block=block)


def texts(segments: list[Segment]) -> list[str]:
    return [s.text for s in segments]


def make_document(*pages: list[list[str]]) -> Document:
    """Build a document from pages of blocks of lines."""
    built = []
    for number, blocks in enumerate(pages, start=1):
        text_blocks = tuple(
            TextBlock(
                lines=tuple(TextLine(line, (0, 0, 100, 10), 11.0) for line in lines),
                bbox=(0, 0, 100, 10 * len(lines)),
            )
            for lines in blocks
        )
        built.append(Page(number=number, width=595, height=842, blocks=text_blocks))
    return Document(path=Path("doc.pdf"), title="doc", pages=tuple(built))


def test_normalize_unicode_expands_ligatures_and_drops_invisibles() -> None:
    result = normalize_unicode([seg("\ufb01ne e\u00adxam\u200bple")])
    assert texts(result) == ["fine example"]


def test_fix_hyphenated_line_breaks() -> None:
    result = fix_hyphenated_line_breaks(
        [seg("an exam-\nple of hy- \n phenation"), seg("Jean-\nPaul and COVID-\n19")]
    )
    assert texts(result) == ["an example of hyphenation", "Jean-Paul and COVID-19"]


def test_fix_hyphenation_leaves_normal_hyphens() -> None:
    result = fix_hyphenated_line_breaks([seg("a well-known fact")])
    assert texts(result) == ["a well-known fact"]


def test_normalize_whitespace() -> None:
    result = normalize_whitespace([seg("  line one\nline\ttwo  \n\n three ")])
    assert texts(result) == ["line one line two three"]


def test_drop_unspeakable() -> None:
    result = drop_unspeakable([seg("\u2022"), seg("---"), seg("Real text"), seg("42")])
    assert texts(result) == ["Real text", "42"]


def test_split_sentences_keeps_origin() -> None:
    result = split_sentences([seg("One. Two.", page=3, block=7)])
    assert [(s.text, s.page, s.block) for s in result] == [("One.", 3, 7), ("Two.", 3, 7)]


def test_split_long_sentences_marks_clause_pieces() -> None:
    step = split_long_sentences(max_chars=20)
    result = step([seg("aaaa bbbb, cccc dddd, eeee ffff gggg.")])
    assert len(result) > 1
    assert [s.ends_sentence for s in result] == [False] * (len(result) - 1) + [True]
    assert all(len(s.text) <= 20 for s in result)


def test_text_step_decorator_preserves_name() -> None:
    @text_step
    def shout(text: str) -> str:
        """Upper-case everything."""
        return text.upper()

    assert shout.__name__ == "shout"
    assert texts(shout([seg("hi")])) == ["HI"]


def test_document_segments_number_blocks_across_pages() -> None:
    doc = make_document([["Title"], ["Para one"]], [["Para two"]])
    result = document_segments(doc)
    assert [(s.text, s.page, s.block) for s in result] == [
        ("Title", 1, 0),
        ("Para one", 1, 1),
        ("Para two", 2, 2),
    ]


def test_default_pipeline_end_to_end() -> None:
    doc = make_document(
        [["A Title"], ["The first sen-", "tence is here. Dr. Who", "arrived later."]],
        [["\u2022"], ["Page two text."]],
    )
    result = TextPipeline().process_document(doc)
    assert [(s.text, s.page) for s in result] == [
        ("A Title", 1),
        ("The first sentence is here.", 1),
        ("Dr. Who arrived later.", 1),
        ("Page two text.", 2),
    ]


def test_adding_a_custom_step_is_trivial() -> None:
    @text_step
    def remove_page_marks(text: str) -> str:
        return text.replace("[p]", "")

    steps = default_steps()
    steps.insert(0, remove_page_marks)
    pipeline = TextPipeline(steps)
    assert texts(pipeline.run([seg("Hello[p] world. Bye.")])) == ["Hello world.", "Bye."]
    assert pipeline.steps[0] is remove_page_marks


def test_empty_pipeline_is_identity() -> None:
    segments = [seg("unchanged  text")]
    assert TextPipeline([]).run(segments) == segments


def test_document_segments_keep_layout_source() -> None:
    doc = make_document([["Line one", "line two"]])
    (segment,) = document_segments(doc)
    assert segment.source is doc.pages[0].blocks[0]
    assert segment.page_size == (595, 842)


def test_strip_superscript_markers() -> None:
    result = strip_superscript_markers(
        [seg("A claim\u00b9 and another.\u00b2\u00b3 But E = mc\u00b2 and x\u00b2 stay.")]
    )
    assert texts(result) == ["A claim and another. But E = mc\u00b2 and x\u00b2 stay."]


def test_superscript_markers_go_before_normalization() -> None:
    result = TextPipeline().run([seg("A claim\u00b9 is made.")])
    assert texts(result) == ["A claim is made."]


class TestTextSegments:
    def test_blank_lines_separate_paragraphs(self) -> None:
        result = text_segments("First paragraph.\n\nSecond paragraph.\r\n\r\nThird.")
        assert [(s.text, s.page, s.block) for s in result] == [
            ("First paragraph.", 1, 0),
            ("Second paragraph.", 1, 1),
            ("Third.", 1, 2),
        ]

    def test_hard_wrapped_lines_stay_together(self) -> None:
        text = (
            "This paragraph was wrapped by an email program at about seventy\n"
            "characters, so its lines break in the middle of sentences and\n"
            "should be read as one paragraph."
        )
        assert len(text_segments(text)) == 1

    def test_heading_line_is_its_own_paragraph(self) -> None:
        result = text_segments("Introduction\nThe study begins here and continues.")
        assert texts(result) == ["Introduction", "The study begins here and continues."]

    def test_sentence_end_breaks_paragraph(self) -> None:
        text = (
            "A long first line that ends with a full stop and is clearly a sentence.\n"
            "Another long line that is a separate paragraph in the original text here."
        )
        assert len(text_segments(text)) == 2

    def test_empty_text(self) -> None:
        assert text_segments("  \n\n \n") == []


def test_process_text_end_to_end() -> None:
    text = "Heading\n\nDr. Smith arrived. He sat down\nand began to read aloud\u00b9.\n\n\u2022"
    result = TextPipeline().process_text(text)
    assert texts(result) == [
        "Heading",
        "Dr. Smith arrived.",
        "He sat down and began to read aloud.",
    ]
    assert all(s.page == 1 for s in result)
