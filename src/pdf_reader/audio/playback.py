"""Look-ahead speech generation feeding the audio player.

A worker thread synthesizes the sentence being played plus a few after it, so the
next sentence is always ready before the current one ends. Two counters keep the
buffer consistent with what the user wants:

* ``epoch`` changes on every seek, stop, or preview. Audio and events from an older
  epoch are discarded, and a synthesis still running for an older epoch is cancelled.
* ``params_version`` changes when the voice or speed changes. Upcoming sentences are
  regenerated with the new settings, and each regenerated chunk replaces its
  outdated version in the player's queue. Until a replacement is ready the outdated
  chunk stays queued, so a settings change never causes a gap: it takes effect from
  the next sentence whenever generation keeps up (it normally does, at about five
  times real time), or one sentence later otherwise.

Recently generated audio is cached, so going back and forth between nearby sentences
starts playing immediately.
"""

import logging
import threading
from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from pdf_reader.audio.player import PREVIEW_INDEX, AudioChunk, AudioPlayer, PlayerListener
from pdf_reader.config.settings import clamp_speed
from pdf_reader.tts.base import AudioArray, SynthesisCancelledError, TtsEngine, TtsError

log = logging.getLogger(__name__)

DEFAULT_LOOKAHEAD = 3
"""Sentences generated ahead of the one playing."""

SENTENCE_PAUSE_SECONDS = 0.2
"""Silence after a sentence within a paragraph (a short breath)."""

PARAGRAPH_PAUSE_SECONDS = 0.55
"""Silence after the last sentence of a paragraph, or after a heading."""

CLAUSE_PAUSE_SECONDS = 0.1
"""Silence after a piece of a long sentence that was split."""

_CACHE_SIZE = 12
_MAX_CONSECUTIVE_FAILURES = 3
_QUIET_LEVEL = 0.01  # Relative to the chunk's peak.


class Speakable(Protocol):
    """Anything with text to speak and a flag for whether it ends a sentence."""

    @property
    def text(self) -> str:
        """Return the text to speak."""
        ...

    @property
    def ends_sentence(self) -> bool:
        """Return whether a full sentence pause should follow."""
        ...


class PlaybackListener(Protocol):
    """Receives playback progress; called from background threads."""

    def on_sentence_started(self, index: int) -> None:
        """Sentence ``index`` started playing (it is now audible)."""

    def on_reached_end(self) -> None:
        """The last sentence of the script finished playing."""

    def on_preview_finished(self) -> None:
        """A voice preview finished playing."""

    def on_playback_error(self, message: str) -> None:
        """Playback failed; ``message`` is suitable for the user."""


type PlayerFactory = Callable[[int, PlayerListener], AudioPlayer]
"""Creates the audio player for ``(sample_rate, listener)``; replaceable in tests."""

type _CacheKey = tuple[int, str, float]


@dataclass(frozen=True, slots=True)
class _Job:
    index: int
    text: str
    ends_sentence: bool
    ends_paragraph: bool
    voice: str
    speed: float
    epoch: int
    params_version: int


class PlaybackController(PlayerListener):
    """Plays a script of sentences with gap-free look-ahead generation.

    All public methods are thread-safe and return immediately; synthesis runs on a
    dedicated worker thread.
    """

    def __init__(
        self,
        engine: TtsEngine,
        listener: PlaybackListener,
        *,
        voice: str,
        speed: float = 1.0,
        lookahead: int = DEFAULT_LOOKAHEAD,
        player_factory: PlayerFactory = AudioPlayer,
    ) -> None:
        self._engine = engine
        self._listener = listener
        self._lookahead = max(0, lookahead)
        self._player = player_factory(engine.sample_rate, self)

        # Reentrant: player and engine callbacks may re-enter on the same thread.
        self._cond = threading.Condition(threading.RLock())
        self._script: Sequence[Speakable] = ()
        self._voice = voice
        self._speed = clamp_speed(speed)
        self._epoch = 0
        self._params_version = 0
        self._active = False  # Generating for document playback.
        self._position = 0  # Sentence being played, or about to be.
        self._next_index = 0  # Next sentence to generate.
        self._needs_restart = True  # The player holds no audio for the current position.
        self._preview: tuple[str, str, float] | None = None
        self._busy: _Job | None = None  # Job being synthesized right now.
        self._cache: OrderedDict[_CacheKey, AudioArray] = OrderedDict()
        self._failures = 0
        self._shutdown = False

        self._worker = threading.Thread(target=self._run, name="tts-lookahead", daemon=True)
        self._worker.start()

    # ------------------------------------------------------------ public API

    @property
    def voice(self) -> str:
        """Return the current voice id."""
        with self._cond:
            return self._voice

    @property
    def speed(self) -> float:
        """Return the current speed multiplier."""
        with self._cond:
            return self._speed

    def set_script(self, script: Sequence[Speakable]) -> None:
        """Replace the sentences to read, stopping any current playback."""
        with self._cond:
            self._stop_locked()
            self._script = script
            self._cache.clear()
            self._position = 0

    def play_from(self, index: int) -> None:
        """Start (or restart) playback at sentence ``index``."""
        with self._cond:
            if not 0 <= index < len(self._script):
                log.warning("play_from(%d) out of range (0..%d)", index, len(self._script) - 1)
                return
            self._new_epoch_locked()
            self._preview = None
            self._active = True
            self._needs_restart = False
            self._position = index
            self._next_index = index
            self._failures = 0
            # Already generated audio starts at once, without waiting for the worker.
            while self._next_index <= index + self._lookahead and self._enqueue_cached_locked():
                pass
            self._cond.notify_all()
        self._player.resume()

    def pause(self) -> None:
        """Pause output. Generation continues filling the look-ahead buffer."""
        self._player.pause()

    def resume(self) -> None:
        """Resume after :meth:`pause`, or restart at the current position if needed."""
        with self._cond:
            restart = self._needs_restart or not self._active
            position = self._position
        if restart:
            self.play_from(position)
        else:
            self._player.resume()

    def stop(self) -> None:
        """Stop playback and discard all buffered audio."""
        with self._cond:
            self._stop_locked()

    def set_voice(self, voice: str) -> None:
        """Use ``voice`` from the next sentence on."""
        with self._cond:
            if voice != self._voice:
                self._voice = voice
                self._params_changed_locked()

    def set_speed(self, speed: float) -> None:
        """Use ``speed`` from the next sentence on."""
        speed = clamp_speed(speed)
        with self._cond:
            if abs(speed - self._speed) > 1e-6:
                self._speed = speed
                self._params_changed_locked()

    def preview(self, text: str, voice: str, speed: float) -> None:
        """Interrupt reading to speak ``text`` with ``voice``.

        Document playback does not resume by itself afterwards; :meth:`resume`
        restarts it at the current sentence.
        """
        with self._cond:
            self._new_epoch_locked()
            self._active = False
            self._needs_restart = True
            self._preview = (text, voice, clamp_speed(speed))
            self._cond.notify_all()
        self._player.resume()

    def shutdown(self) -> None:
        """Stop everything and release the audio device. Safe to call twice."""
        with self._cond:
            self._shutdown = True
            self._new_epoch_locked()
            self._cond.notify_all()
        self._worker.join(timeout=5.0)
        if self._worker.is_alive():
            log.warning("TTS worker did not stop within 5 s; abandoning it")
        self._player.close()

    # ------------------------------------------------------- player callbacks

    def on_chunk_started(self, chunk: AudioChunk) -> None:
        """Track the playing sentence and let generation move ahead."""
        with self._cond:
            if chunk.epoch != self._epoch or chunk.index == PREVIEW_INDEX:
                return
            self._position = chunk.index
            self._cond.notify_all()
        self._listener.on_sentence_started(chunk.index)

    def on_chunk_finished(self, chunk: AudioChunk) -> None:
        """Detect the end of the document or of a preview."""
        with self._cond:
            if chunk.epoch != self._epoch:
                return
            is_preview = chunk.index == PREVIEW_INDEX
            at_end = not is_preview and chunk.index == len(self._script) - 1
            if at_end:
                self._active = False
                self._needs_restart = True
        if is_preview:
            self._listener.on_preview_finished()
        elif at_end:
            self._listener.on_reached_end()

    def on_audio_error(self, message: str) -> None:
        """Stop and report an audio device problem."""
        self.stop()
        self._listener.on_playback_error(message)

    # ---------------------------------------------------------------- internals

    def _new_epoch_locked(self) -> None:
        """Invalidate all queued audio and any synthesis in progress."""
        self._epoch += 1
        self._player.clear()
        self._cancel_stale_locked()

    def _cancel_stale_locked(self) -> None:
        busy = self._busy
        if busy is not None and self._is_stale_locked(busy):
            self._engine.cancel()

    def _is_stale_locked(self, job: _Job) -> bool:
        if job.epoch != self._epoch:
            return True
        return job.index != PREVIEW_INDEX and job.params_version != self._params_version

    def _stop_locked(self) -> None:
        self._new_epoch_locked()
        self._active = False
        self._needs_restart = True
        self._preview = None

    def _params_changed_locked(self) -> None:
        self._params_version += 1
        if not self._active:
            return
        playing = self._player.current
        if playing is not None and playing.epoch == self._epoch and playing.index >= 0:
            # The audible sentence finishes as it is; regenerate everything after it.
            self._position = max(self._position, playing.index)
            self._next_index = playing.index + 1
        else:
            self._next_index = self._position
        self._cancel_stale_locked()
        self._cond.notify_all()

    def _has_work_locked(self) -> bool:
        if self._preview is not None:
            return True
        return (
            self._active
            and self._next_index < len(self._script)
            and self._next_index <= self._position + self._lookahead
        )

    def _job_for_locked(self, index: int) -> _Job:
        item = self._script[index]
        return _Job(
            index,
            item.text,
            item.ends_sentence,
            getattr(item, "ends_paragraph", False),
            self._voice,
            self._speed,
            self._epoch,
            self._params_version,
        )

    def _enqueue_cached_locked(self) -> bool:
        """Queue the next sentence straight from the cache, if it is there."""
        if self._next_index >= len(self._script):
            return False
        samples = self._cache.get((self._next_index, self._voice, self._speed))
        if samples is None:
            return False
        self._player.offer(AudioChunk(self._next_index, self._epoch, samples))
        self._next_index += 1
        return True

    def _run(self) -> None:
        while True:
            with self._cond:
                while True:
                    if self._shutdown:
                        return
                    if self._has_work_locked():
                        if self._preview is None and self._enqueue_cached_locked():
                            continue
                        break
                    self._cond.wait()
                job = self._take_job_locked()
                self._busy = job
            try:
                samples, failed = self._synthesize(job)
            finally:
                with self._cond:
                    self._busy = None
            if samples is not None:
                self._deliver(job, samples, failed)

    def _take_job_locked(self) -> _Job:
        if self._preview is not None:
            text, voice, speed = self._preview
            self._preview = None
            return _Job(
                PREVIEW_INDEX, text, True, False, voice, speed, self._epoch, self._params_version
            )
        job = self._job_for_locked(self._next_index)
        self._next_index += 1
        return job

    def _synthesize(self, job: _Job) -> tuple[AudioArray | None, bool]:
        """Run the engine. Returns ``(None, False)`` if the job was cancelled."""
        try:
            raw = self._engine.synthesize(job.text, job.voice, job.speed)
        except SynthesisCancelledError:
            log.debug("Synthesis of %d cancelled", job.index)
            return None, False
        except TtsError:
            log.exception("Could not synthesize sentence %d", job.index)
            return np.zeros(0, dtype=np.float32), True
        if job.ends_paragraph:
            pause = PARAGRAPH_PAUSE_SECONDS
        elif job.ends_sentence:
            pause = SENTENCE_PAUSE_SECONDS
        else:
            pause = CLAUSE_PAUSE_SECONDS
        # Faster reading gets proportionally shorter pauses, but never rushed ones.
        pause /= max(job.speed, 1.0) ** 0.6
        samples = ensure_trailing_silence(raw, self._engine.sample_rate, pause)
        if job.index != PREVIEW_INDEX:
            with self._cond:
                self._cache[(job.index, job.voice, job.speed)] = samples
                while len(self._cache) > _CACHE_SIZE:
                    self._cache.popitem(last=False)
        return samples, False

    def _deliver(self, job: _Job, samples: AudioArray, failed: bool) -> None:
        give_up = False
        with self._cond:
            if self._is_stale_locked(job):
                return  # The user moved on while this was being generated.
            self._failures = self._failures + 1 if failed else 0
            if self._failures >= _MAX_CONSECUTIVE_FAILURES:
                self._stop_locked()
                give_up = True
            else:
                # Offer under the lock so a concurrent seek can't slip in between.
                self._player.offer(AudioChunk(job.index, job.epoch, samples))
        if give_up:
            self._listener.on_playback_error(
                "Speech generation failed several times in a row. Please try another "
                "voice, or restart the app."
            )


def ensure_trailing_silence(samples: AudioArray, sample_rate: int, seconds: float) -> AudioArray:
    """Pad ``samples`` with zeros so they end with at least ``seconds`` of quiet.

    Engines often add a natural pause after punctuation already; only the missing
    part is added, so pauses don't double up.
    """
    target = int(seconds * sample_rate)
    if len(samples) == 0:
        return np.zeros(target, dtype=np.float32)
    peak = float(np.max(np.abs(samples)))
    loud = np.nonzero(np.abs(samples) > peak * _QUIET_LEVEL)[0]
    trailing = len(samples) - 1 - int(loud[-1]) if len(loud) else len(samples)
    missing = target - trailing
    if missing <= 0:
        return samples
    return np.concatenate([samples, np.zeros(missing, dtype=np.float32)])
