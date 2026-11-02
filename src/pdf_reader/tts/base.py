"""The text-to-speech engine interface that the rest of the app depends on.

To add an engine, subclass :class:`TtsEngine` in its own module. Nothing outside
``tts/`` needs to know which engine is in use.
"""

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from pdf_reader.tts.download import ProgressCallback, RemoteFile

type AudioArray = NDArray[np.float32]
"""Mono audio samples in the range [-1, 1]."""


@dataclass(frozen=True, slots=True)
class Voice:
    """A voice offered by an engine.

    Attributes:
        id: Engine-specific identifier, stored in settings.
        name: Short display name, e.g. "Heart".
        language: Language/locale code passed to the engine, e.g. "en-us".
        accent: Short accent label, e.g. "US" or "UK".
        gender: "Female" or "Male".
    """

    id: str
    name: str
    language: str
    accent: str
    gender: str

    @property
    def label(self) -> str:
        """Return a friendly label such as "Heart (US Female)"."""
        return f"{self.name} ({self.accent} {self.gender})"


class TtsError(Exception):
    """Base class for TTS engine failures."""


class ModelLoadError(TtsError):
    """The engine's model could not be loaded (missing, corrupt, or incompatible)."""


class SynthesisError(TtsError):
    """Speech could not be generated for a piece of text."""


class SynthesisCancelledError(TtsError):
    """A :meth:`TtsEngine.synthesize` call was interrupted by :meth:`TtsEngine.cancel`."""


class TtsEngine(ABC):
    """Abstract text-to-speech engine.

    Implementations must allow :meth:`synthesize` to be called from a background
    thread. :meth:`load` may be slow and is always called off the UI thread.
    """

    @property
    @abstractmethod
    def sample_rate(self) -> int:
        """Return the sample rate of generated audio, in Hz."""

    @property
    @abstractmethod
    def is_loaded(self) -> bool:
        """Return whether :meth:`load` has completed successfully."""

    @abstractmethod
    def load(self) -> None:
        """Load the model. Blocking; safe to call more than once.

        Raises:
            ModelLoadError: The model could not be loaded.
        """

    @abstractmethod
    def voices(self) -> list[Voice]:
        """Return the available voices, best first."""

    @abstractmethod
    def synthesize(self, text: str, voice_id: str, speed: float) -> AudioArray:
        """Generate speech for ``text``.

        Args:
            text: The text to speak; may be a sentence or a sentence fragment.
            voice_id: One of the ids returned by :meth:`voices`.
            speed: Speed multiplier, 0.5 to 2.0.

        Returns:
            Mono float32 samples at :attr:`sample_rate`, without leading or trailing
            silence. May be empty if the text contains nothing pronounceable.

        Raises:
            SynthesisError: Generation failed.
            SynthesisCancelledError: :meth:`cancel` was called during generation.
        """

    def cancel(self) -> None:
        """Interrupt any :meth:`synthesize` calls in progress, if the engine supports it.

        Used to stop generating audio the user no longer needs (after a seek, for
        example). Engines that cannot interrupt simply let the call finish.
        """
        return None

    def missing_files(self) -> list[RemoteFile]:
        """Return model files that must be downloaded before :meth:`load` can work.

        Engines that need no downloads keep this default, which returns an empty list.
        """
        return []

    def download_missing_files(
        self, progress: ProgressCallback | None = None, cancel: threading.Event | None = None
    ) -> None:
        """Download and verify the files reported by :meth:`missing_files`. Blocking.

        Raises:
            DownloadError: The download failed.
            DownloadCancelledError: ``cancel`` was set.
        """
        if self.missing_files():
            raise NotImplementedError(f"{type(self).__name__} cannot download its files")

    def discard_model_files(self) -> None:
        """Delete downloaded model files so they will be downloaded again.

        Used when the files exist but fail to load (for example, they are corrupt).
        Engines without downloaded files have nothing to delete.
        """
        return None

    def default_voice_id(self) -> str | None:
        """Return the id of the recommended voice, or ``None`` if there are no voices."""
        voices = self.voices()
        return voices[0].id if voices else None
