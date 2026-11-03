r"""Saved OCR results, so a scanned PDF is only recognized once.

Results are stored per document (keyed by the SHA-256 of the file's contents) as
compressed JSON under ``%LOCALAPPDATA%\\<AppName>\\ocr-cache``. Only the raw words
and their positions are stored; grouping into paragraphs is recomputed on load, so
improvements to that logic apply to cached documents too. A version number in the
file invalidates old caches if recognition itself changes.
"""

import gzip
import json
import logging
from pathlib import Path

from pdf_reader.pdf.ocr import OCR_DPI, RawLine

log = logging.getLogger(__name__)

CACHE_VERSION = 1


class OcrCache:
    """Reads and writes OCR results for documents."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def _path(self, file_hash: str) -> Path:
        return self._directory / f"{file_hash}.json.gz"

    def load(self, file_hash: str) -> dict[int, list[RawLine]]:
        """Return cached results by page number (empty if there are none or they're stale)."""
        path = self._path(file_hash)
        try:
            data = json.loads(gzip.decompress(path.read_bytes()))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError, EOFError):
            log.warning("Ignoring unreadable OCR cache %s", path)
            return {}
        if data.get("version") != CACHE_VERSION or data.get("dpi") != OCR_DPI:
            return {}
        pages: dict[int, list[RawLine]] = {}
        for number, lines in data.get("pages", {}).items():
            pages[int(number)] = [
                [
                    (str(text), (float(b[0]), float(b[1]), float(b[2]), float(b[3])))
                    for text, b in line
                ]
                for line in lines
            ]
        return pages

    def save(self, file_hash: str, pages: dict[int, list[RawLine]]) -> None:
        """Store results for a document, replacing any earlier ones. Errors are logged."""
        data = {
            "version": CACHE_VERSION,
            "dpi": OCR_DPI,
            "pages": {
                str(n): [[[text, list(box)] for text, box in line] for line in lines]
                for n, lines in pages.items()
            },
        }
        path = self._path(file_hash)
        tmp = path.with_suffix(".tmp")
        try:
            self._directory.mkdir(parents=True, exist_ok=True)
            tmp.write_bytes(gzip.compress(json.dumps(data, separators=(",", ":")).encode(), 6))
            tmp.replace(path)
        except OSError:
            log.warning("Could not save OCR cache %s", path, exc_info=True)
