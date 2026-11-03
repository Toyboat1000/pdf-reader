"""Smoke tests for the main window, using the real session with a fake engine."""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pymupdf
import pytest
from PySide6.QtCore import QMimeData, QPoint, Qt, QUrl
from PySide6.QtGui import QGuiApplication, QKeySequence, QTextCursor
from pytestqt.qtbot import QtBot

from pdf_reader.audio.playback import PlaybackController
from pdf_reader.audio.player import AudioPlayer, PlayerListener
from pdf_reader.config.settings import Settings
from pdf_reader.core.session import ReadingSession, ReadingState
from pdf_reader.library import LibraryStore
from pdf_reader.tts.download import RemoteFile
from pdf_reader.ui.bridge import SessionBridge
from pdf_reader.ui.download_dialog import ModelDownloadDialog
from pdf_reader.ui.main_window import MainWindow, _first_pdf
from pdf_reader.ui.text_dialog import TextInputDialog
from tests.fakes import FakeEngine, StreamFactory


def make_pdf(path: Path) -> Path:
    doc = pymupdf.open()
    for page_number in range(2):
        page = doc.new_page()
        for i in range(3):
            page.insert_text((72, 150 + 30 * i), f"Page {page_number} sentence {i}.")
    doc.save(path)
    doc.close()
    return path


def make_window(qtbot: QtBot, tmp_path: Path, settings: Settings | None = None) -> MainWindow:
    """Create a started window with a fake engine and a library in ``tmp_path``."""
    factory = StreamFactory()

    def controller_factory(*args: Any, **kwargs: Any) -> PlaybackController:
        def make_player(rate: int, listener: PlayerListener) -> AudioPlayer:
            return AudioPlayer(rate, listener, stream_factory=factory)

        return PlaybackController(*args, player_factory=make_player, **kwargs)

    bridge = SessionBridge()
    session = ReadingSession(
        FakeEngine(),
        bridge,
        voice="am_adam",
        speed=1.25,
        library=LibraryStore(tmp_path / "library.json"),
        controller_factory=controller_factory,
    )
    settings = settings or Settings(voice="am_adam", speed=1.25)
    win = MainWindow(session, bridge, settings, tmp_path / "s.json")
    qtbot.addWidget(win)
    win.show()
    win.start()
    # The voice list is filled by a queued signal that can arrive just after READY.
    qtbot.waitUntil(lambda: session.state is ReadingState.READY and win._voice_combo.count() > 0)
    return win


@pytest.fixture
def window(qtbot: QtBot, tmp_path: Path) -> Iterator[MainWindow]:
    win = make_window(qtbot, tmp_path)
    yield win
    win.close()


def open_sample(qtbot: QtBot, window: MainWindow, tmp_path: Path) -> None:
    window.open_file(make_pdf(tmp_path / "sample.pdf"))
    qtbot.waitUntil(lambda: window._document is not None)


def test_voices_and_speed_are_shown(window: MainWindow) -> None:
    combo = window._voice_combo
    assert combo.count() == 2
    assert combo.currentData() == "am_adam"
    assert combo.currentText() == "Adam (US Male)"
    assert window._speed_label.text() == "1.25\u00d7"


def test_open_document_shows_text_and_status(
    qtbot: QtBot, window: MainWindow, tmp_path: Path
) -> None:
    open_sample(qtbot, window, tmp_path)
    text = window._view.toPlainText()
    assert "Page 1" in text
    assert "Page 0 sentence 2." in text
    assert window._page_label.text() == "Page 1 of 2"
    assert window._sentence_label.text() == "Sentence 1 of 6"
    assert window._play_action.isEnabled()
    assert "sample.pdf" in window.windowTitle()


def test_clicking_a_sentence_starts_reading_there(
    qtbot: QtBot, window: MainWindow, tmp_path: Path
) -> None:
    open_sample(qtbot, window, tmp_path)
    view = window._view
    cursor = QTextCursor(view.document())
    cursor.setPosition(view._starts[4] + 2)
    point = view.cursorRect(cursor).center()
    qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    qtbot.waitUntil(lambda: window._session.position == 4)
    assert window._session.state is ReadingState.PLAYING
    assert window._sentence_label.text() == "Sentence 5 of 6"
    assert window._page_label.text() == "Page 2 of 2"


def test_sentence_at_maps_positions(qtbot: QtBot, window: MainWindow, tmp_path: Path) -> None:
    open_sample(qtbot, window, tmp_path)
    view = window._view
    for index in range(6):
        cursor = QTextCursor(view.document())
        cursor.setPosition(view._starts[index] + 1)
        assert view.sentence_at(view.cursorRect(cursor).center()) == index
    assert view.sentence_at(QPoint(1, 1)) == 0


def test_playback_actions(qtbot: QtBot, window: MainWindow, tmp_path: Path) -> None:
    open_sample(qtbot, window, tmp_path)
    session = window._session
    window._play_action.trigger()
    assert session.state is ReadingState.PLAYING
    qtbot.waitUntil(lambda: window._play_action.text() == "&Pause")
    window._play_action.trigger()
    assert session.state is ReadingState.PAUSED
    window._next_action.trigger()
    assert session.position == 1
    window._prev_action.trigger()
    assert session.position == 0
    window._stop_action.trigger()
    assert session.state is ReadingState.READY


def test_keyboard_shortcuts(window: MainWindow) -> None:
    assert window._play_action.shortcut() == QKeySequence(Qt.Key.Key_Space)
    assert window._prev_action.shortcut() == QKeySequence(Qt.Key.Key_Left)
    assert window._next_action.shortcut() == QKeySequence(Qt.Key.Key_Right)
    assert window._open_action.shortcut() == QKeySequence(QKeySequence.StandardKey.Open)


def test_speed_slider_snaps_and_applies(qtbot: QtBot, window: MainWindow) -> None:
    window._speed_slider.setValue(152)
    assert window._speed_slider.value() == 150
    assert window._speed_label.text() == "1.50\u00d7"
    qtbot.waitUntil(lambda: window._session.speed == 1.5)


def test_bad_pdf_shows_message(
    qtbot: QtBot, window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown: list[str] = []
    monkeypatch.setattr(
        "pdf_reader.ui.main_window.QMessageBox.warning",
        lambda _parent, _title, text, *args: shown.append(text),
    )
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"nope")
    window.open_file(bad)
    qtbot.waitUntil(lambda: bool(shown))
    assert "damaged" in shown[0]


def test_first_pdf_from_drop() -> None:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile("C:/a.txt"), QUrl.fromLocalFile("C:/b.PDF")])
    assert _first_pdf(mime.urls()) == Path("C:/b.PDF")
    assert _first_pdf([QUrl("https://example.com/x.pdf")]) is None


def test_close_saves_settings(qtbot: QtBot, window: MainWindow, tmp_path: Path) -> None:
    open_sample(qtbot, window, tmp_path)
    window._speed_slider.setValue(175)
    window.close()
    saved = json.loads((tmp_path / "s.json").read_text(encoding="utf-8"))
    assert saved["speed"] == 1.75
    assert saved["voice"] == "am_adam"
    assert saved["last_folder"] == str(tmp_path)
    assert saved["window_geometry"]


def test_wide_window_gets_reading_margins(qtbot: QtBot, window: MainWindow, tmp_path: Path) -> None:
    open_sample(qtbot, window, tmp_path)
    for width in (1100, 1400, 700, 1250):
        window.resize(width, 760)
        qtbot.wait(20)
        view = window._view
        expected = max(0, (view.width() - 820) // 2)
        assert view.viewportMargins().left() == expected
        assert view.viewportMargins().right() == expected


def test_declining_model_download_leaves_app_usable(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class NeedsDownload(FakeEngine):
        def missing_files(self) -> list[Any]:
            return [RemoteFile("model.onnx", "http://unused", 354_000_000, "0" * 64)]

    monkeypatch.setattr(
        "pdf_reader.ui.main_window.ModelDownloadDialog.exec",
        lambda _self: ModelDownloadDialog.DialogCode.Rejected,
    )
    bridge = SessionBridge()
    session = ReadingSession(NeedsDownload(), bridge, voice="af_heart")
    win = MainWindow(session, bridge, Settings(), tmp_path / "s.json")
    qtbot.addWidget(win)
    win.show()
    win.start()
    assert session.state is ReadingState.IDLE
    assert "Download Voice Model" in win._state_label.text()
    assert win._download_action.isVisible()
    assert not win._play_action.isEnabled()
    assert not win._voice_combo.isEnabled()
    win.close()


def test_text_dialog_requires_text(qtbot: QtBot) -> None:
    dialog = TextInputDialog()
    qtbot.addWidget(dialog)
    assert not dialog._read_button.isEnabled()
    dialog.accept()
    assert dialog.result() != TextInputDialog.DialogCode.Accepted
    dialog._editor.setPlainText("Hello there, reader.")
    assert dialog._read_button.isEnabled()
    assert dialog._count.text() == "3 words"
    dialog.accept()
    assert dialog.result() == TextInputDialog.DialogCode.Accepted
    assert dialog.text() == "Hello there, reader."


def test_text_dialog_paste_button(qtbot: QtBot) -> None:
    QGuiApplication.clipboard().setText("From the clipboard.")
    dialog = TextInputDialog(text="Start. ")
    qtbot.addWidget(dialog)
    dialog._paste()
    assert dialog.text() == "Start. From the clipboard."


def accept_dialog_with(monkeypatch: pytest.MonkeyPatch, text: str | None = None) -> list[str]:
    """Make TextInputDialog.exec return Accepted, optionally replacing its text."""
    seen: list[str] = []

    def fake_exec(dialog: TextInputDialog) -> TextInputDialog.DialogCode:
        seen.append(dialog.text())
        if text is not None:
            dialog._editor.setPlainText(text)
        return TextInputDialog.DialogCode.Accepted

    monkeypatch.setattr(TextInputDialog, "exec", fake_exec)
    return seen


def test_new_text_document_is_read(
    qtbot: QtBot, window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = accept_dialog_with(monkeypatch, "My Notes\n\nFirst point. Second point.")
    window._new_text_action.trigger()
    assert seen == [""]
    qtbot.waitUntil(lambda: window._document is not None)
    assert window.windowTitle().startswith("My Notes - ")
    assert "Page 1" not in window._view.toPlainText()
    assert window._view.toPlainText().startswith("My Notes")
    assert not window._page_label.isVisible()
    assert window._sentence_label.text() == "Sentence 1 of 3"
    assert window._edit_text_action.isEnabled()
    window._play_action.trigger()
    assert window._session.state is ReadingState.PLAYING


def test_paste_action_uses_clipboard(
    qtbot: QtBot, window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    QGuiApplication.clipboard().setText("Copied from a web page.")
    seen = accept_dialog_with(monkeypatch)
    window._paste_action.trigger()
    assert seen == ["Copied from a web page."]
    qtbot.waitUntil(lambda: window._document is not None)
    assert window._document is not None
    assert window._document.text == "Copied from a web page."


def test_edit_text_reopens_with_current_text(
    qtbot: QtBot, window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    accept_dialog_with(monkeypatch, "Original text.")
    window._new_text_action.trigger()
    qtbot.waitUntil(lambda: window._document is not None)
    seen = accept_dialog_with(monkeypatch, "Edited text. With two sentences.")
    window._edit_text_action.trigger()
    assert seen == ["Original text."]
    qtbot.waitUntil(lambda: window._document is not None and window._document.sentence_count == 2)


def test_edit_text_disabled_for_pdfs(qtbot: QtBot, window: MainWindow, tmp_path: Path) -> None:
    open_sample(qtbot, window, tmp_path)
    assert not window._edit_text_action.isEnabled()
    assert window._page_label.isVisible()


def test_cancelled_text_dialog_changes_nothing(
    qtbot: QtBot, window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(TextInputDialog, "exec", lambda _self: TextInputDialog.DialogCode.Rejected)
    window._new_text_action.trigger()
    qtbot.wait(50)
    assert window._document is None


def test_text_shortcuts(window: MainWindow) -> None:
    assert window._new_text_action.shortcut() == QKeySequence(QKeySequence.StandardKey.New)
    assert window._paste_action.shortcut() == QKeySequence(QKeySequence.StandardKey.Paste)
    assert window._edit_text_action.shortcut() == QKeySequence("Ctrl+E")


# ------------------------------------------------------------------ bookmarks


def test_add_bookmark_shows_in_panel_and_text(
    qtbot: QtBot, window: MainWindow, tmp_path: Path
) -> None:
    open_sample(qtbot, window, tmp_path)
    assert window._add_bookmark_action.isEnabled()
    window._session.seek(2, play=False)
    window._add_bookmark_action.trigger()
    qtbot.waitUntil(lambda: window._bookmarks_panel.ids() != [])
    assert window._view.bookmarked == {2}
    item = window._bookmarks_panel._list.item(0)
    assert item.text() == "Page 0 sentence 2.\nPage 1"
    assert window.statusBar().currentMessage().startswith("Bookmark added")


def test_bookmark_panel_actions(
    qtbot: QtBot, window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    open_sample(qtbot, window, tmp_path)
    window._session.seek(4, play=False)
    window._add_bookmark_action.trigger()
    qtbot.waitUntil(lambda: len(window._bookmarks_panel.ids()) == 1)
    (bookmark_id,) = window._bookmarks_panel.ids()
    panel = window._bookmarks_panel
    panel._list.setCurrentRow(0)

    monkeypatch.setattr(
        "pdf_reader.ui.main_window.QInputDialog.getText",
        lambda *_args, **_kwargs: ("Chapter start", True),
    )
    panel._rename_button.click()
    qtbot.waitUntil(lambda: panel._list.item(0).text().startswith("Chapter start"))

    window._session.seek(0, play=False)
    panel._on_activated(panel._list.item(0))
    assert window._session.position == 4

    panel._list.setCurrentRow(0)
    panel._remove_button.click()
    qtbot.waitUntil(lambda: panel.ids() == [])
    assert window._view.bookmarked == set()
    assert bookmark_id not in panel.ids()


def test_bookmarks_disabled_for_pasted_text(
    qtbot: QtBot, window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    accept_dialog_with(monkeypatch, "Some pasted text. More text.")
    window._new_text_action.trigger()
    qtbot.waitUntil(lambda: window._document is not None)
    assert not window._add_bookmark_action.isEnabled()
    assert not window._bookmarks_panel._add_button.isEnabled()


def test_bookmarks_panel_toggle_is_saved(qtbot: QtBot, window: MainWindow, tmp_path: Path) -> None:
    assert window._bookmarks_panel.isHidden()
    window._show_bookmarks_action.trigger()
    assert not window._bookmarks_panel.isHidden()
    window.close()
    saved = json.loads((tmp_path / "s.json").read_text(encoding="utf-8"))
    assert saved["show_bookmarks"] is True
    assert saved["window_state"]


# --------------------------------------------------------------------- resume


def test_reopening_shows_resume_banner(qtbot: QtBot, tmp_path: Path) -> None:
    first = make_window(qtbot, tmp_path)
    open_sample(qtbot, first, tmp_path)
    first._session.seek(4, play=False)
    first.close()

    second = make_window(qtbot, tmp_path)
    try:
        second.open_file(tmp_path / "sample.pdf")
        qtbot.waitUntil(lambda: second._banner.isVisible())
        assert second._session.position == 4
        assert second._banner.message == "Continuing where you left off (page 2)."
        assert second._sentence_label.text() == "Sentence 5 of 6"

        second._banner.start_over.emit()
        assert second._session.position == 0
        qtbot.waitUntil(lambda: second._sentence_label.text() == "Sentence 1 of 6")
    finally:
        second.close()


def test_banner_hides_when_reading_starts(qtbot: QtBot, tmp_path: Path) -> None:
    first = make_window(qtbot, tmp_path)
    open_sample(qtbot, first, tmp_path)
    first._session.seek(3, play=False)
    first.close()

    second = make_window(qtbot, tmp_path)
    try:
        second.open_file(tmp_path / "sample.pdf")
        qtbot.waitUntil(lambda: second._banner.isVisible())
        second._play_action.trigger()
        qtbot.waitUntil(lambda: not second._banner.isVisible())
    finally:
        second.close()


def test_open_recent_menu(qtbot: QtBot, window: MainWindow, tmp_path: Path) -> None:
    window._fill_recent_menu()
    (empty,) = window._recent_menu.actions()
    assert not empty.isEnabled()

    open_sample(qtbot, window, tmp_path)
    window._fill_recent_menu()
    (entry,) = window._recent_menu.actions()
    assert entry.text() == "sample.pdf"
    assert entry.isEnabled()

    (tmp_path / "sample.pdf").unlink()
    window._fill_recent_menu()
    (missing,) = window._recent_menu.actions()
    assert missing.text() == "sample.pdf (not found)"
    assert not missing.isEnabled()


def test_pdfs_open_as_page_images_with_copy_and_zoom(
    qtbot: QtBot, window: MainWindow, tmp_path: Path
) -> None:
    open_sample(qtbot, window, tmp_path)
    assert window._views.currentWidget() is window._page_view  # The default view.
    window._page_view.select_all()
    window._copy()
    assert "Page 0 sentence 0." in QGuiApplication.clipboard().text()
    window._copy_all()
    assert QGuiApplication.clipboard().text().startswith("Page 0 sentence 0.")

    window._zoom_by(2.0)
    assert window._page_view.zoom == pytest.approx(2.0)
    window._zoom_reset()
    assert window._page_view.zoom == 1.0

    window._page_images_action.trigger()  # Settings > Show PDFs as Page Images: off.
    assert window._views.currentWidget() is window._view
    window._zoom_by(1.5)
    assert window._view.zoom == pytest.approx(1.5)
