import numpy as np
import pytest

from pdf_reader.tts.stretch import time_stretch
from pdf_reader.tts.word_timing import (
    SpokenWord,
    align_word_starts,
    estimate_word_starts,
    word_weight,
)


def spoken(*lengths: int, gap: float = 0.05) -> list[SpokenWord]:
    """Spoken words of the given lengths, 0.1 s per sound, separated by ``gap``."""
    words, t = [], 0.0
    for length in lengths:
        words.append(SpokenWord(length, t, t + 0.1 * length))
        t += 0.1 * length + gap
    return words


def test_one_spoken_word_per_written_word() -> None:
    words = spoken(5, 3, 4)
    assert align_word_starts("Hello big world.", words) == tuple(w.start for w in words)


def test_rewritten_abbreviation_spans_several_spoken_words() -> None:
    # "e.g.," is spoken as "for example": two spoken words for one written word.
    words = spoken(5, 2, 3, 7, 5)  # "sales", "of", "for", "example", "rose"
    starts = align_word_starts("sales of e.g., rose", words)
    assert starts == (words[0].start, words[1].start, words[2].start, words[4].start)


def test_number_spoken_as_several_words() -> None:
    # "1990" is spoken "nineteen ninety".
    words = spoken(2, 7, 6, 4)  # "In", "nineteen", "ninety", "they"
    starts = align_word_starts("In 1990 they", words)
    assert starts == (words[0].start, words[1].start, words[3].start)


def test_unspoken_word_shares_the_next_start() -> None:
    words = spoken(4, 4)  # "fast", "slow" (the dash is not spoken)
    starts = align_word_starts("fast \u2014 slow", words)
    assert starts == (words[0].start, words[1].start, words[1].start)


def test_starts_never_decrease_and_cover_every_word() -> None:
    text = "Dr. Smith's U.S.-based team, et al., studied 1,234,567 cells at 37.5 degrees."
    words = spoken(6, 6, 2, 10, 4, 3, 9, 7, 3, 8, 5, 6, 8, 5, 2, 8, 5, 4, 7)
    starts = align_word_starts(text, words)
    assert len(starts) == len(text.split())
    assert list(starts) == sorted(starts)
    assert starts[0] == words[0].start


def test_empty_inputs() -> None:
    assert align_word_starts("", spoken(3)) == ()
    assert align_word_starts("two words", []) == (0.0, 0.0)
    assert estimate_word_starts("", 2.0) == ()


def test_estimate_spreads_words_by_length() -> None:
    starts = estimate_word_starts("a extraordinarily b", 3.0)
    assert starts[0] == 0.0
    assert starts[2] - starts[1] > starts[1] - starts[0]
    assert all(0 <= s < 3.0 for s in starts)


def test_word_weight_counts_spoken_sounds() -> None:
    assert word_weight("cat.") == 3
    assert word_weight("42") == 6
    assert word_weight("e.g.,") > word_weight("eg")  # Spoken as "for example".


def test_long_sentence_aligns_quickly() -> None:
    import time

    text = " ".join(f"word{i % 10}" for i in range(120))
    words = spoken(*([5] * 118))
    started = time.perf_counter()
    starts = align_word_starts(text, words)
    assert time.perf_counter() - started < 0.5
    assert len(starts) == 120


# ------------------------------------------------------------------ stretch


def dominant_frequency(audio: np.ndarray, rate: int) -> float:
    spectrum = np.abs(np.fft.rfft(audio * np.hanning(len(audio))))
    return float(np.fft.rfftfreq(len(audio), 1 / rate)[int(np.argmax(spectrum))])


@pytest.mark.parametrize("factor", [1.5, 2.0])
def test_time_stretch_shortens_without_changing_pitch(factor: float) -> None:
    rate = 24_000
    t = np.arange(rate * 2) / rate
    tone = (0.5 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    out = time_stretch(tone, factor, rate)
    assert len(out) == int(len(tone) / factor)
    assert abs(dominant_frequency(out, rate) - 220) < 3
    # No clicks or dropouts: the middle keeps the tone's level.
    middle = out[len(out) // 4 : 3 * len(out) // 4]
    assert 0.3 < float(np.sqrt(np.mean(middle**2))) < 0.42


def test_time_stretch_leaves_audio_alone_at_normal_speed() -> None:
    audio = np.ones(1000, dtype=np.float32)
    assert time_stretch(audio, 1.0, 24_000) is audio
    short = np.ones(10, dtype=np.float32)
    assert time_stretch(short, 2.0, 24_000) is short
