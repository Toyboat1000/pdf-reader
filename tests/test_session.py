"""Tests for the reading session state machine with a fake engine and fake audio."""

import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pymupdf
import pytest

from pdf_reader.audio.playback import PlaybackController
from pdf_reader.audio.player import AudioPlayer, PlayerListener
from pdf_reader.core import session as session_module
from pdf_reader.core.session import ReadingSession, ReadingState
from pdf_reader.library import LibraryStore
from pdf_reader.text import TextPipeline, default_steps
from pdf_reader.tts.base import ModelLoadError
from tests.fakes import FakeEngine, Recorder, StreamFactory, wait_until


def make_pdf(path: Path, sentences_per_page: list[int]) -> Path:
    doc = pymupdf.open()
    counter = 0
    for count in sentences_per_page:
        page = doc.new_page()
        y = 150  # Body area, clear of the header margin.
        for _ in range(count):
            page.insert_text((72, y), f"Sentence {counter}.")
            counter += 1
            y += 30
    doc.save(path)
    doc.close()
    return path


class Harness:
    def __init__(
        self,
        engine: FakeEngine | None = None,
        *,
        library: LibraryStore | None = None,
        pipeline: TextPipeline | None = None,
    ) -> None:
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
            speed=1.0,
            library=library,
            pipeline=pipeline,
            controller_factory=controller_factory,
        )

    def states(self) -> list[ReadingState]:
        return self.listener.named("on_state_changed")

    def load_model(self) -> None:
        self.session.load_model()
        assert wait_until(lambda: self.listener.named("on_model_loaded") != [])

    def open(self, path: Path) -> None:
        before = len(self.listener.named("on_document_loaded"))
        self.session.open_document(path)
        assert wait_until(lambda: len(self.listener.named("on_document_loaded")) > before)


@pytest.fixture
def h() -> Iterator[Harness]:
    harness = Harness()
    yield harness
    harness.session.shutdown()


@pytest.fixture
def pdf(tmp_path: Path) -> Path:
    return make_pdf(tmp_path / "doc.pdf", [3, 2])


def test_starts_idle(h: Harness) -> None:
    assert h.session.state is ReadingState.IDLE
    assert not h.session.is_model_loaded


def test_model_load_transitions(h: Harness) -> None:
    h.load_model()
    assert wait_until(lambda: h.session.state is ReadingState.READY)
    assert h.states() == [ReadingState.LOADING, ReadingState.READY]
    voices, voice = h.listener.named("on_model_loaded")[0]
    assert voice == "af_heart"
    assert len(voices) == 2


def test_unknown_saved_voice_falls_back_to_default() -> None:
    harness = Harness()
    harness.session.set_voice("zz_missing")
    harness.load_model()
    try:
        assert harness.listener.named("on_model_loaded")[0][1] == "af_heart"
        assert harness.session.voice == "af_heart"
    finally:
        harness.session.shutdown()


def test_model_load_failure_returns_to_idle() -> None:
    class BrokenEngine(FakeEngine):
        def load(self) -> None:
            raise ModelLoadError("corrupt model")

    harness = Harness(BrokenEngine())
    try:
        harness.session.load_model()
        assert wait_until(lambda: harness.listener.named("on_model_error") == ["corrupt model"])
        assert wait_until(lambda: harness.session.state is ReadingState.IDLE)
    finally:
        harness.session.shutdown()


def test_open_document_builds_sentences(h: Harness, pdf: Path) -> None:
    h.load_model()
    h.open(pdf)
    document = h.session.document
    assert document is not None
    assert [s.text for s in document.sentences] == [f"Sentence {i}." for i in range(5)]
    assert document.page_count == 2
    assert document.page_of(3) == 2
    assert h.session.state is ReadingState.READY


def test_open_document_before_model_loads(h: Harness, pdf: Path) -> None:
    h.open(pdf)
    assert h.session.state is ReadingState.IDLE
    h.session.play()  # No model: nothing happens.
    assert h.session.state is ReadingState.IDLE


def test_bad_document_reports_friendly_error(h: Harness, tmp_path: Path) -> None:
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf")
    h.load_model()
    h.session.open_document(bad)
    assert wait_until(lambda: h.listener.named("on_document_error") != [])
    path, message = h.listener.named("on_document_error")[0]
    assert path == bad
    assert "damaged" in message
    assert wait_until(lambda: h.session.state is ReadingState.READY)


def test_bad_document_keeps_previous_one(h: Harness, pdf: Path, tmp_path: Path) -> None:
    h.load_model()
    h.open(pdf)
    first = h.session.document
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"")
    h.session.open_document(bad)
    assert wait_until(lambda: h.listener.named("on_document_error") != [])
    assert h.session.document is first


def test_play_pause_resume_stop(h: Harness, pdf: Path) -> None:
    h.load_model()
    h.open(pdf)
    h.session.play()
    assert h.session.state is ReadingState.PLAYING
    h.session.toggle_play_pause()
    assert h.session.state is ReadingState.PAUSED
    h.session.toggle_play_pause()
    assert h.session.state is ReadingState.PLAYING
    h.session.stop()
    assert h.session.state is ReadingState.READY


def test_position_follows_playback(h: Harness, pdf: Path) -> None:
    h.load_model()
    h.open(pdf)
    h.session.play()
    stream = h.factory.wait_active()
    assert wait_until(lambda: len(h.engine.calls) >= 2)
    stream.pump(700)  # Sentence 0 (11 samples + paragraph pause) and into sentence 1.
    assert wait_until(lambda: h.session.position == 1)
    assert 1 in h.listener.named("on_position_changed")


def test_reaching_end_returns_to_ready_and_play_restarts(h: Harness, pdf: Path) -> None:
    h.load_model()
    h.open(pdf)
    h.session.seek(4)
    stream = h.factory.wait_active()
    assert wait_until(lambda: len(h.engine.calls) >= 1)
    stream.pump(700)
    assert wait_until(lambda: h.session.state is ReadingState.READY)
    assert h.session.position == 4
    h.session.play()
    assert h.session.position == 0
    assert h.session.state is ReadingState.PLAYING


def test_seek_clamps_and_starts_playing(h: Harness, pdf: Path) -> None:
    h.load_model()
    h.open(pdf)
    h.session.seek(99)
    assert h.session.position == 4
    assert h.session.state is ReadingState.PLAYING
    h.session.seek(-5)
    assert h.session.position == 0


def test_next_and_previous_while_stopped_only_move(h: Harness, pdf: Path) -> None:
    h.load_model()
    h.open(pdf)
    h.session.next_sentence()
    h.session.next_sentence()
    assert h.session.position == 2
    h.session.previous_sentence()
    assert h.session.position == 1
    assert h.session.state is ReadingState.READY


def test_next_while_paused_stays_paused_and_restarts_there(h: Harness, pdf: Path) -> None:
    h.load_model()
    h.open(pdf)
    h.session.play()
    h.session.pause()
    h.session.next_sentence()
    assert h.session.state is ReadingState.PAUSED
    h.session.play()
    assert wait_until(lambda: any(text == "Sentence 1." for text in h.engine.texts()))


def test_preview_pauses_reading(h: Harness, pdf: Path) -> None:
    h.load_model()
    h.open(pdf)
    h.session.play()
    h.session.preview_voice("am_adam")
    assert h.session.state is ReadingState.PAUSED
    assert wait_until(lambda: any(voice == "am_adam" for _, voice, _ in h.engine.calls))


def test_voice_and_speed_are_forwarded(h: Harness, pdf: Path) -> None:
    h.load_model()
    h.open(pdf)
    h.session.set_speed(5.0)
    assert h.session.speed == 4.0
    h.session.set_voice("am_adam")
    h.session.play()
    assert wait_until(lambda: ("Sentence 0.", "am_adam", 4.0) in h.engine.calls)


def test_opening_new_document_stops_playback(h: Harness, pdf: Path, tmp_path: Path) -> None:
    h.load_model()
    h.open(pdf)
    h.session.play()
    second = make_pdf(tmp_path / "second.pdf", [1])
    h.open(second)
    assert h.session.state is ReadingState.READY
    assert h.session.position == 0
    assert h.session.document is not None
    assert h.session.document.sentence_count == 1


def test_later_open_supersedes_earlier(
    h: Harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = threading.Event()
    first = make_pdf(tmp_path / "first.pdf", [1])
    second = make_pdf(tmp_path / "second.pdf", [2])
    real_load = session_module.load_pdf

    def slow_load(path: Path, **kwargs: Any) -> Any:
        if path == first:
            gate.wait(2)
        return real_load(path, **kwargs)

    monkeypatch.setattr(session_module, "load_pdf", slow_load)
    h.session.open_document(first)
    h.session.open_document(second)
    assert wait_until(lambda: h.session.document is not None)
    gate.set()
    threading.Event().wait(0.2)
    assert h.session.document is not None
    assert h.session.document.sentence_count == 2


def test_model_download_reports_progress_and_finish(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_download(progress: Any, cancel: threading.Event) -> None:
        progress(5, 10)
        progress(10, 10)

    monkeypatch.setattr(h.engine, "download_missing_files", fake_download)
    h.session.start_model_download()
    assert wait_until(lambda: h.listener.named("on_download_finished") != [])
    assert h.listener.named("on_download_progress") == [(5, 10), (10, 10)]


def test_open_text_creates_unpaginated_document(h: Harness) -> None:
    h.load_model()
    before = len(h.listener.named("on_document_loaded"))
    h.session.open_text("Pasted Title\n\nFirst sentence. Second sentence.")
    assert wait_until(lambda: len(h.listener.named("on_document_loaded")) > before)
    document = h.session.document
    assert document is not None
    assert not document.is_paginated
    assert document.title == "Pasted Title"
    assert document.text == "Pasted Title\n\nFirst sentence. Second sentence."
    assert [s.text for s in document.sentences] == [
        "Pasted Title",
        "First sentence.",
        "Second sentence.",
    ]
    assert h.session.state is ReadingState.READY
    h.session.play()
    assert wait_until(lambda: ("Pasted Title", "af_heart", 1.0) in h.engine.calls)


def test_open_blank_text_reports_error(h: Harness) -> None:
    h.load_model()
    h.session.open_text("  • \n\n ---")
    assert wait_until(lambda: h.listener.named("on_document_error") != [])
    path, message = h.listener.named("on_document_error")[0]
    assert path is None
    assert "no text to read" in message
    assert wait_until(lambda: h.session.state is ReadingState.READY)


def test_text_replaces_pdf_document(h: Harness, pdf: Path) -> None:
    h.load_model()
    h.open(pdf)
    h.session.play()
    before = len(h.listener.named("on_document_loaded"))
    h.session.open_text("Something else entirely.")
    assert wait_until(lambda: len(h.listener.named("on_document_loaded")) > before)
    assert h.session.document is not None
    assert h.session.document.sentence_count == 1
    assert h.session.position == 0
    assert h.session.state is ReadingState.READY


# ------------------------------------------------------------- library: resume


@pytest.fixture
def library_path(tmp_path: Path) -> Path:
    return tmp_path / "library.json"


def with_library(library_path: Path, pipeline: TextPipeline | None = None) -> Harness:
    harness = Harness(library=LibraryStore(library_path), pipeline=pipeline)
    harness.load_model()
    return harness


def test_reopening_resumes_where_reading_stopped(library_path: Path, pdf: Path) -> None:
    first = with_library(library_path)
    try:
        first.open(pdf)
        assert first.listener.named("on_resumed") == []
        first.session.seek(3, play=False)
    finally:
        first.session.shutdown()  # Saves the position.

    second = with_library(library_path)
    try:
        second.open(pdf)
        assert second.session.position == 3
        assert second.listener.named("on_resumed") == [3]
        assert second.listener.named("on_position_changed")[-1] == 3
        assert second.session.state is ReadingState.READY  # Not playing by itself.
    finally:
        second.session.shutdown()


def test_resume_survives_renaming_the_file(library_path: Path, pdf: Path, tmp_path: Path) -> None:
    first = with_library(library_path)
    try:
        first.open(pdf)
        first.session.seek(2, play=False)
        first.session.stop()
    finally:
        first.session.shutdown()
    renamed = pdf.rename(tmp_path / "renamed.pdf")

    second = with_library(library_path)
    try:
        second.open(renamed)
        assert second.session.position == 2
        assert second.session.recent_documents()[0].path == str(renamed)
    finally:
        second.session.shutdown()


def test_finishing_a_document_resets_its_position(library_path: Path, pdf: Path) -> None:
    first = with_library(library_path)
    try:
        first.open(pdf)
        first.session.seek(4)  # Last sentence; starts playing.
        stream = first.factory.wait_active()
        assert wait_until(lambda: len(first.engine.calls) >= 1)
        stream.pump(700)
        assert wait_until(lambda: first.session.state is ReadingState.READY)
    finally:
        first.session.shutdown()

    second = with_library(library_path)
    try:
        second.open(pdf)
        assert second.session.position == 0
        assert second.listener.named("on_resumed") == []
    finally:
        second.session.shutdown()


def test_position_is_saved_when_switching_documents(
    library_path: Path, pdf: Path, tmp_path: Path
) -> None:
    other = make_pdf(tmp_path / "other.pdf", [2])
    harness = with_library(library_path)
    try:
        harness.open(pdf)
        harness.session.seek(4, play=False)
        harness.open(other)
        harness.open(pdf)
        assert harness.session.position == 4
    finally:
        harness.session.shutdown()


def test_text_documents_are_not_remembered(library_path: Path) -> None:
    harness = with_library(library_path)
    try:
        harness.session.open_text("Private pasted text. Second sentence.")
        assert wait_until(lambda: harness.session.document is not None)
        assert not harness.session.can_bookmark
        assert harness.session.add_bookmark() is None
        assert harness.session.bookmarks() == []
        harness.session.seek(1, play=False)
    finally:
        harness.session.shutdown()
    saved = library_path.read_text("utf-8") if library_path.exists() else ""
    assert "Private" not in saved


# ---------------------------------------------------------- library: bookmarks


def test_bookmark_add_rename_remove_and_jump(library_path: Path, pdf: Path) -> None:
    harness = with_library(library_path)
    try:
        harness.open(pdf)
        assert harness.listener.named("on_bookmarks_changed")[-1] == []
        harness.session.seek(3, play=False)
        mark = harness.session.add_bookmark()
        assert mark is not None
        assert mark.label == "Sentence 3."
        assert mark.anchor.index == 3
        assert harness.listener.named("on_bookmarks_changed")[-1] == [mark]

        harness.session.seek(1, play=False)
        early = harness.session.add_bookmark("Early part")
        assert early is not None
        assert [b.id for b in harness.session.bookmarks()] == [early.id, mark.id]

        harness.session.rename_bookmark(mark.id, "Important")
        assert [b.label for b in harness.session.bookmarks()] == ["Early part", "Important"]

        harness.session.go_to_bookmark(mark.id)
        assert harness.session.position == 3
        assert harness.session.state is ReadingState.READY

        harness.session.remove_bookmark(early.id)
        assert [b.id for b in harness.session.bookmarks()] == [mark.id]
    finally:
        harness.session.shutdown()

    reopened = with_library(library_path)
    try:
        reopened.open(pdf)
        (saved,) = reopened.listener.named("on_bookmarks_changed")[-1]
        assert saved.label == "Important"
    finally:
        reopened.session.shutdown()


def test_go_to_bookmark_while_playing_keeps_playing(library_path: Path, pdf: Path) -> None:
    harness = with_library(library_path)
    try:
        harness.open(pdf)
        harness.session.seek(4, play=False)
        mark = harness.session.add_bookmark()
        assert mark is not None
        harness.session.seek(0)
        assert harness.session.state is ReadingState.PLAYING
        harness.session.go_to_bookmark(mark.id)
        assert harness.session.position == 4
        assert harness.session.state is ReadingState.PLAYING
    finally:
        harness.session.shutdown()


def test_bookmarks_follow_their_sentence_when_text_processing_changes(
    library_path: Path, pdf: Path
) -> None:
    first = with_library(library_path)
    try:
        first.open(pdf)
        first.session.seek(3, play=False)
        assert first.session.add_bookmark() is not None
    finally:
        first.session.shutdown()

    def drop_first_sentence(segments: list[Any]) -> list[Any]:
        return segments[1:]

    shifted = TextPipeline([*default_steps(), drop_first_sentence])
    second = with_library(library_path, pipeline=shifted)
    try:
        second.open(pdf)
        (mark,) = second.session.bookmarks()
        assert mark.anchor.index == 2
        assert second.session.document is not None
        assert second.session.document.sentences[2].text == "Sentence 3."
        assert second.session.position == 2  # The resume position followed too.
    finally:
        second.session.shutdown()
