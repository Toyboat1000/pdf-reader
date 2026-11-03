# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.4.0] - 2026-11-02

Scanned PDFs (roadmap step 4, MVP).

### Added

- Pages without text but with images are recognized with the offline OCR engine
  built into Windows, with progress shown in the status bar.
- Scanned documents are shown as page images. Click any word to start reading from
  its sentence; the spoken sentence is highlighted on the image and kept in view.
- View > Show Page Images (Ctrl+Shift+P) switches between the images and the
  recognized text.
- `scripts/make_sample_pdf.py --scanned` builds a scanned sample.

### Changed

- Blank PDFs now get their own message; the "scanned PDFs aren't supported" message
  is gone.

## [0.3.0] - 2026-11-02

Reading position and bookmarks (roadmap step 3).

### Added

- Each PDF remembers where you stopped reading. Reopening it continues at that
  sentence, with a banner offering "Start from the beginning". Finished documents
  start from the beginning next time.
- Documents are recognised by their contents, so positions and bookmarks survive moving
  or renaming the file. Saved locations also keep the start of the sentence's text, so
  they stay correct if a future version splits text differently.
- Bookmarks: add (Ctrl+B), rename (F2), remove (Delete), and jump to them from the
  Bookmarks panel (Ctrl+Shift+B). Bookmarked sentences are underlined.
- File > Open Recent lists recently read PDFs.
- The window layout, including the Bookmarks panel, is remembered.
- Positions and bookmarks are stored in `%APPDATA%\PDF Reader\library.json`.

## [0.2.0] - 2026-11-02

Smart text cleanup (roadmap step 2) and pasted-text documents.

### Added

- Page numbers in the top or bottom margin ("12", "- 4 -", "Page 3 of 10", "iv") are
  no longer read.
- Running headers and footers (text repeated in the page margins) are no longer read.
- Footnotes at the bottom of the page are skipped, and footnote reference markers
  (superscript numbers and symbols, including Unicode superscripts) are removed.
- Two-column (and multi-column) pages are read column by column.
- Sentences that continue across a column or page break are read as one sentence,
  including words hyphenated across the break.
- New Text Document (Ctrl+N), Paste Text (Ctrl+V), and Edit Text (Ctrl+E): type or
  paste any text and have it read aloud. Text can also be dropped onto the window.
- A layout sample PDF generator (`scripts/make_sample_pdf.py --layout`).

### Changed

- The PDF loader now keeps text spans with superscript detection.
- Pasted-text documents have no page headings or page numbers in the status bar.

## [0.1.0] - 2026-11-02

First working version (roadmap step 1).

### Added

- Open PDFs from the File menu, the toolbar, drag and drop, or the command line.
- Text extraction page by page in reading order, keeping position data for later
  layout analysis.
- Text pipeline: Unicode normalization, hyphenated line-break repair, whitespace
  cleanup, sentence splitting, and splitting of very long sentences at natural pauses.
- Offline text-to-speech with Kokoro-82M (kokoro-onnx), with 28 English voices and a
  voice preview.
- Gap-free playback with a look-ahead buffer; cancellation of outdated generation when
  seeking; instant replay of recently generated sentences.
- Speed control from 0.5x to 2.0x and voice changes that apply from the next sentence.
- Highlighting of the current sentence with automatic scrolling; click any sentence to
  read from there.
- Play/Pause, Stop, Previous and Next sentence, with keyboard shortcuts (Space,
  Left/Right, Ctrl+O).
- Status bar with page, sentence progress, and state.
- Settings saved between sessions (voice, speed, window geometry, last folder).
- First-run voice model download with size information, progress, SHA-256
  verification, resume, cancel, and retry.
- Friendly messages for password-protected, damaged, and scanned PDFs.
- Rotating log files in `%LOCALAPPDATA%\PDF Reader\logs`.
