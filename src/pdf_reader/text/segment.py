"""The unit of text that flows through the processing pipeline."""

from dataclasses import dataclass

from pdf_reader.pdf.models import BBox, TextBlock


@dataclass(frozen=True, slots=True)
class Segment:
    """A piece of document text with its origin.

    The pipeline starts with one segment per text block (roughly one per paragraph)
    and ends with one segment per spoken chunk (a sentence, or part of a long one).
    Layout information is optional: segments from pasted text have none, and
    layout-based steps leave such segments alone.

    Attributes:
        text: The text itself.
        page: 1-based page number the text came from.
        block: Document-wide index of the source text block; segments that share it
            belong to the same paragraph.
        bbox: Bounding box of the source text block, if known.
        ends_sentence: False when this is a non-final piece of a long sentence that
            was split, so playback can use a shorter pause after it.
        source: The PDF text block this segment came from, with line and span detail,
            if known.
        page_size: ``(width, height)`` of the source page in points, if known.
    """

    text: str
    page: int
    block: int
    bbox: BBox | None = None
    ends_sentence: bool = True
    source: TextBlock | None = None
    page_size: tuple[float, float] | None = None
