"""Display names and languages for Kokoro v1.0 English voices.

Ordered by the quality grades in the Kokoro-82M ``VOICES.md``, best first within
each group. Only English voices are listed for now; other languages need extra
phonemizer setup.
"""

from pdf_reader.tts.base import Voice

_ACCENTS = {"a": ("en-us", "US"), "b": ("en-gb", "UK")}
_GENDERS = {"f": "Female", "m": "Male"}

# Voice ids in display order. The prefix encodes accent (a/b) and gender (f/m).
KOKORO_ENGLISH_VOICE_IDS: tuple[str, ...] = (
    "af_heart", "af_bella", "af_nicole", "af_aoede", "af_kore", "af_sarah", "af_alloy",
    "af_nova", "af_sky", "af_jessica", "af_river",
    "am_fenrir", "am_michael", "am_puck", "am_echo", "am_eric", "am_liam", "am_onyx",
    "am_santa", "am_adam",
    "bf_emma", "bf_isabella", "bf_alice", "bf_lily",
    "bm_fable", "bm_george", "bm_lewis", "bm_daniel",
)  # fmt: skip


def voice_from_id(voice_id: str) -> Voice | None:
    """Describe a Kokoro voice id such as ``"af_heart"``, or return ``None`` if unsupported."""
    prefix, _, name = voice_id.partition("_")
    if len(prefix) != 2 or not name:
        return None
    accent = _ACCENTS.get(prefix[0])
    gender = _GENDERS.get(prefix[1])
    if accent is None or gender is None:
        return None
    language, accent_label = accent
    return Voice(
        id=voice_id,
        name=name.capitalize(),
        language=language,
        accent=accent_label,
        gender=gender,
    )


def english_voices(available: set[str]) -> list[Voice]:
    """Return the supported English voices present in ``available``, best first."""
    return [
        voice
        for voice_id in KOKORO_ENGLISH_VOICE_IDS
        if voice_id in available and (voice := voice_from_id(voice_id)) is not None
    ]
