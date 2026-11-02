"""Data saved per document: reading position and bookmarks."""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Anchor:
    """A location in a document, robust to changes in how text is split.

    The sentence index alone could point at the wrong sentence after an app update
    changes text processing, so the page and the start of the sentence's text are
    kept too, to find it again (see :func:`pdf_reader.library.anchors.resolve`).

    Attributes:
        index: Sentence index when the anchor was saved.
        page: 1-based page of that sentence.
        text: The beginning of the sentence's text.
    """

    index: int
    page: int
    text: str


@dataclass(frozen=True, slots=True)
class Bookmark:
    """A named location in a document.

    Attributes:
        id: Unique identifier.
        anchor: Where the bookmark points.
        label: User-visible name; defaults to the start of the sentence.
        created: ISO 8601 creation time (UTC).
    """

    id: str
    anchor: Anchor
    label: str
    created: str


@dataclass(slots=True)
class DocumentRecord:
    """Everything remembered about one document.

    Attributes:
        doc_id: Content hash identifying the document regardless of its path.
        title: Display title.
        path: Where the document was last opened from.
        last_opened: ISO 8601 time it was last opened (UTC).
        position: Where reading stopped, if anywhere.
        bookmarks: Bookmarks in the order they were added.
    """

    doc_id: str
    title: str
    path: str | None
    last_opened: str
    position: Anchor | None = None
    bookmarks: list[Bookmark] = field(default_factory=list)
