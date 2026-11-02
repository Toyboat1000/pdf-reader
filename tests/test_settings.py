import json
from pathlib import Path

import pytest

from pdf_reader.config import paths
from pdf_reader.config.constants import APP_NAME
from pdf_reader.config.settings import (
    DEFAULT_VOICE,
    MAX_SPEED,
    MIN_SPEED,
    Settings,
    clamp_speed,
    load_settings,
    save_settings,
)


def test_missing_file_gives_defaults(tmp_path: Path) -> None:
    assert load_settings(tmp_path / "nope.json") == Settings()


def test_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "settings.json"
    original = Settings(voice="bm_george", speed=1.35, window_geometry="abcd", last_folder="C:/x")
    save_settings(original, path)
    assert load_settings(path) == original
    assert not path.with_suffix(".json.tmp").exists()


@pytest.mark.parametrize("content", ["{not json", "[1, 2, 3]", '"text"', ""])
def test_invalid_content_gives_defaults(tmp_path: Path, content: str) -> None:
    path = tmp_path / "settings.json"
    path.write_text(content, encoding="utf-8")
    assert load_settings(path) == Settings()


def test_invalid_fields_fall_back_individually(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "voice": 42,
                "speed": "fast",
                "window_geometry": ["x"],
                "last_folder": "D:/docs",
                "unknown": True,
            }
        ),
        encoding="utf-8",
    )
    settings = load_settings(path)
    assert settings.voice == DEFAULT_VOICE
    assert settings.speed == 1.0
    assert settings.window_geometry is None
    assert settings.last_folder == "D:/docs"


@pytest.mark.parametrize(("stored", "expected"), [(9, MAX_SPEED), (0.1, MIN_SPEED), (1.25, 1.25)])
def test_speed_is_clamped_on_load(tmp_path: Path, stored: float, expected: float) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"speed": stored}), encoding="utf-8")
    assert load_settings(path).speed == expected


def test_boolean_speed_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"speed": True}), encoding="utf-8")
    assert load_settings(path).speed == 1.0


def test_clamp_speed() -> None:
    assert clamp_speed(0.0) == MIN_SPEED
    assert clamp_speed(5.0) == MAX_SPEED
    assert clamp_speed(1.5) == 1.5


def test_save_failure_is_logged_not_raised(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    save_settings(Settings(), blocker / "settings.json")  # Parent is a file: cannot write.


def test_paths_use_environment() -> None:
    env = {"APPDATA": "C:/Roaming", "LOCALAPPDATA": "C:/Local"}
    assert paths.settings_file(env) == Path("C:/Roaming") / APP_NAME / "settings.json"
    assert paths.models_dir(env) == Path("C:/Local") / APP_NAME / "models"
    assert paths.logs_dir(env) == Path("C:/Local") / APP_NAME / "logs"


def test_paths_fall_back_without_environment() -> None:
    assert paths.settings_dir({}) == Path.home() / "AppData" / "Roaming" / APP_NAME
    assert paths.local_data_dir({}) == Path.home() / "AppData" / "Local" / APP_NAME
