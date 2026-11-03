"""Write the installer's settings from the app's own constants (one source of truth).

Usage::

    uv run python packaging/write_defines.py build/defines.iss

The app name and version, and the voice model's addresses, sizes, and SHA-256
hashes, come from the code, so the installer can never download a different file
than the app expects.
"""

import sys
from pathlib import Path

from pdf_reader.config.constants import APP_NAME, APP_VERSION, PROJECT_URL
from pdf_reader.tts.kokoro_engine import KOKORO_MODEL, KOKORO_VOICES


def defines() -> str:
    """Return Inno Setup ``#define`` lines."""
    values: dict[str, str | int] = {
        "AppName": APP_NAME,
        "AppVersion": APP_VERSION,
        "AppUrl": PROJECT_URL or "",
        "ModelName": KOKORO_MODEL.name,
        "ModelUrl": KOKORO_MODEL.url,
        "ModelSize": KOKORO_MODEL.size,
        "ModelSha256": KOKORO_MODEL.sha256,
        "VoicesName": KOKORO_VOICES.name,
        "VoicesUrl": KOKORO_VOICES.url,
        "VoicesSize": KOKORO_VOICES.size,
        "VoicesSha256": KOKORO_VOICES.sha256,
    }
    lines = []
    for name, value in values.items():
        if isinstance(value, int):
            lines.append(f"#define {name} {value}")
        else:
            if '"' in value:
                raise ValueError(f"{name} must not contain quotes")
            lines.append(f'#define {name} "{value}"')
    return "\n".join(lines) + "\n"


def main() -> None:
    """Write the defines to the file named on the command line."""
    target = Path(sys.argv[1])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(defines(), encoding="utf-8")


if __name__ == "__main__":
    main()
