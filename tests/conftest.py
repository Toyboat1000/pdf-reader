import os
from collections.abc import Iterator

import pytest

# Run Qt tests without showing windows.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def _no_blocking_message_boxes(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """Make unexpected message boxes return at once instead of waiting for a click.

    A modal dialog in an off-screen test would wait forever. Tests that check a
    message replace these again with their own recorder.
    """
    from PySide6.QtWidgets import QMessageBox

    shown: list[str] = []

    def record(*args: object, **_kwargs: object) -> QMessageBox.StandardButton:
        shown.append(str(args[2]) if len(args) > 2 else "")
        return QMessageBox.StandardButton.No

    for name in ("warning", "information", "critical", "question"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(record))
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
    yield shown
