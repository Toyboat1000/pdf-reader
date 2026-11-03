# CLAUDE.md

Guidance for Claude Code (and human contributors) working in this repository.

## What this is

PDF Reader: a Windows desktop app (Python 3.12, PySide6) that reads PDFs aloud with the
Kokoro-82M voice model via kokoro-onnx, entirely offline. Licensed AGPL-3.0-or-later
(required by PyMuPDF). The display name lives only in
`src/pdf_reader/config/constants.py` (`APP_NAME`); never hard-code it elsewhere.

## Commands

Install uv with `winget install --id astral-sh.uv -e`. If a shell started before the
install can't find it, open a new one (winget's install folder is
`%LOCALAPPDATA%\Microsoft\WinGet\Packages\astral-sh.uv_*\uv.exe`).

```powershell
uv sync                         # install/update the environment from uv.lock
uv run pdf-reader [file.pdf]    # run the app (also: uv run python -m pdf_reader)
uv run pytest                   # all tests, ~25 s, no sound card needed
uv run ruff check .             # lint; must pass with no warnings
uv run ruff format .            # format; run before committing
uv run python scripts/make_sample_pdf.py sample.pdf            # simple test PDF
uv run python scripts/make_sample_pdf.py --layout layout.pdf    # columns, footnotes
uv run python scripts/make_sample_documents.py book.epub        # also .docx, .html
```

Add dependencies with `uv add <pkg>` (or `uv add --dev <pkg>`); commit `uv.lock`.

## Architecture

`src/` layout, one responsibility per package. Dependencies point downward only:

```
ui  ->  core  ->  audio  ->  tts
          |         \-> config
          +-> text -> pdf
          +-> library -> text (Segment)
```

- **config/**: `constants.py` (APP_NAME, version), `paths.py` (%APPDATA% for
  settings, %LOCALAPPDATA% for models and logs), `settings.py` (JSON settings that
  never fail to load), `log_setup.py`.
- **pdf/**: `load_pdf(path) -> Document` (pages, blocks, lines with bounding boxes and
  font sizes). Raises `PdfError` subclasses carrying a `user_message`. Keep the
  position data: roadmap step 2 relies on it.
- **text/**: `TextPipeline` runs ordered steps, each `list[Segment] -> list[Segment]`.
  `Segment` carries text, page, block index, bbox, `ends_sentence`, and (for PDFs) the
  source `TextBlock` and page size. `layout.py` holds the layout cleanup steps (page
  numbers, running headers/footers, footnotes and markers, column order, joining
  sentences across blocks); `steps.py` holds character and sentence steps (use
  `@text_step` for plain `str -> str` transforms). The order is set in
  `default_steps()` in `pipeline.py`: layout steps first (they need each segment to be
  exactly one PDF block), `order_columns` before `join_continued_blocks`,
  `strip_superscript_markers` before `normalize_unicode`, hyphen repair before
  whitespace normalization. Layout steps must leave segments without layout data
  (pasted text) untouched and should err on the side of keeping text.
  `text_segments()` splits pasted text into paragraphs.
- **tts/**: `TtsEngine` ABC (`load`, `voices`, `synthesize`, `cancel`, plus optional
  model-file download hooks). `KokoroEngine` is the only implementation; model URLs,
  sizes, and SHA-256 hashes are pinned in `kokoro_engine.py`. `download.py` does
  resumable, hash-verified downloads. New engines go in new modules; nothing outside
  `tts/` may import an engine's internals.
- **audio/**: `AudioPlayer` plays queued `AudioChunk`s gap-free through one sounddevice
  stream and reports chunk start/finish from a dispatcher thread, timed to when audio
  is audible. `PlaybackController` runs the look-ahead worker (default 3 sentences),
  with an `epoch` counter (bumped on seek/stop/preview; stale audio discarded and
  in-flight synthesis cancelled) and a `params_version` counter (voice/speed changes;
  regenerated chunks replace queued ones in place, so changes never cause a gap).
- **OCR (step 4)**: `pdf/ocr.py` uses Windows OCR via the `winrt-*` packages
  (word-level boxes, no model download). `load_pdf` runs it on pages with images and
  no text, storing `Page.words`. `core/word_map.py` aligns OCR words with the final
  sentences per page (difflib opcodes), giving `ReadingDocument.word_map` for
  highlighting and click-to-read. `ui/page_view.py` paints visible pages rendered by
  `pdf/render.py` (LRU cache) and overlays word boxes. OCR results are not cached.
- **Page view for all PDFs (v0.5)**: `load_pdf` stores word positions for every
  page (`get_text("words")` for text pages, OCR for scans; `Page.ocr` marks scans).
  `word_map._reading_order` orders a page's words by the blocks the sentences use, so
  alignment survives column reordering and skipped asides. `text/layout.remove_asides`
  keeps the main text column(s) and drops sidebars, captions, and figure labels;
  `steps.remove_parentheticals` is optional. Build pipelines with
  `text.pipeline.build_pipeline(read_parentheses=..., skip_asides=...)`;
  `ReadingSession.set_pipeline` re-reads the open document.
- **UI design (v0.6)**: `ui/theme.py` (style sheet + font, `apply_theme`),
  `ui/player_bar.py` (floating capsule bound to the window's actions; owns the speed
  slider/label, voice combo, preview button, and sentence label), `ui/toast.py`
  (`MainWindow._notify`), `ui/welcome_view.py`, `ui/slim_slider.py` (custom-painted
  slider; QSS can't thin the native one). The status bar is hidden but still records
  the last message. Keep controls `NoFocus` so Space and the arrow keys stay global.
- **Speed and speech (v0.7)**: `pdf/ocr.recognize_pages` OCRs scanned pages in a
  thread pool (per-thread document + engine, Gray8 bitmaps); `pdf/ocr_cache.OcrCache`
  stores raw words per file hash (`load_pdf(..., ocr_cache=, file_hash=)`). The page
  view paints only visible pages (`_visible_pages`, bisect). `tts/kokoro_engine.polish`
  trims, loudness-normalizes, and fades each sentence; `PlaybackController` adds the
  pause (sentence / paragraph via `Segment.ends_paragraph` / clause). `tts/speech_text`
  rewrites shorthand for speech only (display text is unchanged).
- **Home page (v0.7)**: `ui/home_view.HomeView` (recents grid with covers from
  `library/thumbnails.save_thumbnail`, made by the session when a PDF opens; progress
  from `DocumentRecord.page_count/sentence_count`). `MainWindow._home_action` toggles it.
- **v0.8**: `tts/base.Speech` (samples + `word_starts`, one per `text.split()` word);
  `TtsEngine.synthesize_timed` (default estimates by length); `KokoroEngine` uses
  `create_timed`, groups phonemes into spoken words (`spoken_words`), and
  `tts/word_timing.align_word_starts` matches them to written words (banded DP);
  speeds above 2x are made at 2x and time-stretched (`tts/stretch.time_stretch`,
  WSOLA). `AudioChunk.word_starts`; `AudioPlayer.playhead()` (latency-compensated);
  `PlaybackController.current_word()` / `heard_position()`; `ReadingSession`
  `current_word()` and `listening_time()`. `WordBox.word` + `WordMap.word_boxes()`
  for page images; `DocumentView`/`PageView.highlight_word()`; `MainWindow._on_tick`
  polls every 30 ms while playing. Formats: `pdf/formats.open_paged` (every PyMuPDF
  open goes through it, e-books laid out on `EBOOK_PAGE`); `sources/` (docx, html
  article extraction, text files, `web.fetch` with truststore) produce `TextSource`;
  `ReadingSession.open_document` dispatches by suffix, `open_url` fetches (the only
  network use besides the model download). `audio/export.export_audio` (MP3 via
  lameenc, WAV) and `ReadingSession.start_export`. `ui/theme.apply_theme(app, theme)`
  (system/light/sepia/dark) and the bundled OpenDyslexic in `ui/fonts/`.
  `system/media_controls.MediaControls` (Windows SMTC; `MainWindow(media_controls=True)`
  only in the app, never in tests).
- **library/**: `LibraryStore` keeps per-document records (title, path, last opened,
  reading position, bookmarks) in `library.json`, thread-safe, written atomically by
  `flush()` (the session flushes on pause, stop, document switch, bookmark changes,
  and shutdown; `save_if_due()` throttles writes during reading). Documents are keyed
  by `file_id()` (SHA-256 of the file). Locations are `Anchor`s (index, page, start of
  the sentence text); `resolve()` finds them again even if text processing changes,
  and the session re-anchors bookmarks on open. Pasted text is never stored.
- **core/**: `ReadingSession` is the only API the UI uses. Owns the state machine
  (IDLE, LOADING, READY, PLAYING, PAUSED), the document, and the position, and runs
  model download, model loading, and document loading (`open_document` for PDFs,
  `open_text` for pasted text) on background threads. Reports via `SessionListener`
  callbacks from any thread. `ReadingDocument` is source-agnostic: `pdf` is set for
  PDFs, `text` for pasted text (`is_paginated` tells them apart).
- **ui/**: all Qt code. `SessionBridge` turns listener callbacks into Qt signals
  (queued onto the UI thread). `MainWindow`, `DocumentView`, `ModelDownloadDialog`,
  `TextInputDialog` (type or paste text), `BookmarksPanel` (dock widget),
  `ResumeBanner`, `icons.py`, and `app.py` (start-up wiring).
- **scripts/**: sample PDF generators. It is a package so tests can import the
  builders (`tests/test_layout_sample.py` checks the layout sample end to end).

## Rules and conventions

- No Qt imports outside `ui/`. No UI logic outside `ui/`.
- Never block the UI thread: anything slow (model, PDF, synthesis, opening the audio
  device) runs on a background thread. Public methods on `ReadingSession`,
  `PlaybackController`, and `AudioPlayer` must return immediately.
- Lock order: session lock, then controller lock, then player locks. Never call a
  listener while holding a player lock; the player posts events to its dispatcher
  thread instead.
- Type hints everywhere; Google-style docstrings on public classes and functions
  (ruff `D` rules enforce this, except in tests).
- Use `logging` (module-level `log = logging.getLogger(__name__)`), never `print`.
- User-facing error text must be friendly and actionable. Keep technical details in
  the log.
- Never commit model files (`*.onnx`, `voices-*.bin`); they are git-ignored.
- Tests: use the fakes in `tests/fakes.py` (`FakeEngine`, `StreamFactory`/`FakeStream`,
  `Recorder`, `wait_until`). Unit tests must not need the real model, the network, or
  a sound card. Qt tests run off-screen (`tests/conftest.py`). The only exception is
  `tests/test_kokoro_integration.py`, which skips itself when the model is missing.
- Commits: small and logical, imperative subject line.

## Gotchas

- kokoro-onnx installs its own stderr log handler; `KokoroEngine` re-routes it, and
  silences phonemizer's harmless "words count mismatch" warnings.
- ONNX Runtime's first inference is slow, so `KokoroEngine.load()` runs a short
  warm-up. Cancellation uses `RunOptions.terminate` via `_InterruptibleSession`.
- Opening a sounddevice stream takes about 0.6 s on Windows (MME), so the player opens
  it on its dispatcher thread.
- `QAbstractScrollArea` forwards viewport resizes to `resizeEvent`; `DocumentView`
  computes its margins from the widget width to avoid infinite recursion.
- Test PDFs must keep body text out of the top and bottom 12% of the page, or
  repeated first lines (e.g. "Sentence 0." and "Sentence 3." with digits ignored) are
  treated as running headers.
- Keep non-ASCII characters in code as escapes (for example `"\u2014"`); ruff flags
  ambiguous literal characters (RUF001).
- PyMuPDF 2.x pulls in `pymupdf-layout`, `pymupdf4llm`, and onnxruntime as
  dependencies even though we don't use their layout features.
