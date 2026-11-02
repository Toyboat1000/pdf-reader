"""User settings persisted as JSON between sessions.

Loading never fails: a missing, unreadable, or partially invalid file falls back to
defaults field by field, so a bad settings file can never stop the app from starting.
"""

import json
import logging
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

MIN_SPEED = 0.5
"""Slowest supported reading speed."""

MAX_SPEED = 2.0
"""Fastest supported reading speed."""

DEFAULT_VOICE = "af_heart"
"""Voice used until the user picks another one."""


@dataclass
class Settings:
    """Everything the app remembers between sessions.

    Attributes:
        voice: Identifier of the selected TTS voice.
        speed: Reading speed multiplier, between ``MIN_SPEED`` and ``MAX_SPEED``.
        window_geometry: Opaque, hex-encoded window size and position from the UI.
        last_folder: Folder of the most recently opened document.
    """

    voice: str = DEFAULT_VOICE
    speed: float = 1.0
    window_geometry: str | None = None
    last_folder: str | None = None


def clamp_speed(speed: float) -> float:
    """Limit a speed value to the supported range."""
    return max(MIN_SPEED, min(MAX_SPEED, speed))


def _validated(raw: dict[str, Any]) -> Settings:
    """Build settings from parsed JSON, keeping only values of the expected type."""
    result = Settings()
    if isinstance(voice := raw.get("voice"), str) and voice:
        result.voice = voice
    speed = raw.get("speed")
    if isinstance(speed, int | float) and not isinstance(speed, bool):
        result.speed = clamp_speed(float(speed))
    for name in ("window_geometry", "last_folder"):
        if isinstance(value := raw.get(name), str) and value:
            setattr(result, name, value)
    known = {f.name for f in fields(Settings)}
    if unknown := set(raw) - known:
        log.debug("Ignoring unknown settings keys: %s", sorted(unknown))
    return result


def load_settings(path: Path) -> Settings:
    """Load settings from ``path``, falling back to defaults on any problem."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        log.info("No settings file at %s; using defaults", path)
        return Settings()
    except OSError:
        log.warning("Could not read settings file %s; using defaults", path, exc_info=True)
        return Settings()
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        log.warning("Settings file %s is not valid JSON; using defaults", path)
        return Settings()
    if not isinstance(raw, dict):
        log.warning("Settings file %s does not contain an object; using defaults", path)
        return Settings()
    return _validated(raw)


def save_settings(settings: Settings, path: Path) -> None:
    """Write settings to ``path`` atomically (a crash never leaves a half-written file).

    Errors are logged rather than raised: failing to save settings should not
    interrupt the user.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        log.exception("Could not save settings to %s", path)
