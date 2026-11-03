"""Kokoro-82M text-to-speech via kokoro-onnx, running on the CPU with ONNX Runtime."""

import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from pdf_reader.config.settings import clamp_speed
from pdf_reader.tts.base import (
    AudioArray,
    ModelLoadError,
    SynthesisCancelledError,
    SynthesisError,
    TtsEngine,
    Voice,
)
from pdf_reader.tts.download import ProgressCallback, RemoteFile, download_files, is_present
from pdf_reader.tts.kokoro_voices import english_voices
from pdf_reader.tts.speech_text import speech_text

if TYPE_CHECKING:
    import onnxruntime
    from kokoro_onnx import Kokoro

log = logging.getLogger(__name__)

_RELEASE_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1"

KOKORO_MODEL = RemoteFile(
    name="kokoro-v1.0.onnx",
    url=f"{_RELEASE_URL}/kokoro-v1.0.onnx",
    size=325_505_369,
    sha256="beb0d1848dee9a49da392cc3df26958d46cfa35d321edf434f52949153f0df3a",
)
"""The full-precision Kokoro v1.0 model (best quality and speed on CPU)."""

KOKORO_VOICES = RemoteFile(
    name="voices-v1.0.bin",
    url=f"{_RELEASE_URL}/voices-v1.0.bin",
    size=28_214_398,
    sha256="bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
)
"""Voice style vectors for the v1.0 model (54 voices)."""

KOKORO_FILES: tuple[RemoteFile, ...] = (KOKORO_MODEL, KOKORO_VOICES)
"""Everything the Kokoro engine needs, for the first-run download."""

SAMPLE_RATE = 24_000


class KokoroEngine(TtsEngine):
    """:class:`TtsEngine` backed by the Kokoro-82M ONNX model."""

    def __init__(self, model_dir: Path) -> None:
        self._model_dir = model_dir
        self._model_path = model_dir / KOKORO_MODEL.name
        self._voices_path = model_dir / KOKORO_VOICES.name
        self._kokoro: Kokoro | None = None
        self._session: _InterruptibleSession | None = None
        self._voices: list[Voice] = []
        self._load_lock = threading.Lock()

    @property
    def sample_rate(self) -> int:
        """Return Kokoro's fixed output rate of 24 kHz."""
        return SAMPLE_RATE

    @property
    def is_loaded(self) -> bool:
        """Return whether the model is ready for synthesis."""
        return self._kokoro is not None

    def load(self) -> None:
        """Load the ONNX model and voices (a few seconds on a typical CPU)."""
        with self._load_lock:
            if self._kokoro is not None:
                return
            try:
                # Heavy imports; keep them off the app's start-up path.
                import onnxruntime as rt
                from kokoro_onnx import Kokoro

                _route_library_logging()
                session = _InterruptibleSession(
                    rt.InferenceSession(str(self._model_path), providers=["CPUExecutionProvider"])
                )
                kokoro = Kokoro.from_session(session, str(self._voices_path))
            except Exception as exc:
                log.exception("Failed to load Kokoro model from %s", self._model_path)
                raise ModelLoadError(f"Could not load the voice model: {exc}") from exc
            voices = english_voices(set(kokoro.get_voices()))
            if not voices:
                raise ModelLoadError("The voice file does not contain any supported voices.")
            try:
                # ONNX Runtime's first inference is several times slower than later
                # ones; doing it now makes the first Play start quickly. It also
                # proves the model actually works.
                kokoro.create("Ready.", voice=voices[0].id, lang=voices[0].language)
            except Exception as exc:
                log.exception("Kokoro warm-up synthesis failed")
                raise ModelLoadError(f"The voice model failed a test run: {exc}") from exc
            self._voices = voices
            self._session = session
            self._kokoro = kokoro
            log.info("Kokoro loaded with %d voices", len(self._voices))

    def missing_files(self) -> list[RemoteFile]:
        """Return the Kokoro files not yet present in the model folder."""
        return [f for f in KOKORO_FILES if not is_present(f, self._model_dir)]

    def download_missing_files(
        self, progress: ProgressCallback | None = None, cancel: threading.Event | None = None
    ) -> None:
        """Download the missing Kokoro files into the model folder."""
        download_files(self.missing_files(), self._model_dir, progress, cancel)

    def discard_model_files(self) -> None:
        """Delete the Kokoro files so the next start downloads fresh copies."""
        for file in KOKORO_FILES:
            path = self._model_dir / file.name
            try:
                path.unlink(missing_ok=True)
            except OSError:
                log.warning("Could not delete %s", path, exc_info=True)

    def voices(self) -> list[Voice]:
        """Return the supported voices; empty until the model is loaded."""
        return list(self._voices)

    def synthesize(self, text: str, voice_id: str, speed: float) -> AudioArray:
        """Generate speech for one sentence or sentence fragment."""
        kokoro = self._kokoro
        if kokoro is None:
            raise SynthesisError("The voice model is not loaded.")
        voice = next((v for v in self._voices if v.id == voice_id), None)
        if voice is None:
            raise SynthesisError(f"Unknown voice {voice_id!r}.")
        try:
            audio, _ = kokoro.create(
                speech_text(text), voice=voice_id, speed=clamp_speed(speed), lang=voice.language
            )
        except SynthesisCancelledError:
            raise
        except ValueError as exc:
            # kokoro-onnx raises ValueError when text yields no pronounceable phonemes.
            log.warning("Nothing to synthesize for %r: %s", text, exc)
            return np.zeros(0, dtype=np.float32)
        except Exception as exc:
            log.exception("Synthesis failed for %r", text)
            raise SynthesisError(str(exc)) from exc
        return polish(np.asarray(audio, dtype=np.float32).ravel(), SAMPLE_RATE)

    def cancel(self) -> None:
        """Abort synthesis in progress (ONNX Runtime stops between graph nodes)."""
        if self._session is not None:
            self._session.cancel_all()


class _InterruptibleSession:
    """Wraps an ONNX Runtime session so running inferences can be terminated.

    kokoro-onnx calls ``session.run(...)`` without run options; this wrapper supplies
    a ``RunOptions`` per call and sets its ``terminate`` flag on :meth:`cancel_all`.
    Every other attribute is forwarded to the real session.
    """

    def __init__(self, session: "onnxruntime.InferenceSession") -> None:
        self._session = session
        self._lock = threading.Lock()
        self._active: list[Any] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._session, name)

    def run(self, output_names: Any, input_feed: Any, run_options: Any = None) -> Any:
        """Run the model like ``InferenceSession.run``, but cancellably."""
        import onnxruntime as rt

        options = run_options or rt.RunOptions()
        with self._lock:
            self._active.append(options)
        try:
            return self._session.run(output_names, input_feed, options)
        except Exception as exc:
            if options.terminate:
                raise SynthesisCancelledError("Synthesis was cancelled.") from exc
            raise
        finally:
            with self._lock:
                self._active.remove(options)

    def cancel_all(self) -> None:
        """Ask every running inference to stop as soon as possible."""
        with self._lock:
            for options in self._active:
                options.terminate = True


_QUIET_DB = -42.0  # Below this (relative to the peak) counts as silence.
_TARGET_RMS = 0.085  # About -21 dBFS: comfortable and consistent.
_FADE_IN_S = 0.004
_FADE_OUT_S = 0.012


def polish(audio: AudioArray, sample_rate: int) -> AudioArray:
    """Prepare a sentence's audio so consecutive sentences join seamlessly.

    Trims the model's own leading and trailing silence (playback adds pauses that
    suit the text instead), evens out loudness from sentence to sentence, and fades
    the very edges by a few milliseconds so joins never click.
    """
    if audio.size == 0:
        return audio
    level = np.abs(audio)
    peak = float(level.max())
    if peak <= 0:
        return np.zeros(0, dtype=np.float32)
    loud = np.nonzero(level > peak * 10 ** (_QUIET_DB / 20))[0]
    start = max(0, int(loud[0]) - int(0.008 * sample_rate))
    end = min(audio.size, int(loud[-1]) + int(0.020 * sample_rate))
    audio = audio[start:end].astype(np.float32, copy=True)
    voiced = audio[np.abs(audio) > peak * 0.02]
    rms = float(np.sqrt(np.mean(voiced**2))) if voiced.size else 0.0
    if rms > 0:
        gain = min(max(_TARGET_RMS / rms, 0.6), 1.8)
        gain = min(gain, 0.97 / peak)  # Never clip.
        audio *= gain
    fade_in = min(int(_FADE_IN_S * sample_rate), audio.size)
    fade_out = min(int(_FADE_OUT_S * sample_rate), audio.size)
    if fade_in:
        audio[:fade_in] *= np.linspace(0.0, 1.0, fade_in, dtype=np.float32)
    if fade_out:
        audio[-fade_out:] *= np.linspace(1.0, 0.0, fade_out, dtype=np.float32)
    return audio


def _route_library_logging() -> None:
    """Send kokoro-onnx's log output through the app's handlers instead of its own.

    phonemizer warns about word-count mismatches for most punctuated sentences; the
    warning is harmless for Kokoro, so only its errors are kept.
    """
    library_log = logging.getLogger("kokoro_onnx")
    library_log.handlers.clear()
    library_log.setLevel(logging.WARNING)
    library_log.propagate = True
    logging.getLogger("phonemizer").setLevel(logging.ERROR)
