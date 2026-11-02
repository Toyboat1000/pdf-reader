"""The ordered text-processing pipeline that turns a document into spoken chunks."""

import logging
from collections.abc import Iterable, Sequence

from pdf_reader.pdf.models import Document
from pdf_reader.text.segment import Segment
from pdf_reader.text.steps import (
    TextStep,
    drop_unspeakable,
    fix_hyphenated_line_breaks,
    normalize_unicode,
    normalize_whitespace,
    split_long_sentences,
    split_sentences,
)

log = logging.getLogger(__name__)


def default_steps() -> list[TextStep]:
    """Return the standard steps in order.

    Order matters: hyphenated line breaks must be fixed while line breaks still
    exist, i.e. before whitespace is normalized. Future cleanup steps (headers,
    footers, page numbers) belong before :func:`split_sentences`.
    """
    return [
        normalize_unicode,
        fix_hyphenated_line_breaks,
        normalize_whitespace,
        drop_unspeakable,
        split_sentences,
        split_long_sentences(),
        drop_unspeakable,
    ]


class TextPipeline:
    """Runs a sequence of :data:`TextStep` functions over segments, in order."""

    def __init__(self, steps: Iterable[TextStep] | None = None) -> None:
        self._steps: list[TextStep] = list(default_steps() if steps is None else steps)

    @property
    def steps(self) -> Sequence[TextStep]:
        """Return the steps in execution order."""
        return tuple(self._steps)

    def run(self, segments: Iterable[Segment]) -> list[Segment]:
        """Pass ``segments`` through every step and return the result."""
        result = list(segments)
        for step in self._steps:
            result = step(result)
            log.debug("Step %s -> %d segments", getattr(step, "__name__", step), len(result))
        return result

    def process_document(self, document: Document) -> list[Segment]:
        """Turn a document into speakable segments in reading order."""
        return self.run(document_segments(document))


def document_segments(document: Document) -> list[Segment]:
    """Create one raw segment per text block, numbering blocks across the document."""
    segments: list[Segment] = []
    for page in document.pages:
        for block in page.blocks:
            segments.append(
                Segment(text=block.text, page=page.number, block=len(segments), bbox=block.bbox)
            )
    return segments
