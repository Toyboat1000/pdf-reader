"""Gap-free audio playback of a queue of chunks through a single output stream.

The sound card pulls samples through a callback. Chunks queued back to back are
played without any gap, because the callback moves straight from the end of one
chunk to the start of the next within the same buffer.

The callback runs on a real-time audio thread, so it only copies samples and posts
events. A separate dispatcher thread delivers "chunk started/finished" events to the
listener at the moment the audio actually reaches the speakers (compensating for
the output latency), so the text highlight stays in sync with what is heard.
"""

import logging
import queue
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Protocol

import numpy as np

from pdf_reader.tts.base import AudioArray

log = logging.getLogger(__name__)

PREVIEW_INDEX = -1
"""Chunk index used for voice previews, which are not part of the document."""

_IDLE_SUSPEND_SECONDS = 5.0
"""After this long with nothing to play, the stream is stopped so it does not keep
the audio device busy (and the PC awake). It restarts automatically when needed."""


@dataclass(frozen=True, slots=True, eq=False)
class AudioChunk:
    """A piece of audio to play, tagged with where it belongs.

    Attributes:
        index: Sentence index in the document, or :data:`PREVIEW_INDEX`.
        epoch: Playback epoch the chunk was generated for; used to ignore events
            from chunks that belong to an earlier seek.
        samples: Mono float32 samples, including any trailing pause.
    """

    index: int
    epoch: int
    samples: AudioArray = field(repr=False)


class PlayerListener(Protocol):
    """Receives playback events on the player's dispatcher thread."""

    def on_chunk_started(self, chunk: AudioChunk) -> None:
        """A chunk's first sample is now audible."""

    def on_chunk_finished(self, chunk: AudioChunk) -> None:
        """A chunk's last sample has been played."""

    def on_audio_error(self, message: str) -> None:
        """The audio device could not be opened or failed."""


class OutputStream(Protocol):
    """The subset of ``sounddevice.OutputStream`` the player uses."""

    @property
    def active(self) -> bool:
        """Return whether the stream is running."""
        ...

    def start(self) -> None:
        """Start calling the callback."""

    def stop(self) -> None:
        """Stop after the buffered audio has played."""

    def close(self) -> None:
        """Release the device."""


type AudioCallback = Callable[[np.ndarray, int, Any, Any], None]
type StreamFactory = Callable[[int, AudioCallback], OutputStream]
"""Creates an output stream for ``(sample_rate, callback)``."""


def sounddevice_stream(sample_rate: int, callback: AudioCallback) -> OutputStream:
    """Create a mono float32 output stream on the default device."""
    import sounddevice as sd

    return sd.OutputStream(
        samplerate=sample_rate, channels=1, dtype="float32", callback=callback, latency="low"
    )


class _Event(Enum):
    STARTED = auto()
    FINISHED = auto()
    IDLE = auto()
    ERROR = auto()
    STOP = auto()


class AudioPlayer:
    """Plays queued :class:`AudioChunk` objects back to back.

    All public methods are thread-safe and return quickly.
    """

    def __init__(
        self,
        sample_rate: int,
        listener: PlayerListener,
        stream_factory: StreamFactory = sounddevice_stream,
    ) -> None:
        self._sample_rate = sample_rate
        self._listener = listener
        self._stream_factory = stream_factory

        self._lock = threading.Lock()  # Guards the queue, current chunk, and pause flag.
        self._queue: deque[AudioChunk] = deque()
        self._current: AudioChunk | None = None
        self._offset = 0
        self._paused = False
        self._silent_frames = 0
        self._idle_reported = False

        self._stream_lock = threading.Lock()  # Guards stream creation, start, and stop.
        self._stream: OutputStream | None = None
        self._latency = 0.0
        self._closed = False
        self._underflows = 0

        self._events: queue.SimpleQueue[tuple[_Event, AudioChunk | str | None, float]] = (
            queue.SimpleQueue()
        )
        self._dispatcher = threading.Thread(
            target=self._dispatch_loop, name="audio-events", daemon=True
        )
        self._dispatcher.start()

    # ----------------------------------------------------------------- control

    def enqueue(self, chunk: AudioChunk) -> None:
        """Append a chunk to play after everything already queued."""
        with self._lock:
            self._queue.append(chunk)
            self._idle_reported = False
        self._ensure_running()

    def clear(self) -> None:
        """Drop the current chunk and everything queued, silencing output at once."""
        with self._lock:
            self._queue.clear()
            self._current = None
            self._offset = 0

    def drop_queued(self) -> AudioChunk | None:
        """Drop queued chunks but let the current one finish.

        Returns:
            The chunk that keeps playing, or ``None`` if nothing is playing.
        """
        with self._lock:
            self._queue.clear()
            return self._current

    def pause(self) -> None:
        """Pause output; the current position is kept."""
        with self._lock:
            self._paused = True

    def resume(self) -> None:
        """Resume output from where it was paused."""
        with self._lock:
            self._paused = False
            self._idle_reported = False
        self._ensure_running()

    @property
    def paused(self) -> bool:
        """Return whether output is paused."""
        with self._lock:
            return self._paused

    @property
    def has_audio(self) -> bool:
        """Return whether there is a current or queued chunk."""
        with self._lock:
            return self._current is not None or bool(self._queue)

    def close(self) -> None:
        """Stop playback, release the audio device, and end the dispatcher thread."""
        self.clear()
        with self._stream_lock:
            self._closed = True
            stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.close()
            except Exception:
                log.warning("Error closing audio stream", exc_info=True)
        self._events.put((_Event.STOP, None, 0.0))
        self._dispatcher.join(timeout=2.0)
        if self._underflows:
            log.info("Audio output underflows during session: %d", self._underflows)

    # ---------------------------------------------------------------- internals

    def _ensure_running(self) -> None:
        """Open and start the stream if needed.

        Errors are reported to the listener from the dispatcher thread, never from
        here: callers may be holding their own locks.
        """
        with self._stream_lock:
            if self._closed:
                return
            try:
                if self._stream is None:
                    self._stream = self._stream_factory(self._sample_rate, self._callback)
                    self._latency = float(getattr(self._stream, "latency", 0.0) or 0.0)
                    log.info("Opened audio stream (latency %.0f ms)", self._latency * 1000)
                if not self._stream.active:
                    self._stream.start()
            except Exception as exc:
                log.exception("Could not start audio output")
                self._stream = None
                message = (
                    "Couldn't play audio. Please check that a speaker or headphones are "
                    f"connected and enabled. ({exc})"
                )
                self._events.put((_Event.ERROR, message, 0.0))

    def _suspend_if_idle(self) -> None:
        with self._stream_lock:
            with self._lock:
                still_idle = self._idle_reported
            if still_idle and self._stream is not None and self._stream.active:
                try:
                    self._stream.stop()
                    log.debug("Audio stream suspended while idle")
                except Exception:
                    log.warning("Error stopping idle audio stream", exc_info=True)

    def _callback(self, outdata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        """Fill ``outdata`` from the queue. Runs on the real-time audio thread."""
        out = outdata[:, 0] if outdata.ndim == 2 else outdata
        out.fill(0.0)
        if status is not None and getattr(status, "output_underflow", False):
            self._underflows += 1
        delay = self._output_delay(time_info)
        posted: list[tuple[_Event, AudioChunk | str | None, float]] = []
        with self._lock:
            pos = 0
            if not self._paused:
                while pos < frames:
                    if self._current is None:
                        if not self._queue:
                            break
                        self._current = self._queue.popleft()
                        self._offset = 0
                        posted.append((_Event.STARTED, self._current, pos))
                    samples = self._current.samples
                    count = min(frames - pos, len(samples) - self._offset)
                    out[pos : pos + count] = samples[self._offset : self._offset + count]
                    pos += count
                    self._offset += count
                    if self._offset >= len(samples):
                        posted.append((_Event.FINISHED, self._current, pos))
                        self._current = None
            if pos == 0:
                self._silent_frames += frames
                if (
                    not self._idle_reported
                    and self._silent_frames >= _IDLE_SUSPEND_SECONDS * self._sample_rate
                ):
                    self._idle_reported = True
                    posted.append((_Event.IDLE, None, 0))
            else:
                self._silent_frames = 0
        now = time.monotonic()
        for kind, chunk, frame_pos in posted:
            self._events.put((kind, chunk, now + delay + frame_pos / self._sample_rate))

    def _output_delay(self, time_info: Any) -> float:
        """Seconds until the first sample of this buffer reaches the speakers."""
        try:
            dac = float(time_info.outputBufferDacTime)
            current = float(time_info.currentTime)
        except (AttributeError, TypeError, ValueError):
            return self._latency
        if dac > 0 and current > 0 and 0 <= dac - current < 1.0:
            return dac - current
        return self._latency

    def _dispatch_loop(self) -> None:
        while True:
            kind, payload, fire_at = self._events.get()
            if kind is _Event.STOP:
                return
            if kind is _Event.IDLE:
                self._suspend_if_idle()
                continue
            delay = fire_at - time.monotonic()
            if delay > 0:
                time.sleep(min(delay, 1.0))  # Wait until the audio is actually audible.
            try:
                if kind is _Event.ERROR and isinstance(payload, str):
                    self._listener.on_audio_error(payload)
                elif kind is _Event.STARTED and isinstance(payload, AudioChunk):
                    self._listener.on_chunk_started(payload)
                elif kind is _Event.FINISHED and isinstance(payload, AudioChunk):
                    self._listener.on_chunk_finished(payload)
            except Exception:
                log.exception("Error in playback event listener")
