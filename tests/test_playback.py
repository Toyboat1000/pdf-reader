"""Tests for the look-ahead generation queue, using a fake engine and audio stream."""

import threading
from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np
import pytest

from pdf_reader.audio.playback import (
    PlaybackController,
    ensure_trailing_silence,
)
from pdf_reader.audio.player import AudioPlayer, PlayerListener
from tests.fakes import (
    SAMPLE_RATE,
    FakeEngine,
    FakeStream,
    Recorder,
    StreamFactory,
    hash_value,
    wait_until,
)


@dataclass(frozen=True)
class Line:
    text: str
    ends_sentence: bool = True


SCRIPT = [Line(f"Sentence number {i}.") for i in range(10)]


class Harness:
    def __init__(self, lookahead: int = 2) -> None:
        self.engine = FakeEngine()
        self.engine.load()
        self.listener = Recorder()
        self.factory = StreamFactory()

        def make_player(rate: int, listener: PlayerListener) -> AudioPlayer:
            return AudioPlayer(rate, listener, stream_factory=self.factory)

        self.controller = PlaybackController(
            self.engine,
            self.listener,
            voice="af_heart",
            speed=1.0,
            lookahead=lookahead,
            player_factory=make_player,
        )
        self.controller.set_script(SCRIPT)

    @property
    def stream(self) -> FakeStream:
        return self.factory.wait_active()

    def started(self) -> list[int]:
        return self.listener.named("on_sentence_started")

    def play_sentence(self) -> np.ndarray:
        """Pump exactly one sentence (plus its pause) of audio once it is queued."""
        text_len = len(SCRIPT[0].text)
        pause = int(0.25 * SAMPLE_RATE)
        return self.stream.pump(text_len + pause)

    def close(self) -> None:
        self.controller.shutdown()


@pytest.fixture
def h() -> Iterator[Harness]:
    harness = Harness()
    yield harness
    harness.close()


def generated(h: Harness) -> list[int]:
    return [int(text.split()[2].rstrip(".")) for text in h.engine.texts()]


def test_generates_only_within_lookahead(h: Harness) -> None:
    h.controller.play_from(0)
    assert wait_until(lambda: generated(h) == [0, 1, 2])
    threading.Event().wait(0.1)
    assert generated(h) == [0, 1, 2]  # Waits for playback before going further.


def test_lookahead_advances_as_sentences_play(h: Harness) -> None:
    h.controller.play_from(0)
    assert wait_until(lambda: generated(h) == [0, 1, 2])
    h.play_sentence()
    h.play_sentence()  # Sentence 1 starts within this buffer.
    assert wait_until(lambda: generated(h) == [0, 1, 2, 3])
    assert wait_until(lambda: h.started() == [0, 1])


def test_audio_matches_script_order(h: Harness) -> None:
    h.controller.play_from(4)
    assert wait_until(lambda: len(generated(h)) == 3)
    out = h.play_sentence()
    expected = hash_value(SCRIPT[4].text, "af_heart", 1.0)
    assert out[0] == pytest.approx(expected)
    assert wait_until(lambda: h.started() == [4])


def test_seek_discards_stale_buffer(h: Harness) -> None:
    h.controller.play_from(0)
    assert wait_until(lambda: generated(h) == [0, 1, 2])
    h.controller.play_from(7)
    assert wait_until(lambda: generated(h) == [0, 1, 2, 7, 8, 9])
    out = h.play_sentence()
    assert out[0] == pytest.approx(hash_value(SCRIPT[7].text, "af_heart", 1.0))
    assert wait_until(lambda: h.started() == [7])


def test_seek_back_uses_cache(h: Harness) -> None:
    h.controller.play_from(0)
    assert wait_until(lambda: generated(h) == [0, 1, 2])
    h.controller.play_from(5)
    assert wait_until(lambda: generated(h)[-3:] == [5, 6, 7])
    h.controller.play_from(0)
    out = h.play_sentence()
    assert out[0] == pytest.approx(hash_value(SCRIPT[0].text, "af_heart", 1.0))
    threading.Event().wait(0.1)
    assert generated(h).count(0) == 1  # Not regenerated.


def test_speed_change_applies_from_next_sentence(h: Harness) -> None:
    h.controller.play_from(0)
    assert wait_until(lambda: generated(h) == [0, 1, 2])
    h.stream.pump(5)  # Sentence 0 is now playing.
    h.controller.set_speed(1.5)
    assert wait_until(lambda: (SCRIPT[1].text, "af_heart", 1.5) in h.engine.calls)
    assert wait_until(lambda: (SCRIPT[2].text, "af_heart", 1.5) in h.engine.calls)
    assert (SCRIPT[0].text, "af_heart", 1.5) not in h.engine.calls

    rest_of_first = h.stream.pump(len(SCRIPT[0].text) + 250 - 5)
    assert rest_of_first[0] == pytest.approx(hash_value(SCRIPT[0].text, "af_heart", 1.0))
    second = h.play_sentence()
    assert second[0] == pytest.approx(hash_value(SCRIPT[1].text, "af_heart", 1.5))


def test_voice_change_regenerates_upcoming(h: Harness) -> None:
    h.controller.play_from(0)
    assert wait_until(lambda: generated(h) == [0, 1, 2])
    h.stream.pump(5)
    h.controller.set_voice("am_adam")
    assert wait_until(lambda: (SCRIPT[2].text, "am_adam", 1.0) in h.engine.calls)
    h.stream.pump(len(SCRIPT[0].text) + 250 - 5)
    assert h.play_sentence()[0] == pytest.approx(hash_value(SCRIPT[1].text, "am_adam", 1.0))


def test_outdated_audio_plays_if_replacement_is_late(h: Harness) -> None:
    """A settings change never causes silence: old audio fills in until new is ready."""
    h.controller.play_from(0)
    assert wait_until(lambda: generated(h) == [0, 1, 2])
    h.stream.pump(5)
    h.engine.gate = threading.Event()  # Block all further synthesis.
    h.controller.set_speed(2.0)
    h.stream.pump(len(SCRIPT[0].text) + 250 - 5)
    second = h.play_sentence()
    assert second[0] == pytest.approx(hash_value(SCRIPT[1].text, "af_heart", 1.0))
    h.engine.gate.set()


def test_seek_cancels_synthesis_in_progress(h: Harness) -> None:
    h.engine.gate = threading.Event()
    h.controller.play_from(0)
    assert wait_until(lambda: generated(h) == [0])
    h.controller.play_from(6)
    assert wait_until(lambda: h.engine.cancel_count >= 1)
    h.engine.gate.set()
    assert wait_until(lambda: 6 in generated(h))
    assert h.play_sentence()[0] == pytest.approx(hash_value(SCRIPT[6].text, "af_heart", 1.0))


def test_reaching_the_end(h: Harness) -> None:
    h.controller.play_from(8)
    assert wait_until(lambda: generated(h) == [8, 9])
    h.play_sentence()
    h.play_sentence()
    assert wait_until(lambda: h.listener.named("on_reached_end") != [])
    assert h.started() == [8, 9]


def test_pause_and_resume(h: Harness) -> None:
    h.controller.play_from(0)
    assert wait_until(lambda: generated(h) == [0, 1, 2])
    first = h.stream.pump(3)
    h.controller.pause()
    np.testing.assert_array_equal(h.stream.pump(3), np.zeros(3, dtype=np.float32))
    h.controller.resume()
    assert h.stream.pump(3)[0] == first[0]


def test_stop_then_resume_restarts_current_sentence(h: Harness) -> None:
    h.controller.play_from(3)
    assert wait_until(lambda: generated(h) == [3, 4, 5])
    h.stream.pump(5)
    h.controller.stop()
    np.testing.assert_array_equal(h.stream.pump(4), np.zeros(4, dtype=np.float32))
    h.controller.resume()
    assert h.play_sentence()[0] == pytest.approx(hash_value(SCRIPT[3].text, "af_heart", 1.0))


def test_preview_plays_sample_and_reports_end(h: Harness) -> None:
    h.controller.preview("Hi there", "am_adam", 1.0)
    assert wait_until(lambda: ("Hi there", "am_adam", 1.0) in h.engine.calls)
    out = h.stream.pump(8 + 250)
    assert out[0] == pytest.approx(hash_value("Hi there", "am_adam", 1.0))
    assert wait_until(lambda: h.listener.named("on_preview_finished") != [])
    assert h.listener.named("on_sentence_started") == []


def test_repeated_failures_stop_playback(h: Harness) -> None:
    h.engine.fail_texts = {line.text for line in SCRIPT}
    h.controller.play_from(0)
    assert wait_until(lambda: h.listener.named("on_playback_error") != [])


def test_single_failure_is_skipped(h: Harness) -> None:
    h.engine.fail_texts = {SCRIPT[1].text}
    h.controller.play_from(0)
    assert wait_until(lambda: generated(h) == [0, 1, 2])
    h.play_sentence()  # Sentence 0; sentence 1 is skipped as zero-length audio.
    out = h.play_sentence()
    assert out[0] == pytest.approx(hash_value(SCRIPT[2].text, "af_heart", 1.0))
    assert h.listener.named("on_playback_error") == []


def test_shutdown_is_prompt_and_idempotent() -> None:
    harness = Harness()
    harness.engine.gate = threading.Event()
    harness.controller.play_from(0)
    assert wait_until(lambda: generated(harness) == [0])
    harness.close()  # Cancels the blocked synthesis instead of hanging.
    harness.close()


def test_play_from_out_of_range_is_ignored(h: Harness) -> None:
    h.controller.play_from(99)
    threading.Event().wait(0.05)
    assert h.engine.calls == []


class TestEnsureTrailingSilence:
    def test_pads_to_target(self) -> None:
        audio = np.ones(10, dtype=np.float32)
        out = ensure_trailing_silence(audio, 100, 0.2)
        assert len(out) == 30
        assert not out[10:].any()

    def test_existing_silence_counts(self) -> None:
        audio = np.concatenate([np.ones(10), np.zeros(15)]).astype(np.float32)
        out = ensure_trailing_silence(audio, 100, 0.2)
        assert len(out) == 30

    def test_long_silence_untouched(self) -> None:
        audio = np.concatenate([np.ones(10), np.zeros(50)]).astype(np.float32)
        assert ensure_trailing_silence(audio, 100, 0.2) is audio

    def test_empty_input(self) -> None:
        out = ensure_trailing_silence(np.zeros(0, dtype=np.float32), 100, 0.1)
        assert len(out) == 10
