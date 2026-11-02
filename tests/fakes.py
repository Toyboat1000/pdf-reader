"""Test doubles: a fast fake TTS engine and a manually driven audio stream."""

import threading
import time
from collections.abc import Callable
from typing import Any

import numpy as np

from pdf_reader.audio.player import AudioCallback
from pdf_reader.tts.base import (
    AudioArray,
    SynthesisCancelledError,
    SynthesisError,
    TtsEngine,
    Voice,
)

SAMPLE_RATE = 1000  # Small rate keeps arrays tiny and arithmetic obvious.


def wait_until(predicate: Callable[[], bool], timeout: float = 3.0) -> bool:
    """Poll ``predicate`` until it is true or ``timeout`` seconds pass."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


class FakeEngine(TtsEngine):
    """Returns one sample per character, valued by sentence and speed.

    Every synthesized sample equals ``hash_value(text, voice, speed)``, which lets
    tests tell which text/voice/speed produced the audio that was played.
    """

    def __init__(self, voices: list[Voice] | None = None) -> None:
        self._voices = voices or [
            Voice("af_heart", "Heart", "en-us", "US", "Female"),
            Voice("am_adam", "Adam", "en-us", "US", "Male"),
        ]
        self.loaded = False
        self.calls: list[tuple[str, str, float]] = []
        self.cancel_count = 0
        self.fail_texts: set[str] = set()
        self.gate: threading.Event | None = None  # When set, synthesize waits on it.
        self._cancelled = threading.Event()
        self._lock = threading.Lock()

    @property
    def sample_rate(self) -> int:
        return SAMPLE_RATE

    @property
    def is_loaded(self) -> bool:
        return self.loaded

    def load(self) -> None:
        self.loaded = True

    def voices(self) -> list[Voice]:
        return list(self._voices)

    def synthesize(self, text: str, voice_id: str, speed: float) -> AudioArray:
        with self._lock:
            self.calls.append((text, voice_id, speed))
        self._cancelled.clear()
        if self.gate is not None:
            while not self.gate.wait(0.01):
                if self._cancelled.is_set():
                    raise SynthesisCancelledError("cancelled")
        if text in self.fail_texts:
            raise SynthesisError("boom")
        return np.full(len(text), hash_value(text, voice_id, speed), dtype=np.float32)

    def cancel(self) -> None:
        self.cancel_count += 1
        self._cancelled.set()

    def texts(self) -> list[str]:
        with self._lock:
            return [text for text, _, _ in self.calls]


def hash_value(text: str, voice: str, speed: float) -> float:
    """A distinct, non-zero sample value for a (text, voice, speed) combination."""
    return 0.1 + (abs(hash((text, voice, round(speed, 3)))) % 800) / 1000


class FakeStream:
    """Stands in for ``sounddevice.OutputStream``; tests call :meth:`pump`."""

    latency = 0.0

    def __init__(self, sample_rate: int, callback: AudioCallback) -> None:
        self.sample_rate = sample_rate
        self.callback = callback
        self.active = False
        self.closed = False
        self.output: list[np.ndarray] = []

    def start(self) -> None:
        self.active = True

    def stop(self) -> None:
        self.active = False

    def close(self) -> None:
        self.active = False
        self.closed = True

    def pump(self, frames: int) -> np.ndarray:
        """Ask the player for ``frames`` samples, as the sound card would."""
        out = np.full((frames, 1), np.nan, dtype=np.float32)
        self.callback(out, frames, None, None)
        self.output.append(out[:, 0].copy())
        return out[:, 0]


class StreamFactory:
    """Creates :class:`FakeStream` objects and remembers the latest one."""

    def __init__(self, fail: Exception | None = None) -> None:
        self.stream: FakeStream | None = None
        self.fail = fail
        self.created = threading.Event()

    def __call__(self, sample_rate: int, callback: AudioCallback) -> FakeStream:
        if self.fail is not None:
            raise self.fail
        self.stream = FakeStream(sample_rate, callback)
        self.created.set()
        return self.stream

    def wait_active(self) -> FakeStream:
        assert wait_until(lambda: self.stream is not None and self.stream.active)
        assert self.stream is not None
        return self.stream


class Recorder:
    """Records listener callbacks generically: ``recorder.events`` is a list of tuples."""

    def __init__(self) -> None:
        self.events: list[tuple[str, Any]] = []
        self._lock = threading.Lock()

    def __getattr__(self, name: str) -> Callable[..., None]:
        if not name.startswith("on_"):
            raise AttributeError(name)

        def record(*args: Any, **_kwargs: Any) -> None:
            with self._lock:
                self.events.append((name, args[0] if len(args) == 1 else args))

        return record

    def named(self, name: str) -> list[Any]:
        with self._lock:
            return [payload for event, payload in self.events if event == name]
