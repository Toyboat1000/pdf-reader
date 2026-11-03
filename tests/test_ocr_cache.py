"""Saved OCR results: reuse, invalidation, and the parallel recognizer."""

from pathlib import Path
from typing import Any

import pytest

from pdf_reader.pdf import load_pdf, ocr_cache
from pdf_reader.pdf import loader as loader_module
from pdf_reader.pdf.ocr import ocr_available
from pdf_reader.pdf.ocr_cache import OcrCache
from scripts.make_sample_pdf import build_scanned_sample

LINES = {1: [[("Hello", (1.0, 2.0, 3.0, 4.0)), ("world.", (5.0, 2.0, 9.0, 4.0))]], 3: []}


def test_round_trip(tmp_path: Path) -> None:
    cache = OcrCache(tmp_path)
    cache.save("abc", LINES)
    assert cache.load("abc") == LINES
    assert cache.load("missing") == {}


def test_stale_or_damaged_cache_is_ignored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache = OcrCache(tmp_path)
    cache.save("abc", LINES)
    monkeypatch.setattr(ocr_cache, "CACHE_VERSION", 99)
    assert cache.load("abc") == {}
    (tmp_path / "bad.json.gz").write_bytes(b"not gzip")
    assert cache.load("bad") == {}


@pytest.mark.skipif(not ocr_available(), reason="Windows OCR is not available")
def test_scanned_pdf_is_recognized_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "scan.pdf"
    build_scanned_sample(path)
    cache = OcrCache(tmp_path / "cache")
    first = load_pdf(path, ocr_cache=cache)

    def no_ocr(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("OCR should not run again")

    monkeypatch.setattr(loader_module, "recognize_pages", no_ocr)
    second = load_pdf(path, ocr_cache=cache)
    assert [p.words for p in second.pages] == [p.words for p in first.pages]
    assert [b.text for p in second.pages for b in p.blocks] == [
        b.text for p in first.pages for b in p.blocks
    ]
