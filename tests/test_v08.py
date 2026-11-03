"""Version 0.8: word-by-word timing, more formats, export, speeds, themes, and media keys."""

import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pymupdf
import pytest
from pytestqt.qtbot import QtBot

from pdf_reader.audio.export import ExportCancelledError, ExportError, export_audio, id3_tag
from pdf_reader.audio.playback import PlaybackController
from pdf_reader.audio.player import AudioChunk, AudioPlayer, PlayerListener
from pdf_reader.config.settings import MAX_SPEED, Settings, _validated, clamp_speed
from pdf_reader.core.session import ReadingSession, ReadingState
from pdf_reader.core.word_map import build_word_map
from pdf_reader.library import LibraryStore
from pdf_reader.library.thumbnails import save_thumbnail
from pdf_reader.pdf.formats import EBOOK_PAGE, filetype_of, is_paged
from pdf_reader.pdf.loader import load_pdf
from pdf_reader.pdf.render import PageRenderer
from pdf_reader.system.media_controls import MediaCommand
from pdf_reader.text.pipeline import build_pipeline
from pdf_reader.tts.base import SynthesisCancelledError
from pdf_reader.ui.main_window import MainWindow
from pdf_reader.ui.player_bar import format_duration, format_time_left
from pdf_reader.ui.theme import DYSLEXIC_FONT
from scripts.make_sample_documents import CHAPTERS, build_docx, build_epub, build_html
from tests.fakes import SAMPLE_RATE, FakeEngine, Recorder, StreamFactory, wait_until
from tests.test_ui import make_window, open_sample

# ------------------------------------------------------------------ e-books


def test_epub_is_read_as_pages(tmp_path: Path) -> None:
    path = build_epub(tmp_path / "book.epub")
    document = load_pdf(path)
    assert document.title == "A Sample Book"
    assert document.page_count == 2  # One chapter per page.
    assert (document.pages[0].width, document.pages[0].height) == EBOOK_PAGE
    sentences = build_pipeline().process_document(document)
    assert sentences[0].text == CHAPTERS[0][0]
    assert sentences[0].ends_paragraph
    assert build_word_map(document, sentences) is not None
    renderer = PageRenderer(path)
    page = renderer.render(1, 1.0)
    assert (page.width, page.height) == (round(EBOOK_PAGE[0]), round(EBOOK_PAGE[1]))
    renderer.close()
    cover = tmp_path / "cover.png"
    save_thumbnail(path, cover)
    assert cover.read_bytes().startswith(b"\x89PNG")


def test_paged_formats() -> None:
    assert filetype_of(Path("a.EPUB")) == "epub"
    assert filetype_of(Path("a.pdf")) == "pdf"
    assert is_paged(Path("x.mobi")) and not is_paged(Path("x.docx"))


# ------------------------------------------------------------------ word map


def test_word_map_knows_each_spoken_word(tmp_path: Path) -> None:
    pdf = pymupdf.open()
    pdf.new_page().insert_text((72, 150), "Good morning to you all.")
    path = tmp_path / "w.pdf"
    pdf.save(path)
    pdf.close()
    document = load_pdf(path)
    sentences = build_pipeline().process_document(document)
    word_map = build_word_map(document, sentences)
    assert word_map is not None
    assert [b.word for b in word_map.sentence_boxes(0)] == [0, 1, 2, 3, 4]
    ((page, box),) = word_map.word_boxes(0, 1)
    morning = word_map.sentence_boxes(0)[1].bbox
    assert page == 1
    assert box[0] == morning[0] and box[2] == morning[2]
    band = word_map.sentence_lines(0)[0][1]
    assert (box[1], box[3]) == (band[1], band[3])  # Lines up with the sentence pill.
    assert word_map.word_boxes(0, 9) == []


# ------------------------------------------------------------------ playhead


def test_playhead_follows_audible_samples() -> None:
    factory = StreamFactory()
    player = AudioPlayer(SAMPLE_RATE, Recorder(), stream_factory=factory)
    try:
        assert player.playhead() is None
        player.offer(AudioChunk(0, 1, np.ones(500, np.float32), (0.0, 0.2)))
        stream = factory.wait_active()
        stream.pump(300)  # 0.3 s of audio, heard over the next 0.3 s.
        time.sleep(0.1)
        head = player.playhead()
        assert head is not None and head[0].index == 0
        assert 0.08 <= head[1] < 0.3
        player.pause()
        stream.pump(100)  # Paused: silence, so the playhead stops where the sound did.
        time.sleep(0.3)
        paused = player.playhead()
        assert paused is not None and paused[1] == pytest.approx(0.3)
        player.clear()
        assert player.playhead() is None
    finally:
        player.close()


class _Harness:
    def __init__(self, tmp_path: Path, engine: FakeEngine | None = None) -> None:
        self.engine = engine or FakeEngine()
        self.listener = Recorder()
        self.factory = StreamFactory()

        def controller_factory(*args: Any, **kwargs: Any) -> PlaybackController:
            def make_player(rate: int, listener: PlayerListener) -> AudioPlayer:
                return AudioPlayer(rate, listener, stream_factory=self.factory)

            return PlaybackController(*args, player_factory=make_player, **kwargs)

        self.session = ReadingSession(
            self.engine,
            self.listener,
            voice="af_heart",
            library=LibraryStore(tmp_path / "library.json"),
            download_dir=tmp_path / "downloads",
            controller_factory=controller_factory,
        )
        self.session.load_model()
        assert wait_until(lambda: self.listener.named("on_model_loaded") != [])

    def open(self, path: Path) -> Any:
        before = len(self.listener.named("on_document_loaded"))
        self.session.open_document(path)
        assert wait_until(
            lambda: (
                len(self.listener.named("on_document_loaded")) > before
                or self.listener.named("on_document_error") != []
            )
        )
        assert self.listener.named("on_document_error") == []
        return self.listener.named("on_document_loaded")[-1]


@pytest.fixture
def harness(tmp_path: Path) -> Iterator[_Harness]:
    h = _Harness(tmp_path)
    yield h
    h.session.shutdown()


def test_current_word_moves_through_the_sentence(harness: _Harness, tmp_path: Path) -> None:
    path = tmp_path / "words.txt"
    path.write_text("One two three four.", encoding="utf-8")
    harness.open(path)
    assert harness.session.current_word() is None
    harness.session.play()
    stream = harness.factory.wait_active()
    stream.pump(1)
    assert wait_until(lambda: harness.session.current_word() == (0, 0))
    seen = set()
    for _ in range(25):
        stream.pump(1)
        word = harness.session.current_word()
        if word is not None:
            seen.add(word[1])
    assert seen == {0, 1, 2, 3}
    harness.session.stop()
    assert harness.session.current_word() is None


def test_listening_time_estimates(harness: _Harness, tmp_path: Path) -> None:
    path = tmp_path / "time.txt"
    path.write_text("A first sentence here. " * 10, encoding="utf-8")
    document = harness.open(path)
    listened, total = harness.session.listening_time()
    assert listened == 0
    assert total == pytest.approx(document.total_characters / 15.0)
    harness.session.set_speed(2.0)
    assert harness.session.listening_time()[1] == pytest.approx(total / 2)
    harness.session.seek(5, play=False)
    listened, _ = harness.session.listening_time()
    assert listened == pytest.approx(document.characters_before(5) / 30.0)


# ------------------------------------------------------------------ formats


def test_session_opens_every_format(harness: _Harness, tmp_path: Path) -> None:
    epub = harness.open(build_epub(tmp_path / "book.epub"))
    assert epub.is_paginated and epub.word_map is not None
    docx = harness.open(build_docx(tmp_path / "story.docx"))
    assert not docx.is_paginated
    assert docx.title == "A Sample Story"
    assert docx.sentences[0].text == CHAPTERS[0][0]
    assert docx.doc_id is not None  # Remembered, so reading resumes next time.
    page = tmp_path / "saved.html"
    page.write_text(build_html(), encoding="utf-8")
    assert harness.open(page).title == "A Sample Story"
    recent = harness.session.recent_documents()
    assert {r.title for r in recent} >= {"A Sample Book", "A Sample Story"}
    assert next(r for r in recent if r.title == "A Sample Book").page_count == 2


def test_open_url_reads_the_article(harness: _Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    from pdf_reader.sources import FetchResult, TextSource

    def fake_fetch(address: str, folder: Path) -> FetchResult:
        assert folder.name == "downloads"
        return FetchResult(
            "https://example.com/story",
            article=TextSource("A Story", ("A Story", "It was a calm night.")),
        )

    monkeypatch.setattr("pdf_reader.core.session.fetch", fake_fetch)
    harness.session.open_url("example.com/story")
    assert wait_until(lambda: harness.listener.named("on_document_loaded") != [])
    document = harness.listener.named("on_document_loaded")[-1]
    assert document.source_url == "https://example.com/story"
    assert document.title == "A Story"
    record = harness.session.recent_documents()[0]
    assert record.path == "https://example.com/story"
    # Changing reading options re-reads the page's text without fetching it again.
    monkeypatch.setattr("pdf_reader.core.session.fetch", None)
    harness.session.set_pipeline(build_pipeline(read_parentheses=False))
    assert wait_until(lambda: len(harness.listener.named("on_document_loaded")) == 2)
    assert harness.listener.named("on_document_loaded")[-1].source_url == document.source_url


def test_open_url_error(harness: _Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    from pdf_reader.sources import SourceError

    def failing(address: str, folder: Path) -> None:
        raise SourceError("This page wasn't found.")

    monkeypatch.setattr("pdf_reader.core.session.fetch", failing)
    harness.session.open_url("https://example.com/missing")
    assert wait_until(lambda: harness.listener.named("on_document_error") != [])
    assert harness.listener.named("on_document_error")[0] == (None, "This page wasn't found.")
    assert harness.session.state is ReadingState.READY


# ------------------------------------------------------------------ export


class _Sentence:
    def __init__(self, text: str, ends_paragraph: bool = False) -> None:
        self.text = text
        self.ends_sentence = True
        self.ends_paragraph = ends_paragraph


def test_export_wav_has_speech_and_pauses(tmp_path: Path) -> None:
    import wave

    engine = FakeEngine()
    engine.loaded = True
    progress: list[tuple[int, int]] = []
    path = tmp_path / "out.wav"
    export_audio(
        engine,
        [_Sentence("Hello."), _Sentence("World.", ends_paragraph=True)],
        path,
        voice="af_heart",
        speed=1.0,
        progress=lambda done, total: progress.append((done, total)),
    )
    assert progress == [(1, 2), (2, 2)]
    with wave.open(str(path)) as wav:
        assert wav.getframerate() == SAMPLE_RATE
        frames = wav.getnframes()
    # Six samples of speech per sentence plus a 0.2 s and a 0.55 s pause.
    assert frames == 6 + 200 + 6 + 550
    assert not (tmp_path / "out.wav.part").exists()


def test_export_mp3_is_tagged(tmp_path: Path) -> None:
    engine = FakeEngine()
    engine.loaded = True
    path = tmp_path / "out.mp3"
    export_audio(engine, [_Sentence("Hello there.")], path, voice="af_heart", speed=1.0, title="T")
    data = path.read_bytes()
    assert data.startswith(id3_tag(title="T"))
    assert len(data) > len(id3_tag(title="T"))


def test_id3_tag_layout() -> None:
    tag = id3_tag(title="Hi", artist="Me")
    assert tag[:5] == b"ID3\x03\x00"
    size = tag[6] << 21 | tag[7] << 14 | tag[8] << 7 | tag[9]
    assert size == len(tag) - 10
    assert b"TIT2" in tag and b"TPE1" in tag
    assert id3_tag() == b""


def test_export_cancel_removes_the_file(tmp_path: Path) -> None:
    engine = FakeEngine()
    engine.loaded = True
    cancel = threading.Event()
    path = tmp_path / "out.mp3"

    def progress(done: int, total: int) -> None:
        cancel.set()

    with pytest.raises(ExportCancelledError):
        export_audio(
            engine,
            [_Sentence("One."), _Sentence("Two.")],
            path,
            voice="af_heart",
            speed=1.0,
            progress=progress,
            cancel=cancel,
        )
    assert not path.exists() and not (tmp_path / "out.mp3.part").exists()


def test_export_retries_when_playback_interrupts(tmp_path: Path) -> None:
    class Interrupted(FakeEngine):
        def __init__(self) -> None:
            super().__init__()
            self.interruptions = 2

        def synthesize(self, text: str, voice_id: str, speed: float) -> Any:
            if self.interruptions:
                self.interruptions -= 1
                raise SynthesisCancelledError("seek")
            return super().synthesize(text, voice_id, speed)

    engine = Interrupted()
    engine.loaded = True
    export_audio(engine, [_Sentence("Hi.")], tmp_path / "a.wav", voice="af_heart", speed=1.0)
    assert engine.interruptions == 0
    assert (tmp_path / "a.wav").exists()


def test_export_reports_bad_types_and_repeated_failures(tmp_path: Path) -> None:
    engine = FakeEngine()
    engine.loaded = True
    with pytest.raises(ExportError, match="MP3 or WAV"):
        export_audio(engine, [], tmp_path / "a.ogg", voice="af_heart", speed=1.0)
    engine.fail_texts = {"A.", "B.", "C."}
    with pytest.raises(ExportError, match="several times"):
        export_audio(
            engine,
            [_Sentence("A."), _Sentence("B."), _Sentence("C.")],
            tmp_path / "b.wav",
            voice="af_heart",
            speed=1.0,
        )
    assert not (tmp_path / "b.wav").exists()


def test_session_export(harness: _Harness, tmp_path: Path) -> None:
    path = tmp_path / "doc.txt"
    path.write_text("First sentence. Second sentence.", encoding="utf-8")
    harness.open(path)
    target = tmp_path / "doc.wav"
    assert harness.session.start_export(target)
    assert wait_until(lambda: harness.listener.named("on_export_finished") == [target])
    assert target.exists()
    assert not harness.session.is_exporting
    assert harness.listener.named("on_export_progress")[-1] == (2, 2)


# ------------------------------------------------------------------ settings


def test_speed_goes_up_to_four() -> None:
    assert MAX_SPEED == 4.0
    assert clamp_speed(3.5) == 3.5


def test_new_settings_are_validated() -> None:
    settings = _validated({"theme": "sepia", "dyslexic_font": True, "word_highlight": False})
    assert (settings.theme, settings.dyslexic_font, settings.word_highlight) == (
        "sepia",
        True,
        False,
    )
    assert _validated({"theme": "neon", "dyslexic_font": "yes"}) == Settings()


def test_time_formats() -> None:
    assert format_duration(65) == "1:05"
    assert format_duration(3729) == "1:02:09"
    assert format_time_left(30) == "Less than a minute left"
    assert format_time_left(12 * 60) == "12 min left"
    assert format_time_left(65 * 60) == "1 h 5 min left"
    assert format_time_left(120 * 60) == "2 h left"


# ------------------------------------------------------------------ window


@pytest.fixture
def window(qtbot: QtBot, tmp_path: Path) -> Iterator[MainWindow]:
    win = make_window(qtbot, tmp_path)
    yield win
    win.close()


def test_player_shows_listening_time(qtbot: QtBot, window: MainWindow, tmp_path: Path) -> None:
    open_sample(qtbot, window, tmp_path)
    player = window._player
    assert player.elapsed_label.text() == "0:00"
    assert player.remaining_label.text().startswith("\u2212")
    assert "0%" in player.progress_label.text()


def test_words_are_highlighted_while_reading(
    qtbot: QtBot, window: MainWindow, tmp_path: Path
) -> None:
    open_sample(qtbot, window, tmp_path)
    window._show_page_images(False)
    window._session.play()
    qtbot.waitUntil(lambda: window._word_timer.isActive())
    window._view.highlight_word(window._session.position, 1)
    assert window._view._word == (window._session.position, 1)
    assert len(window._view.extraSelections()) == 2  # The sentence and its spoken word.
    window._word_highlight_action.setChecked(False)
    assert window._view._word is None
    assert window._settings.word_highlight is False
    window._session.stop()
    qtbot.waitUntil(lambda: not window._word_timer.isActive())


def test_page_view_word_highlight(qtbot: QtBot, window: MainWindow, tmp_path: Path) -> None:
    open_sample(qtbot, window, tmp_path)
    view = window._page_view
    view.highlight(0)
    view.highlight_word(0, 1)
    assert view._word == 1 and view._word_pieces
    view.highlight_word(0, 2)  # Same line: glides from the previous word.
    assert view._word_from is not None
    view.highlight_word(5, 0)  # Not the current sentence: ignored.
    assert view._word == 2
    view.highlight(1)
    assert view._word == -1 and not view._word_pieces


def test_theme_and_dyslexic_font(qtbot: QtBot, window: MainWindow) -> None:
    sepia = next(a for a in window._theme_group.actions() if a.data() == "sepia")
    sepia.trigger()
    assert window._settings.theme == "sepia"
    assert window._page_view._tint is not None
    dark = next(a for a in window._theme_group.actions() if a.data() == "dark")
    dark.trigger()
    assert window._page_view._tint is None
    system = next(a for a in window._theme_group.actions() if a.data() == "system")
    system.trigger()
    window._dyslexic_action.setChecked(True)
    assert window._view.font().family() == DYSLEXIC_FONT
    assert window._settings.dyslexic_font
    window._dyslexic_action.setChecked(False)
    assert window._view.font().family() == "Segoe UI"


def test_media_buttons_control_reading(qtbot: QtBot, window: MainWindow, tmp_path: Path) -> None:
    open_sample(qtbot, window, tmp_path)
    window._on_media_command(MediaCommand.PLAY)
    qtbot.waitUntil(lambda: window._session.state is ReadingState.PLAYING)
    window._on_media_command(MediaCommand.NEXT)
    qtbot.waitUntil(lambda: window._session.position == 1)
    window._on_media_command(MediaCommand.PREVIOUS)
    qtbot.waitUntil(lambda: window._session.position == 0)
    window._on_media_command(MediaCommand.PAUSE)
    qtbot.waitUntil(lambda: window._session.state is ReadingState.PAUSED)
    window._on_media_command(MediaCommand.STOP)
    qtbot.waitUntil(lambda: window._session.state is ReadingState.READY)
    # Buttons pressed on a Windows thread arrive on the UI thread through a signal.
    threading.Thread(target=lambda: window._media_signals.command.emit(MediaCommand.PLAY)).start()
    qtbot.waitUntil(lambda: window._session.state is ReadingState.PLAYING)
    window._session.stop()


def test_pasting_a_link_opens_it(
    qtbot: QtBot, window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[str] = []
    monkeypatch.setattr(window._session, "open_url", opened.append)
    window.open_text("  https://example.com/article  ")
    assert opened == ["https://example.com/article"]
    window._open_location("https://example.com/other")
    assert opened[-1] == "https://example.com/other"


def test_export_from_the_window(
    qtbot: QtBot, window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    open_sample(qtbot, window, tmp_path)
    target = tmp_path / "sample audio"
    monkeypatch.setattr(
        "pdf_reader.ui.main_window.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: (str(target), "MP3 audio (*.mp3)"),
    )
    shown: list[str] = []
    monkeypatch.setattr(
        "pdf_reader.ui.main_window.QMessageBox.exec", lambda box: shown.append(box.text())
    )
    window._export_action.trigger()
    qtbot.waitUntil(lambda: bool(shown), timeout=10000)
    assert shown == ["Saved sample audio.mp3"]
    assert (tmp_path / "sample audio.mp3").exists()
    assert window._export_dialog is None
    assert window._export_action.isEnabled()


def test_open_link_dialog(
    qtbot: QtBot, window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[str] = []
    monkeypatch.setattr(window._session, "open_url", opened.append)
    monkeypatch.setattr(
        "pdf_reader.ui.main_window.QInputDialog.getText",
        lambda *args, **kwargs: ("www.example.com/page", True),
    )
    window._open_link_action.trigger()
    assert opened == ["www.example.com/page"]


def test_recent_web_page_card(qtbot: QtBot, tmp_path: Path) -> None:
    from pdf_reader.library.models import DocumentRecord
    from pdf_reader.ui.home_view import DocumentCard

    card = DocumentCard(
        DocumentRecord(
            doc_id="web-1",
            title="A Story",
            path="https://example.com/story",
            last_opened="2026-01-01T00:00:00+00:00",
        ),
        None,
    )
    qtbot.addWidget(card)
    assert card.isEnabled()
    assert "Web page" in card._details()
    clicked: list[str] = []
    card.clicked.connect(clicked.append)
    card.clicked.emit(card.record.path or "")
    assert clicked == ["https://example.com/story"]
