"""Generate small EPUB, Word, and web page files for trying out and testing the app.

Usage::

    uv run python scripts/make_sample_documents.py sample.epub
    uv run python scripts/make_sample_documents.py sample.docx
    uv run python scripts/make_sample_documents.py sample.html
"""

import argparse
import html
import zipfile
from pathlib import Path

CHAPTERS = (
    (
        "The Lighthouse",
        "The keeper climbed the stairs at dusk. Below him the sea was calm and grey. "
        "He lit the lamp, as he had every evening for thirty years.",
    ),
    (
        "The Storm",
        "By midnight the wind had risen. Waves broke against the rocks, and the light "
        "swept over the water again and again. Far out, a small boat turned for home.",
    ),
)


def build_epub(path: Path, chapters: tuple[tuple[str, str], ...] = CHAPTERS) -> Path:
    """Write a minimal valid EPUB 3 book with one XHTML file per chapter."""
    items, spine, nav = [], [], []
    files: dict[str, str] = {}
    for number, (title, text) in enumerate(chapters, start=1):
        name = f"chapter{number}.xhtml"
        paragraphs = "".join(f"<p>{html.escape(p.strip())}.</p>" for p in text.split(". ") if p)
        files[name] = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<html xmlns="http://www.w3.org/1999/xhtml"><head>'
            f"<title>{html.escape(title)}</title></head><body>"
            f"<h1>{html.escape(title)}</h1>{paragraphs.replace('..', '.')}</body></html>"
        )
        items.append(f'<item id="c{number}" href="{name}" media-type="application/xhtml+xml"/>')
        spine.append(f'<itemref idref="c{number}"/>')
        nav.append(f'<li><a href="{name}">{html.escape(title)}</a></li>')
    files["nav.xhtml"] = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">'
        '<head><title>Contents</title></head><body><nav epub:type="toc"><ol>'
        f"{''.join(nav)}</ol></nav></body></html>"
    )
    opf = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        '<dc:identifier id="id">sample-book</dc:identifier>'
        "<dc:title>A Sample Book</dc:title><dc:language>en</dc:language>"
        '<meta property="dcterms:modified">2026-01-01T00:00:00Z</meta></metadata>'
        '<manifest><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" '
        f'properties="nav"/>{"".join(items)}</manifest><spine>{"".join(spine)}</spine></package>'
    )
    container = (
        '<?xml version="1.0"?><container version="1.0" '
        'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
        '<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
        "</rootfiles></container>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", container, compress_type=zipfile.ZIP_DEFLATED)
        archive.writestr("OEBPS/content.opf", opf, compress_type=zipfile.ZIP_DEFLATED)
        for name, content in files.items():
            archive.writestr(f"OEBPS/{name}", content, compress_type=zipfile.ZIP_DEFLATED)
    return path


_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def build_docx(path: Path, chapters: tuple[tuple[str, str], ...] = CHAPTERS) -> Path:
    """Write a minimal Word document: a heading and a paragraph per chapter."""
    body = []
    for title, text in chapters:
        body.append(
            '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
            f"<w:r><w:t>{html.escape(title)}</w:t></w:r></w:p>"
        )
        # Split one paragraph into two runs, as Word often does.
        middle = len(text) // 2
        cut = text.index(" ", middle)
        body.append(
            f'<w:p><w:r><w:t xml:space="preserve">{html.escape(text[: cut + 1])}</w:t></w:r>'
            f"<w:r><w:t>{html.escape(text[cut + 1 :])}</w:t></w:r></w:p>"
        )
    document = (
        f'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="{_W}">'
        f"<w:body>{''.join(body)}</w:body></w:document>"
    )
    core = (
        '<?xml version="1.0" encoding="UTF-8"?><cp:coreProperties '
        'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>A Sample Story</dc:title>'
        "</cp:coreProperties>"
    )
    types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/'
        'vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        'relationships/officeDocument" Target="word/document.xml"/></Relationships>'
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("word/document.xml", document)
        archive.writestr("docProps/core.xml", core)
    return path


def build_html(chapters: tuple[tuple[str, str], ...] = CHAPTERS) -> str:
    """Return a web page with an article surrounded by typical page clutter."""
    article = "".join(
        f"<h2>{html.escape(title)}</h2><p>{html.escape(text)}</p>" for title, text in chapters
    )
    return (
        "<!DOCTYPE html><html><head><title>A Sample Story | Example News</title>"
        '<meta property="og:title" content="A Sample Story">'
        "<script>var tracking = 'this is not text to read, it is a long script';</script>"
        "<style>body { font-family: serif; }</style></head><body>"
        '<header class="site-header"><a href="/">Example News</a>'
        '<nav><ul><li><a href="/world">World</a></li><li><a href="/sport">Sport</a></li>'
        "</ul></nav></header>"
        '<div class="cookie-banner">We use cookies to improve your experience.</div>'
        '<main><article><h1>A Sample Story</h1><p class="byline">By A. Writer</p>'
        f"{article}"
        '<div class="share-buttons"><a href="#">Share on social media</a></div></article>'
        '<aside class="sidebar"><h3>Most read</h3><ul><li><a href="/1">Another story about '
        "something</a></li></ul></aside></main>"
        '<footer class="site-footer"><p>Copyright Example News. All rights reserved.</p>'
        "</footer></body></html>"
    )


def main() -> None:
    """Write the sample whose type matches the output file's extension."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help=".epub, .docx, or .html file to write")
    args = parser.parse_args()
    suffix = args.output.suffix.lower()
    if suffix == ".epub":
        build_epub(args.output)
    elif suffix == ".docx":
        build_docx(args.output)
    elif suffix in (".html", ".htm"):
        args.output.write_text(build_html(), encoding="utf-8")
    else:
        parser.error("the output must end in .epub, .docx, or .html")


if __name__ == "__main__":
    main()
