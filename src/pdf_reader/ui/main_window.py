"""The main application window: menus, toolbar, document view, and status bar."""

import logging
from pathlib import Path

from PySide6.QtCore import QByteArray, QSize, Qt, QTimer, QUrl, Slot
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QDesktopServices,
    QDragEnterEvent,
    QDropEvent,
    QKeySequence,
)
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSlider,
    QToolBar,
    QToolButton,
)

from pdf_reader.config.constants import APP_NAME, APP_VERSION, PROJECT_URL
from pdf_reader.config.paths import logs_dir, models_dir
from pdf_reader.config.settings import MAX_SPEED, MIN_SPEED, Settings, save_settings
from pdf_reader.core.document import ReadingDocument
from pdf_reader.core.session import ReadingSession, ReadingState
from pdf_reader.tts.base import Voice
from pdf_reader.ui.bridge import SessionBridge
from pdf_reader.ui.document_view import DocumentView
from pdf_reader.ui.download_dialog import ModelDownloadDialog
from pdf_reader.ui.icons import Glyph, make_icon

log = logging.getLogger(__name__)

_SPEED_STEP = 5  # Slider units are hundredths, so this is 0.05x.
_SPEED_APPLY_DELAY_MS = 250  # Wait for the slider to settle before regenerating audio.

_STATE_LABELS = {
    ReadingState.IDLE: "Voice model not loaded",
    ReadingState.LOADING: "Loading...",
    ReadingState.READY: "Ready",
    ReadingState.PLAYING: "Reading",
    ReadingState.PAUSED: "Paused",
}


class MainWindow(QMainWindow):
    """Top-level window. Talks only to :class:`ReadingSession` (via :class:`SessionBridge`)."""

    def __init__(
        self,
        session: ReadingSession,
        bridge: SessionBridge,
        settings: Settings,
        settings_path: Path,
    ) -> None:
        super().__init__()
        self._session = session
        self._bridge = bridge
        self._settings = settings
        self._settings_path = settings_path
        self._document: ReadingDocument | None = None
        self._model_loading = False
        self._doc_loading_name: str | None = None
        self._shut_down = False

        self.setWindowTitle(APP_NAME)
        self.setAcceptDrops(True)
        self.resize(1000, 760)
        self.setMinimumSize(QSize(640, 420))

        self._view = DocumentView(self)
        self.setCentralWidget(self._view)

        self._create_actions()
        self._create_menus()
        self._create_toolbar()
        self._create_status_bar()
        self._connect_signals()
        self._restore_geometry()

        self._speed_timer = QTimer(self)
        self._speed_timer.setSingleShot(True)
        self._speed_timer.setInterval(_SPEED_APPLY_DELAY_MS)
        self._speed_timer.timeout.connect(self._apply_speed)

        self._update_controls()

    # ------------------------------------------------------------- start-up

    def start(self, initial_file: Path | None = None) -> None:
        """Begin loading the model (downloading it first if needed), then open a file."""
        if initial_file is not None:
            self.open_file(initial_file)
        self._ensure_model()

    def _ensure_model(self) -> None:
        missing = self._session.missing_model_files()
        if missing:
            dialog = ModelDownloadDialog(
                self._session,
                self._bridge,
                total_bytes=sum(f.size for f in missing),
                target_dir=models_dir(),
                parent=self,
            )
            accepted = dialog.exec() == ModelDownloadDialog.DialogCode.Accepted
            dialog.deleteLater()
            if not accepted:
                log.info("Model download declined")
                self._update_controls()
                return
        self._model_loading = True
        self._session.load_model()
        self._update_controls()

    # --------------------------------------------------------------- set-up

    def _create_actions(self) -> None:
        self._open_action = QAction(make_icon(Glyph.OPEN, self), "&Open PDF...", self)
        self._open_action.setShortcut(QKeySequence.StandardKey.Open)
        self._open_action.setToolTip("Open a PDF (Ctrl+O)")
        self._open_action.triggered.connect(self._choose_file)

        self._exit_action = QAction("E&xit", self)
        self._exit_action.setShortcut(QKeySequence("Alt+F4"))
        self._exit_action.triggered.connect(self.close)

        self._play_icon = make_icon(Glyph.PLAY, self)
        self._pause_icon = make_icon(Glyph.PAUSE, self)
        self._play_action = QAction(self._play_icon, "&Play", self)
        self._play_action.setShortcut(QKeySequence(Qt.Key.Key_Space))
        self._play_action.setToolTip("Play / Pause (Space)")
        self._play_action.triggered.connect(self._session.toggle_play_pause)

        self._stop_action = QAction(make_icon(Glyph.STOP, self), "&Stop", self)
        self._stop_action.setToolTip("Stop")
        self._stop_action.triggered.connect(self._session.stop)

        self._prev_action = QAction(make_icon(Glyph.PREVIOUS, self), "P&revious Sentence", self)
        self._prev_action.setShortcut(QKeySequence(Qt.Key.Key_Left))
        self._prev_action.setToolTip("Previous sentence (Left arrow)")
        self._prev_action.triggered.connect(self._session.previous_sentence)

        self._next_action = QAction(make_icon(Glyph.NEXT, self), "&Next Sentence", self)
        self._next_action.setShortcut(QKeySequence(Qt.Key.Key_Right))
        self._next_action.setToolTip("Next sentence (Right arrow)")
        self._next_action.triggered.connect(self._session.next_sentence)

        self._download_action = QAction("&Download Voice Model...", self)
        self._download_action.triggered.connect(self._ensure_model)

        self._logs_action = QAction("Open &Log Folder", self)
        self._logs_action.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(logs_dir())))
        )

        self._about_action = QAction(f"&About {APP_NAME}", self)
        self._about_action.triggered.connect(self._show_about)

        for action in (self._play_action, self._prev_action, self._next_action):
            # Window-wide, so they work whichever control was clicked last.
            action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            self.addAction(action)

    def _create_menus(self) -> None:
        bar = self.menuBar()
        file_menu = bar.addMenu("&File")
        file_menu.addAction(self._open_action)
        file_menu.addSeparator()
        file_menu.addAction(self._exit_action)

        playback = bar.addMenu("&Playback")
        playback.addAction(self._play_action)
        playback.addAction(self._stop_action)
        playback.addSeparator()
        playback.addAction(self._prev_action)
        playback.addAction(self._next_action)

        help_menu = bar.addMenu("&Help")
        help_menu.addAction(self._download_action)
        help_menu.addAction(self._logs_action)
        help_menu.addSeparator()
        help_menu.addAction(self._about_action)

    def _create_toolbar(self) -> None:
        toolbar = QToolBar("Playback", self)
        toolbar.setObjectName("playback-toolbar")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(22, 22))
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.addToolBar(toolbar)

        toolbar.addAction(self._open_action)
        toolbar.addSeparator()
        toolbar.addAction(self._prev_action)
        toolbar.addAction(self._play_action)
        toolbar.addAction(self._stop_action)
        toolbar.addAction(self._next_action)
        toolbar.addSeparator()

        toolbar.addWidget(QLabel(" Speed "))
        self._speed_slider = QSlider(Qt.Orientation.Horizontal)
        self._speed_slider.setRange(int(MIN_SPEED * 100), int(MAX_SPEED * 100))
        self._speed_slider.setSingleStep(_SPEED_STEP)
        self._speed_slider.setPageStep(25)
        self._speed_slider.setTickInterval(25)
        self._speed_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._speed_slider.setFixedWidth(150)
        self._speed_slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._speed_slider.setToolTip("Reading speed")
        self._speed_slider.setValue(round(self._session.speed * 100))
        toolbar.addWidget(self._speed_slider)
        self._speed_label = QLabel()
        self._speed_label.setMinimumWidth(48)
        self._speed_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        toolbar.addWidget(self._speed_label)
        self._show_speed(self._speed_slider.value())
        toolbar.addSeparator()

        toolbar.addWidget(QLabel(" Voice "))
        self._voice_combo = QComboBox()
        self._voice_combo.setMinimumWidth(190)
        self._voice_combo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._voice_combo.setToolTip("Voice")
        self._voice_combo.setPlaceholderText("Loading voices...")
        toolbar.addWidget(self._voice_combo)

        self._preview_button = QToolButton()
        self._preview_button.setText("Preview")
        self._preview_button.setToolTip("Hear a short sample of the selected voice")
        self._preview_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._preview_button.clicked.connect(self._preview_voice)
        toolbar.addWidget(self._preview_button)

    def _create_status_bar(self) -> None:
        status = self.statusBar()
        self._state_label = QLabel()
        self._page_label = QLabel()
        self._sentence_label = QLabel()
        status.addWidget(self._state_label, 1)
        status.addPermanentWidget(self._page_label)
        status.addPermanentWidget(self._sentence_label)

    def _connect_signals(self) -> None:
        b = self._bridge
        b.state_changed.connect(self._on_state_changed)
        b.model_loaded.connect(self._on_model_loaded)
        b.model_error.connect(self._on_model_error)
        b.document_loaded.connect(self._on_document_loaded)
        b.document_error.connect(self._on_document_error)
        b.position_changed.connect(self._on_position_changed)
        b.playback_error.connect(self._on_playback_error)
        self._view.sentence_clicked.connect(lambda index: self._session.seek(index, play=True))
        self._speed_slider.valueChanged.connect(self._on_speed_slider)
        self._voice_combo.activated.connect(self._on_voice_chosen)

    # ---------------------------------------------------------- open files

    @Slot()
    def _choose_file(self) -> None:
        folder = self._settings.last_folder or str(Path.home() / "Documents")
        path, _ = QFileDialog.getOpenFileName(
            self, "Open PDF", folder, "PDF documents (*.pdf);;All files (*)"
        )
        if path:
            self.open_file(Path(path))

    def open_file(self, path: Path) -> None:
        """Open ``path`` in the background."""
        log.info("Opening %s", path)
        self._settings.last_folder = str(path.parent)
        self._doc_loading_name = path.name
        self._session.open_document(path)
        self._update_controls()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """Accept drags that contain a PDF file."""
        if _first_pdf(event.mimeData().urls()) is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        """Open the first dropped PDF."""
        path = _first_pdf(event.mimeData().urls())
        if path is not None:
            event.acceptProposedAction()
            self.open_file(path)

    # ------------------------------------------------------ session events

    @Slot(object)
    def _on_state_changed(self, _state: ReadingState) -> None:
        self._update_controls()

    @Slot(list, str)
    def _on_model_loaded(self, voices: list[Voice], voice_id: str) -> None:
        self._model_loading = False
        self._voice_combo.clear()
        for voice in voices:
            self._voice_combo.addItem(voice.label, voice.id)
        index = self._voice_combo.findData(voice_id)
        self._voice_combo.setCurrentIndex(max(0, index))
        self._settings.voice = voice_id
        self._update_controls()

    @Slot(str)
    def _on_model_error(self, message: str) -> None:
        self._model_loading = False
        self._update_controls()
        log.error("Model error: %s", message)
        answer = QMessageBox.warning(
            self,
            "Voice model problem",
            "The voice model couldn't be loaded. The downloaded files may be damaged.\n\n"
            "Would you like to download them again?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._session.discard_model_files()
            self._ensure_model()

    @Slot(object)
    def _on_document_loaded(self, document: ReadingDocument) -> None:
        self._document = document
        self._doc_loading_name = None
        self._view.set_document(document)
        self.setWindowTitle(f"{document.document.path.name} - {APP_NAME}")
        self._view.highlight(self._session.position)
        self._update_controls()

    @Slot(object, str)
    def _on_document_error(self, path: Path, message: str) -> None:
        self._doc_loading_name = None
        self._update_controls()
        QMessageBox.warning(self, "Can't open this PDF", f"{path.name}\n\n{message}")

    @Slot(int)
    def _on_position_changed(self, index: int) -> None:
        self._view.highlight(index)
        self._update_position_labels()

    @Slot(str)
    def _on_playback_error(self, message: str) -> None:
        self._update_controls()
        QMessageBox.warning(self, "Playback problem", message)

    # ------------------------------------------------------ voice & speed

    @Slot(int)
    def _on_speed_slider(self, value: int) -> None:
        snapped = round(value / _SPEED_STEP) * _SPEED_STEP
        if snapped != value:
            self._speed_slider.setValue(snapped)
            return
        self._show_speed(value)
        self._speed_timer.start()

    def _show_speed(self, value: int) -> None:
        self._speed_label.setText(f"{value / 100:.2f}x")

    @Slot()
    def _apply_speed(self) -> None:
        speed = self._speed_slider.value() / 100
        self._settings.speed = speed
        self._session.set_speed(speed)

    @Slot(int)
    def _on_voice_chosen(self, index: int) -> None:
        voice_id = self._voice_combo.itemData(index)
        if isinstance(voice_id, str):
            self._settings.voice = voice_id
            self._session.set_voice(voice_id)

    @Slot()
    def _preview_voice(self) -> None:
        voice_id = self._voice_combo.currentData()
        if isinstance(voice_id, str):
            self._session.preview_voice(voice_id)

    # ------------------------------------------------------------ helpers

    def _update_controls(self) -> None:
        state = self._session.state
        model_ready = self._session.is_model_loaded
        has_doc = self._document is not None
        can_read = model_ready and has_doc and state is not ReadingState.LOADING
        playing = state is ReadingState.PLAYING

        self._play_action.setEnabled(can_read)
        self._play_action.setIcon(self._pause_icon if playing else self._play_icon)
        self._play_action.setText("&Pause" if playing else "&Play")
        self._stop_action.setEnabled(state in (ReadingState.PLAYING, ReadingState.PAUSED))
        self._prev_action.setEnabled(has_doc and state is not ReadingState.LOADING)
        self._next_action.setEnabled(has_doc and state is not ReadingState.LOADING)
        self._voice_combo.setEnabled(model_ready)
        self._preview_button.setEnabled(model_ready)
        self._download_action.setVisible(not model_ready and not self._model_loading)

        if state is ReadingState.LOADING:
            if self._model_loading:
                label = "Loading voice model..."
            elif self._doc_loading_name:
                label = f"Opening {self._doc_loading_name}..."
            else:
                label = _STATE_LABELS[state]
        elif state is ReadingState.IDLE and not model_ready:
            label = "Voice model not installed. Use Help > Download Voice Model."
        elif state is ReadingState.READY and not has_doc:
            label = "Ready. Open a PDF to start."
        else:
            label = _STATE_LABELS[state]
        self._state_label.setText(label)
        self._update_position_labels()

    def _update_position_labels(self) -> None:
        document = self._document
        if document is None:
            self._page_label.clear()
            self._sentence_label.clear()
            return
        index = self._session.position
        page = document.page_of(index) if 0 <= index < document.sentence_count else 1
        self._page_label.setText(f"Page {page} of {document.page_count}")
        self._sentence_label.setText(f"Sentence {index + 1} of {document.sentence_count}")

    def _show_about(self) -> None:
        link = f'<p><a href="{PROJECT_URL}">{PROJECT_URL}</a></p>' if PROJECT_URL else ""
        QMessageBox.about(
            self,
            f"About {APP_NAME}",
            f"<h3>{APP_NAME} {APP_VERSION}</h3>"
            "<p>Reads PDF documents aloud with natural AI voices, entirely on your "
            "computer.</p>"
            "<p>Voices: Kokoro-82M (Apache-2.0) via kokoro-onnx (MIT).<br>"
            "PDF: PyMuPDF (AGPL-3.0). UI: Qt / PySide6 (LGPL-3.0).</p>"
            "<p>Licensed under the GNU AGPL v3.0 or later.</p>" + link,
        )

    def _restore_geometry(self) -> None:
        if self._settings.window_geometry:
            try:
                data = QByteArray.fromHex(self._settings.window_geometry.encode("ascii"))
                self.restoreGeometry(data)
            except (UnicodeEncodeError, ValueError):
                log.warning("Ignoring invalid saved window geometry")

    def closeEvent(self, event: QCloseEvent) -> None:
        """Save settings and stop audio and background work before closing."""
        if not self._shut_down:
            self._shut_down = True
            self._speed_timer.stop()
            self._settings.window_geometry = bytes(self.saveGeometry().toHex().data()).decode()
            self._settings.speed = self._speed_slider.value() / 100
            save_settings(self._settings, self._settings_path)
            self._session.shutdown()
        super().closeEvent(event)


def _first_pdf(urls: list[QUrl]) -> Path | None:
    for url in urls:
        if url.isLocalFile():
            path = Path(url.toLocalFile())
            if path.suffix.lower() == ".pdf":
                return path
    return None
