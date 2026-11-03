"""Word documents, web pages, text files, and links (served from this computer)."""

import threading
import zipfile
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

import pymupdf
import pytest

from pdf_reader.sources import (
    SourceError,
    fetch,
    is_web_address,
    normalize_address,
    read_text_document,
)
from pdf_reader.sources.docx import read_docx
from pdf_reader.sources.files import strip_markdown
from pdf_reader.sources.html import extract_article
from scripts.make_sample_documents import CHAPTERS, build_docx, build_html

# ------------------------------------------------------------------ Word


def test_docx_paragraphs_and_title(tmp_path: Path) -> None:
    source = read_docx(build_docx(tmp_path / "story.docx"))
    assert source.title == "A Sample Story"
    assert source.paragraphs == (
        CHAPTERS[0][0],
        CHAPTERS[0][1],
        CHAPTERS[1][0],
        CHAPTERS[1][1],
    )


def test_docx_skips_deleted_text_and_reads_tables(tmp_path: Path) -> None:
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = (
        "<w:p><w:r><w:t>Kept</w:t></w:r><w:del><w:r><w:delText>gone</w:delText></w:r></w:del>"
        "<w:r><w:tab/><w:t>text.</w:t></w:r></w:p>"
        "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>In a table.</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
    )
    path = tmp_path / "plain.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "word/document.xml", f'<w:document xmlns:w="{w}"><w:body>{body}</w:body></w:document>'
        )
    source = read_docx(path)
    assert source.title == "plain"
    assert source.paragraphs == ("Kept text.", "In a table.")


def test_not_a_docx(tmp_path: Path) -> None:
    path = tmp_path / "old.docx"
    path.write_bytes(b"\xd0\xcf\x11\xe0 an old binary .doc file")
    with pytest.raises(SourceError, match="Word"):
        read_docx(path)


# ------------------------------------------------------------------ web pages


def test_article_is_found_among_page_clutter() -> None:
    source = extract_article(build_html())
    assert source.title == "A Sample Story"
    text = source.text
    for title, body in CHAPTERS:
        assert title in text and body in text
    for clutter in ("cookies", "World", "Sport", "Share on", "Most read", "Copyright", "script"):
        assert clutter not in text
    assert source.paragraphs[0] == "A Sample Story"  # The heading, read once.


def test_article_without_article_element_uses_the_densest_text() -> None:
    paragraphs = "".join(
        f"<p>Paragraph {i} of the story, with enough words, commas, and length to count.</p>"
        for i in range(8)
    )
    html = (
        "<html><head><title>Story - Site</title></head><body>"
        '<div id="menu"><a href="/">Home</a> <a href="/a">About</a></div>'
        f'<div class="content"><h1>Story</h1>{paragraphs}</div>'
        '<div class="links"><p><a href="/x">A link to another story elsewhere</a></p></div>'
        "</body></html>"
    )
    source = extract_article(html)
    assert source.title == "Story"  # The heading, without the site's name.
    assert len(source.paragraphs) == 9
    assert "Home" not in source.text
    assert "another story" not in source.text


def test_page_title_ignores_icon_titles() -> None:
    html = (
        "<html><head><title>Real title</title></head><body><svg><title>icon</title></svg>"
        "<p>Some readable text that is long enough to be a paragraph of the page.</p></body></html>"
    )
    assert extract_article(html).title == "Real title"


def test_page_without_text() -> None:
    with pytest.raises(SourceError, match="No readable text"):
        extract_article("<html><body><script>app()</script></body></html>")


# ------------------------------------------------------------------ text files


def test_markdown_formatting_is_removed(tmp_path: Path) -> None:
    path = tmp_path / "notes.md"
    path.write_text(
        "# Title\n\nSome **bold** and *italic* text with a [link](http://x).\n\n"
        "- first item\n- second item\n\n```\ncode()\n```\n",
        encoding="utf-8",
    )
    source = read_text_document(path)
    assert source.title == "notes"
    assert source.paragraphs[:2] == ("Title", "Some bold and italic text with a link.")
    assert "first item second item" in source.text
    assert strip_markdown("![picture](a.png)") == ""


def test_text_file_encodings(tmp_path: Path) -> None:
    utf8 = tmp_path / "a.txt"
    utf8.write_bytes("\ufeffCaf\u00e9 au lait.".encode())
    assert read_text_document(utf8).text == "Caf\u00e9 au lait."
    legacy = tmp_path / "b.txt"
    legacy.write_bytes("Caf\u00e9 cr\u00e8me.".encode("cp1252"))
    assert read_text_document(legacy).text == "Caf\u00e9 cr\u00e8me."


def test_saved_web_page_and_empty_file(tmp_path: Path) -> None:
    page = tmp_path / "saved.html"
    page.write_text(build_html(), encoding="utf-8")
    assert read_text_document(page).title == "A Sample Story"
    empty = tmp_path / "empty.txt"
    empty.write_text("  \n\n ", encoding="utf-8")
    with pytest.raises(SourceError):
        read_text_document(empty)


# ------------------------------------------------------------------ links


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("https://example.com/page", True),
        ("http://example.com", True),
        ("www.example.com/a?b=c", True),
        ("  https://example.com  ", True),
        ("example", False),
        ("Read https://example.com later", False),
        ("C:\\files\\doc.pdf", False),
        ("ftp://example.com", False),
        ("", False),
    ],
)
def test_is_web_address(text: str, expected: bool) -> None:
    assert is_web_address(text) is expected


def test_normalize_address() -> None:
    assert normalize_address("www.example.com") == "https://www.example.com"
    assert normalize_address("http://a.org") == "http://a.org"


class _Site(BaseHTTPRequestHandler):
    pages: ClassVar[dict[str, tuple[int, str, bytes]]] = {}

    def do_GET(self) -> None:
        status, content_type, body = self.pages.get(self.path, (404, "text/plain", b"missing"))
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        pass


@pytest.fixture
def site(tmp_path: Path) -> Iterator[str]:
    pdf = pymupdf.open()
    pdf.new_page().insert_text((72, 150), "A linked document.")
    pdf_bytes = pdf.tobytes()
    pdf.close()
    _Site.pages = {
        "/story": (200, "text/html; charset=utf-8", build_html().encode()),
        "/latin": (
            200,
            "text/html",
            b'<meta charset="windows-1252"><p>Caf\xe9 and cr\xe8me make a good paragraph here.</p>',
        ),
        "/paper.pdf": (200, "application/pdf", pdf_bytes),
        "/download": (200, "application/octet-stream", b"binary"),
        "/private": (403, "text/html", b"no"),
    }
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Site)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_fetch_web_page(site: str, tmp_path: Path) -> None:
    result = fetch(f"{site}/story", tmp_path)
    assert result.file is None and result.article is not None
    assert result.article.title == "A Sample Story"
    assert result.url == f"{site}/story"


def test_fetch_uses_the_declared_charset(site: str, tmp_path: Path) -> None:
    result = fetch(f"{site}/latin", tmp_path)
    assert result.article is not None
    assert "Caf\u00e9 and cr\u00e8me" in result.article.text


def test_fetch_linked_pdf_is_saved(site: str, tmp_path: Path) -> None:
    result = fetch(f"{site}/paper.pdf", tmp_path)
    assert result.file is not None and result.file.name == "paper.pdf"
    assert result.file.read_bytes().startswith(b"%PDF")
    again = fetch(f"{site}/paper.pdf", tmp_path)
    assert again.file == result.file


@pytest.mark.parametrize(
    ("path", "message"),
    [
        ("/missing", "wasn't found"),
        ("/private", "outside a browser"),
        ("/download", "doesn't lead to"),
    ],
)
def test_fetch_errors_are_friendly(site: str, tmp_path: Path, path: str, message: str) -> None:
    with pytest.raises(SourceError, match=message):
        fetch(f"{site}{path}", tmp_path)


def test_fetch_unreachable(tmp_path: Path) -> None:
    with pytest.raises(SourceError, match="Couldn't reach"):
        fetch("http://127.0.0.1:9/", tmp_path, timeout=2)
