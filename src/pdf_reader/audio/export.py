"""Save a document's speech as an audio file (MP3 or WAV) to listen to anywhere.

Sentences are synthesized one after another with the same pauses as playback and
written to the file as they are made, so memory use stays small even for a whole
book. The file is written under a temporary name and renamed when complete, so a
cancelled or failed export never leaves a half-written file behind.
"""

import logging
import struct
import threading
import wave
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol

import numpy as np

from pdf_reader.audio.playback import Speakable, ensure_trailing_silence, pause_seconds
from pdf_reader.tts.base import AudioArray, SynthesisCancelledError, TtsEngine, TtsError

log = logging.getLogger(__name__)

EXPORT_SUFFIXES = (".mp3", ".wav")
"""Audio file types that can be exported."""

MP3_BITRATE_KBPS = 64
"""Clear speech in a small file (about 30 MB per hour of listening)."""

_MAX_RETRIES = 20  # Synthesis is retried when playback interrupts it (a seek).
_MAX_CONSECUTIVE_FAILURES = 3


class ExportError(Exception):
    """The audio file could not be made.

    Attributes:
        user_message: A friendly explanation suitable for showing in the UI.
    """

    def __init__(self, user_message: str) -> None:
        super().__init__(user_message)
        self.user_message = user_message


class ExportCancelledError(ExportError):
    """The export was cancelled."""

    def __init__(self) -> None:
        super().__init__("The export was cancelled.")


class _Writer(Protocol):
    def write(self, samples: AudioArray) -> None: ...

    def close(self) -> None: ...


def export_audio(
    engine: TtsEngine,
    sentences: Sequence[Speakable],
    path: Path,
    *,
    voice: str,
    speed: float,
    title: str = "",
    artist: str = "",
    progress: Callable[[int, int], None] | None = None,
    cancel: threading.Event | None = None,
) -> None:
    """Synthesize ``sentences`` and save them to ``path``. Blocking.

    Args:
        engine: A loaded engine.
        sentences: What to read, in order.
        path: The ``.mp3`` or ``.wav`` file to write (replaced if it exists).
        voice: Voice id.
        speed: Reading speed.
        title: Track title stored in the MP3 file.
        artist: Artist name stored in the MP3 file.
        progress: Called with ``(sentences_done, sentences_total)``.
        cancel: Set it to stop the export.

    Raises:
        ExportCancelledError: ``cancel`` was set.
        ExportError: Speech could not be generated or the file could not be written.
    """
    suffix = path.suffix.lower()
    if suffix not in EXPORT_SUFFIXES:
        raise ExportError("Audio can be saved as MP3 or WAV files.")
    rate = engine.sample_rate
    partial = path.with_name(path.name + ".part")
    try:
        writer: _Writer = (
            _Mp3Writer(partial, rate, title, artist)
            if suffix == ".mp3"
            else _WavWriter(partial, rate)
        )
    except OSError as exc:
        log.warning("Cannot create %s", partial, exc_info=True)
        raise ExportError("Couldn't create the audio file. Please choose another folder.") from exc
    try:
        failures = 0
        for done, sentence in enumerate(sentences, start=1):
            samples = _synthesize(engine, sentence.text, voice, speed, cancel)
            if samples is None:
                failures += 1
                if failures >= _MAX_CONSECUTIVE_FAILURES:
                    raise ExportError(
                        "Speech generation failed several times in a row. Please try another voice."
                    )
                samples = np.zeros(0, dtype=np.float32)
            else:
                failures = 0
            pause = pause_seconds(
                sentence.ends_sentence, getattr(sentence, "ends_paragraph", False), speed
            )
            writer.write(ensure_trailing_silence(samples, rate, pause))
            if progress is not None:
                progress(done, len(sentences))
        writer.close()
        partial.replace(path)
    except BaseException as exc:
        try:
            writer.close()
        finally:
            partial.unlink(missing_ok=True)
        if isinstance(exc, OSError):
            log.warning("Writing %s failed", path, exc_info=True)
            raise ExportError(
                "Couldn't write the audio file. The disk may be full, or the file may be "
                "open in another app."
            ) from exc
        raise
    log.info("Exported %d sentences to %s", len(sentences), path)


def _synthesize(
    engine: TtsEngine, text: str, voice: str, speed: float, cancel: threading.Event | None
) -> AudioArray | None:
    """Synthesize one sentence; ``None`` if it failed. Retries interrupted attempts."""
    for _ in range(_MAX_RETRIES):
        if cancel is not None and cancel.is_set():
            raise ExportCancelledError
        try:
            return engine.synthesize(text, voice, speed)
        except SynthesisCancelledError:
            continue  # Playback cancelled synthesis for its own reasons: try again.
        except TtsError:
            log.exception("Could not synthesize %r for export", text)
            return None
    return None


def _to_pcm16(samples: AudioArray) -> bytes:
    return (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()


class _WavWriter:
    def __init__(self, path: Path, rate: int) -> None:
        self._file = wave.open(str(path), "wb")  # noqa: SIM115 - closed by close().
        self._file.setnchannels(1)
        self._file.setsampwidth(2)
        self._file.setframerate(rate)
        self._closed = False

    def write(self, samples: AudioArray) -> None:
        self._file.writeframes(_to_pcm16(samples))

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._file.close()


class _Mp3Writer:
    def __init__(self, path: Path, rate: int, title: str, artist: str) -> None:
        import lameenc

        self._encoder = lameenc.Encoder()
        self._encoder.set_bit_rate(MP3_BITRATE_KBPS)
        self._encoder.set_in_sample_rate(rate)
        self._encoder.set_channels(1)
        self._encoder.set_quality(2)  # 2 = high quality, still fast.
        self._file = path.open("wb")
        self._closed = False
        self._file.write(id3_tag(title=title, artist=artist))

    def write(self, samples: AudioArray) -> None:
        self._file.write(self._encoder.encode(_to_pcm16(samples)))

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            try:
                self._file.write(self._encoder.flush())
            finally:
                self._file.close()


def id3_tag(*, title: str = "", artist: str = "") -> bytes:
    """Return an ID3v2.3 tag naming the track, so players show the document's title."""
    frames = b""
    for frame_id, value in (("TIT2", title), ("TPE1", artist)):
        if value:
            data = b"\x01" + value.encode("utf-16")  # UTF-16 with a byte-order mark.
            frames += frame_id.encode("ascii") + struct.pack(">I", len(data)) + b"\x00\x00" + data
    if not frames:
        return b""
    size = len(frames)
    syncsafe = bytes((size >> shift) & 0x7F for shift in (21, 14, 7, 0))
    return b"ID3\x03\x00\x00" + syncsafe + frames
