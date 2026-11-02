"""Application-wide constants.

The display name lives here and only here, so renaming the app is a one-line change.
It is also used for the per-user data folders under ``%APPDATA%`` and ``%LOCALAPPDATA%``.
"""

from typing import Final

from pdf_reader import __version__

APP_NAME: Final = "PDF Reader"
"""Human-readable application name, used for window titles and data folders."""

APP_VERSION: Final = __version__
"""Application version, kept in sync with the package version."""

PROJECT_URL: Final[str | None] = None
"""Project home page shown in the About dialog. Set once the repository is published."""
