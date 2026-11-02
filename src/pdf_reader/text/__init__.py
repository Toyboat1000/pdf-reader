"""Text-processing pipeline: small ordered steps from raw PDF text to spoken chunks."""

from pdf_reader.text.pipeline import TextPipeline, default_steps, document_segments
from pdf_reader.text.segment import Segment
from pdf_reader.text.steps import TextStep, text_step

__all__ = [
    "Segment",
    "TextPipeline",
    "TextStep",
    "default_steps",
    "document_segments",
    "text_step",
]
