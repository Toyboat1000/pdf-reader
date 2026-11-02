"""Resumable, verified file downloads for model files.

Files are written to ``<name>.part`` and only renamed into place after their size and
SHA-256 hash match, so an interrupted or corrupted download never looks complete.
"""

import hashlib
import http.client
import logging
import threading
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from pdf_reader.config.constants import APP_NAME, APP_VERSION

log = logging.getLogger(__name__)

type ProgressCallback = Callable[[int, int], None]
"""Called with ``(bytes_done, bytes_total)`` across all files being downloaded."""

_CHUNK_SIZE = 256 * 1024
_TIMEOUT_SECONDS = 30


@dataclass(frozen=True, slots=True)
class RemoteFile:
    """A file to download and verify.

    Attributes:
        name: File name on disk.
        url: Download URL.
        size: Expected size in bytes.
        sha256: Expected SHA-256 hex digest.
    """

    name: str
    url: str
    size: int
    sha256: str


class DownloadError(Exception):
    """A download failed; ``user_message`` explains why in plain language."""

    def __init__(self, user_message: str) -> None:
        super().__init__(user_message)
        self.user_message = user_message


class DownloadCancelledError(Exception):
    """The download was cancelled by the user."""


def is_present(file: RemoteFile, directory: Path) -> bool:
    """Return whether ``file`` exists in ``directory`` with the expected size.

    This is a quick check suitable for every app start; the full hash is verified
    right after downloading.
    """
    path = directory / file.name
    try:
        return path.is_file() and path.stat().st_size == file.size
    except OSError:
        return False


def sha256_of(path: Path, cancel: threading.Event | None = None) -> str:
    """Compute the SHA-256 hex digest of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            if cancel is not None and cancel.is_set():
                raise DownloadCancelledError
            digest.update(chunk)
    return digest.hexdigest()


def download_files(
    files: Sequence[RemoteFile],
    directory: Path,
    progress: ProgressCallback | None = None,
    cancel: threading.Event | None = None,
) -> None:
    """Download every file in ``files`` that is not already present.

    Partial downloads from earlier attempts are resumed when the server supports it.

    Args:
        files: Files to fetch.
        directory: Destination folder; created if needed.
        progress: Optional progress callback, called from the calling thread.
        cancel: Optional event; when set, the download stops promptly.

    Raises:
        DownloadError: Network, disk, or verification failure.
        DownloadCancelledError: ``cancel`` was set.
    """
    cancel = cancel or threading.Event()
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise DownloadError(f"Couldn't create the folder {directory}: {exc.strerror}") from exc

    total = sum(f.size for f in files)
    done_before = 0
    for file in files:
        if is_present(file, directory):
            done_before += file.size
            continue

        def report(file_done: int, base: int = done_before) -> None:
            if progress is not None:
                progress(base + file_done, total)

        _download_one(file, directory, report, cancel)
        done_before += file.size
    if progress is not None:
        progress(total, total)


def _download_one(
    file: RemoteFile, directory: Path, report: Callable[[int], None], cancel: threading.Event
) -> None:
    final = directory / file.name
    part = directory / (file.name + ".part")
    resume_from = part.stat().st_size if part.exists() else 0
    if resume_from > file.size:
        part.unlink()
        resume_from = 0

    if resume_from < file.size:
        _fetch(file, part, resume_from, report, cancel)
    report(file.size)

    log.info("Verifying %s", file.name)
    actual = sha256_of(part, cancel)
    if actual != file.sha256:
        part.unlink(missing_ok=True)
        log.error("Hash mismatch for %s: expected %s, got %s", file.name, file.sha256, actual)
        raise DownloadError(
            f"The downloaded file {file.name} was damaged or has changed on the server. "
            "Please try again. If this keeps happening, please report it on the "
            "project's GitHub page."
        )
    part.replace(final)
    log.info("Downloaded %s", file.name)


def _fetch(
    file: RemoteFile,
    part: Path,
    resume_from: int,
    report: Callable[[int], None],
    cancel: threading.Event,
) -> None:
    headers = {"User-Agent": f"{APP_NAME}/{APP_VERSION}"}
    if resume_from:
        headers["Range"] = f"bytes={resume_from}-"
    request = urllib.request.Request(file.url, headers=headers)
    log.info("Downloading %s (resume from %d)", file.url, resume_from)
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            if resume_from and response.status != 206:
                resume_from = 0  # Server ignored the Range header; start over.
            done = resume_from
            with part.open("ab" if resume_from else "wb") as out:
                while chunk := response.read(_CHUNK_SIZE):
                    if cancel.is_set():
                        raise DownloadCancelledError
                    out.write(chunk)
                    done += len(chunk)
                    if done > file.size:
                        raise DownloadError(
                            f"The server sent more data than expected for {file.name}. "
                            "Please try again later."
                        )
                    report(done)
    except DownloadCancelledError:
        log.info("Download of %s cancelled", file.name)
        raise
    except urllib.error.HTTPError as exc:
        if exc.code == 416:  # Range not satisfiable: the partial file is unusable.
            part.unlink(missing_ok=True)
        raise DownloadError(
            f"The download server responded with an error ({exc.code} {exc.reason}). "
            "Please try again later."
        ) from exc
    except (urllib.error.URLError, http.client.HTTPException, TimeoutError, ConnectionError) as exc:
        log.warning("Network error downloading %s: %s", file.url, exc)
        raise DownloadError(
            "Couldn't connect to the download server. Please check your internet "
            "connection and try again."
        ) from exc
    except OSError as exc:
        log.warning("Disk error writing %s: %s", part, exc)
        raise DownloadError(
            f"Couldn't save the file: {exc.strerror or exc}. Check that there is enough "
            "free disk space."
        ) from exc
    if done != file.size:
        raise DownloadError(
            f"The download of {file.name} was interrupted. Please try again; it will "
            "continue where it left off."
        )
