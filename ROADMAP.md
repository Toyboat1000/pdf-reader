# Roadmap

PDF Reader is built in steps. Each step should leave the app working, tested, and
documented.

## 1. Foundation (done, v0.1.0)

Open PDFs (menu, toolbar, drag and drop); extract text page by page; split it into
sentences; read aloud offline with Kokoro voices; highlight and follow the current
sentence; click to jump; play/pause/stop/previous/next; speed and voice controls with
preview; gap-free look-ahead playback; keyboard shortcuts; status bar; remembered
settings; first-run model download with verification and retry.

## 2. Smart text cleanup (done, v0.2.0)

- Remove running headers, footers, and page numbers (detected by position and
  repetition across pages).
- Skip footnotes and remove footnote reference markers.
- Read multi-column layouts in the correct order.
- Join sentences that continue across column and page breaks.
- Also added: read pasted or typed text (File > New Text Document, Paste Text).

Possible refinements: an option to read footnotes instead of skipping them, and a way
to turn cleanup off for unusual documents.

## 3. Reading position and bookmarks (done, v0.3.0)

- Remember the reading position for each PDF (identified by content, so moving or
  renaming the file doesn't matter) and resume there, with a "Start from the
  beginning" option.
- Add, name, list, remove, and jump to bookmarks; bookmarked sentences are underlined.
- Also added: File > Open Recent.

Pasted text is deliberately not saved to disk, so it has no saved position or
bookmarks.

## 4. OCR for scanned PDFs (MVP done, v0.4.0)

- Scanned pages are recognized offline with the Windows OCR engine (no download).
- Scans are shown as page images; clicking a word reads from there, and the spoken
  sentence is highlighted on the image. Page numbers and headers are removed as for
  other PDFs.

Possible refinements: cache OCR results so reopening a long scan is instant, OCR
language choice, bookmarks underlined on page images, and zoom controls.

## 5. Custom pronunciation dictionary

- Let users define how specific words, names, and abbreviations are pronounced.

## 6. Export to MP3

- Save a whole document, or a range of pages, as audio files.

## 7. Windows installer

- Package a standalone `.exe` with PyInstaller.
- Publish builds on GitHub Releases.
- Trim dependencies for a smaller download (for example, depend on
  `pyside6-essentials` instead of the full `pyside6` package, which includes
  QtWebEngine).

## 8. EPUB and DOCX support

- Open and read EPUB e-books and Word documents with the same reading experience.
