"""Per-user file locations.

Settings are small and roam with the user profile (``%APPDATA%``); models and logs are
large or machine-specific and go to ``%LOCALAPPDATA%``.
"""

import os
from collections.abc import Mapping
from pathlib import Path

from pdf_reader.config.constants import APP_NAME


def _base_dir(env_var: str, fallback: Path, env: Mapping[str, str] | None) -> Path:
    environ = os.environ if env is None else env
    value = environ.get(env_var)
    return Path(value) if value else fallback


def settings_dir(env: Mapping[str, str] | None = None) -> Path:
    r"""Return the folder holding the settings file (``%APPDATA%\<AppName>``)."""
    base = _base_dir("APPDATA", Path.home() / "AppData" / "Roaming", env)
    return base / APP_NAME


def local_data_dir(env: Mapping[str, str] | None = None) -> Path:
    r"""Return the folder for machine-local data (``%LOCALAPPDATA%\<AppName>``)."""
    base = _base_dir("LOCALAPPDATA", Path.home() / "AppData" / "Local", env)
    return base / APP_NAME


def settings_file(env: Mapping[str, str] | None = None) -> Path:
    """Return the path of the JSON settings file."""
    return settings_dir(env) / "settings.json"


def library_file(env: Mapping[str, str] | None = None) -> Path:
    """Return the path of the JSON file with reading positions and bookmarks."""
    return settings_dir(env) / "library.json"


def models_dir(env: Mapping[str, str] | None = None) -> Path:
    """Return the folder where downloaded voice models are stored."""
    return local_data_dir(env) / "models"


def logs_dir(env: Mapping[str, str] | None = None) -> Path:
    """Return the folder where log files are written."""
    return local_data_dir(env) / "logs"
