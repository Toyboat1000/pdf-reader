"""Tests for verified, resumable downloads against a local HTTP server."""

import hashlib
import http.server
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from pdf_reader.tts.download import (
    DownloadCancelledError,
    DownloadError,
    RemoteFile,
    download_files,
    is_present,
)

PAYLOAD = bytes(range(256)) * 4096  # 1 MiB of varied data.


class _Handler(http.server.BaseHTTPRequestHandler):
    payload = PAYLOAD
    honour_range = True
    requests: list[str | None] = []  # noqa: RUF012 - shared by design in tests.

    def do_GET(self) -> None:
        range_header = self.headers.get("Range")
        type(self).requests.append(range_header)
        if self.path == "/missing":
            self.send_error(404)
            return
        start = 0
        if range_header and self.honour_range:
            start = int(range_header.removeprefix("bytes=").split("-")[0])
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(self.payload) - 1}/*")
        else:
            self.send_response(200)
        body = self.payload[start:]
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *args: object) -> None:
        pass


@pytest.fixture
def server() -> Iterator[str]:
    _Handler.requests = []
    _Handler.honour_range = True
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def remote(base: str, name: str = "model.bin", sha: str | None = None) -> RemoteFile:
    return RemoteFile(
        name=name,
        url=f"{base}/{name}",
        size=len(PAYLOAD),
        sha256=sha or hashlib.sha256(PAYLOAD).hexdigest(),
    )


def test_downloads_and_verifies(server: str, tmp_path: Path) -> None:
    progress: list[tuple[int, int]] = []
    file = remote(server)
    download_files([file], tmp_path, lambda done, total: progress.append((done, total)))
    assert (tmp_path / "model.bin").read_bytes() == PAYLOAD
    assert not (tmp_path / "model.bin.part").exists()
    assert progress[-1] == (len(PAYLOAD), len(PAYLOAD))
    assert all(done <= total for done, total in progress)
    assert is_present(file, tmp_path)


def test_progress_spans_multiple_files(server: str, tmp_path: Path) -> None:
    progress: list[tuple[int, int]] = []
    files = [remote(server, "a.bin"), remote(server, "b.bin")]
    download_files(files, tmp_path, lambda done, total: progress.append((done, total)))
    totals = {total for _, total in progress}
    assert totals == {2 * len(PAYLOAD)}
    dones = [done for done, _ in progress]
    assert dones == sorted(dones)


def test_present_files_are_skipped(server: str, tmp_path: Path) -> None:
    (tmp_path / "model.bin").write_bytes(PAYLOAD)
    download_files([remote(server)], tmp_path)
    assert _Handler.requests == []


def test_hash_mismatch_fails_and_leaves_nothing(server: str, tmp_path: Path) -> None:
    with pytest.raises(DownloadError, match="damaged"):
        download_files([remote(server, sha="0" * 64)], tmp_path)
    assert not (tmp_path / "model.bin").exists()
    assert not (tmp_path / "model.bin.part").exists()


def test_resumes_partial_download(server: str, tmp_path: Path) -> None:
    (tmp_path / "model.bin.part").write_bytes(PAYLOAD[:1000])
    download_files([remote(server)], tmp_path)
    assert _Handler.requests == ["bytes=1000-"]
    assert (tmp_path / "model.bin").read_bytes() == PAYLOAD


def test_restarts_when_server_ignores_range(server: str, tmp_path: Path) -> None:
    _Handler.honour_range = False
    (tmp_path / "model.bin.part").write_bytes(b"x" * 1000)  # Junk that must be replaced.
    download_files([remote(server)], tmp_path)
    assert (tmp_path / "model.bin").read_bytes() == PAYLOAD


def test_oversized_partial_file_is_discarded(server: str, tmp_path: Path) -> None:
    (tmp_path / "model.bin.part").write_bytes(b"x" * (len(PAYLOAD) + 10))
    download_files([remote(server)], tmp_path)
    assert _Handler.requests == [None]
    assert (tmp_path / "model.bin").read_bytes() == PAYLOAD


def test_cancel_keeps_partial_file(server: str, tmp_path: Path) -> None:
    cancel = threading.Event()

    def progress(done: int, _total: int) -> None:
        if done > 0:
            cancel.set()

    with pytest.raises(DownloadCancelledError):
        download_files([remote(server)], tmp_path, progress, cancel)
    assert not (tmp_path / "model.bin").exists()
    assert (tmp_path / "model.bin.part").exists()


def test_http_error_is_friendly(server: str, tmp_path: Path) -> None:
    file = RemoteFile("missing", f"{server}/missing", 10, "0" * 64)
    with pytest.raises(DownloadError, match="404"):
        download_files([file], tmp_path)


def test_no_connection_is_friendly(tmp_path: Path) -> None:
    file = RemoteFile("x.bin", "http://127.0.0.1:9/x.bin", 10, "0" * 64)
    with pytest.raises(DownloadError, match="internet connection"):
        download_files([file], tmp_path)


def test_is_present_checks_size(tmp_path: Path) -> None:
    file = RemoteFile("f.bin", "http://unused", 4, "0" * 64)
    assert not is_present(file, tmp_path)
    (tmp_path / "f.bin").write_bytes(b"abc")
    assert not is_present(file, tmp_path)
    (tmp_path / "f.bin").write_bytes(b"abcd")
    assert is_present(file, tmp_path)
