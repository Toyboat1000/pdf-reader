"""The main application window: menus, toolbar, document view, and status bar."""

import logging
from pathlib import Path

from PySide6.QtCore import QByteArray, QEvent, QObject, QSize, Qt, QTimer, QUrl, Slot
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QDesktopServices,
    QDragEnterEvent,
    QDropEvent,
    QGuiApplication,
    QKeySequence,
)
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSizePolicy,
    QStackedWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from pdf_reader.config.constants import APP_NAME, APP_VERSION, PROJECT_URL
from pdf_reader.config.paths import logs_dir, models_dir
from pdf_reader.config.settings import Settings, save_settings
from pdf_reader.core.document import ReadingDocument
from pdf_reader.core.session import ReadingSession, ReadingState
from pdf_reader.library import Bookmark
from pdf_reader.text.pipeline import build_pipeline
from pdf_reader.tts.base import Voice
from pdf_reader.ui.bookmarks_panel import BookmarksPanel
from pdf_reader.ui.bridge import SessionBridge
from pdf_reader.ui.document_view import DocumentView
from pdf_reader.ui.download_dialog import ModelDownloadDialog
from pdf_reader.ui.icons import Glyph, make_icon
from pdf_reader.ui.page_view import PageView
from pdf_reader.ui.player_bar import PlayerBar
from pdf_reader.ui.resume_banner import ResumeBanner
from pdf_reader.ui.text_dialog import TextInputDialog
from pdf_reader.ui.toast import Toast
from pdf_reader.ui.welcome_view import WelcomeView

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

        self._view = DocumentView()
        self._page_view = PageView()
        self._views = QStackedWidget()
        self._welcome = WelcomeView()
        self._views.addWidget(self._view)
        self._views.addWidget(self._page_view)
        self._views.addWidget(self._welcome)
        self._views.setCurrentWidget(self._welcome)
        self._ocr_progress: str | None = None
        self._banner = ResumeBanner()
        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(self._banner)
        central_layout.addWidget(self._views, 1)
        self.setCentralWidget(central)
        self._bookmarks_panel = BookmarksPanel(self)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._bookmarks_panel)

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

        self._new_text_action = QAction(
            make_icon(Glyph.NEW_TEXT, self), "&New Text Document...", self
        )
        self._new_text_action.setShortcut(QKeySequence.StandardKey.New)
        self._new_text_action.setToolTip("Type or paste text to read aloud (Ctrl+N)")
        self._new_text_action.triggered.connect(lambda: self._ask_for_text(""))

        self._paste_action = QAction(make_icon(Glyph.PASTE, self), "&Paste Text...", self)
        self._paste_action.setShortcut(QKeySequence.StandardKey.Paste)
        self._paste_action.setToolTip("Read the text on the clipboard (Ctrl+V)")
        self._paste_action.triggered.connect(
            lambda: self._ask_for_text(QGuiApplication.clipboard().text())
        )

        self._edit_text_action = QAction(make_icon(Glyph.EDIT, self), "&Edit Text...", self)
        self._edit_text_action.setShortcut(QKeySequence("Ctrl+E"))
        self._edit_text_action.setToolTip("Change the current text document (Ctrl+E)")
        self._edit_text_action.triggered.connect(self._edit_text)

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

        self._add_bookmark_action = QAction(make_icon(Glyph.BOOKMARK, self), "&Add Bookmark", self)
        self._add_bookmark_action.setShortcut(QKeySequence("Ctrl+B"))
        self._add_bookmark_action.setToolTip("Bookmark the current sentence (Ctrl+B)")
        self._add_bookmark_action.triggered.connect(self._add_bookmark)

        self._show_bookmarks_action = self._bookmarks_panel.toggleViewAction()
        self._show_bookmarks_action.setText("Show &Bookmarks Panel")
        self._show_bookmarks_action.setIcon(make_icon(Glyph.BOOKMARKS, self))
        self._show_bookmarks_action.setShortcut(QKeySequence("Ctrl+Shift+B"))
        self._show_bookmarks_action.setToolTip("Show or hide your bookmarks (Ctrl+Shift+B)")

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
        self._recent_menu = file_menu.addMenu("Open &Recent")
        self._recent_menu.setToolTipsVisible(True)
        self._recent_menu.aboutToShow.connect(self._fill_recent_menu)
        file_menu.addSeparator()
        file_menu.addAction(self._new_text_action)
        file_menu.addAction(self._paste_action)
        file_menu.addAction(self._edit_text_action)
        file_menu.addSeparator()
        file_menu.addAction(self._exit_action)

        playback = bar.addMenu("&Playback")
        playback.addAction(self._play_action)
        playback.addAction(self._stop_action)
        playback.addSeparator()
        playback.addAction(self._prev_action)
        playback.addAction(self._next_action)

        edit_menu = bar.addMenu("&Edit")
        self._copy_action = edit_menu.addAction("&Copy", self._copy)
        self._copy_action.setShortcut(QKeySequence.StandardKey.Copy)
        self._copy_all_action = edit_menu.addAction("Copy &All Text", self._copy_all)
        self._copy_all_action.setShortcut(QKeySequence("Ctrl+Shift+C"))
        edit_menu.addSeparator()
        select_all = edit_menu.addAction("Select A&ll", self._select_all)
        select_all.setShortcut(QKeySequence.StandardKey.SelectAll)

        view_menu = bar.addMenu("&View")
        zoom_in = view_menu.addAction("Zoom &In", lambda: self._zoom_by(1.15))
        zoom_in.setShortcuts([QKeySequence("Ctrl+="), QKeySequence.StandardKey.ZoomIn])
        zoom_out = view_menu.addAction("Zoom &Out", lambda: self._zoom_by(1 / 1.15))
        zoom_out.setShortcuts([QKeySequence("Ctrl+-"), QKeySequence.StandardKey.ZoomOut])
        reset = view_menu.addAction("&Actual Size", self._zoom_reset)
        reset.setShortcut(QKeySequence("Ctrl+0"))

        self._page_images_action = QAction("Show PDFs as &Page Images", self)
        self._page_images_action.setCheckable(True)
        self._page_images_action.setChecked(self._settings.page_view)
        self._page_images_action.setShortcut(QKeySequence("Ctrl+Shift+P"))
        self._page_images_action.setToolTip(
            "On: see the real pages (click any word to read from there). "
            "Off: see the extracted text only."
        )
        self._page_images_action.toggled.connect(self._show_page_images)
        self._parentheses_action = QAction("Read Text in (&Parentheses)", self)
        self._parentheses_action.setCheckable(True)
        self._parentheses_action.setChecked(self._settings.read_parentheses)
        self._parentheses_action.toggled.connect(self._reading_options_changed)
        self._asides_action = QAction("Skip &Sidebars, Captions && Labels", self)
        self._asides_action.setCheckable(True)
        self._asides_action.setChecked(self._settings.skip_asides)
        self._asides_action.setToolTip(
            "Follow the main text of textbooks and articles; skip boxes in the margins, "
            "figure captions, and labels inside diagrams."
        )
        self._asides_action.toggled.connect(self._reading_options_changed)
        settings_menu = bar.addMenu("&Settings")
        settings_menu.setToolTipsVisible(True)
        settings_menu.addAction(self._page_images_action)
        settings_menu.addSeparator()
        settings_menu.addAction(self._parentheses_action)
        settings_menu.addAction(self._asides_action)

        bookmarks_menu = bar.addMenu("&Bookmarks")
        bookmarks_menu.addAction(self._add_bookmark_action)
        bookmarks_menu.addAction(self._show_bookmarks_action)

        help_menu = bar.addMenu("&Help")
        help_menu.addAction(self._download_action)
        help_menu.addAction(self._logs_action)
        help_menu.addSeparator()
        help_menu.addAction(self._about_action)

    def _create_toolbar(self) -> None:
        toolbar = QToolBar("Main", self)
        toolbar.setObjectName("main-toolbar")
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setIconSize(QSize(20, 20))
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        toolbar.toggleViewAction().setVisible(False)
        self.addToolBar(toolbar)

        toolbar.addAction(self._open_action)
        toolbar.addAction(self._new_text_action)
        toolbar.addAction(self._paste_action)
        toolbar.addWidget(_spacer())

        # Centre: what's open, and what's happening.
        self._title_label = QLabel(APP_NAME)
        self._title_label.setObjectName("title-label")
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._state_label = QLabel()
        self._state_label.setObjectName("subtitle-label")
        self._page_label = QLabel()
        self._page_label.setObjectName("subtitle-label")
        subtitle = QHBoxLayout()
        subtitle.setSpacing(10)
        subtitle.addStretch()
        subtitle.addWidget(self._state_label)
        subtitle.addWidget(self._page_label)
        subtitle.addStretch()
        title_box = QWidget()
        title_column = QVBoxLayout(title_box)
        title_column.setContentsMargins(0, 0, 0, 0)
        title_column.setSpacing(0)
        title_column.addWidget(self._title_label)
        title_column.addLayout(subtitle)
        toolbar.addWidget(title_box)

        toolbar.addWidget(_spacer())
        toolbar.addAction(self._add_bookmark_action)
        toolbar.addAction(self._show_bookmarks_action)

        # The floating "now playing" capsule over the reading area.
        self._player = PlayerBar(
            self.centralWidget(),
            previous=self._prev_action,
            play=self._play_action,
            stop=self._stop_action,
            following=self._next_action,
        )
        self._speed_slider = self._player.speed_slider
        self._speed_label = self._player.speed_label
        self._voice_combo = self._player.voice_combo
        self._preview_button = self._player.preview_button
        self._sentence_label = self._player.position_label
        self._speed_slider.setValue(round(self._session.speed * 100))
        self._show_speed(self._speed_slider.value())
        self._preview_button.clicked.connect(self._preview_voice)
        self._toast = Toast(self.centralWidget())
        self.centralWidget().installEventFilter(self)

    def _create_status_bar(self) -> None:
        # Messages appear as toasts; the status bar only keeps the latest message
        # (used by tests and accessibility tools) and stays hidden.
        self.statusBar().hide()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Keep the floating capsule and toast placed as the window resizes."""
        if watched is self.centralWidget() and event.type() == QEvent.Type.Resize:
            self._place_overlays()
        return super().eventFilter(watched, event)

    def _place_overlays(self) -> None:
        area = self.centralWidget()
        width = min(max(area.width() - 48, 360), 900)
        self._player.setFixedWidth(width)
        self._player.adjustSize()
        self._player.move((area.width() - width) // 2, area.height() - self._player.height() - 18)
        self._player.raise_()
        self._toast.bottom_offset = self._player.height() + 30
        self._toast.reposition()

    def _notify(self, message: str, duration_ms: int = 1800) -> None:
        """Show a brief message as a toast."""
        self._toast.show_message(message, duration_ms)
        self.statusBar().showMessage(message, duration_ms)

    def _connect_signals(self) -> None:
        b = self._bridge
        b.state_changed.connect(self._on_state_changed)
        b.model_loaded.connect(self._on_model_loaded)
        b.model_error.connect(self._on_model_error)
        b.document_loaded.connect(self._on_document_loaded)
        b.document_error.connect(self._on_document_error)
        b.position_changed.connect(self._on_position_changed)
        b.playback_error.connect(self._on_playback_error)
        b.resumed.connect(self._on_resumed)
        b.loading_progress.connect(self._on_loading_progress)
        self._page_view.sentence_clicked.connect(lambda index: self._session.seek(index, play=True))
        self._page_view.copy_requested.connect(self._copy)
        self._player.seek_requested.connect(lambda index: self._session.seek(index, play=False))
        self._welcome.open_requested.connect(self._choose_file)
        self._welcome.paste_requested.connect(self._paste_action.trigger)
        self._welcome.new_text_requested.connect(self._new_text_action.trigger)
        self._page_view.copy_all_requested.connect(self._copy_all)
        self._page_view.zoom_changed.connect(self._on_zoom_changed)
        self._view.zoom_changed.connect(self._on_zoom_changed)
        b.bookmarks_changed.connect(self._on_bookmarks_changed)
        self._banner.start_over.connect(lambda: self._session.seek(0, play=False))
        panel = self._bookmarks_panel
        panel.add_requested.connect(self._add_bookmark)
        panel.jump_requested.connect(self._session.go_to_bookmark)
        panel.rename_requested.connect(self._rename_bookmark)
        panel.remove_requested.connect(self._session.remove_bookmark)
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

    def open_text(self, text: str) -> None:
        """Read ``text`` as a document, in the background."""
        log.info("Opening pasted text (%d characters)", len(text))
        self._doc_loading_name = "text"
        self._session.open_text(text)
        self._update_controls()

    def _ask_for_text(self, initial: str, title: str = "New Text Document") -> None:
        """Show the text dialog; read the text if the user chooses Read Aloud."""
        dialog = TextInputDialog(self, text=initial, title=title)
        accepted = dialog.exec() == TextInputDialog.DialogCode.Accepted
        text = dialog.text()
        dialog.deleteLater()
        if accepted:
            self.open_text(text)

    @Slot()
    def _edit_text(self) -> None:
        if self._document is not None and self._document.text is not None:
            self._ask_for_text(self._document.text, title="Edit Text")

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """Accept drags that contain a PDF file or plain text."""
        mime = event.mimeData()
        if _first_pdf(mime.urls()) is not None or (mime.hasText() and not mime.hasUrls()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        """Open the first dropped PDF, or offer dropped text for reading."""
        mime = event.mimeData()
        path = _first_pdf(mime.urls())
        if path is not None:
            event.acceptProposedAction()
            self.open_file(path)
        elif mime.hasText() and not mime.hasUrls():
            event.acceptProposedAction()
            # Show the dialog after the drop completes, not inside the drag handler.
            text = mime.text()
            QTimer.singleShot(0, lambda: self._ask_for_text(text))

    # ------------------------------------------------------ session events

    @Slot(object)
    def _on_state_changed(self, state: ReadingState) -> None:
        if state is ReadingState.PLAYING:
            self._banner.hide()  # Reading on means the user accepted where it resumed.
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
        self._banner.hide()
        self._view.set_document(document)
        self._ocr_progress = None
        if document.word_map is not None:
            self._page_view.set_document(document)
        else:
            self._page_view.clear_document()
        self._show_page_images(self._page_images_action.isChecked())
        self.setWindowTitle(f"{document.display_name} - {APP_NAME}")
        self._title_label.setText(document.display_name)
        self._player.set_document_length(document.sentence_count)
        self._view.highlight(self._session.position)
        self._update_controls()

    @Slot(int)
    def _on_resumed(self, index: int) -> None:
        document = self._document
        if document is None or not 0 <= index < document.sentence_count:
            return
        self._banner.show_resumed(document.page_of(index) if document.is_paginated else None)

    @Slot(list)
    def _on_bookmarks_changed(self, bookmarks: list[Bookmark]) -> None:
        paginated = self._document is not None and self._document.is_paginated
        self._bookmarks_panel.set_bookmarks(bookmarks, show_pages=paginated)
        self._view.set_bookmarked({b.anchor.index for b in bookmarks})

    # ----------------------------------------------------------- bookmarks

    @Slot()
    def _add_bookmark(self) -> None:
        bookmark = self._session.add_bookmark()
        if bookmark is None:
            return
        if self._bookmarks_panel.isHidden():
            self._notify("Bookmark added \u2014 Ctrl+Shift+B shows your bookmarks", 3000)

    @Slot(str)
    def _rename_bookmark(self, bookmark_id: str) -> None:
        bookmark = next((b for b in self._session.bookmarks() if b.id == bookmark_id), None)
        if bookmark is None:
            return
        label, accepted = QInputDialog.getText(
            self, "Rename Bookmark", "Bookmark name:", text=bookmark.label
        )
        if accepted and label.strip():
            self._session.rename_bookmark(bookmark_id, label)

    @Slot()
    def _fill_recent_menu(self) -> None:
        menu = self._recent_menu
        menu.clear()
        records = self._session.recent_documents()
        if not records:
            menu.addAction("No recent documents").setEnabled(False)
            return
        for record in records:
            if record.path is None:
                continue
            path = Path(record.path)
            action = menu.addAction(path.name)
            action.setToolTip(str(path))
            if path.is_file():
                action.triggered.connect(lambda _checked=False, p=path: self.open_file(p))
            else:
                action.setText(f"{path.name} (not found)")
                action.setEnabled(False)

    @Slot(object, str)
    def _on_document_error(self, path: Path | None, message: str) -> None:
        self._doc_loading_name = None
        self._update_controls()
        if path is None:
            QMessageBox.warning(self, "Can't read this text", message)
        else:
            QMessageBox.warning(self, "Can't open this PDF", f"{path.name}\n\n{message}")

    @Slot(int)
    def _on_position_changed(self, index: int) -> None:
        self._view.highlight(index)
        self._page_view.highlight(index)
        self._update_position_labels()

    @Slot(bool)
    def _show_page_images(self, show: bool) -> None:
        self._settings.page_view = show
        if self._document is None:
            self._views.setCurrentWidget(self._welcome)
            return
        use_pages = show and self._document.word_map is not None
        self._views.setCurrentWidget(self._page_view if use_pages else self._view)

    @Slot()
    def _reading_options_changed(self) -> None:
        self._settings.read_parentheses = self._parentheses_action.isChecked()
        self._settings.skip_asides = self._asides_action.isChecked()
        self._session.set_pipeline(
            build_pipeline(
                read_parentheses=self._settings.read_parentheses,
                skip_asides=self._settings.skip_asides,
            )
        )
        self._update_controls()

    # ------------------------------------------------------------ copy & zoom

    def _active_view(self) -> PageView | DocumentView:
        return self._page_view if self._views.currentWidget() is self._page_view else self._view

    @Slot()
    def _copy(self) -> None:
        view = self._active_view()
        text = view.selected_text()
        if not text and self._document is not None and self._document.sentences:
            # Nothing selected: copy the sentence being read.
            text = self._document.sentences[self._session.position].text
        if text:
            QGuiApplication.clipboard().setText(text)
            self._notify("Copied")

    @Slot()
    def _copy_all(self) -> None:
        if self._document is None:
            return
        paragraphs: list[list[str]] = []
        last_block = None
        for sentence in self._document.sentences:
            if sentence.block != last_block or not paragraphs:
                paragraphs.append([])
                last_block = sentence.block
            paragraphs[-1].append(sentence.text)
        QGuiApplication.clipboard().setText("\n\n".join(" ".join(p) for p in paragraphs))
        self._notify("All text copied")

    @Slot()
    def _select_all(self) -> None:
        view = self._active_view()
        if isinstance(view, PageView):
            view.select_all()
        else:
            view.selectAll()

    def _zoom_by(self, factor: float) -> None:
        view = self._active_view()
        view.set_zoom(view.zoom * factor)

    def _zoom_reset(self) -> None:
        self._active_view().set_zoom(1.0)

    @Slot(float)
    def _on_zoom_changed(self, zoom: float) -> None:
        self._notify(f"Zoom {zoom:.0%}", 1200)

    @Slot(int, int)
    def _on_loading_progress(self, done: int, total: int) -> None:
        self._ocr_progress = f"Reading scanned pages… {done} of {total}"
        self._update_controls()

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
        self._player.show_speed(value / 100)

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
        can_bookmark = self._session.can_bookmark and state is not ReadingState.LOADING
        self._add_bookmark_action.setEnabled(can_bookmark)
        self._bookmarks_panel.set_can_add(can_bookmark)
        self._edit_text_action.setEnabled(
            self._document is not None
            and self._document.text is not None
            and state is not ReadingState.LOADING
        )
        self._prev_action.setEnabled(has_doc and state is not ReadingState.LOADING)
        self._next_action.setEnabled(has_doc and state is not ReadingState.LOADING)
        self._voice_combo.setEnabled(model_ready)
        self._preview_button.setEnabled(model_ready)
        self._download_action.setVisible(not model_ready and not self._model_loading)

        if state is ReadingState.LOADING:
            if self._model_loading:
                label = "Loading voice model..."
            elif self._ocr_progress is not None:
                label = self._ocr_progress
            elif self._doc_loading_name == "text":
                label = "Preparing text..."
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
            self._page_label.setVisible(True)
            self._sentence_label.clear()
            return
        index = self._session.position
        page = document.page_of(index) if 0 <= index < document.sentence_count else 1
        self._player.set_position(index)
        # Pasted text has no pages, so its status bar shows only the sentence.
        self._page_label.setVisible(document.is_paginated)
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
        try:
            if self._settings.window_geometry:
                self.restoreGeometry(
                    QByteArray.fromHex(self._settings.window_geometry.encode("ascii"))
                )
            if self._settings.window_state:
                self.restoreState(QByteArray.fromHex(self._settings.window_state.encode("ascii")))
        except (UnicodeEncodeError, ValueError):
            log.warning("Ignoring invalid saved window layout")
        self._bookmarks_panel.setVisible(self._settings.show_bookmarks)
        self._page_view.set_zoom(self._settings.page_zoom)
        self._view.set_zoom(self._settings.text_zoom)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Save settings and stop audio and background work before closing."""
        if not self._shut_down:
            self._shut_down = True
            self._speed_timer.stop()
            self._settings.window_geometry = bytes(self.saveGeometry().toHex().data()).decode()
            self._settings.window_state = bytes(self.saveState().toHex().data()).decode()
            self._settings.show_bookmarks = not self._bookmarks_panel.isHidden()
            self._settings.page_zoom = self._page_view.zoom
            self._settings.text_zoom = self._view.zoom
            self._settings.speed = self._speed_slider.value() / 100
            save_settings(self._settings, self._settings_path)
            self._session.shutdown()
            self._page_view.clear_document()
        super().closeEvent(event)


def _first_pdf(urls: list[QUrl]) -> Path | None:
    for url in urls:
        if url.isLocalFile():
            path = Path(url.toLocalFile())
            if path.suffix.lower() == ".pdf":
                return path
    return None


def _spacer() -> QWidget:
    spacer = QWidget()
    spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    return spacer
