import json
from pathlib import Path

import pytest

from pdf_reader.library import Anchor, LibraryStore, file_id, make_anchor, resolve
from pdf_reader.text.segment import Segment


def sentences(*texts: str, pages: list[int] | None = None) -> list[Segment]:
    return [Segment(text, pages[i] if pages else 1, i) for i, text in enumerate(texts)]


DOC = sentences(
    "The first sentence of the document.",
    "A second sentence follows here.",
    "Third sentence on page two.",
    "Fourth and final sentence.",
    pages=[1, 1, 2, 2],
)


# ------------------------------------------------------------------- anchors


def test_make_anchor() -> None:
    assert make_anchor(DOC, 2) == Anchor(2, 2, "Third sentence on page two.")
    long = sentences("x" * 200)
    assert len(make_anchor(long, 0).text) == 80


def test_resolve_exact() -> None:
    assert resolve(make_anchor(DOC, 3), DOC) == 3


def test_resolve_after_sentences_shift() -> None:
    anchor = make_anchor(DOC, 2)
    shifted = sentences("New intro.", *(s.text for s in DOC))
    assert resolve(anchor, shifted) == 3


def test_resolve_picks_nearest_duplicate() -> None:
    doc = sentences("Repeat this line.", "Other.", "Repeat this line.", "Other.", "End.")
    assert resolve(Anchor(3, 1, "Repeat this line."), doc) == 2
    assert resolve(Anchor(0, 1, "Repeat this line."), doc) == 0


def test_resolve_sentence_now_split_in_two() -> None:
    anchor = Anchor(1, 1, "A long sentence, which has since been split into two parts.")
    doc = sentences("Intro.", "A long sentence,", "which has since been split into two parts.")
    assert resolve(anchor, doc) == 1


def test_resolve_falls_back_to_page_then_clamp() -> None:
    assert resolve(Anchor(9, 2, "Text that no longer exists."), DOC) == 2
    assert resolve(Anchor(9, 7, "Text that no longer exists."), DOC) == 3


def test_resolve_empty_document() -> None:
    with pytest.raises(ValueError, match="empty"):
        resolve(Anchor(0, 1, "x"), [])


def test_file_id_depends_only_on_content(tmp_path: Path) -> None:
    a = tmp_path / "a.pdf"
    b = tmp_path / "renamed copy.pdf"
    a.write_bytes(b"%PDF same content")
    b.write_bytes(b"%PDF same content")
    assert file_id(a) == file_id(b)
    b.write_bytes(b"%PDF different")
    assert file_id(a) != file_id(b)
    assert len(file_id(a)) == 64


# -------------------------------------------------------------------- store


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    return tmp_path / "library.json"


def test_open_creates_and_updates_record(store_path: Path) -> None:
    store = LibraryStore(store_path)
    record = store.open_document("id1", "Title", Path("C:/a.pdf"))
    assert record.title == "Title"
    assert record.path == str(Path("C:/a.pdf"))
    assert record.position is None
    store.open_document("id1", "New Title", Path("C:/moved/a.pdf"))
    record = store.get("id1")
    assert record is not None
    assert record.title == "New Title"
    assert record.path == str(Path("C:/moved/a.pdf"))


def test_round_trip_through_disk(store_path: Path) -> None:
    store = LibraryStore(store_path)
    store.open_document("id1", "Doc", Path("C:/a.pdf"))
    store.set_position("id1", Anchor(5, 2, "Some text"))
    mark = store.add_bookmark("id1", Anchor(3, 1, "Marked"), "  My   mark ")
    store.flush()

    reloaded = LibraryStore(store_path).get("id1")
    assert reloaded is not None
    assert reloaded.position == Anchor(5, 2, "Some text")
    assert reloaded.bookmarks == [mark]
    assert mark.label == "My mark"
    assert not store_path.with_suffix(".json.tmp").exists()


def test_returned_records_are_copies(store_path: Path) -> None:
    store = LibraryStore(store_path)
    record = store.open_document("id1", "Doc", None)
    record.bookmarks.append(object())  # type: ignore[arg-type]
    record.title = "changed"
    fresh = store.get("id1")
    assert fresh is not None
    assert fresh.bookmarks == []
    assert fresh.title == "Doc"


def test_bookmark_lifecycle(store_path: Path) -> None:
    store = LibraryStore(store_path)
    store.open_document("id1", "Doc", None)
    first = store.add_bookmark("id1", Anchor(1, 1, "One"), "One")
    second = store.add_bookmark("id1", Anchor(4, 2, "Four"), "")
    assert second.label == "Bookmark"
    assert store.add_bookmark("id1", Anchor(1, 1, "One"), "Again") == first  # Same sentence.

    store.rename_bookmark("id1", first.id, "Renamed")
    store.remove_bookmark("id1", second.id)
    store.remove_bookmark("id1", "unknown")
    record = store.get("id1")
    assert record is not None
    assert [(b.id, b.label) for b in record.bookmarks] == [(first.id, "Renamed")]


def test_bookmark_on_unknown_document(store_path: Path) -> None:
    with pytest.raises(KeyError):
        LibraryStore(store_path).add_bookmark("nope", Anchor(0, 1, "x"), "x")


def test_set_bookmark_anchors(store_path: Path) -> None:
    store = LibraryStore(store_path)
    store.open_document("id1", "Doc", None)
    mark = store.add_bookmark("id1", Anchor(1, 1, "One"), "One")
    store.set_bookmark_anchors("id1", {mark.id: Anchor(2, 1, "One")})
    record = store.get("id1")
    assert record is not None
    assert record.bookmarks[0].anchor == Anchor(2, 1, "One")


def test_recent_orders_by_last_opened_and_skips_pathless(
    store_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    times = iter(["2026-01-01T00:00:00", "2026-01-02T00:00:00", "2026-01-03T00:00:00"])
    monkeypatch.setattr("pdf_reader.library.store._now", lambda: next(times))
    store = LibraryStore(store_path)
    store.open_document("old", "Old", Path("C:/old.pdf"))
    store.open_document("text", "Text", None)
    store.open_document("new", "New", Path("C:/new.pdf"))
    assert [r.doc_id for r in store.recent()] == ["new", "old"]
    assert [r.doc_id for r in store.recent(limit=1)] == ["new"]


def test_prunes_least_recently_opened(store_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    counter = iter(range(100))
    monkeypatch.setattr(
        "pdf_reader.library.store._now", lambda: f"2026-01-01T00:00:{next(counter):02d}"
    )
    store = LibraryStore(store_path, max_documents=3)
    for name in ("a", "b", "c", "d"):
        store.open_document(name, name, None)
    assert store.get("a") is None
    assert all(store.get(n) is not None for n in ("b", "c", "d"))


def test_forget(store_path: Path) -> None:
    store = LibraryStore(store_path)
    store.open_document("id1", "Doc", None)
    store.forget("id1")
    assert store.get("id1") is None


@pytest.mark.parametrize("content", ["{broken", "[]", '{"documents": 5}', ""])
def test_damaged_file_starts_empty(store_path: Path, content: str) -> None:
    store_path.write_text(content, encoding="utf-8")
    assert LibraryStore(store_path).recent() == []


def test_invalid_entries_are_skipped(store_path: Path) -> None:
    store_path.write_text(
        json.dumps(
            {
                "version": 1,
                "documents": {
                    "good": {
                        "title": "Good",
                        "path": "C:/good.pdf",
                        "last_opened": "2026-01-01T00:00:00",
                        "position": {"index": -1, "page": 1, "text": "bad index"},
                        "bookmarks": [
                            {"id": "b1", "label": "ok", "index": 2, "page": 1, "text": "t"},
                            {"id": 5, "index": 2, "page": 1, "text": "bad id"},
                            {"id": "b3", "index": "x", "page": 1, "text": "bad"},
                        ],
                    },
                    "bad": {"title": 42},
                    "worse": "nonsense",
                },
            }
        ),
        encoding="utf-8",
    )
    store = LibraryStore(store_path)
    record = store.get("good")
    assert record is not None
    assert record.position is None
    assert [b.id for b in record.bookmarks] == ["b1"]
    assert store.get("bad") is None
    assert store.get("worse") is None


def test_flush_only_when_dirty(store_path: Path) -> None:
    store = LibraryStore(store_path)
    store.flush()
    assert not store_path.exists()
    store.open_document("id1", "Doc", None)
    store.flush()
    assert store_path.exists()


def test_save_if_due_respects_interval(store_path: Path) -> None:
    store = LibraryStore(store_path)
    store.open_document("id1", "Doc", None)
    store.save_if_due(interval=3600)
    assert not store_path.exists()
    store.save_if_due(interval=0)
    assert store_path.exists()


def test_flush_failure_is_logged_and_retried(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    store = LibraryStore(blocker / "library.json")  # Parent is a file: cannot write.
    store.open_document("id1", "Doc", None)
    store.flush()  # Must not raise.
    store.save_if_due(interval=0)  # Still dirty, tries again without raising.


def test_counts_and_progress_round_trip(store_path: Path) -> None:
    store = LibraryStore(store_path)
    store.open_document(
        "id1", "Doc", Path("C:/a.pdf"), page_count=12, sentence_count=101, scanned=True
    )
    store.set_position("id1", Anchor(25, 3, "Text"))
    store.flush()
    record = LibraryStore(store_path).get("id1")
    assert record is not None
    assert (record.page_count, record.sentence_count, record.scanned) == (12, 101, True)
    assert record.progress == pytest.approx(0.25)


def test_progress_without_position_or_counts(store_path: Path) -> None:
    store = LibraryStore(store_path)
    record = store.open_document("id1", "Doc", None)
    assert record.progress == 0.0


def test_thumbnail_is_made_once(tmp_path: Path) -> None:
    import pymupdf

    from pdf_reader.library.thumbnails import THUMBNAIL_WIDTH, save_thumbnail

    pdf = tmp_path / "doc.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 100), "Cover page")
    doc.save(pdf)
    doc.close()
    thumb = tmp_path / "thumbs" / "doc.png"
    save_thumbnail(pdf, thumb)
    assert thumb.exists()
    assert pymupdf.Pixmap(str(thumb)).width == THUMBNAIL_WIDTH
    stamp = thumb.stat().st_mtime_ns
    save_thumbnail(pdf, thumb)
    assert thumb.stat().st_mtime_ns == stamp  # Not redone.
    save_thumbnail(tmp_path / "missing.pdf", tmp_path / "thumbs" / "x.png")  # No error.
