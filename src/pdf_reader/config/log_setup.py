"""Logging configuration: a rotating log file plus stderr for development."""

import logging
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType

LOG_FORMAT = "%(asctime)s %(levelname)-8s [%(threadName)s] %(name)s: %(message)s"


def configure_logging(log_dir: Path, level: int = logging.INFO) -> Path | None:
    """Send log records to ``log_dir/app.log`` (rotated) and to stderr.

    Also routes uncaught exceptions, including those in background threads, to the log.

    Args:
        log_dir: Folder for the log files; created if needed.
        level: Minimum level for the application's own loggers.

    Returns:
        The log file path, or ``None`` if the file could not be opened.
    """
    root = logging.getLogger()
    root.setLevel(level)
    formatter = logging.Formatter(LOG_FORMAT)

    log_file: Path | None = log_dir / "app.log"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError:
        log_file = None

    # pythonw.exe (used for the GUI entry point) has no stderr.
    if sys.stderr is not None:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)

    _install_exception_hooks()
    if log_file is None:
        logging.getLogger(__name__).warning("Could not open log file in %s", log_dir)
    return log_file


def _install_exception_hooks() -> None:
    log = logging.getLogger("pdf_reader.uncaught")

    def handle(
        exc_type: type[BaseException],
        exc: BaseException,
        tb: TracebackType | None,
    ) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        log.critical("Uncaught exception", exc_info=(exc_type, exc, tb))

    def handle_thread(args: threading.ExceptHookArgs) -> None:
        if args.exc_value is None:
            return
        log.critical(
            "Uncaught exception in thread %s",
            args.thread.name if args.thread else "?",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = handle
    threading.excepthook = handle_thread
