from pathlib import Path

from pdf_reader.tts.base import Voice
from pdf_reader.tts.kokoro_engine import KOKORO_FILES, KokoroEngine
from pdf_reader.tts.kokoro_voices import KOKORO_ENGLISH_VOICE_IDS, english_voices, voice_from_id


def test_friendly_labels() -> None:
    assert voice_from_id("af_heart") == Voice("af_heart", "Heart", "en-us", "US", "Female")
    assert voice_from_id("bm_george") == Voice("bm_george", "George", "en-gb", "UK", "Male")
    heart = voice_from_id("af_heart")
    assert heart is not None
    assert heart.label == "Heart (US Female)"


def test_unsupported_ids() -> None:
    for voice_id in ("jf_alpha", "zf_xiaobei", "heart", "a_x", "xx_name", "af_"):
        assert voice_from_id(voice_id) is None


def test_english_voices_filters_and_orders() -> None:
    available = {"bm_george", "af_heart", "jf_alpha", "am_michael"}
    assert [v.id for v in english_voices(available)] == ["af_heart", "am_michael", "bm_george"]


def test_catalogue_has_default_first_and_no_duplicates() -> None:
    assert KOKORO_ENGLISH_VOICE_IDS[0] == "af_heart"
    assert len(set(KOKORO_ENGLISH_VOICE_IDS)) == len(KOKORO_ENGLISH_VOICE_IDS) == 28
    assert all(voice_from_id(v) is not None for v in KOKORO_ENGLISH_VOICE_IDS)


def test_engine_reports_missing_files(tmp_path: Path) -> None:
    engine = KokoroEngine(tmp_path)
    assert engine.missing_files() == list(KOKORO_FILES)
    assert not engine.is_loaded
    assert engine.voices() == []


def test_discard_model_files(tmp_path: Path) -> None:
    for file in KOKORO_FILES:
        (tmp_path / file.name).write_bytes(b"x")
    KokoroEngine(tmp_path).discard_model_files()
    assert not any(tmp_path.iterdir())
