"""Text-to-speech engines behind a common interface, plus model file management."""

from pdf_reader.tts.base import (
    AudioArray,
    ModelLoadError,
    Speech,
    SynthesisCancelledError,
    SynthesisError,
    TtsEngine,
    TtsError,
    Voice,
)

__all__ = [
    "AudioArray",
    "ModelLoadError",
    "Speech",
    "SynthesisCancelledError",
    "SynthesisError",
    "TtsEngine",
    "TtsError",
    "Voice",
]
