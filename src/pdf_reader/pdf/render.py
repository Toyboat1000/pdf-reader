"""Render PDF pages to RGB images for display."""

from dataclasses import dataclass
from pathlib import Path

import pymupdf

from pdf_reader.pdf.formats import filetype_of, open_paged


@dataclass(frozen=True, slots=True)
class RenderedPage:
    """An RGB image of a page.

    Attributes:
        width: Width in pixels.
        height: Height in pixels.
        stride: Bytes per row.
        samples: Pixel data, 3 bytes per pixel.
    """

    width: int
    height: int
    stride: int
    samples: bytes


class PageRenderer:
    """Keeps a PDF open and renders its pages on request. Not thread-safe."""

    def __init__(self, path: Path) -> None:
        # Read into memory so the file isn't locked: it can be moved or renamed while open.
        self._pdf = open_paged(data=path.read_bytes(), filetype=filetype_of(path))

    def render(self, page_number: int, zoom: float) -> RenderedPage:
        """Render 1-based ``page_number`` at ``zoom`` pixels per PDF point."""
        pix = self._pdf[page_number - 1].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        return RenderedPage(pix.width, pix.height, pix.stride, bytes(pix.samples))

    def close(self) -> None:
        """Release the file."""
        self._pdf.close()
