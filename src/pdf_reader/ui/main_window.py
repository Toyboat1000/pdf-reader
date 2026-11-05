"""The main application window: menus, toolbar, document view, and status bar."""

import logging
import re
import subprocess
import time
from pathlib import Path

from PySide6.QtCore import QByteArray, QEvent, QObject, QSize, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QDesktopServices,
    QDragEnterEvent,
    QDropEvent,
    QGuiApplication,
    QKeySequence,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QSizePolicy,
    QStackedWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from pdf_reader.audio.export import EXPORT_SUFFIXES
from pdf_reader.config.constants import APP_NAME, APP_VERSION, PROJECT_URL
from pdf_reader.config.paths import logs_dir, models_dir
from pdf_reader.config.settings import Settings, save_settings
from pdf_reader.core.document import ReadingDocument, text_title
from pdf_reader.core.session import ReadingSession, ReadingState
from pdf_reader.library import Bookmark
from pdf_reader.pdf.formats import PAGED_FORMATS
from pdf_reader.sources import TEXT_SUFFIXES, is_web_address
from pdf_reader.system.media_controls import MediaCommand, MediaControls, PlaybackStatus
from pdf_reader.text.pipeline import build_pipeline
from pdf_reader.tts.base import Voice
from pdf_reader.ui.bookmarks_panel import BookmarksPanel
from pdf_reader.ui.bridge import SessionBridge
from pdf_reader.ui.document_view import DocumentView
from pdf_reader.ui.download_dialog import ModelDownloadDialog
from pdf_reader.ui.home_view import HomeView
from pdf_reader.ui.icons import Glyph, make_icon
from pdf_reader.ui.loading_view import LoadingView
from pdf_reader.ui.page_view import PageView
from pdf_reader.ui.player_bar import PlayerBar
from pdf_reader.ui.resume_banner import ResumeBanner
from pdf_reader.ui.tabs import DocumentTab, TabStrip
from pdf_reader.ui.text_dialog import TextInputDialog
from pdf_reader.ui.theme import DYSLEXIC_FONT, SEPIA_PAGE_TINT, THEME_LABELS, apply_theme
from pdf_reader.ui.toast import Toast

log = logging.getLogger(__name__)

_SPEED_STEP = 5  # Slider units are hundredths, so this is 0.05x.
_SPEED_APPLY_DELAY_MS = 250  # Wait for the slider to settle before regenerating audio.
_WORD_TICK_MS = 30  # How often the spoken word is looked up while reading.
_TIME_REFRESH_SECONDS = 0.5  # How often the listening times are refreshed while reading.

_DOCUMENT_SUFFIXES = sorted(set(PAGED_FORMATS) | TEXT_SUFFIXES)
_OPEN_FILTER = ";;".join(
    [
        "All documents (" + " ".join(f"*{s}" for s in _DOCUMENT_SUFFIXES) + ")",
        "PDF documents (*.pdf)",
        "E-books (*.epub *.mobi *.fb2 *.cbz)",
        "Word documents (*.docx)",
        "Web pages (*.html *.htm *.xhtml)",
        "Text files (*.txt *.md *.markdown)",
        "All files (*)",
    ]
)

_STATE_LABELS = {
    ReadingState.IDLE: "Voice model not loaded",
    ReadingState.LOADING: "Loading...",
    ReadingState.READY: "Ready",
    ReadingState.PLAYING: "Reading",
    ReadingState.PAUSED: "Paused",
}


class _MediaSignals(QObject):
    """Carries media buttons (pressed on a Windows thread) to the UI thread."""

    command = Signal(object)  # MediaCommand


class MainWindow(QMainWindow):
    """Top-level window. Talks only to :class:`ReadingSession` (via :class:`SessionBridge`).

    Args:
        session: The reading session.
        bridge: Delivers the session's events as Qt signals.
        settings: Settings to show and update (saved on close).
        settings_path: Where settings are saved.
        media_controls: Connect to the Windows media panel and media keys (off in tests).
    """

    def __init__(
        self,
        session: ReadingSession,
        bridge: SessionBridge,
        settings: Settings,
        settings_path: Path,
        *,
        media_controls: bool = False,
    ) -> None:
        super().__init__()
        self._session = session
        self._bridge = bridge
        self._settings = settings
        self._settings_path = settings_path
        self._document: ReadingDocument | None = None  # The one being read aloud.
        self._tabs: list[DocumentTab] = []
        self._listening: DocumentTab | None = None
        self._shown: ReadingDocument | None = None  # The one in the views now.
        self._text_view_document: ReadingDocument | None = None
        self._page_view_document: ReadingDocument | None = None
        self._model_loading = False
        self._doc_loading_name: str | None = None
        self._shut_down = False
        self._export_dialog: QProgressDialog | None = None
        self._export_started = 0.0
        self._times_refreshed = 0.0

        self.setWindowTitle(APP_NAME)
        self.setAcceptDrops(True)
        self.resize(1000, 760)
        self.setMinimumSize(QSize(640, 420))

        self._view = DocumentView()
        self._page_view = PageView()
        self._views = QStackedWidget()
        self._home = HomeView()
        self._loading = LoadingView()
        self._views.addWidget(self._view)
        self._views.addWidget(self._page_view)
        self._views.addWidget(self._home)
        self._views.addWidget(self._loading)
        self._tab_strip = TabStrip()
        self._views.setCurrentWidget(self._home)
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
        self._word_timer = QTimer(self)
        self._word_timer.setInterval(_WORD_TICK_MS)
        self._word_timer.timeout.connect(self._on_tick)

        self._media_signals = _MediaSignals(self)
        self._media_signals.command.connect(self._on_media_command)
        self._media = MediaControls(self._media_signals.command.emit) if media_controls else None

        self._view.set_font_family(DYSLEXIC_FONT if settings.dyslexic_font else "Segoe UI")
        self._page_view.set_page_tint(SEPIA_PAGE_TINT if settings.theme == "sepia" else None)
        self._show_tab(None)  # Home, with the recent documents filled in.
        self._update_controls()

    # ------------------------------------------------------------- start-up

    def start(self, initial: Path | str | None = None) -> None:
        """Begin loading the model (downloading it first if needed), then open a document.

        ``initial`` is a file or a web address (from the command line). Files that
        were open in tabs last time come back too (opened when first shown).
        """
        self._restore_tabs()
        if isinstance(initial, Path):
            self.open_file(initial)
        elif initial:
            self._open_location(initial)
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
        self._open_action = QAction(make_icon(Glyph.OPEN, self), "&Open...", self)
        self._open_action.setShortcut(QKeySequence.StandardKey.Open)
        self._open_action.setToolTip("Open a PDF, e-book, Word document, or web page (Ctrl+O)")
        self._open_action.triggered.connect(self._choose_file)

        self._open_link_action = QAction(make_icon(Glyph.LINK, self), "Open &Link...", self)
        self._open_link_action.setShortcut(QKeySequence("Ctrl+L"))
        self._open_link_action.setToolTip("Listen to a web page or an online PDF (Ctrl+L)")
        self._open_link_action.triggered.connect(self._ask_for_link)

        self._export_action = QAction(make_icon(Glyph.SAVE, self), "&Export Audio...", self)
        self._export_action.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self._export_action.setToolTip("Save the document as an MP3 to listen anywhere")
        self._export_action.triggered.connect(self._export_audio)

        self._new_text_action = QAction(
            make_icon(Glyph.NEW_TEXT, self), "&New Text Document...", self
        )
        self._new_text_action.setShortcut(QKeySequence.StandardKey.New)
        self._new_text_action.setToolTip("Type or paste text to read aloud (Ctrl+N)")
        self._new_text_action.triggered.connect(lambda: self._ask_for_text(""))

        self._paste_action = QAction(make_icon(Glyph.PASTE, self), "&Paste Text...", self)
        self._paste_action.setShortcut(QKeySequence.StandardKey.Paste)
        self._paste_action.setToolTip("Read the text on the clipboard (Ctrl+V)")
        self._paste_action.triggered.connect(self._paste)

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
        self._play_action.triggered.connect(self._toggle_play)

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

        self._home_action = QAction(make_icon(Glyph.HOME, self), "&Home", self)
        self._home_action.setShortcuts([QKeySequence("Ctrl+H"), QKeySequence("Ctrl+T")])
        self._home_action.setToolTip("Home: recent documents and new text (Ctrl+H)")
        self._home_action.triggered.connect(lambda: self._tab_strip.setCurrentIndex(0))

        self._close_tab_action = QAction("&Close Tab", self)
        self._close_tab_action.setShortcuts([QKeySequence("Ctrl+W"), QKeySequence("Ctrl+F4")])
        self._close_tab_action.triggered.connect(self._close_current_tab)
        self._next_tab_action = QAction("Next Ta&b", self)
        self._next_tab_action.setShortcut(QKeySequence("Ctrl+Tab"))
        self._next_tab_action.triggered.connect(lambda: self._step_tab(1))
        self._previous_tab_action = QAction("Previous Tab", self)
        self._previous_tab_action.setShortcut(QKeySequence("Ctrl+Shift+Tab"))
        self._previous_tab_action.triggered.connect(lambda: self._step_tab(-1))
        self._show_listening_action = QAction("Show What's &Playing", self)
        self._show_listening_action.setShortcut(QKeySequence("Ctrl+J"))
        self._show_listening_action.triggered.connect(self._show_listening_tab)

        self._about_action = QAction(f"&About {APP_NAME}", self)
        self._about_action.triggered.connect(self._show_about)

        for action in (
            self._play_action,
            self._prev_action,
            self._next_action,
            self._next_tab_action,
            self._previous_tab_action,
        ):
            # Window-wide, so they work whichever control was clicked last.
            action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            self.addAction(action)

    def _create_menus(self) -> None:
        bar = self.menuBar()
        file_menu = bar.addMenu("&File")
        file_menu.addAction(self._home_action)
        file_menu.addAction(self._open_action)
        file_menu.addAction(self._open_link_action)
        self._recent_menu = file_menu.addMenu("Open &Recent")
        self._recent_menu.setToolTipsVisible(True)
        self._recent_menu.aboutToShow.connect(self._fill_recent_menu)
        file_menu.addSeparator()
        file_menu.addAction(self._new_text_action)
        file_menu.addAction(self._paste_action)
        file_menu.addAction(self._edit_text_action)
        file_menu.addSeparator()
        file_menu.addAction(self._export_action)
        file_menu.addSeparator()
        file_menu.addAction(self._close_tab_action)
        file_menu.addAction(self._exit_action)

        playback = bar.addMenu("&Playback")
        playback.addAction(self._play_action)
        playback.addAction(self._stop_action)
        playback.addSeparator()
        playback.addAction(self._prev_action)
        playback.addAction(self._next_action)
        playback.addSeparator()
        playback.addAction(self._show_listening_action)

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
        view_menu.addSeparator()
        view_menu.addAction(self._next_tab_action)
        view_menu.addAction(self._previous_tab_action)
        view_menu.addSeparator()
        theme_menu = view_menu.addMenu("&Theme")
        self._theme_group = QActionGroup(self)
        self._theme_group.setExclusive(True)
        for name, label in THEME_LABELS.items():
            action = theme_menu.addAction(label)
            action.setCheckable(True)
            action.setData(name)
            action.setChecked(name == self._settings.theme)
            self._theme_group.addAction(action)
        self._theme_group.triggered.connect(self._on_theme_chosen)
        self._dyslexic_action = view_menu.addAction("&Dyslexia-Friendly Font")
        self._dyslexic_action.setCheckable(True)
        self._dyslexic_action.setChecked(self._settings.dyslexic_font)
        self._dyslexic_action.toggled.connect(self._on_dyslexic_font)
        self._word_highlight_action = view_menu.addAction("Highlight Each &Word as It's Read")
        self._word_highlight_action.setCheckable(True)
        self._word_highlight_action.setChecked(self._settings.word_highlight)
        self._word_highlight_action.toggled.connect(self._on_word_highlight)

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
        toolbar.addAction(self._open_link_action)
        toolbar.addAction(self._new_text_action)
        toolbar.addAction(self._paste_action)
        toolbar.addSeparator()

        # The tabs take the middle of the toolbar, like a browser's.
        self._tab_strip.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(self._tab_strip)
        self._state_label = QLabel()
        self._state_label.setObjectName("subtitle-label")
        toolbar.addWidget(self._state_label)
        toolbar.addSeparator()
        toolbar.addAction(self._export_action)
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
        self._page_label = self._player.page_label
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
        self._page_view.sentence_clicked.connect(self._on_sentence_clicked)
        b.document_prepared.connect(self._on_document_prepared)
        b.prepare_progress.connect(self._on_prepare_progress)
        self._tab_strip.currentChanged.connect(self._on_tab_changed)
        self._tab_strip.close_requested.connect(self.close_tab)
        self._player.show_listening_requested.connect(self._show_listening_tab)
        self._page_view.copy_requested.connect(self._copy)
        self._player.seek_requested.connect(lambda index: self._session.seek(index, play=False))
        self._home.open_requested.connect(self._choose_file)
        self._home.open_link_requested.connect(self._ask_for_link)
        self._home.paste_requested.connect(self._paste)
        self._home.open_path_requested.connect(self._open_location)
        self._home.listen_text_requested.connect(self.open_text)
        self._home.remove_requested.connect(self._forget_document)
        self._page_view.copy_all_requested.connect(self._copy_all)
        self._page_view.zoom_changed.connect(self._on_zoom_changed)
        self._view.zoom_changed.connect(self._on_zoom_changed)
        b.bookmarks_changed.connect(self._on_bookmarks_changed)
        b.export_progress.connect(self._on_export_progress)
        b.export_finished.connect(self._on_export_finished)
        b.export_failed.connect(self._on_export_failed)
        self._banner.start_over.connect(lambda: self._session.seek(0, play=False))
        panel = self._bookmarks_panel
        panel.add_requested.connect(self._add_bookmark)
        panel.jump_requested.connect(self._session.go_to_bookmark)
        panel.rename_requested.connect(self._rename_bookmark)
        panel.remove_requested.connect(self._session.remove_bookmark)
        self._view.sentence_clicked.connect(self._on_sentence_clicked)
        self._speed_slider.valueChanged.connect(self._on_speed_slider)
        self._voice_combo.activated.connect(self._on_voice_chosen)

    # ---------------------------------------------------------- open files

    @Slot()
    def _choose_file(self) -> None:
        folder = self._settings.last_folder or str(Path.home() / "Documents")
        path, _ = QFileDialog.getOpenFileName(self, "Open", folder, _OPEN_FILTER)
        if path:
            self.open_file(Path(path))

    def open_url(self, address: str) -> None:
        """Open a web page or online document in a new tab (in the background)."""
        log.info("Opening link %s", address)
        title = address.split("://", 1)[-1].split("/", 1)[0] or "web page"
        tab = self._find_tab(address)
        if tab is not None:
            self._select(tab)
            return
        tab = self._add_tab(DocumentTab(title, location=address))
        tab.request = self._session.prepare_url(address)
        self._select(tab)

    @Slot(str)
    def _open_location(self, location: str) -> None:
        """Open a recent document, which is a file path or a web address."""
        if is_web_address(location):
            self.open_url(location)
        else:
            self.open_file(Path(location))

    @Slot(str)
    def bring_forward(self, location: str = "") -> None:
        """Come to the front (another launch of the app asked), opening ``location``."""
        if self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()
        if location:
            self._open_location(location)

    @Slot()
    def _ask_for_link(self) -> None:
        clipboard = QGuiApplication.clipboard().text().strip()
        address, accepted = QInputDialog.getText(
            self,
            "Open Link",
            "Paste the address of a web page, or of a PDF or e-book online:",
            text=clipboard if is_web_address(clipboard) else "",
        )
        if accepted and address.strip():
            if is_web_address(address) or "." in address:
                self.open_url(address.strip())
            else:
                QMessageBox.warning(self, "Open Link", "That doesn't look like a web address.")

    @Slot()
    def _paste(self) -> None:
        """Read the clipboard: a copied link opens the page, other text opens the editor."""
        text = QGuiApplication.clipboard().text()
        if is_web_address(text):
            self.open_url(text.strip())
        else:
            self._ask_for_text(text)

    def open_file(self, path: Path) -> None:
        """Open ``path`` in a tab (in the background), or show it if it is already open."""
        log.info("Opening %s", path)
        self._settings.last_folder = str(path.parent)
        tab = self._find_tab(str(path))
        if tab is None:
            tab = self._add_tab(DocumentTab(path.name, location=str(path)))
        if tab.document is None and tab.request is None:
            tab.request = self._session.prepare_document(path)
        self._select(tab)

    def open_text(self, text: str) -> None:
        """Read ``text`` in a new tab (or open it, if it is a web link), in the background."""
        if is_web_address(text):
            self.open_url(text.strip())
            return
        log.info("Opening pasted text (%d characters)", len(text))
        tab = self._add_tab(DocumentTab(text_title(text)))
        tab.request = self._session.prepare_text(text)
        self._select(tab)

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
        tab = self._current_tab()
        if tab is None or tab.document is None or tab.document.text is None:
            return
        dialog = TextInputDialog(self, text=tab.document.text, title="Edit Text")
        accepted = dialog.exec() == TextInputDialog.DialogCode.Accepted
        text = dialog.text()
        dialog.deleteLater()
        if accepted and text.strip():
            # The edited text replaces this tab's document, read from the start.
            tab.title = text_title(text)
            tab.position = 0
            tab.request = self._session.prepare_text(text)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """Accept drags that contain a document, a link, or plain text."""
        mime = event.mimeData()
        if _first_document(mime.urls()) is not None or (mime.hasText() and not mime.hasUrls()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        """Open the first dropped document or link, or offer dropped text for reading."""
        mime = event.mimeData()
        target = _first_document(mime.urls())
        if isinstance(target, Path):
            event.acceptProposedAction()
            files = [p for p in _documents(mime.urls()) if isinstance(p, Path)]
            for path in files:  # Several files: one tab each, the first one shown.
                self.open_file(path)
            first = self._find_tab(str(files[0]))
            if first is not None:
                self._select(first)
        elif isinstance(target, str):
            event.acceptProposedAction()
            self.open_url(target)
        elif mime.hasText() and is_web_address(mime.text()):
            event.acceptProposedAction()
            self.open_url(mime.text().strip())
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
            self._word_timer.start()
        else:
            self._word_timer.stop()
            if state is not ReadingState.PAUSED:
                self._clear_word_highlight()
        self._update_media_status(state)
        self._update_now_playing()
        self._update_controls()
        self._update_times()

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
        """The session now reads ``document``: it's the listening tab's."""
        self._document = document
        self._doc_loading_name = None
        self._ocr_progress = None
        self._banner.hide()
        tab = next((t for t in self._tabs if t.document is document), None)
        if tab is None:  # Opened directly through the session: give it a tab.
            location = str(document.path) if document.path else document.source_url
            tab = self._add_tab(DocumentTab(document.display_name, location=location))
            tab.document = document
            self._select(tab)
        previous, self._listening = self._listening, tab
        for other in (previous, tab):
            if other is not None:
                self._tab_strip.update_tab(other, listening=other is self._listening)
        self._player.set_document_length(document.sentence_count)
        if self._current_tab() is tab:
            self._show_tab(tab)
        self._update_now_playing()
        self._update_controls()
        self._update_times()
        if self._media is not None:
            cover = self._cover_for(document.doc_id) if document.doc_id else None
            self._media.set_track(document.title, APP_NAME, cover)
            self._update_media_status(self._session.state)

    @Slot(int)
    def _on_resumed(self, index: int) -> None:
        document = self._document
        if document is None or not 0 <= index < document.sentence_count:
            return
        if self._listening is not None and self._listening.quiet:
            self._listening.quiet = False  # Only re-read with new settings: no news.
            return
        if self._current_tab() is not self._listening:
            return
        self._banner.show_resumed(document.page_of(index) if document.is_paginated else None)

    @Slot(list)
    def _on_bookmarks_changed(self, bookmarks: list[Bookmark]) -> None:
        paginated = self._document is not None and self._document.is_paginated
        self._bookmarks_panel.set_bookmarks(bookmarks, show_pages=paginated)
        if self._shown is self._document:
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
            if is_web_address(record.path):
                link = menu.addAction(record.title)
                link.setToolTip(record.path)
                link.triggered.connect(lambda _checked=False, u=record.path: self.open_url(u))
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
        was_link = self._doc_loading_name == "link"
        self._doc_loading_name = None
        self._update_controls()
        if path is not None:
            QMessageBox.warning(self, "Can't open this file", f"{path.name}\n\n{message}")
        elif was_link:
            QMessageBox.warning(self, "Can't open this link", message)
        else:
            QMessageBox.warning(self, "Can't read this text", message)

    @Slot(int)
    def _on_position_changed(self, index: int) -> None:
        if self._listening is not None:
            self._listening.position = index
        if self._shown is not None and self._shown is self._document:
            self._view.highlight(index)
            self._page_view.highlight(index)
        self._update_position_labels()
        self._update_times()

    # ---------------------------------------------------------------- tabs

    def _current_tab(self) -> DocumentTab | None:
        """Return the tab being looked at, or ``None`` on the home page."""
        return self._tab_by_key(self._tab_strip.key_at(self._tab_strip.currentIndex()))

    def _tab_by_key(self, key: int) -> DocumentTab | None:
        return next((t for t in self._tabs if t.key == key), None)

    def _find_tab(self, location: str) -> DocumentTab | None:
        """Return the open tab for a file or address, if any."""
        if is_web_address(location):
            return next((t for t in self._tabs if t.location == location), None)
        try:
            wanted = Path(location).resolve()
        except OSError:
            return None
        for tab in self._tabs:
            if tab.location and not is_web_address(tab.location):
                try:
                    if Path(tab.location).resolve() == wanted:
                        return tab
                except OSError:
                    continue
        return None

    def _add_tab(self, tab: DocumentTab) -> DocumentTab:
        self._tabs.append(tab)
        self._tab_strip.add_document_tab(tab)
        return tab

    def _select(self, tab: DocumentTab) -> None:
        index = self._tab_strip.index_of(tab.key)
        if index == self._tab_strip.currentIndex():
            self._on_tab_changed(index)
        else:
            self._tab_strip.setCurrentIndex(index)

    def _step_tab(self, step: int) -> None:
        count = self._tab_strip.count()
        self._tab_strip.setCurrentIndex((self._tab_strip.currentIndex() + step) % count)

    @Slot()
    def _show_listening_tab(self) -> None:
        if self._listening is not None:
            self._select(self._listening)

    @Slot(int)
    def _on_tab_changed(self, index: int) -> None:
        tab = self._tab_by_key(self._tab_strip.key_at(index))
        if tab is not None and tab.document is None and tab.request is None:
            self._load_tab(tab)  # Restored from last time: opened when first shown.
        if (
            tab is not None
            and tab.document is not None
            and tab is not self._listening
            and self._session.state is not ReadingState.PLAYING
        ):
            # Nothing is being read aloud: the player follows what's on screen.
            self._activate(tab)
        self._show_tab(tab)
        self._update_now_playing()
        self._update_controls()

    def _load_tab(self, tab: DocumentTab) -> None:
        """Start loading a tab's document from where it came from."""
        if tab.location is None:
            return
        if is_web_address(tab.location):
            tab.request = self._session.prepare_url(tab.location)
        else:
            tab.request = self._session.prepare_document(Path(tab.location))

    def _activate(self, tab: DocumentTab, position: int | None = None) -> None:
        """Make ``tab`` the listening tab (its document is what the player reads)."""
        if tab.document is None:
            return
        self._session.activate(tab.document, position if position is not None else tab.position)

    @Slot(int, object, object)
    def _on_document_prepared(
        self, request: int, path: Path | None, result: ReadingDocument | str
    ) -> None:
        if self._shut_down:
            return  # Finished after the window closed.
        tab = next((t for t in self._tabs if t.request == request), None)
        if tab is None:
            return  # Its tab was closed meanwhile.
        tab.request = None
        tab.progress = None
        if isinstance(result, str):
            failed_location = tab.location
            if tab.document is None:
                self.close_tab(tab.key)
            if path is not None:
                QMessageBox.warning(self, "Can't open this file", f"{path.name}\n\n{result}")
            elif failed_location and is_web_address(failed_location):
                QMessageBox.warning(self, "Can't open this link", result)
            else:
                QMessageBox.warning(self, "Can't read this text", result)
            return
        replacing = tab.document is not None
        tab.document = result
        tab.title = result.display_name
        if result.source_url is not None and tab.location is not None:
            tab.location = result.source_url
        self._tab_strip.update_tab(tab, listening=tab is self._listening)
        if tab is self._listening and replacing:
            tab.quiet = result.doc_id is not None
            # Re-read with new settings: continue at the same sentence.
            self._session.activate(result, None if result.doc_id else tab.position)
        elif self._current_tab() is tab:
            self._on_tab_changed(self._tab_strip.currentIndex())
        self._update_controls()

    @Slot(int, int, int)
    def _on_prepare_progress(self, request: int, done: int, total: int) -> None:
        tab = next((t for t in self._tabs if t.request == request), None)
        if tab is None:
            return
        tab.progress = f"Reading scanned pages\u2026 {done} of {total}"
        if self._current_tab() is tab and tab.document is None:
            self._loading.show_loading(tab.title, tab.progress)
            self._loading.set_progress(done, total)

    @Slot(int)
    def close_tab(self, key: int) -> None:
        """Close the tab with ``key``; closing the listening tab stops reading."""
        tab = self._tab_by_key(key)
        if tab is None:
            return
        if tab is self._listening:
            self._session.close_document()
            self._listening = None
            self._document = None
            self._player.set_document_length(0)
            self._bookmarks_panel.set_bookmarks([], show_pages=False)
            if self._media is not None:
                self._media.set_status(PlaybackStatus.CLOSED)
        if tab.document is self._text_view_document:
            self._text_view_document = None
            self._view.clear_document()
        if tab.document is self._page_view_document:
            self._page_view_document = None
            self._page_view.clear_document()  # Also lets go of the file.
        if tab.document is self._shown:
            self._shown = None
        self._tabs.remove(tab)
        index = self._tab_strip.index_of(key)
        if index == self._tab_strip.currentIndex() and index > 0:
            # Show the tab to the left, as browsers do (the home page if none).
            self._tab_strip.setCurrentIndex(index - 1)
        self._tab_strip.removeTab(self._tab_strip.index_of(key))
        self._update_now_playing()
        self._update_controls()
        self._update_times()

    @Slot()
    def _close_current_tab(self) -> None:
        tab = self._current_tab()
        if tab is not None:
            self.close_tab(tab.key)

    def _show_tab(self, tab: DocumentTab | None) -> None:
        """Show a tab's document (or the home page, or a loading page)."""
        shown_view = self._views.currentWidget()
        if shown_view in (self._view, self._page_view) and self._shown is not None:
            leaving = next((t for t in self._tabs if t.document is self._shown), None)
            if leaving is not None and leaving is not tab:
                leaving.scroll = self._active_view().verticalScrollBar().value()
        if tab is None:
            self._home.set_recents(self._session.recent_documents(limit=24), self._cover_for)
            self._views.setCurrentWidget(self._home)
            self._banner.hide()
            self.setWindowTitle(APP_NAME)
            return
        self.setWindowTitle(f"{tab.title} - {APP_NAME}")
        document = tab.document
        if document is None:
            self._loading.show_loading(tab.title, tab.progress)
            self._loading.set_progress(0, 0)
            self._views.setCurrentWidget(self._loading)
            return
        use_pages = self._page_images_action.isChecked() and document.word_map is not None
        view: PageView | DocumentView = self._page_view if use_pages else self._view
        new_document = document is not self._shown
        self._shown = document
        # Only the view on screen is filled in; the other waits until it's needed
        # (laying out the text of a long book takes a moment).
        if view is self._page_view and self._page_view_document is not document:
            self._page_view_document = document
            self._page_view.set_document(document)
        elif view is self._view and self._text_view_document is not document:
            self._text_view_document = document
            self._view.set_document(document)
        self._views.setCurrentWidget(view)
        listening = tab is self._listening
        # Only what's being read is highlighted; other tabs are just shown.
        position = self._session.position if listening else -1
        view.highlight(position)
        if listening:
            self._view.set_bookmarked({b.anchor.index for b in self._session.bookmarks()})
        else:
            self._banner.hide()
        reading = listening and self._session.state is ReadingState.PLAYING
        if new_document and not reading and tab.scroll is not None:
            # Back where this tab was left (once the new layout is in place); while it
            # is being read aloud, the view follows the voice instead.
            value = tab.scroll
            QTimer.singleShot(0, lambda: view.restore_scroll(value))

    def _update_now_playing(self) -> None:
        """Show what's being read when another tab (or home) is on screen."""
        listening = self._listening
        reading = self._session.state in (ReadingState.PLAYING, ReadingState.PAUSED)
        if listening is None or self._current_tab() is listening or not reading:
            self._player.set_now_playing(None)
        else:
            self._player.set_now_playing(listening.title)

    @Slot()
    def _toggle_play(self) -> None:
        """Play/Pause; on another tab (with nothing playing), read that tab instead."""
        if self._session.state is ReadingState.PLAYING:
            self._session.pause()
            return
        tab = self._current_tab()
        if tab is not None and tab.document is not None and tab is not self._listening:
            self._activate(tab)
        self._session.play()

    @Slot(int)
    def _on_sentence_clicked(self, index: int) -> None:
        """Read from the clicked sentence, switching listening to this tab if needed."""
        tab = self._current_tab()
        if tab is not None and tab is not self._listening and tab.document is not None:
            self._activate(tab, index)
        self._session.seek(index, play=True)

    def _restore_tabs(self) -> None:
        """Bring back the files that were open in tabs when the app was closed."""
        current = None
        for i, location in enumerate(self._settings.open_tabs):
            if is_web_address(location) or not Path(location).is_file():
                continue
            tab = self._add_tab(DocumentTab(Path(location).name, location=location))
            if i == self._settings.current_tab:
                current = tab
        if current is not None:
            self._select(current)

    def _viewed_document(self) -> ReadingDocument | None:
        tab = self._current_tab()
        return tab.document if tab is not None else None

    # ------------------------------------------------- spoken word and time

    @Slot()
    def _on_tick(self) -> None:
        """Follow the spoken word, and refresh the listening times now and then."""
        if self._word_highlight_action.isChecked() and self._shown is self._document:
            word = self._session.current_word()
            if word is not None:
                self._view.highlight_word(*word)
                self._page_view.highlight_word(*word)
        if time.monotonic() - self._times_refreshed >= _TIME_REFRESH_SECONDS:
            self._update_times()

    def _clear_word_highlight(self) -> None:
        position = self._session.position
        self._view.highlight_word(position, -1)
        self._page_view.highlight_word(position, -1)

    def _update_times(self) -> None:
        self._times_refreshed = time.monotonic()
        if self._document is None:
            self._player.set_times(0.0, 0.0)
            return
        self._player.set_times(*self._session.listening_time())

    @Slot(bool)
    def _on_word_highlight(self, on: bool) -> None:
        self._settings.word_highlight = on
        if not on:
            self._clear_word_highlight()

    # ------------------------------------------------------ reading comfort

    @Slot(QAction)
    def _on_theme_chosen(self, action: QAction) -> None:
        theme = action.data()
        if not isinstance(theme, str) or theme == self._settings.theme:
            return
        self._settings.theme = theme
        app = QApplication.instance()
        if isinstance(app, QApplication):
            apply_theme(app, theme)
        self._page_view.set_page_tint(SEPIA_PAGE_TINT if theme == "sepia" else None)
        # Colours fixed when things were drawn: refresh them for the new theme.
        self._view.refresh_colors()
        self._home.refresh_style()
        self._refresh_icons()

    def _refresh_icons(self) -> None:
        for action, glyph in self._glyph_actions():
            action.setIcon(make_icon(glyph, self))
        self._play_icon = make_icon(Glyph.PLAY, self)
        self._pause_icon = make_icon(Glyph.PAUSE, self)
        self._preview_button.setIcon(make_icon(Glyph.VOLUME, self))
        self._tab_strip.refresh_icons()
        for tab in self._tabs:
            self._tab_strip.update_tab(tab, listening=tab is self._listening)
        self._update_controls()

    def _glyph_actions(self) -> list[tuple[QAction, Glyph]]:
        return [
            (self._open_action, Glyph.OPEN),
            (self._open_link_action, Glyph.LINK),
            (self._export_action, Glyph.SAVE),
            (self._new_text_action, Glyph.NEW_TEXT),
            (self._paste_action, Glyph.PASTE),
            (self._edit_text_action, Glyph.EDIT),
            (self._stop_action, Glyph.STOP),
            (self._prev_action, Glyph.PREVIOUS),
            (self._next_action, Glyph.NEXT),
            (self._add_bookmark_action, Glyph.BOOKMARK),
            (self._show_bookmarks_action, Glyph.BOOKMARKS),
            (self._home_action, Glyph.HOME),
        ]

    @Slot(bool)
    def _on_dyslexic_font(self, on: bool) -> None:
        self._settings.dyslexic_font = on
        self._view.set_font_family(DYSLEXIC_FONT if on else "Segoe UI")
        if on and self._views.currentWidget() is self._page_view:
            self._notify(
                "The dyslexia-friendly font is used in the text view "
                "(Settings > Show PDFs as Page Images: off)",
                4000,
            )

    # ------------------------------------------------------------- export

    @Slot()
    def _export_audio(self) -> None:
        document = self._viewed_document() or self._document
        if document is None:
            return
        if self._session.is_exporting:
            self._notify("Audio is already being saved")
            return
        folder = self._settings.last_folder or str(Path.home() / "Documents")
        name = _safe_file_name(document.title) + ".mp3"
        chosen, _ = QFileDialog.getSaveFileName(
            self,
            "Export Audio",
            str(Path(folder) / name),
            "MP3 audio (*.mp3);;WAV audio (*.wav)",
        )
        if not chosen:
            return
        path = Path(chosen)
        if path.suffix.lower() not in EXPORT_SUFFIXES:
            path = path.with_name(path.name + ".mp3")
        if not self._session.start_export(path, document):
            self._notify("Audio can be saved once the voice model is ready")
            return
        dialog = QProgressDialog("Saving audio\u2026", "Cancel", 0, document.sentence_count, self)
        dialog.setWindowTitle("Export Audio")
        dialog.setWindowModality(Qt.WindowModality.NonModal)
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.canceled.connect(self._session.cancel_export)
        dialog.show()
        self._export_dialog = dialog
        self._export_started = time.monotonic()
        self._update_controls()

    @Slot(int, int)
    def _on_export_progress(self, done: int, total: int) -> None:
        dialog = self._export_dialog
        if dialog is None:
            return
        dialog.setMaximum(total)
        dialog.setValue(done)
        elapsed = time.monotonic() - self._export_started
        if done >= 3 and elapsed > 2:
            left = elapsed / done * (total - done)
            minutes = max(1, round(left / 60))
            dialog.setLabelText(
                f"Saving audio\u2026 {done:,} of {total:,} sentences (about {minutes} min left)"
            )
        else:
            dialog.setLabelText(f"Saving audio\u2026 {done:,} of {total:,} sentences")

    def _close_export_dialog(self) -> None:
        if self._export_dialog is not None:
            self._export_dialog.canceled.disconnect()
            self._export_dialog.close()
            self._export_dialog.deleteLater()
            self._export_dialog = None
        self._update_controls()

    @Slot(object)
    def _on_export_finished(self, path: Path) -> None:
        self._close_export_dialog()
        box = QMessageBox(self)
        box.setWindowTitle("Audio saved")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(f"Saved {path.name}")
        box.setInformativeText(str(path.parent))
        show = box.addButton("Show in Folder", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Ok)
        box.exec()
        if box.clickedButton() is show:
            subprocess.Popen(["explorer", f"/select,{path}"])

    @Slot(str, bool)
    def _on_export_failed(self, message: str, cancelled: bool) -> None:
        self._close_export_dialog()
        if cancelled:
            self._notify("Export cancelled")
        else:
            QMessageBox.warning(self, "Couldn't save the audio", message)

    # -------------------------------------------------------------- media

    @Slot(object)
    def _on_media_command(self, command: MediaCommand) -> None:
        """Handle media keys, headset buttons, and the Windows media panel."""
        if command is MediaCommand.PLAY:
            self._session.play()
        elif command is MediaCommand.PAUSE:
            self._session.pause()
        elif command is MediaCommand.STOP:
            self._session.stop()
        elif command is MediaCommand.NEXT:
            self._session.next_sentence()
        elif command is MediaCommand.PREVIOUS:
            self._session.previous_sentence()

    def _update_media_status(self, state: ReadingState) -> None:
        if self._media is None:
            return
        if self._document is None:
            status = PlaybackStatus.CLOSED
        elif state is ReadingState.PLAYING:
            status = PlaybackStatus.PLAYING
        elif state is ReadingState.PAUSED:
            status = PlaybackStatus.PAUSED
        else:
            status = PlaybackStatus.STOPPED
        self._media.set_status(status)

    @Slot(bool)
    def _show_page_images(self, show: bool) -> None:
        self._settings.page_view = show
        if self._page_images_action.isChecked() != show:
            self._page_images_action.blockSignals(True)
            self._page_images_action.setChecked(show)
            self._page_images_action.blockSignals(False)
        self._show_tab(self._current_tab())

    def _show_home(self) -> None:
        """Show the home page with up-to-date recent documents."""
        if self._tab_strip.currentIndex() != 0:
            self._tab_strip.setCurrentIndex(0)
        else:
            self._show_tab(None)

    def _cover_for(self, doc_id: str) -> Path | None:
        path = self._session.thumbnail_path(doc_id)
        return path if path.exists() else None

    @Slot(str)
    def _forget_document(self, doc_id: str) -> None:
        self._session.forget_document(doc_id)
        self._show_tab(None)

    @Slot()
    def _reading_options_changed(self) -> None:
        self._settings.read_parentheses = self._parentheses_action.isChecked()
        self._settings.skip_asides = self._asides_action.isChecked()
        self._session.set_pipeline(
            build_pipeline(
                read_parentheses=self._settings.read_parentheses,
                skip_asides=self._settings.skip_asides,
            ),
            reopen=False,
        )
        # Every open document is read again with the new settings.
        for tab in self._tabs:
            document = tab.document
            if document is None:
                continue
            if document.path is not None:
                tab.request = self._session.prepare_document(document.path)
            elif document.text is not None:
                tab.request = self._session.prepare_text(
                    document.text,
                    title=document.title,
                    doc_id=document.doc_id,
                    source_url=document.source_url,
                )
        self._update_controls()

    # ------------------------------------------------------------ copy & zoom

    def _active_view(self) -> PageView | DocumentView:
        return self._page_view if self._views.currentWidget() is self._page_view else self._view

    @Slot()
    def _copy(self) -> None:
        view = self._active_view()
        text = view.selected_text()
        document = self._viewed_document()
        if not text and document is not None and document.sentences:
            # Nothing selected: copy the sentence being read (or this tab's sentence).
            tab = self._current_tab()
            if document is self._document:
                index = self._session.position
            else:
                index = (tab.position or 0) if tab is not None else 0
            text = document.sentences[min(index, document.sentence_count - 1)].text
        if text:
            QGuiApplication.clipboard().setText(text)
            self._notify("Copied")

    @Slot()
    def _copy_all(self) -> None:
        document = self._viewed_document()
        if document is None:
            return
        paragraphs: list[list[str]] = []
        last_block = None
        for sentence in document.sentences:
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
        self._ocr_progress = f"Reading scanned pages\u2026 {done} of {total}"
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
        self._update_times()

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
        viewed = self._viewed_document()
        can_read = (
            model_ready and (has_doc or viewed is not None) and state is not ReadingState.LOADING
        )
        playing = state is ReadingState.PLAYING

        self._play_action.setEnabled(can_read)
        self._play_action.setIcon(self._pause_icon if playing else self._play_icon)
        self._play_action.setText("&Pause" if playing else "&Play")
        self._stop_action.setEnabled(state in (ReadingState.PLAYING, ReadingState.PAUSED))
        can_bookmark = self._session.can_bookmark and state is not ReadingState.LOADING
        self._add_bookmark_action.setEnabled(can_bookmark)
        self._bookmarks_panel.set_can_add(can_bookmark)
        self._edit_text_action.setEnabled(
            viewed is not None
            and viewed.text is not None
            and viewed.source_url is None
            and viewed.path is None
            and state is not ReadingState.LOADING
        )
        self._export_action.setEnabled(
            model_ready
            and viewed is not None
            and state is not ReadingState.LOADING
            and not self._session.is_exporting
        )
        self._close_tab_action.setEnabled(self._current_tab() is not None)
        # The player appears once there is something to listen to.
        self._player.setVisible(has_doc or viewed is not None)
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
            elif self._doc_loading_name == "link":
                label = "Opening link..."
            elif self._doc_loading_name:
                label = f"Opening {self._doc_loading_name}..."
            else:
                label = _STATE_LABELS[state]
        elif state is ReadingState.IDLE and not model_ready:
            label = "Voice model not installed. Use Help > Download Voice Model."
        else:
            label = ""  # The play button and the tabs already say what's going on.
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
        # Pages where there are pages; sentences for text, which has none.
        self._page_label.setVisible(document.is_paginated)
        self._page_label.setText(f"Page {page} of {document.page_count}")
        self._sentence_label.setVisible(not document.is_paginated)
        self._sentence_label.setText(f"Sentence {index + 1} of {document.sentence_count}")

    def _show_about(self) -> None:
        link = f'<p><a href="{PROJECT_URL}">{PROJECT_URL}</a></p>' if PROJECT_URL else ""
        QMessageBox.about(
            self,
            f"About {APP_NAME}",
            f"<h3>{APP_NAME} {APP_VERSION}</h3>"
            "<p>Reads PDFs, e-books, Word documents, and web pages aloud with natural AI "
            "voices, on your own computer.</p>"
            "<p>Voices: Kokoro-82M (Apache-2.0) via kokoro-onnx (MIT).<br>"
            "PDF: PyMuPDF (AGPL-3.0). UI: Qt / PySide6 (LGPL-3.0).<br>"
            "MP3: LAME via lameenc (LGPL). Font: OpenDyslexic (SIL OFL 1.1).</p>"
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
            # Files open in tabs come back next time (pasted text and web pages don't).
            files = [t for t in self._tabs if t.location and not is_web_address(t.location)]
            self._settings.open_tabs = [t.location for t in files if t.location]
            current = self._current_tab()
            self._settings.current_tab = files.index(current) if current in files else -1
            self._word_timer.stop()
            save_settings(self._settings, self._settings_path)
            self._session.shutdown()
            self._page_view.clear_document()
            if self._media is not None:
                self._media.close()
        super().closeEvent(event)


def _first_document(urls: list[QUrl]) -> Path | str | None:
    """Return the first dropped document file (a Path) or web link (a str)."""
    for url in urls:
        if url.isLocalFile():
            path = Path(url.toLocalFile())
            if path.suffix.lower() in _DOCUMENT_SUFFIXES:
                return path
        elif url.scheme() in ("http", "https"):
            return url.toString()
    return None


def _documents(urls: list[QUrl]) -> list[Path | str]:
    """Return every dropped document file (a Path) and web link (a str), in order."""
    found: list[Path | str] = []
    for url in urls:
        target = _first_document([url])
        if target is not None:
            found.append(target)
    return found


def _safe_file_name(title: str) -> str:
    """Make a file name from a document title."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", title).strip(" .")
    return " ".join(name.split())[:80] or "Audio"


def _spacer() -> QWidget:
    spacer = QWidget()
    spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    return spacer
