"""Tabs: several documents open, one listened to; and the home page on start-up."""

import threading
from collections.abc import Iterator
from pathlib import Path

import pymupdf
import pytest
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from pdf_reader.config.settings import Settings, load_settings
from pdf_reader.core.session import ReadingState
from pdf_reader.ui.main_window import MainWindow
from tests.test_ui import make_window


def make_pdf(path: Path, word: str, pages: int = 1) -> Path:
    doc = pymupdf.open()
    for page_number in range(pages):
        page = doc.new_page()
        for i in range(3):
            page.insert_text((72, 150 + 30 * i), f"{word} page {page_number} sentence {i}.")
    doc.save(path)
    doc.close()
    return path


@pytest.fixture
def window(qtbot: QtBot, tmp_path: Path) -> Iterator[MainWindow]:
    win = make_window(qtbot, tmp_path)
    yield win
    win.close()


def open_tab(qtbot: QtBot, window: MainWindow, path: Path) -> None:
    window.open_file(path)
    qtbot.waitUntil(lambda: (tab := window._current_tab()) is not None and not tab.loading)


def test_each_document_gets_a_tab_and_the_shown_one_is_listened_to(
    qtbot: QtBot, window: MainWindow, tmp_path: Path
) -> None:
    open_tab(qtbot, window, make_pdf(tmp_path / "a.pdf", "Alpha"))
    open_tab(qtbot, window, make_pdf(tmp_path / "b.pdf", "Beta"))
    assert window._tab_strip.count() == 3  # Home, a.pdf, b.pdf.
    assert [t.title for t in window._tabs] == ["a.pdf", "b.pdf"]
    # Nothing is playing, so the player follows the tab on screen.
    assert window._listening is window._current_tab()
    assert window._session.document is window._listening.document
    window._step_tab(-1)
    assert window._current_tab().title == "a.pdf"
    assert window._session.document is window._current_tab().document


def test_reading_goes_on_while_another_tab_is_browsed(
    qtbot: QtBot, window: MainWindow, tmp_path: Path
) -> None:
    open_tab(qtbot, window, make_pdf(tmp_path / "a.pdf", "Alpha"))
    listening = window._listening
    window._session.play()
    qtbot.waitUntil(lambda: window._session.state is ReadingState.PLAYING)

    open_tab(qtbot, window, make_pdf(tmp_path / "b.pdf", "Beta"))
    assert window._session.state is ReadingState.PLAYING
    assert window._listening is listening  # Still reading a.pdf.
    assert window._player.now_playing.isVisibleTo(window._player)
    assert "a.pdf" in window._player.now_playing.text()

    window._player.now_playing.click()  # "Show": back to what's playing.
    assert window._current_tab() is listening
    assert not window._player.now_playing.isVisibleTo(window._player)
    window._session.stop()


def test_play_or_click_on_another_tab_switches_listening(
    qtbot: QtBot, window: MainWindow, tmp_path: Path
) -> None:
    open_tab(qtbot, window, make_pdf(tmp_path / "a.pdf", "Alpha"))
    first = window._listening
    window._session.play()
    qtbot.waitUntil(lambda: window._session.state is ReadingState.PLAYING)
    open_tab(qtbot, window, make_pdf(tmp_path / "b.pdf", "Beta"))
    second = window._current_tab()

    window._on_sentence_clicked(2)  # Click a sentence of b.pdf.
    assert window._listening is second
    assert window._session.document is second.document
    qtbot.waitUntil(lambda: window._session.position == 2)
    assert window._session.state is ReadingState.PLAYING

    window._toggle_play()  # Pause.
    assert window._session.state is ReadingState.PAUSED
    window._select(first)  # Nothing playing: the shown tab is read from now on.
    assert window._listening is first
    window._toggle_play()
    qtbot.waitUntil(lambda: window._session.state is ReadingState.PLAYING)
    assert window._session.document is first.document
    window._session.stop()


def test_closing_the_listening_tab_stops_reading(
    qtbot: QtBot, window: MainWindow, tmp_path: Path
) -> None:
    open_tab(qtbot, window, make_pdf(tmp_path / "a.pdf", "Alpha"))
    window._session.play()
    qtbot.waitUntil(lambda: window._session.state is ReadingState.PLAYING)
    window._close_tab_action.trigger()
    assert window._session.state is ReadingState.READY
    assert window._session.document is None
    assert window._listening is None and window._tabs == []
    assert window._views.currentWidget() is window._home
    assert window._player.elapsed_label.text() == ""


def test_opening_an_open_file_shows_its_tab(
    qtbot: QtBot, window: MainWindow, tmp_path: Path
) -> None:
    path = make_pdf(tmp_path / "a.pdf", "Alpha")
    open_tab(qtbot, window, path)
    window._show_home()
    window.open_file(path)
    assert window._tab_strip.count() == 2
    assert window._current_tab() is window._tabs[0]


def test_pasted_text_opens_in_its_own_tab(qtbot: QtBot, window: MainWindow) -> None:
    window.open_text("A note to self. Buy milk.")
    qtbot.waitUntil(lambda: window._tabs and not window._tabs[0].loading)
    assert window._tabs[0].title == "A note to self. Buy milk."
    assert window._edit_text_action.isEnabled()


def test_a_failed_file_closes_its_tab(qtbot: QtBot, window: MainWindow, tmp_path: Path) -> None:
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf")
    window.open_file(bad)
    qtbot.waitUntil(lambda: window._tabs == [])
    assert window._tab_strip.count() == 1


def test_home_shows_recent_documents_right_after_starting(qtbot: QtBot, tmp_path: Path) -> None:
    first = make_window(qtbot, tmp_path)
    open_tab(qtbot, first, make_pdf(tmp_path / "a.pdf", "Alpha"))
    first.close()

    second = make_window(qtbot, tmp_path)  # The app started again.
    try:
        assert second._views.currentWidget() is second._home
        assert [c.record.title for c in second._home.cards()] == ["a"]
    finally:
        second.close()


def test_open_tabs_come_back_after_a_restart(qtbot: QtBot, tmp_path: Path) -> None:
    first = make_window(qtbot, tmp_path)
    open_tab(qtbot, first, make_pdf(tmp_path / "a.pdf", "Alpha"))
    open_tab(qtbot, first, make_pdf(tmp_path / "b.pdf", "Beta"))
    first._step_tab(-1)  # Leave a.pdf on screen.
    first.open_text("Private pasted text.")  # Not restored.
    qtbot.waitUntil(lambda: not first._tabs[-1].loading)
    first._select(first._tabs[0])
    first.close()

    saved = load_settings(tmp_path / "s.json")
    assert [Path(p).name for p in saved.open_tabs] == ["a.pdf", "b.pdf"]
    assert saved.current_tab == 0
    second = make_window(qtbot, tmp_path, Settings(open_tabs=saved.open_tabs, current_tab=0))
    try:
        assert [t.title for t in second._tabs] == ["a.pdf", "b.pdf"]
        qtbot.waitUntil(lambda: not second._tabs[0].loading)  # Shown, so loaded.
        assert second._tabs[1].loading and second._tabs[1].request is None  # Not yet.
        second._select(second._tabs[1])
        qtbot.waitUntil(lambda: not second._tabs[1].loading)
    finally:
        second.close()


def test_new_reading_options_reread_every_tab(
    qtbot: QtBot, window: MainWindow, tmp_path: Path
) -> None:
    open_tab(qtbot, window, make_pdf(tmp_path / "a.pdf", "Alpha", pages=2))
    window._session.seek(4, play=False)
    old = window._listening.document
    window._parentheses_action.toggle()
    qtbot.waitUntil(lambda: window._listening.document is not old)
    qtbot.waitUntil(lambda: window._session.document is window._listening.document)
    assert window._session.position == 4
    assert not window._banner.isVisible()  # No "continuing where you left off".


def test_a_tab_remembers_where_it_was_scrolled(
    qtbot: QtBot, window: MainWindow, tmp_path: Path
) -> None:
    window._page_images_action.setChecked(False)
    open_tab(qtbot, window, make_pdf(tmp_path / "a.pdf", "Alpha", pages=30))
    first = window._current_tab()
    open_tab(qtbot, window, make_pdf(tmp_path / "b.pdf", "Beta", pages=2))
    window._select(first)
    bar = window._view.verticalScrollBar()
    qtbot.waitUntil(lambda: bar.maximum() > 400)
    bar.setValue(400)
    window._show_home()  # Away, through the home page, and back.
    window._select(window._tabs[1])
    window._select(first)
    qtbot.waitUntil(lambda: bar.value() == 400)


def test_only_the_view_on_screen_is_filled_in(
    qtbot: QtBot, window: MainWindow, tmp_path: Path
) -> None:
    open_tab(qtbot, window, make_pdf(tmp_path / "a.pdf", "Alpha"))
    document = window._current_tab().document
    assert window._views.currentWidget() is window._page_view
    assert window._page_view_document is document
    assert window._text_view_document is None  # Not laid out until needed.
    window._page_images_action.setChecked(False)
    assert window._text_view_document is document
    assert window._views.currentWidget() is window._view


def test_dropping_several_files_opens_a_tab_for_each(
    qtbot: QtBot, window: MainWindow, tmp_path: Path
) -> None:
    from PySide6.QtCore import QMimeData, QPoint, QPointF, QUrl
    from PySide6.QtGui import QDropEvent

    paths = [make_pdf(tmp_path / f"{n}.pdf", n) for n in ("one", "two", "three")]
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    event = QDropEvent(
        QPointF(QPoint(10, 10)),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.dropEvent(event)
    assert [t.title for t in window._tabs] == ["one.pdf", "two.pdf", "three.pdf"]
    assert window._current_tab() is window._tabs[0]
    qtbot.waitUntil(lambda: all(not t.loading for t in window._tabs[:1]))


def test_a_second_launch_hands_its_file_to_the_running_copy(
    qtbot: QtBot, window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pdf_reader.ui import single_instance

    monkeypatch.setattr(single_instance, "_server_name", lambda: f"PDFReaderTest-{tmp_path.name}")
    running = single_instance.SingleInstance()
    running.listen()
    running.message_received.connect(window.bring_forward)
    path = make_pdf(tmp_path / "from-explorer.pdf", "Explorer")

    # The second copy is another process; here, another thread does its part.
    handed: list[bool] = []
    launch = threading.Thread(
        target=lambda: handed.append(single_instance.SingleInstance().send_to_running(str(path)))
    )
    launch.start()
    qtbot.waitUntil(lambda: [t.title for t in window._tabs] == ["from-explorer.pdf"])
    launch.join(5)
    assert handed == [True]

    monkeypatch.setattr(single_instance, "_server_name", lambda: "PDFReaderTest-nobody")
    assert not single_instance.SingleInstance().send_to_running("")  # Nobody running.
