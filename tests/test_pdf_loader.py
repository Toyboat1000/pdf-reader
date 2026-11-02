from pathlib import Path

import pymupdf
import pytest

from pdf_reader.pdf import (
    CorruptPdfError,
    EncryptedPdfError,
    NoTextError,
    PdfError,
    PdfNotFoundError,
    load_pdf,
)


def make_pdf(path: Path, pages: list[list[str]], **save_options: object) -> Path:
    """Write a PDF with one text paragraph per string, top to bottom."""
    doc = pymupdf.open()
    for paragraphs in pages:
        page = doc.new_page()
        y = 72
        for text in paragraphs:
            page.insert_text((72, y), text, fontsize=11)
            y += 40
    doc.save(path, **save_options)
    doc.close()
    return path


def test_extracts_pages_in_order_with_positions(tmp_path: Path) -> None:
    path = make_pdf(tmp_path / "doc.pdf", [["First page top.", "First page lower."], ["Page 2."]])
    document = load_pdf(path)

    assert document.page_count == 2
    assert document.title == "doc"
    first, second = document.pages
    assert first.number == 1
    assert [b.text for b in first.blocks] == ["First page top.", "First page lower."]
    assert first.blocks[0].bbox[1] < first.blocks[1].bbox[1]  # Top-to-bottom.
    assert first.blocks[0].lines[0].font_size == pytest.approx(11, abs=0.5)
    assert second.number == 2
    assert second.text == "Page 2."


def test_title_from_metadata(tmp_path: Path) -> None:
    path = tmp_path / "meta.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Body text.")
    doc.set_metadata({"title": "  Real Title  "})
    doc.save(path)
    doc.close()
    assert load_pdf(path).title == "Real Title"


def test_blank_pages_are_kept(tmp_path: Path) -> None:
    path = make_pdf(tmp_path / "doc.pdf", [["Text."], [], ["More."]])
    document = load_pdf(path)
    assert document.page_count == 3
    assert document.pages[1].blocks == ()


def test_encrypted_pdf(tmp_path: Path) -> None:
    path = make_pdf(
        tmp_path / "locked.pdf",
        [["Secret."]],
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        user_pw="user",
        owner_pw="owner",
    )
    with pytest.raises(EncryptedPdfError) as info:
        load_pdf(path)
    assert "password" in info.value.user_message


def test_pdf_without_text(tmp_path: Path) -> None:
    path = make_pdf(tmp_path / "scan.pdf", [[], []])
    with pytest.raises(NoTextError) as info:
        load_pdf(path)
    assert "scanned" in info.value.user_message


def test_whitespace_only_text_counts_as_no_text(tmp_path: Path) -> None:
    path = make_pdf(tmp_path / "blank.pdf", [["   "]])
    with pytest.raises(NoTextError):
        load_pdf(path)


@pytest.mark.parametrize("content", [b"", b"this is not a pdf at all", b"%PDF-1.7\n garbage"])
def test_corrupt_files(tmp_path: Path, content: bytes) -> None:
    path = tmp_path / "bad.pdf"
    path.write_bytes(content)
    with pytest.raises(CorruptPdfError) as info:
        load_pdf(path)
    assert "damaged" in info.value.user_message


def test_truncated_pdf(tmp_path: Path) -> None:
    good = make_pdf(tmp_path / "good.pdf", [["Hello there."] * 5] * 3)
    truncated = tmp_path / "truncated.pdf"
    truncated.write_bytes(good.read_bytes()[: good.stat().st_size // 3])
    # Either PyMuPDF repairs enough to read some text, or we get a friendly error.
    try:
        document = load_pdf(truncated)
    except PdfError as exc:
        assert exc.user_message
    else:
        assert document.has_text


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(PdfNotFoundError):
        load_pdf(tmp_path / "missing.pdf")


def test_directory_is_not_a_file(tmp_path: Path) -> None:
    with pytest.raises(PdfNotFoundError):
        load_pdf(tmp_path)
