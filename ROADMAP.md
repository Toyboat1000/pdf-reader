# Roadmap

PDF Reader is built in steps. Each step should leave the app working, tested, and
documented.

## 1. Foundation (done, v0.1.0)

Open PDFs (menu, toolbar, drag and drop); extract text page by page; split it into
sentences; read aloud offline with Kokoro voices; highlight and follow the current
sentence; click to jump; play/pause/stop/previous/next; speed and voice controls with
preview; gap-free look-ahead playback; keyboard shortcuts; status bar; remembered
settings; first-run model download with verification and retry.

## 2. Smart text cleanup

Make documents sound the way a person would read them:

- Remove running headers, footers, and page numbers (detected by position and
  repetition across pages).
- Handle footnotes and footnote markers.
- Read multi-column layouts in the correct order.
- Join sentences that continue across page breaks.

The `pdf/` package already keeps bounding boxes and font sizes for this, and the
`text/` pipeline is designed to take new cleanup steps.

## 3. Reading position and bookmarks

- Remember the reading position for each document and offer to resume.
- Add, list, and jump to bookmarks.

## 4. OCR for scanned PDFs

- Recognise text in scanned (image-only) PDFs, locally and offline.

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
