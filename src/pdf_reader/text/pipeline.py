"""The ordered text-processing pipeline that turns a document into spoken chunks."""

import logging
import re
from collections.abc import Iterable, Sequence

from pdf_reader.pdf.models import Document
from pdf_reader.text.layout import (
    join_continued_blocks,
    order_columns,
    remove_asides,
    remove_footnote_markers,
    remove_footnotes,
    remove_page_numbers,
    remove_running_headers_footers,
)
from pdf_reader.text.segment import Segment
from pdf_reader.text.steps import (
    TextStep,
    drop_unspeakable,
    fix_hyphenated_line_breaks,
    normalize_unicode,
    normalize_whitespace,
    remove_parentheticals,
    split_long_sentences,
    split_sentences,
    strip_superscript_markers,
)

log = logging.getLogger(__name__)


def default_steps(*, read_parentheses: bool = True, skip_asides: bool = True) -> list[TextStep]:
    """Return the standard steps in order.

    Args:
        read_parentheses: Keep text in (parentheses); when False it is not read.
        skip_asides: Skip sidebars, captions, and figure labels (see
            :func:`~pdf_reader.text.layout.remove_asides`).

    Order:

    1. Layout cleanup (see :mod:`pdf_reader.text.layout`). These need each segment to
       still be exactly one PDF block, so they come first; ``order_columns`` must
       precede ``join_continued_blocks`` so text is joined in reading order.
    2. Character-level cleanup. Superscript markers go before Unicode normalization,
       and hyphenated line breaks are fixed while line breaks still exist.
    3. Splitting into sentences and speakable chunks.
    """
    return [
        remove_page_numbers,
        remove_running_headers_footers,
        remove_footnotes,
        *([remove_asides] if skip_asides else []),
        remove_footnote_markers,
        order_columns,
        join_continued_blocks,
        strip_superscript_markers,
        normalize_unicode,
        fix_hyphenated_line_breaks,
        normalize_whitespace,
        *([] if read_parentheses else [remove_parentheticals]),
        drop_unspeakable,
        split_sentences,
        split_long_sentences(),
        drop_unspeakable,
    ]


def build_pipeline(*, read_parentheses: bool = True, skip_asides: bool = True) -> "TextPipeline":
    """Create a pipeline with the standard steps and the given reading options."""
    return TextPipeline(default_steps(read_parentheses=read_parentheses, skip_asides=skip_asides))


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
        """Turn a PDF document into speakable segments in reading order."""
        return self.run(document_segments(document))

    def process_text(self, text: str) -> list[Segment]:
        """Turn plain text (for example, pasted from the clipboard) into segments."""
        return self.run(text_segments(text))


def document_segments(document: Document) -> list[Segment]:
    """Create one raw segment per text block, numbering blocks across the document."""
    segments: list[Segment] = []
    for page in document.pages:
        for block in page.blocks:
            segments.append(
                Segment(
                    text=block.text,
                    page=page.number,
                    block=len(segments),
                    bbox=block.bbox,
                    source=block,
                    page_size=(page.width, page.height),
                )
            )
    return segments


_BLANK_LINES = re.compile(r"\n\s*\n")
_ENDS_PARAGRAPH = re.compile(r"[.!?:\u2026][\"'\u201d\u2019)\]]*$")
_HEADING_MAX_CHARS = 60


def text_segments(text: str) -> list[Segment]:
    """Split plain text into one segment per paragraph, all on page 1.

    Blank lines always separate paragraphs. A single line break also does when the
    line before it ends a sentence or looks like a heading (short, no final
    punctuation); otherwise the break is treated as hard-wrapping inside a paragraph.
    """
    paragraphs: list[str] = []
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    for chunk in _BLANK_LINES.split(normalized):
        current: list[str] = []
        for line in chunk.split("\n"):
            if not line.strip():
                continue
            current.append(line)
            stripped = line.strip()
            if _ENDS_PARAGRAPH.search(stripped) or len(stripped) <= _HEADING_MAX_CHARS:
                paragraphs.append("\n".join(current))
                current = []
        if current:
            paragraphs.append("\n".join(current))
    return [Segment(text=p, page=1, block=i) for i, p in enumerate(paragraphs)]
