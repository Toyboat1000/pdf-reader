"""First-run dialog that explains and performs the one-time voice model download."""

import logging
from pathlib import Path

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pdf_reader.config.constants import APP_NAME
from pdf_reader.core.session import ReadingSession
from pdf_reader.ui.bridge import SessionBridge

log = logging.getLogger(__name__)


def format_megabytes(size: int) -> str:
    """Format a byte count as whole megabytes, e.g. ``"354 MB"``."""
    return f"{size / 1_000_000:,.0f} MB"


class ModelDownloadDialog(QDialog):
    """Asks permission, then downloads the voice model with progress and retry.

    The dialog is accepted once the files are downloaded and verified, and rejected
    if the user declines or cancels.
    """

    def __init__(
        self,
        session: ReadingSession,
        bridge: SessionBridge,
        total_bytes: int,
        target_dir: Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._session = session
        self._downloading = False
        self.setWindowTitle(f"{APP_NAME}: Voice model download")
        self.setModal(True)
        self.setMinimumWidth(480)

        intro = QLabel(
            f"<h3>One-time download</h3>"
            f"<p>{APP_NAME} reads aloud with the <b>Kokoro</b> AI voice model, which runs "
            f"entirely on your computer. Your documents never leave your PC.</p>"
            f"<p>The voice model needs to be downloaded once "
            f"(about <b>{format_megabytes(total_bytes)}</b>). After that, the app works "
            f"completely offline.</p>"
        )
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.TextFormat.RichText)

        location = QLabel(f"Saved to: {target_dir}")
        location.setWordWrap(True)
        location.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        location.setStyleSheet("color: palette(placeholder-text);")

        self._progress = QProgressBar()
        self._progress.setRange(0, 1000)
        self._progress.setTextVisible(False)
        self._progress.hide()
        self._status = QLabel()
        self._status.setWordWrap(True)
        self._status.hide()

        self._buttons = QDialogButtonBox()
        self._start_button = QPushButton("Download")
        self._start_button.setDefault(True)
        self._close_button = QPushButton("Not now")
        self._buttons.addButton(self._start_button, QDialogButtonBox.ButtonRole.AcceptRole)
        self._buttons.addButton(self._close_button, QDialogButtonBox.ButtonRole.RejectRole)
        self._start_button.clicked.connect(self._start)
        self._close_button.clicked.connect(self._close_or_cancel)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(location)
        layout.addSpacing(8)
        layout.addWidget(self._progress)
        layout.addWidget(self._status)
        layout.addStretch()
        layout.addWidget(self._buttons)

        bridge.download_progress.connect(self._on_progress)
        bridge.download_finished.connect(self._on_finished)
        bridge.download_failed.connect(self._on_failed)

    @Slot()
    def _start(self) -> None:
        self._downloading = True
        self._start_button.setEnabled(False)
        self._start_button.setText("Retry")
        self._close_button.setText("Cancel")
        self._progress.show()
        self._status.show()
        self._status.setText("Connecting...")
        log.info("User started model download")
        self._session.start_model_download()

    @Slot()
    def _close_or_cancel(self) -> None:
        if self._downloading:
            self._status.setText("Cancelling...")
            self._session.cancel_model_download()
        else:
            self.reject()

    @Slot(object, object)
    def _on_progress(self, done: int, total: int) -> None:
        if total > 0:
            self._progress.setValue(int(done * 1000 / total))
        if done >= total:
            self._status.setText("Verifying the downloaded files...")
        else:
            self._status.setText(f"{format_megabytes(done)} of {format_megabytes(total)}")

    @Slot()
    def _on_finished(self) -> None:
        self._downloading = False
        log.info("Model download finished")
        self.accept()

    @Slot(str, bool)
    def _on_failed(self, message: str, cancelled: bool) -> None:
        self._downloading = False
        self._start_button.setEnabled(True)
        self._close_button.setText("Close")
        if cancelled:
            self._status.setText(
                "Download cancelled. Already downloaded data is kept, so it "
                "will continue where it left off."
            )
        else:
            self._status.setText(f"<b>Download failed.</b> {message}")

    def reject(self) -> None:
        """Cancel any running download before closing (Esc and the title-bar X land here)."""
        if self._downloading:
            self._session.cancel_model_download()
            self._downloading = False
        super().reject()
