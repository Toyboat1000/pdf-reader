# PDF Reader

**Listen to your PDFs and any text with natural-sounding AI voices, 100% offline and
private.**

PDF Reader is a free, open-source Windows desktop app that reads PDF documents, or any
text you paste into it, aloud.
It uses the [Kokoro](https://huggingface.co/hexgrad/Kokoro-82M) neural text-to-speech
model, which runs entirely on your own computer: no cloud, no account, no API keys, and
your documents never leave your PC. Think of it as a private alternative to Speechify.

> **Status:** early development (v0.2). See the [roadmap](ROADMAP.md) for what's next.

![PDF Reader reading a document, with the current sentence highlighted](docs/screenshot.png)

## Features

- **Natural AI voices.** 28 English voices (American and British, female and male),
  with friendly names such as "Heart (US Female)" and a **Preview** button.
- **Runs offline.** After a one-time download of the voice model (about 354 MB), the
  app never needs the internet again.
- **Smart text cleanup.** Page numbers, running headers and footers, and footnotes are
  skipped; two-column pages are read column by column; and sentences that continue
  across a column or page break are read as one sentence.
- **Read any text.** Paste text from a web page, email, or anywhere else (Ctrl+V), or
  type it in a new text document (Ctrl+N), and have it read aloud.
- **Follow along.** The sentence being read is highlighted and kept in view.
- **Click to jump.** Click any sentence to start reading from there.
- **Smooth playback.** Upcoming sentences are prepared in the background, so there are
  no gaps between them.
- **Speed control.** 0.5x to 2.0x; changes apply from the next sentence without a
  pause.
- **Simple controls.** Play/Pause, Stop, Previous/Next sentence, and keyboard shortcuts.
- **Open PDFs your way.** Use File > Open, the toolbar, or drag and drop a file (or
  text) onto the window.
- **Remembers your preferences.** Voice, speed, window size and position, and the last
  folder you opened.
- **Friendly errors.** Password-protected, damaged, and scanned (image-only) PDFs are
  explained clearly instead of crashing the app.

### Keyboard shortcuts

| Key | Action |
| --- | --- |
| Space | Play / Pause |
| Left arrow | Previous sentence |
| Right arrow | Next sentence |
| Ctrl+O | Open a PDF |
| Ctrl+N | New text document (type or paste text) |
| Ctrl+V | Paste text from the clipboard and read it |
| Ctrl+E | Edit the current text document |

## Requirements

- Windows 10 or 11, 64-bit
- About 1.5 GB of free disk space (app dependencies plus the voice model)
- About 1 GB of free memory while reading
- An internet connection **once**, for the voice model download

## Installation

A one-click Windows installer is planned (see the [roadmap](ROADMAP.md)). Until then,
PDF Reader runs from source using [uv](https://docs.astral.sh/uv/), which takes care of
Python and all dependencies for you.

1. **Install uv** (one time). Open PowerShell and run:

   ```powershell
   winget install --id astral-sh.uv -e
   ```

   Close and reopen PowerShell afterwards.

2. **Download PDF Reader.** Either clone the repository with Git, or download it as a
   ZIP from GitHub (green **Code** button, then **Download ZIP**) and extract it.

3. **Start the app** from the project folder:

   ```powershell
   uv run pdf-reader
   ```

   The first start installs dependencies, which takes a minute or two. You can also
   open a file straight away with `uv run pdf-reader "C:\path\to\file.pdf"`.

4. **Download the voice model.** On first launch, the app explains the one-time
   download and shows its progress. If the download is interrupted, it resumes where it
   left off when you click **Retry**.

## Where your data is stored

| What | Location |
| --- | --- |
| Settings | `%APPDATA%\PDF Reader\settings.json` |
| Voice model | `%LOCALAPPDATA%\PDF Reader\models\` |
| Log files | `%LOCALAPPDATA%\PDF Reader\logs\` (also via **Help > Open Log Folder**) |

To uninstall completely, delete the project folder and the two `PDF Reader` folders
above.

## Troubleshooting

- **No sound:** check that speakers or headphones are connected and set as the default
  output device in Windows, then press Play again.
- **The model download fails:** check your internet connection and click **Retry**. If
  you skipped the download, use **Help > Download Voice Model**.
- **"No readable text was found":** the PDF is probably a scanned document (pages
  stored as images). Support for scanned PDFs (OCR) is planned.
- **Something else:** open **Help > Open Log Folder** and attach `app.log` to a GitHub
  issue.

## For developers

### Setup

```powershell
git clone <repository-url>
cd pdf-reader
uv sync              # creates .venv with Python 3.12 and all dependencies
uv run pdf-reader    # or: uv run python -m pdf_reader
```

### Tests and linting

```powershell
uv run pytest                 # unit tests (fast; no model or sound card needed)
uv run ruff check .           # lint
uv run ruff format .          # format
```

The tests use a fake TTS engine and a fake audio device, so they run in seconds on any
machine, including CI. Qt tests run off-screen. A few integration tests in
`tests/test_kokoro_integration.py` use the real voice model; they are skipped
automatically until the model has been downloaded (by running the app once).

To try the app without a PDF of your own, generate a sample:

```powershell
uv run python scripts/make_sample_pdf.py sample.pdf
uv run python scripts/make_sample_pdf.py --layout layout-sample.pdf   # columns, footnotes
```

### Project layout

```
src/pdf_reader/
  config/   app name, file locations, settings, logging
  pdf/      PDF loading and text extraction (with page/position data)
  text/     text pipeline: layout cleanup and text steps (small ordered steps)
  tts/      TTS engine interface, Kokoro engine, model download
  audio/    gap-free player and look-ahead generation queue
  core/     reading session: document, position, state machine
  ui/       all PySide6 code
tests/      pytest suite with fakes for the engine and audio device
scripts/    developer utilities (sample PDF generators)
```

[CLAUDE.md](CLAUDE.md) documents the architecture and conventions in more detail.

### Contributing

Issues and pull requests are welcome. Please run `uv run pytest` and
`uv run ruff check .` before submitting, and keep each module within its
responsibility (see [CLAUDE.md](CLAUDE.md)).

## Credits

PDF Reader is built on these projects. Thank you to their authors and contributors.

| Project | Used for | License |
| --- | --- | --- |
| [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) by hexgrad | The AI voice model | Apache-2.0 |
| [kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx) by thewh1teagle | Running Kokoro with ONNX Runtime; model file hosting | MIT |
| [PyMuPDF](https://github.com/pymupdf/PyMuPDF) by Artifex | PDF text extraction | AGPL-3.0 (or commercial) |
| [PySide6 / Qt for Python](https://doc.qt.io/qtforpython-6/) | User interface | LGPL-3.0 |
| [ONNX Runtime](https://github.com/microsoft/onnxruntime) by Microsoft | Neural network inference | MIT |
| [eSpeak NG](https://github.com/espeak-ng/espeak-ng) (via espeakng-loader) and [phonemizer](https://github.com/bootphon/phonemizer) | Converting text to phonemes | GPL-3.0-or-later |
| [python-sounddevice](https://github.com/spatialaudio/python-sounddevice) and PortAudio | Audio output | MIT |
| [NumPy](https://numpy.org/) | Audio buffers | BSD-3-Clause |

## License

Copyright (C) 2026 Luke Oberlin.

PDF Reader is free software, licensed under the
[GNU Affero General Public License v3.0 or later](LICENSE). This license is required
because the app uses PyMuPDF, which is AGPL-licensed.
