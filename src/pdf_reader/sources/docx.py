"""Read the text of Word documents (.docx) without Word.

A .docx file is a zip archive; the text is in ``word/document.xml`` as paragraphs
(``w:p``) of runs of text (``w:t``). Tables and text boxes are read in document
order; deleted text (tracked changes) and field codes are left out.
"""

import logging
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from pdf_reader.sources.models import SourceError, TextSource

log = logging.getLogger(__name__)

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"
_DC_TITLE = "{http://purl.org/dc/elements/1.1/}title"
_MAX_XML_BYTES = 200 * 1024 * 1024


def read_docx(path: Path) -> TextSource:
    """Return the paragraphs of a Word document.

    Raises:
        SourceError: The file is not a readable Word document.
    """
    try:
        with zipfile.ZipFile(path) as archive:
            info = archive.getinfo("word/document.xml")
            if info.file_size > _MAX_XML_BYTES:
                raise SourceError("This Word document is too large to read.")
            body_xml = archive.read(info)
            has_core = _has(archive, "docProps/core.xml")
            core_xml = archive.read("docProps/core.xml") if has_core else b""
    except SourceError:
        raise
    except (zipfile.BadZipFile, KeyError, OSError) as exc:
        log.warning("Cannot read %s as .docx: %s", path, exc)
        raise SourceError(
            "This file isn't a Word document this app can read. If it's an older .doc "
            "file, save it as .docx (or PDF) in Word and open it again."
        ) from exc
    try:
        root = ElementTree.fromstring(body_xml)
    except ElementTree.ParseError as exc:
        log.warning("Malformed document.xml in %s: %s", path, exc)
        raise SourceError("This Word document appears to be damaged.") from exc

    paragraphs: list[str] = []
    body = root.find(f"{_W}body")
    if body is not None:
        _collect(body, paragraphs)
    return TextSource(_title(core_xml) or path.stem, tuple(paragraphs))


def _has(archive: zipfile.ZipFile, name: str) -> bool:
    try:
        archive.getinfo(name)
    except KeyError:
        return False
    return True


def _collect(element: ElementTree.Element, paragraphs: list[str]) -> None:
    """Add the text of every paragraph under ``element``, in document order."""
    for child in element:
        if child.tag == _FALLBACK:
            continue  # The same content again, for old versions of Word.
        if child.tag == f"{_W}p":
            text = " ".join(_paragraph_text(child).split())
            if text:
                paragraphs.append(text)
        else:
            _collect(child, paragraphs)


def _paragraph_text(paragraph: ElementTree.Element) -> str:
    parts: list[str] = []

    def walk(element: ElementTree.Element) -> None:
        for child in element:
            tag = child.tag
            if tag == _FALLBACK:
                continue
            if tag == f"{_W}t":
                parts.append(child.text or "")
            elif tag in (f"{_W}tab", f"{_W}br", f"{_W}cr"):
                parts.append(" ")
            elif tag == f"{_W}noBreakHyphen":
                parts.append("-")
            elif tag == f"{_W}p":
                # A text box inside the paragraph: keep it apart from the sentence.
                parts.append(" ")
                walk(child)
                parts.append(" ")
            else:
                walk(child)

    walk(paragraph)
    return "".join(parts)


def _title(core_xml: bytes) -> str:
    if not core_xml:
        return ""
    try:
        node = ElementTree.fromstring(core_xml).find(_DC_TITLE)
    except ElementTree.ParseError:
        return ""
    return " ".join((node.text or "").split()) if node is not None else ""
