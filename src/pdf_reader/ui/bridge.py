"""Turns session callbacks (from any thread) into Qt signals (handled on the UI thread)."""

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from pdf_reader.core.document import ReadingDocument
from pdf_reader.core.session import ReadingState, SessionListener
from pdf_reader.library import Bookmark
from pdf_reader.tts.base import Voice


class SessionBridge(QObject, SessionListener):
    """A :class:`SessionListener` that re-emits every event as a Qt signal.

    Create it on the UI thread. Signals emitted from background threads are
    delivered to slots on the UI thread through Qt's queued connections, so slots
    can safely touch widgets.
    """

    state_changed = Signal(object)  # ReadingState
    model_loaded = Signal(list, str)  # list[Voice], voice id
    model_error = Signal(str)
    download_progress = Signal(object, object)  # bytes done, bytes total (may exceed 2**31)
    download_finished = Signal()
    download_failed = Signal(str, bool)  # message, cancelled
    document_loaded = Signal(object)  # ReadingDocument
    document_error = Signal(object, str)  # Path or None, message
    position_changed = Signal(int)
    playback_error = Signal(str)
    resumed = Signal(int)
    loading_progress = Signal(int, int)  # pages done, page count
    bookmarks_changed = Signal(list)  # list[Bookmark]
    export_progress = Signal(int, int)  # sentences done, total
    export_finished = Signal(object)  # Path
    export_failed = Signal(str, bool)  # message, cancelled

    def on_state_changed(self, state: ReadingState) -> None:
        """Emit :attr:`state_changed`."""
        self.state_changed.emit(state)

    def on_model_loaded(self, voices: list[Voice], voice_id: str) -> None:
        """Emit :attr:`model_loaded`."""
        self.model_loaded.emit(voices, voice_id)

    def on_model_error(self, message: str) -> None:
        """Emit :attr:`model_error`."""
        self.model_error.emit(message)

    def on_download_progress(self, done: int, total: int) -> None:
        """Emit :attr:`download_progress`."""
        self.download_progress.emit(done, total)

    def on_download_finished(self) -> None:
        """Emit :attr:`download_finished`."""
        self.download_finished.emit()

    def on_download_failed(self, message: str, cancelled: bool) -> None:
        """Emit :attr:`download_failed`."""
        self.download_failed.emit(message, cancelled)

    def on_document_loaded(self, document: ReadingDocument) -> None:
        """Emit :attr:`document_loaded`."""
        self.document_loaded.emit(document)

    def on_document_error(self, path: Path | None, message: str) -> None:
        """Emit :attr:`document_error`."""
        self.document_error.emit(path, message)

    def on_position_changed(self, index: int) -> None:
        """Emit :attr:`position_changed`."""
        self.position_changed.emit(index)

    def on_playback_error(self, message: str) -> None:
        """Emit :attr:`playback_error`."""
        self.playback_error.emit(message)

    def on_loading_progress(self, done: int, total: int) -> None:
        """Emit :attr:`loading_progress`."""
        self.loading_progress.emit(done, total)

    def on_resumed(self, index: int) -> None:
        """Emit :attr:`resumed`."""
        self.resumed.emit(index)

    def on_bookmarks_changed(self, bookmarks: list[Bookmark]) -> None:
        """Emit :attr:`bookmarks_changed`."""
        self.bookmarks_changed.emit(bookmarks)

    def on_export_progress(self, done: int, total: int) -> None:
        """Emit :attr:`export_progress`."""
        self.export_progress.emit(done, total)

    def on_export_finished(self, path: Path) -> None:
        """Emit :attr:`export_finished`."""
        self.export_finished.emit(path)

    def on_export_failed(self, message: str, cancelled: bool) -> None:
        """Emit :attr:`export_failed`."""
        self.export_failed.emit(message, cancelled)
