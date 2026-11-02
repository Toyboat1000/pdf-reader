"""Text-to-speech engines behind a common interface, plus model file management."""

from pdf_reader.tts.base import (
    AudioArray,
    ModelLoadError,
    SynthesisError,
    TtsEngine,
    TtsError,
    Voice,
)

__all__ = ["AudioArray", "ModelLoadError", "SynthesisError", "TtsEngine", "TtsError", "Voice"]
