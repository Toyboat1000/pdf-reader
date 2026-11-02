import pytest

from pdf_reader.text.sentences import split_into_sentences


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", []),
        ("   ", []),
        ("No punctuation here", ["No punctuation here"]),
        ("One. Two. Three.", ["One.", "Two.", "Three."]),
        ("Really? Yes! Fine.", ["Really?", "Yes!", "Fine."]),
        ("Wait... Then it happened.", ["Wait...", "Then it happened."]),
        ("Wait… Then it happened.", ["Wait…", "Then it happened."]),
        ("It costs 3.50 dollars. Cheap.", ["It costs 3.50 dollars.", "Cheap."]),
        ("Chapter 2. The end.", ["Chapter 2.", "The end."]),
    ],
)
def test_basic_splitting(text: str, expected: list[str]) -> None:
    assert split_into_sentences(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Mr. Smith arrived.",
        "Dr. Jones and Prof. Brown agreed.",
        "We met e.g. Anna and others.",
        "J. R. R. Tolkien wrote it.",
        "The U.S. Army replied.",
        "See Fig. 3 for details.",
        "Turn to pp. 12 and read.",
        "Smith et al. Found it first.",
    ],
)
def test_abbreviations_do_not_split(text: str) -> None:
    assert split_into_sentences(text) == [text]


def test_number_abbreviation_only_before_digits() -> None:
    assert split_into_sentences("I said no. Then I left.") == ["I said no.", "Then I left."]
    assert split_into_sentences("Item No. 5 is here.") == ["Item No. 5 is here."]


def test_lowercase_continuation_does_not_split() -> None:
    text = '"Is it?" she asked. "Yes."'
    assert split_into_sentences(text) == ['"Is it?" she asked.', '"Yes."']


def test_closing_quotes_stay_with_sentence() -> None:
    text = "He said “Go now.” Then he left."
    assert split_into_sentences(text) == ["He said “Go now.”", "Then he left."]


def test_brackets_and_quotes_before_capital() -> None:
    assert split_into_sentences("First one. (Second one.)") == ["First one.", "(Second one.)"]


def test_no_text_is_lost() -> None:
    text = "Mr. A. B. Smith (b. 1950) went home. He slept! Did he? Yes… Ok."
    assert " ".join(split_into_sentences(text)) == text
