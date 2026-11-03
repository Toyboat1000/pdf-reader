"""Integration tests with the real Kokoro model; skipped when it isn't downloaded."""

import threading
import time
from collections.abc import Iterator

import numpy as np
import pytest

from pdf_reader.config.paths import models_dir
from pdf_reader.tts.base import SynthesisCancelledError
from pdf_reader.tts.kokoro_engine import KokoroEngine

pytestmark = pytest.mark.skipif(
    bool(KokoroEngine(models_dir()).missing_files()),
    reason="Kokoro model not downloaded (run the app once to download it)",
)

LONG_TEXT = (
    "This is a deliberately long sentence that takes the model a noticeable amount of "
    "time to synthesize, so that there is plenty of opportunity to cancel it while it "
    "is still running, which is exactly what this test needs to happen."
)


@pytest.fixture(scope="module")
def engine() -> Iterator[KokoroEngine]:
    kokoro = KokoroEngine(models_dir())
    kokoro.load()
    yield kokoro


def test_synthesizes_audio(engine: KokoroEngine) -> None:
    audio = engine.synthesize("Hello there.", "af_heart", 1.0)
    assert audio.dtype == np.float32
    assert 0.3 * engine.sample_rate < len(audio) < 5 * engine.sample_rate
    assert np.abs(audio).max() > 0.01


def test_faster_speed_is_shorter(engine: KokoroEngine) -> None:
    normal = engine.synthesize("A sentence to time at two speeds.", "af_heart", 1.0)
    fast = engine.synthesize("A sentence to time at two speeds.", "af_heart", 2.0)
    assert len(fast) < 0.75 * len(normal)


def test_unpronounceable_text_gives_empty_audio(engine: KokoroEngine) -> None:
    assert len(engine.synthesize("•", "af_heart", 1.0)) == 0


def test_cancel_interrupts_synthesis(engine: KokoroEngine) -> None:
    started = time.monotonic()
    full = engine.synthesize(LONG_TEXT, "af_heart", 1.0)
    full_duration = time.monotonic() - started
    assert len(full) > 0

    def cancel_once_running() -> None:
        # Cancelling only affects inference already in progress, so wait for it to start.
        session = engine._session
        assert session is not None
        deadline = time.monotonic() + 30
        while not session._active and time.monotonic() < deadline:
            time.sleep(0.005)
        engine.cancel()

    canceller = threading.Thread(target=cancel_once_running)
    canceller.start()
    started = time.monotonic()
    with pytest.raises(SynthesisCancelledError):
        engine.synthesize(LONG_TEXT, "af_heart", 1.0)
    assert time.monotonic() - started < full_duration * 0.8 + 1.0
    canceller.join()

    # The engine keeps working after a cancellation.
    assert len(engine.synthesize("Still working.", "af_heart", 1.0)) > 0


def test_voices_have_friendly_labels(engine: KokoroEngine) -> None:
    labels = [v.label for v in engine.voices()]
    assert labels[0] == "Heart (US Female)"
    assert len(labels) == 28
