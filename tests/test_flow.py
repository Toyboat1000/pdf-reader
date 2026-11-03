"""Natural-sounding speech: spoken wording, audio polishing, and paragraph pauses."""

import numpy as np
import pytest

from pdf_reader.text import Segment, TextPipeline
from pdf_reader.text.pipeline import text_segments
from pdf_reader.tts.kokoro_engine import polish
from pdf_reader.tts.speech_text import speech_text


@pytest.mark.parametrize(
    ("written", "spoken"),
    [
        ("Cats, e.g. lions, roar.", "Cats, for example, lions, roar."),
        ("Big cats, i.e., lions.", "Big cats, that is, lions."),
        ("See Fig. 3 and pp. 12\u201314.", "See Figure 3 and pages 12 to 14."),
        ("Salt & pepper.", "Salt and pepper."),
        ("Red vs. blue.", "Red versus blue."),
        ("Wait \u2014 what?", "Wait, what?"),
        ("Apples, pears, etc.", "Apples, pears, etcetera."),
        ("\u2022 A bullet point.", "A bullet point."),
        ("Plain text stays the same.", "Plain text stays the same."),
        # Years are said the way people say them.
        ("In 1930 it rained.", "In nineteen thirty it rained."),
        ("Built in 1740.", "Built in seventeen forty."),
        ("By 1900, cars.", "By nineteen hundred, cars."),
        ("Born in 1905.", "Born in nineteen oh five."),
        ("Jazz of the 1930s.", "Jazz of the nineteen thirties."),
        ("The 1930's best film.", "The nineteen thirty's best film."),
        ("The 1930\u2019s best film.", "The nineteen thirty\u2019s best film."),
        ("In 2024 we met.", "In twenty twenty-four we met."),
        ("In 2010 and 2099.", "In twenty ten and twenty ninety-nine."),
        ("From 1100 on.", "From eleven hundred on."),
        ("Sales in 1990\u20132000.", "Sales in nineteen ninety to 2000."),
        ("From 2010\u20132020.", "From twenty ten to twenty twenty."),
        (
            "(1930) and 1930, then 1930.",
            "(nineteen thirty) and nineteen thirty, then nineteen thirty.",
        ),
        ("Some 1930 people came.", "Some nineteen thirty people came."),
        # Not years: other numbers, amounts, and parts of larger numbers.
        ("In 2005 it ended.", "In 2005 it ended."),
        ("In 1099 and 2100.", "In 1099 and 2100."),
        ("It cost $1930.", "It cost $1930."),
        ("It cost \u20ac1930 or \u00a31930.", "It cost \u20ac1930 or \u00a31930."),
        ("About 1,930 or 11930 or 19300.", "About 1,930 or 11930 or 19300."),
        ("It was 1930,000 strong.", "It was 1930,000 strong."),
        ("Pi is 3.1930 and 1930.5 too.", "Pi is 3.1930 and 1930.5 too."),
        ("Up 1930% now.", "Up 1930% now."),
        ("A 1930 kg or 1930kg load.", "A 1930 kg or 1930kg load."),
        (
            "Walk 1930 km, 1930 m, 1930 mi, or 1930 ft.",
            "Walk 1930 km, 1930 m, 1930 mi, or 1930 ft.",
        ),
        ("Lift 1930 lb or 1930 g.", "Lift 1930 lb or 1930 g."),
    ],
)
def test_speech_text(written: str, spoken: str) -> None:
    assert speech_text(written) == spoken


def test_polish_trims_silence_and_evens_loudness() -> None:
    rate = 1000
    tone = 0.16 * np.sin(np.linspace(0, 60, 400)).astype(np.float32)  # Typical speech level.

    quiet = (tone * 0.5).astype(np.float32)  # A quieter sentence.
    padded = np.concatenate([np.zeros(300), tone, np.zeros(500)]).astype(np.float32)
    loud_out = polish(padded, rate)
    quiet_out = polish(
        np.concatenate([np.zeros(300), quiet, np.zeros(500)]).astype(np.float32), rate
    )
    assert len(loud_out) < 450  # Leading and trailing silence trimmed (small margins kept).
    assert loud_out[0] == 0.0  # Faded in: joins never click.
    rms = [float(np.sqrt(np.mean(a[np.abs(a) > 0.001] ** 2))) for a in (loud_out, quiet_out)]
    assert rms[0] == pytest.approx(rms[1], rel=0.15)  # Same loudness either way.
    assert np.abs(loud_out).max() < 0.98  # Never clips.


def test_polish_handles_silence() -> None:
    assert polish(np.zeros(100, dtype=np.float32), 1000).size == 0
    assert polish(np.zeros(0, dtype=np.float32), 1000).size == 0


def test_last_sentence_of_each_paragraph_is_marked() -> None:
    segments = TextPipeline().run(text_segments("A heading\n\nFirst one. Second one.\n\nNext."))
    assert [(s.text, s.ends_paragraph) for s in segments] == [
        ("A heading", True),
        ("First one.", False),
        ("Second one.", True),
        ("Next.", True),
    ]


def test_long_sentence_keeps_paragraph_mark_on_last_piece() -> None:
    long = ", ".join(f"clause number {i}" for i in range(40)) + "."
    pieces = TextPipeline().run([Segment(long, 1, 0)])
    assert len(pieces) > 1
    assert [p.ends_paragraph for p in pieces] == [False] * (len(pieces) - 1) + [True]
