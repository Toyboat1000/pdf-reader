"""Application start-up: logging, settings, engine, session, and the main window."""

import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from pdf_reader.config.constants import APP_NAME, APP_VERSION
from pdf_reader.config.log_setup import configure_logging
from pdf_reader.config.paths import (
    library_file,
    local_data_dir,
    logs_dir,
    models_dir,
    settings_file,
)
from pdf_reader.config.settings import load_settings
from pdf_reader.core.session import ReadingSession
from pdf_reader.library import LibraryStore
from pdf_reader.pdf.ocr_cache import OcrCache
from pdf_reader.sources import is_web_address
from pdf_reader.text.pipeline import build_pipeline
from pdf_reader.tts.kokoro_engine import KokoroEngine
from pdf_reader.ui.bridge import SessionBridge
from pdf_reader.ui.main_window import MainWindow
from pdf_reader.ui.single_instance import SingleInstance
from pdf_reader.ui.theme import apply_theme, load_bundled_fonts

log = logging.getLogger(__name__)

APP_ICON = Path(__file__).parent / "assets" / "app.ico"
"""The window and taskbar icon (drawn by ``packaging/make_artwork.py``)."""


def run(argv: Sequence[str] | None = None) -> int:
    """Start the GUI and block until it exits.

    Args:
        argv: Command-line arguments; an optional first argument is a document to open
            (a file or a web address).

    Returns:
        The process exit code.
    """
    args = list(sys.argv if argv is None else argv)
    log_file = configure_logging(logs_dir())
    log.info("Starting %s %s (log: %s)", APP_NAME, APP_VERSION, log_file)
    _set_windows_app_id()

    app = QApplication(args)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setWindowIcon(QIcon(str(APP_ICON)))

    initial = args[1] if len(args) > 1 else None
    if initial and not is_web_address(initial):
        initial = str(Path(initial).resolve())  # The running copy has another folder.
    instance = SingleInstance()
    if instance.send_to_running(initial or ""):
        log.info("Already running: handed over to that copy")
        return 0
    instance.listen()
    load_bundled_fonts()

    settings_path = settings_file()
    settings = load_settings(settings_path)
    apply_theme(app, settings.theme)
    bridge = SessionBridge()
    session = ReadingSession(
        KokoroEngine(models_dir()),
        bridge,
        voice=settings.voice,
        speed=settings.speed,
        library=LibraryStore(library_file()),
        ocr_cache=OcrCache(local_data_dir() / "ocr-cache"),
        thumbnail_dir=local_data_dir() / "thumbnails",
        download_dir=local_data_dir() / "downloads",
        pipeline=build_pipeline(
            read_parentheses=settings.read_parentheses, skip_asides=settings.skip_asides
        ),
    )
    window = MainWindow(session, bridge, settings, settings_path, media_controls=True)
    window.show()
    instance.message_received.connect(window.bring_forward)

    # Start after the event loop is running so the window paints first.
    QTimer.singleShot(0, lambda: window.start(initial))
    code = app.exec()
    log.info("Exiting with code %d", code)
    return code


def _set_windows_app_id() -> None:
    """Give the app its own taskbar identity instead of grouping it with Python."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_NAME)
    except (AttributeError, OSError):
        log.debug("Could not set AppUserModelID", exc_info=True)
