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
uv run pytest                   # all tests, ~15 s, no model or sound card needed
uv run ruff check .             # lint; must pass with no warnings
uv run ruff format .            # format; run before committing
uv run python scripts/make_sample_pdf.py sample.pdf   # multi-page test PDF
```

Add dependencies with `uv add <pkg>` (or `uv add --dev <pkg>`); commit `uv.lock`.

## Architecture

`src/` layout, one responsibility per package. Dependencies point downward only:

```
ui  ->  core  ->  audio  ->  tts
          |         \-> config
          +-> text -> pdf
```

- **config/**: `constants.py` (APP_NAME, version), `paths.py` (%APPDATA% for
  settings, %LOCALAPPDATA% for models and logs), `settings.py` (JSON settings that
  never fail to load), `log_setup.py`.
- **pdf/**: `load_pdf(path) -> Document` (pages, blocks, lines with bounding boxes and
  font sizes). Raises `PdfError` subclasses carrying a `user_message`. Keep the
  position data: roadmap step 2 relies on it.
- **text/**: `TextPipeline` runs ordered steps, each `list[Segment] -> list[Segment]`.
  `Segment` carries text, page, block index, bbox, and `ends_sentence`. Add a step by
  writing a function in `steps.py` (use `@text_step` for plain `str -> str`
  transforms) and inserting it in `default_steps()` in `pipeline.py`. Cleanup steps go
  before `split_sentences`.
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
- **core/**: `ReadingSession` is the only API the UI uses. Owns the state machine
  (IDLE, LOADING, READY, PLAYING, PAUSED), the document, and the position, and runs
  model download, model loading, and PDF loading on background threads. Reports via
  `SessionListener` callbacks from any thread.
- **ui/**: all Qt code. `SessionBridge` turns listener callbacks into Qt signals
  (queued onto the UI thread). `MainWindow`, `DocumentView`, `ModelDownloadDialog`,
  `icons.py`, and `app.py` (start-up wiring).

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
  a sound card. Qt tests run off-screen (`tests/conftest.py`).
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
- PyMuPDF 2.x pulls in `pymupdf-layout`, `pymupdf4llm`, and onnxruntime as
  dependencies even though we don't use their layout features.
