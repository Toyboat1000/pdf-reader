"""Persistent, thread-safe storage of reading positions and bookmarks.

Everything lives in one small JSON file (``library.json`` next to the settings).
Changes are kept in memory and written by :meth:`LibraryStore.flush`, which callers
invoke at natural moments (pause, stop, closing a document); :meth:`save_if_due`
limits writes while reading continuously. Loading never fails: a missing or damaged
file starts an empty library, and invalid entries are skipped individually.
"""

import json
import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pdf_reader.library.models import Anchor, Bookmark, DocumentRecord

log = logging.getLogger(__name__)

FORMAT_VERSION = 1
MAX_DOCUMENTS = 200
"""Documents remembered; the least recently opened are forgotten first."""

MAX_LABEL_CHARS = 120


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class LibraryStore:
    """Remembers documents, their reading positions, and their bookmarks."""

    def __init__(self, path: Path, *, max_documents: int = MAX_DOCUMENTS) -> None:
        self._path = path
        self._max_documents = max_documents
        self._lock = threading.Lock()
        self._records: dict[str, DocumentRecord] = _load(path)
        self._dirty = False
        self._last_flush = time.monotonic()

    # ------------------------------------------------------------- documents

    def open_document(self, doc_id: str, title: str, path: Path | None) -> DocumentRecord:
        """Record that a document was opened and return a copy of its record."""
        now = _now()
        with self._lock:
            record = self._records.get(doc_id)
            if record is None:
                record = DocumentRecord(doc_id, title, None, now)
                self._records[doc_id] = record
            record.title = title
            record.path = str(path) if path is not None else record.path
            record.last_opened = now
            self._prune()
            self._dirty = True
            return _copy(record)

    def get(self, doc_id: str) -> DocumentRecord | None:
        """Return a copy of a document's record, if it is known."""
        with self._lock:
            record = self._records.get(doc_id)
            return _copy(record) if record is not None else None

    def recent(self, limit: int = 10) -> list[DocumentRecord]:
        """Return copies of the most recently opened documents that have a path."""
        with self._lock:
            records = sorted(
                (r for r in self._records.values() if r.path),
                key=lambda r: r.last_opened,
                reverse=True,
            )
            return [_copy(r) for r in records[:limit]]

    def forget(self, doc_id: str) -> None:
        """Remove everything remembered about a document."""
        with self._lock:
            if self._records.pop(doc_id, None) is not None:
                self._dirty = True

    # -------------------------------------------------------------- position

    def set_position(self, doc_id: str, anchor: Anchor) -> None:
        """Remember where reading stopped (in memory until the next flush)."""
        with self._lock:
            record = self._records.get(doc_id)
            if record is not None and record.position != anchor:
                record.position = anchor
                self._dirty = True

    # ------------------------------------------------------------- bookmarks

    def add_bookmark(self, doc_id: str, anchor: Anchor, label: str) -> Bookmark:
        """Add a bookmark; adding one at an already bookmarked sentence returns that one.

        Raises:
            KeyError: The document is unknown (open it first).
        """
        with self._lock:
            record = self._records[doc_id]
            existing = next((b for b in record.bookmarks if b.anchor.index == anchor.index), None)
            if existing is not None:
                return existing
            bookmark = Bookmark(uuid.uuid4().hex[:12], anchor, _clean_label(label), _now())
            record.bookmarks.append(bookmark)
            self._dirty = True
            return bookmark

    def rename_bookmark(self, doc_id: str, bookmark_id: str, label: str) -> None:
        """Change a bookmark's label. Unknown ids are ignored."""
        self._update_bookmarks(
            doc_id,
            lambda b: replace(b, label=_clean_label(label)) if b.id == bookmark_id else b,
        )

    def remove_bookmark(self, doc_id: str, bookmark_id: str) -> None:
        """Delete a bookmark. Unknown ids are ignored."""
        self._update_bookmarks(doc_id, lambda b: None if b.id == bookmark_id else b)

    def set_bookmark_anchors(self, doc_id: str, anchors: dict[str, Anchor]) -> None:
        """Update bookmark anchors (after re-resolving them in a reprocessed document)."""
        self._update_bookmarks(
            doc_id, lambda b: replace(b, anchor=anchors[b.id]) if b.id in anchors else b
        )

    def _update_bookmarks(self, doc_id: str, change: Callable[[Bookmark], Bookmark | None]) -> None:
        with self._lock:
            record = self._records.get(doc_id)
            if record is None:
                return
            updated = [new for b in record.bookmarks if (new := change(b)) is not None]
            if updated != record.bookmarks:
                record.bookmarks = updated
                self._dirty = True

    # ----------------------------------------------------------- persistence

    def flush(self) -> None:
        """Write pending changes to disk (atomically). Errors are logged, not raised."""
        with self._lock:
            if not self._dirty:
                return
            data = {
                "version": FORMAT_VERSION,
                "documents": {doc_id: _to_json(r) for doc_id, r in self._records.items()},
            }
            self._dirty = False
            self._last_flush = time.monotonic()
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self._path)
        except OSError:
            log.exception("Could not save the library to %s", self._path)
            with self._lock:
                self._dirty = True

    def save_if_due(self, interval: float = 30.0) -> None:
        """Flush if there are changes and the last write was ``interval`` seconds ago."""
        with self._lock:
            due = self._dirty and time.monotonic() - self._last_flush >= interval
        if due:
            self.flush()

    def _prune(self) -> None:
        excess = len(self._records) - self._max_documents
        if excess > 0:
            oldest = sorted(self._records.values(), key=lambda r: r.last_opened)[:excess]
            for record in oldest:
                del self._records[record.doc_id]


def _clean_label(label: str) -> str:
    return " ".join(label.split())[:MAX_LABEL_CHARS] or "Bookmark"


def _copy(record: DocumentRecord) -> DocumentRecord:
    return replace(record, bookmarks=list(record.bookmarks))


# ---------------------------------------------------------------- JSON format


def _anchor_json(anchor: Anchor) -> dict[str, Any]:
    return {"index": anchor.index, "page": anchor.page, "text": anchor.text}


def _to_json(record: DocumentRecord) -> dict[str, Any]:
    return {
        "title": record.title,
        "path": record.path,
        "last_opened": record.last_opened,
        "position": _anchor_json(record.position) if record.position else None,
        "bookmarks": [
            {"id": b.id, "label": b.label, "created": b.created, **_anchor_json(b.anchor)}
            for b in record.bookmarks
        ],
    }


def _anchor_from(raw: Any) -> Anchor | None:
    if not isinstance(raw, dict):
        return None
    index, page, text = raw.get("index"), raw.get("page"), raw.get("text")
    if (
        isinstance(index, int)
        and not isinstance(index, bool)
        and index >= 0
        and isinstance(page, int)
        and not isinstance(page, bool)
        and isinstance(text, str)
    ):
        return Anchor(index, page, text)
    return None


def _record_from(doc_id: str, raw: Any) -> DocumentRecord | None:
    if not isinstance(raw, dict):
        return None
    title = raw.get("title")
    last_opened = raw.get("last_opened")
    if not isinstance(title, str) or not isinstance(last_opened, str):
        return None
    path = raw.get("path")
    bookmarks: list[Bookmark] = []
    for item in raw.get("bookmarks") or []:
        anchor = _anchor_from(item)
        if anchor is None or not isinstance(item.get("id"), str):
            continue
        label = item.get("label") if isinstance(item.get("label"), str) else "Bookmark"
        created = item.get("created") if isinstance(item.get("created"), str) else ""
        bookmarks.append(Bookmark(item["id"], anchor, label, created))
    return DocumentRecord(
        doc_id=doc_id,
        title=title,
        path=path if isinstance(path, str) else None,
        last_opened=last_opened,
        position=_anchor_from(raw.get("position")),
        bookmarks=bookmarks,
    )


def _load(path: Path) -> dict[str, DocumentRecord]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        log.warning("Library file %s is unreadable; starting an empty library", path)
        return {}
    documents = raw.get("documents") if isinstance(raw, dict) else None
    if not isinstance(documents, dict):
        log.warning("Library file %s has an unexpected format; starting empty", path)
        return {}
    records: dict[str, DocumentRecord] = {}
    for doc_id, entry in documents.items():
        record = _record_from(doc_id, entry)
        if record is None:
            log.warning("Skipping invalid library entry %s", doc_id)
        else:
            records[doc_id] = record
    return records
