"""Unit tests for the layout cleanup steps, using hand-built segments."""

import pytest

from pdf_reader.pdf.models import BBox, TextBlock, TextLine, TextSpan
from pdf_reader.text.layout import (
    body_font_size,
    is_page_number,
    join_continued_blocks,
    order_columns,
    remove_footnote_markers,
    remove_footnotes,
    remove_page_numbers,
    remove_running_headers_footers,
)
from pdf_reader.text.segment import Segment

PAGE = (595.0, 842.0)
BODY = 10.5


def seg(
    text: str,
    bbox: BBox,
    *,
    page: int = 1,
    size: float = BODY,
    spans: list[list[TextSpan]] | None = None,
    block: int = 0,
) -> Segment:
    lines = text.split("\n")
    source = TextBlock(
        lines=tuple(
            TextLine(
                line,
                bbox,
                size,
                tuple(spans[i]) if spans else (TextSpan(line, size),),
            )
            for i, line in enumerate(lines)
        ),
        bbox=bbox,
    )
    return Segment(text, page, block, bbox, source=source, page_size=PAGE)


def body(page: int = 1, y: float = 300, text: str = "Body text that is long enough.") -> Segment:
    return seg(text, (72, y, 523, y + 40), page=page)


def texts(segments: list[Segment]) -> list[str]:
    return [s.text for s in segments]


# ----------------------------------------------------------------- page numbers


@pytest.mark.parametrize(
    "text", ["7", "12", "- 4 -", "\u2013 4 \u2013", "Page 3", "page 3 of 10", "3 / 10", "iv", "XII"]
)
def test_page_number_patterns(text: str) -> None:
    assert is_page_number(text)


@pytest.mark.parametrize("text", ["", "Chapter 3", "12 Angry Men", "2026 results", "mid", "civil"])
def test_not_page_numbers(text: str) -> None:
    assert not is_page_number(text)


def test_page_numbers_removed_only_in_margins() -> None:
    footer = seg("12", (290, 800, 305, 812))
    header = seg("iv", (290, 30, 305, 42))
    in_body = seg("12", (72, 400, 90, 412))  # E.g. a number in a table.
    result = remove_page_numbers([header, body(), in_body, footer])
    assert result == [body(), in_body]


def test_segments_without_layout_are_kept() -> None:
    plain = Segment("12", 1, 0)
    assert remove_page_numbers([plain]) == [plain]


# ------------------------------------------------- running headers and footers


def header(page: int, text: str = "Journal of Examples \u2014 Vol. 3") -> Segment:
    return seg(text, (72, 30, 300, 42), page=page)


def test_repeated_header_removed() -> None:
    segments = [s for p in (1, 2, 3) for s in (header(p), body(p))]
    assert remove_running_headers_footers(segments) == [body(1), body(2), body(3)]


def test_headers_differing_only_in_numbers_match() -> None:
    footers = [seg(f"Chapter 2, page {n}", (72, 800, 300, 812), page=n) for n in (1, 2, 3)]
    assert remove_running_headers_footers(footers) == []


def test_single_occurrence_is_kept() -> None:
    title = seg("A Unique Title", (72, 30, 300, 50))
    segments = [title, body(1), body(2)]
    assert remove_running_headers_footers(segments) == segments


def test_long_documents_need_three_repeats() -> None:
    pages = [body(p) for p in range(1, 7)]
    twice = [header(1, "Section Alpha"), header(2, "Section Alpha")]
    thrice = [header(p, "Section Beta") for p in (3, 4, 5)]
    result = remove_running_headers_footers(pages + twice + thrice)
    assert texts(result).count("Section Alpha") == 2
    assert "Section Beta" not in texts(result)


def test_repeated_text_in_body_is_kept() -> None:
    repeated = [seg("Summary", (72, 300, 200, 312), page=p) for p in (1, 2, 3)]
    assert remove_running_headers_footers(repeated) == repeated


# ----------------------------------------------------------------- footnotes


def test_body_font_size_is_weighted_by_text() -> None:
    segments = [
        seg("Big title", (72, 80, 300, 100), size=18),
        body(),
        seg("1 Note.", (72, 700, 300, 710), size=8),
    ]
    assert body_font_size(segments) == BODY


def test_footnotes_removed_with_continuations() -> None:
    note1 = seg("1 First note text.", (72, 700, 500, 710), size=8)
    note1_more = seg("continues on another line.", (72, 712, 500, 722), size=8)
    note2 = seg("\u2020 Dagger note.", (72, 724, 500, 734), size=8)
    segments = [body(y=200), body(y=400), note1, note1_more, note2]
    assert remove_footnotes(segments) == [body(y=200), body(y=400)]


def test_small_text_without_marker_is_kept() -> None:
    caption = seg("Figure 2: a small caption.", (72, 700, 500, 710), size=8)
    segments = [body(), body(y=400), caption]
    assert remove_footnotes(segments) == segments


def test_marker_text_high_on_page_is_kept() -> None:
    small_numbered = seg("1 Small numbered item.", (72, 150, 500, 160), size=8)
    segments = [body(), body(y=400), small_numbered]
    assert remove_footnotes(segments) == segments


def test_normal_size_numbered_paragraph_is_kept() -> None:
    numbered = seg("1 A numbered paragraph in body text.", (72, 700, 500, 712))
    segments = [body(), numbered]
    assert remove_footnotes(segments) == segments


# ------------------------------------------------------------ footnote markers


def spanned(*parts: tuple[str, bool]) -> list[TextSpan]:
    return [TextSpan(text, 6 if sup else BODY, sup) for text, sup in parts]


def test_superscript_markers_removed() -> None:
    spans = spanned(
        ("A claim", False), ("12", True), (" and more", False), ("3", True), (".", False)
    )
    segment = seg("A claim12 and more3.", (72, 300, 500, 312), spans=[spans])
    assert texts(remove_footnote_markers([segment])) == ["A claim and more."]


def test_marker_after_punctuation_removed() -> None:
    spans = spanned(("The end.", False), ("4", True))
    segment = seg("The end.4", (72, 300, 500, 312), spans=[spans])
    assert texts(remove_footnote_markers([segment])) == ["The end."]


@pytest.mark.parametrize(
    "parts",
    [
        [("E = mc", False), ("2", True)],  # Maths: short word.
        [("x", False), ("2", True)],
        [("area in m", False), ("2", True)],
        [("value ", False), ("1", True)],  # Detached from the word.
        [("a word", False), ("th", True)],  # Ordinal-style, not a marker.
    ],
)
def test_non_marker_superscripts_kept(parts: list[tuple[str, bool]]) -> None:
    text = "".join(t for t, _ in parts)
    segment = seg(text, (72, 300, 500, 312), spans=[spanned(*parts)])
    assert texts(remove_footnote_markers([segment])) == [text]


def test_markers_on_multiple_lines() -> None:
    line1 = spanned(("first line", False), ("1", True))
    line2 = spanned(("second line", False))
    segment = seg("first line1\nsecond line", (72, 300, 500, 330), spans=[line1, line2])
    assert texts(remove_footnote_markers([segment])) == ["first line\nsecond line"]


# ------------------------------------------------------------------- columns


def test_two_columns_read_left_then_right() -> None:
    title = seg("Title spanning the page", (72, 80, 523, 100))
    left_top = seg("L1", (72, 120, 285, 200))
    right_top = seg("R1", (308, 120, 523, 180))
    left_bottom = seg("L2", (72, 210, 285, 300))
    right_bottom = seg("R2", (308, 190, 523, 290))
    footer_wide = seg("Closing paragraph across the page", (72, 320, 523, 360))
    shuffled = [title, right_top, left_top, right_bottom, left_bottom, footer_wide]
    result = order_columns(shuffled)
    assert texts(result) == ["Title spanning the page", "L1", "L2", "R1", "R2", footer_wide.text]


def test_single_column_keeps_top_down_order() -> None:
    segments = [seg(f"P{i}", (72, 100 + 60 * i, 523, 150 + 60 * i)) for i in range(4)]
    assert order_columns(list(reversed(segments))) == segments


def test_stacked_narrow_blocks_are_not_columns() -> None:
    # A centred title above a left-aligned byline: no vertical overlap, not columns.
    title = seg("Centred title", (250, 100, 350, 115))
    byline = seg("By someone", (72, 125, 150, 137))
    text_block = seg("Body", (72, 150, 523, 300))
    assert order_columns([title, byline, text_block]) == [title, byline, text_block]


def test_columns_are_ordered_per_page() -> None:
    page1 = [seg("A", (72, 100, 285, 200), page=1), seg("B", (308, 100, 523, 200), page=1)]
    page2 = [
        seg("D", (308, 100, 523, 200), page=2),
        seg("C", (72, 100, 285, 200), page=2),
        seg("E", (72, 210, 285, 260), page=2),
    ]
    assert texts(order_columns(page1 + page2)) == ["A", "B", "C", "E", "D"]


def test_segments_without_boxes_keep_order() -> None:
    plain = [Segment(t, 1, i) for i, t in enumerate("cba")]
    assert order_columns(plain) == plain


# --------------------------------------------------------- continued blocks


def test_sentence_across_blocks_is_joined_and_rest_kept() -> None:
    first = seg("The listener", (72, 700, 285, 712), page=1, block=1)
    second = seg("can follow along. A new sentence\nhere.", (72, 80, 285, 100), page=2, block=2)
    result = join_continued_blocks([first, second])
    assert [(s.text, s.page, s.block) for s in result] == [
        ("The listener\ncan follow along.", 1, 1),
        ("A new sentence\nhere.", 2, 2),
    ]


def test_hyphenated_word_across_blocks() -> None:
    first = seg("an exam-", (72, 700, 285, 712))
    second = seg("ple of it.", (72, 80, 285, 92), page=2)
    assert texts(join_continued_blocks([first, second])) == ["an exam-\nple of it."]


def test_whole_block_joined_when_it_never_ends() -> None:
    blocks = [seg("one", (0, 0, 1, 1)), seg("two", (0, 0, 1, 1)), seg("three.", (0, 0, 1, 1))]
    assert texts(join_continued_blocks(blocks)) == ["one\ntwo\nthree."]


@pytest.mark.parametrize(
    ("previous", "following"),
    [
        ("Complete sentence.", "lowercase start"),
        ("A heading", "Capitalised paragraph."),
        ("As follows:", "item one"),
        ('He said "stop."', "and then"),
    ],
)
def test_blocks_not_joined(previous: str, following: str) -> None:
    a = seg(previous, (0, 0, 1, 1))
    b = seg(following, (0, 0, 1, 1))
    assert texts(join_continued_blocks([a, b])) == [previous, following]
