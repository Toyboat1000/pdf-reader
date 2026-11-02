import pytest

from pdf_reader.text.chunking import split_long_text


def test_short_text_unchanged() -> None:
    assert split_long_text("  Short sentence.  ", 50) == ["Short sentence."]


def test_empty_text() -> None:
    assert split_long_text("   ", 10) == []


def test_chunks_respect_limit_and_keep_all_words() -> None:
    text = " ".join(f"word{i}," for i in range(200))
    chunks = split_long_text(text, 60)
    assert all(len(chunk) <= 60 for chunk in chunks)
    assert " ".join(chunks).split() == text.split()


def test_prefers_semicolon_over_comma() -> None:
    text = "first part, still first; second part, more of the second part here"
    chunks = split_long_text(text, 40)
    assert chunks[0] == "first part, still first;"


def test_prefers_comma_over_plain_space() -> None:
    text = "alpha beta gamma delta, epsilon zeta eta theta iota kappa"
    chunks = split_long_text(text, 30)
    assert chunks[0] == "alpha beta gamma delta,"


def test_splits_at_spaced_dash() -> None:
    text = "the first thought goes here — and then another one follows on"
    chunks = split_long_text(text, 35)
    assert chunks[0].endswith("—")


def test_balances_chunk_lengths() -> None:
    # A limit just under the length must not leave a tiny trailing chunk.
    text = "aaaa, bbbb, cccc, dddd, eeee, ffff, gggg, hhhh, iiii, jjjj"
    chunks = split_long_text(text, len(text) - 2)
    assert len(chunks) == 2
    assert min(len(c) for c in chunks) > len(text) // 4


def test_hard_split_of_unbreakable_text() -> None:
    chunks = split_long_text("x" * 250, 100)
    assert chunks == ["x" * 100, "x" * 100, "x" * 50]


def test_invalid_limit() -> None:
    with pytest.raises(ValueError, match="positive"):
        split_long_text("text", 0)
