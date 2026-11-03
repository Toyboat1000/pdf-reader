"""Small cover images of documents' first pages, for the home page."""

import logging
from pathlib import Path

import pymupdf

from pdf_reader.pdf.formats import filetype_of, open_paged

log = logging.getLogger(__name__)

THUMBNAIL_WIDTH = 320
"""Pixel width of saved thumbnails (sharp at twice the card size on high-DPI screens)."""


def save_thumbnail(pdf_path: Path, destination: Path) -> None:
    """Render the first page of ``pdf_path`` to a PNG at ``destination``, once.

    Does nothing if the thumbnail already exists. Errors are logged, not raised: a
    missing cover must never stop a document from opening.
    """
    if destination.exists():
        return
    try:
        with open_paged(pdf_path, filetype=filetype_of(pdf_path)) as pdf:
            page = pdf[0]
            zoom = THUMBNAIL_WIDTH / max(page.rect.width, 1)
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
            destination.parent.mkdir(parents=True, exist_ok=True)
            tmp = destination.with_suffix(".tmp")
            tmp.write_bytes(pix.tobytes("png"))
            tmp.replace(destination)
    except Exception:
        log.warning("Could not make a thumbnail for %s", pdf_path, exc_info=True)
