"""Read text documents from disk: Word, saved web pages, Markdown, and plain text."""

import logging
import re
from pathlib import Path

from pdf_reader.sources.docx import read_docx
from pdf_reader.sources.html import extract_article
from pdf_reader.sources.models import SourceError, TextSource

log = logging.getLogger(__name__)

TEXT_SUFFIXES = frozenset({".docx", ".html", ".htm", ".xhtml", ".txt", ".md", ".markdown"})
"""File types read as flowing text (rather than as pages)."""

MAX_TEXT_BYTES = 50 * 1024 * 1024

_MARKDOWN_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^```.*$|^~~~.*$", re.MULTILINE), ""),  # Code fences.
    (re.compile(r"!\[[^\]]*\]\([^)]*\)"), ""),  # Images.
    (re.compile(r"\[([^\]]+)\]\([^)]*\)"), r"\1"),  # Links keep their text.
    (re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+", re.MULTILINE), ""),  # Heading marks.
    (re.compile(r"^[ \t]{0,3}>[ \t]?", re.MULTILINE), ""),  # Quote marks.
    (re.compile(r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]+", re.MULTILINE), ""),  # List markers.
    (re.compile(r"^[ \t]*(?:-{3,}|\*{3,}|_{3,})[ \t]*$", re.MULTILINE), ""),  # Rules.
    (re.compile(r"(\*\*|__)(.+?)\1"), r"\2"),  # Bold.
    (re.compile(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])"), r"\1"),  # Italics.
    (re.compile(r"`([^`]+)`"), r"\1"),  # Inline code.
]


def read_text_document(path: Path) -> TextSource:
    """Read a text document of one of the :data:`TEXT_SUFFIXES` types.

    Raises:
        SourceError: The file is missing, too large, or can't be read.
    """
    suffix = path.suffix.lower()
    if suffix not in TEXT_SUFFIXES:
        raise SourceError("This type of file can't be opened.")
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise SourceError("The file could not be found or opened.") from exc
    if size > MAX_TEXT_BYTES:
        raise SourceError("This file is too large to read.")
    if suffix == ".docx":
        source = read_docx(path)
    else:
        try:
            data = path.read_bytes()
        except OSError as exc:
            log.warning("Cannot read %s", path, exc_info=True)
            raise SourceError("The file could not be found or opened.") from exc
        text = _decode(data)
        if suffix in (".html", ".htm", ".xhtml"):
            source = extract_article(text, path.stem)
        else:
            if suffix in (".md", ".markdown"):
                text = strip_markdown(text)
            paragraphs = tuple(
                " ".join(p.split()) if suffix != ".txt" else p.strip()
                for p in re.split(r"\n\s*\n", text)
                if p.strip()
            )
            source = TextSource(path.stem, paragraphs)
    if not source.paragraphs:
        raise SourceError("No readable text was found in this file.")
    return source


def strip_markdown(text: str) -> str:
    """Remove Markdown formatting marks, keeping the words."""
    for pattern, replacement in _MARKDOWN_RULES:
        text = pattern.sub(replacement, text)
    return text


def _decode(data: bytes) -> str:
    """Decode text that is most likely UTF-8 (with or without a BOM), else Windows-1252."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")
