from pathlib import Path

from pdf_reader.pdf.models import Document, Page, TextBlock, TextLine
from pdf_reader.text import Segment, TextPipeline, default_steps, document_segments, text_step
from pdf_reader.text.steps import (
    drop_unspeakable,
    fix_hyphenated_line_breaks,
    normalize_unicode,
    normalize_whitespace,
    split_long_sentences,
    split_sentences,
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
    result = normalize_unicode([seg("ﬁne e­xam​ple")])
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
    result = drop_unspeakable([seg("•"), seg("---"), seg("Real text"), seg("42")])
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
        [["•"], ["Page two text."]],
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
