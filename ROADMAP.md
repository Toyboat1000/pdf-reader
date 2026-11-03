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

## 6. Export to MP3 (done, v0.8.0)

- Save a whole document as an MP3 or WAV file.

Possible refinements: a range of pages, and one track per chapter.

## 6b. Listening experience (done, v0.8.0)

- Word-by-word highlighting, speeds up to 4x, listening time and progress on the
  player, light/sepia/dark themes, a dyslexia-friendly font, and Windows media keys
  and media panel.

## 7. Windows installer (done, v0.9.0)

- Standalone app built with PyInstaller; Inno Setup wizard with system checks, voice
  download with SHA-256 verification, shortcuts, "Open with", and a clean uninstaller.
- Published on GitHub Releases with a SHA-256 checksum file.

Possible refinements: code signing (removes the SmartScreen warning), automatic update
checks, and depending on `pyside6-essentials` instead of `pyside6` for faster builds.

## 8. EPUB, DOCX, and web pages (done, v0.8.0)

- EPUB and other e-books are shown as pages; Word documents, web pages (from a link
  or saved), Markdown, and text files are read as text.

Possible refinements: a reader view for web pages that need a browser to show their
content.
