"""The reading session: the single entry point the UI uses.

It owns the current document, the reading position, and the state machine, and runs
every slow operation (model download and loading, PDF loading) on background
threads. Results are reported through :class:`SessionListener`, whose methods may be
called from any thread; the UI layer is responsible for marshalling them onto its
own thread.

State machine::

    IDLE ──load──▶ LOADING ──done──▶ READY ◀──stop / end──┐
      ▲               │ (model failed)  │ play            │
      └───────────────┘                 ▼                 │
                                     PLAYING ◀──play──▶ PAUSED
                                         └────────────────┘

``IDLE`` means no voice model is available yet. Opening a document from any state
passes through ``LOADING``.
"""

import logging
import threading
from collections.abc import Callable
from enum import Enum
from pathlib import Path

from pdf_reader.audio.playback import PlaybackController, PlaybackListener
from pdf_reader.config.settings import clamp_speed
from pdf_reader.core.document import ReadingDocument
from pdf_reader.pdf import NoTextError, PdfError, load_pdf
from pdf_reader.text.pipeline import TextPipeline
from pdf_reader.tts.base import ModelLoadError, TtsEngine, Voice
from pdf_reader.tts.download import DownloadCancelledError, DownloadError, RemoteFile

log = logging.getLogger(__name__)

PREVIEW_TEXT = "Hello! This is how I sound when reading your documents aloud."
"""Sample spoken by the voice preview."""


class ReadingState(Enum):
    """What the session is doing."""

    IDLE = "idle"
    LOADING = "loading"
    READY = "ready"
    PLAYING = "playing"
    PAUSED = "paused"


_ALLOWED_TRANSITIONS: dict[ReadingState, frozenset[ReadingState]] = {
    ReadingState.IDLE: frozenset({ReadingState.LOADING}),
    ReadingState.LOADING: frozenset({ReadingState.IDLE, ReadingState.READY}),
    ReadingState.READY: frozenset({ReadingState.LOADING, ReadingState.PLAYING}),
    ReadingState.PLAYING: frozenset(
        {ReadingState.PAUSED, ReadingState.READY, ReadingState.LOADING}
    ),
    ReadingState.PAUSED: frozenset(
        {ReadingState.PLAYING, ReadingState.READY, ReadingState.LOADING}
    ),
}


class SessionListener:
    """Receives session events. Methods may be called from any thread.

    Subclass and override what you need; every method defaults to doing nothing.
    """

    def on_state_changed(self, state: ReadingState) -> None:
        """The session moved to ``state``."""

    def on_model_loaded(self, voices: list[Voice], voice_id: str) -> None:
        """The voice model is ready; ``voice_id`` is the voice in use."""

    def on_model_error(self, message: str) -> None:
        """The voice model failed to load."""

    def on_download_progress(self, done: int, total: int) -> None:
        """Model download progress in bytes."""

    def on_download_finished(self) -> None:
        """The model download completed and was verified."""

    def on_download_failed(self, message: str, cancelled: bool) -> None:
        """The model download failed or was cancelled."""

    def on_document_loaded(self, document: ReadingDocument) -> None:
        """A document was opened and is ready to read."""

    def on_document_error(self, path: Path | None, message: str) -> None:
        """A document could not be opened; ``message`` is user-friendly.

        ``path`` is ``None`` for pasted text.
        """

    def on_position_changed(self, index: int) -> None:
        """The current sentence changed (by playback or by the user)."""

    def on_playback_error(self, message: str) -> None:
        """Playback stopped because of an error; ``message`` is user-friendly."""


type ControllerFactory = Callable[..., PlaybackController]


class ReadingSession(PlaybackListener):
    """Coordinates document, position, model, and playback for the UI."""

    def __init__(
        self,
        engine: TtsEngine,
        listener: SessionListener,
        *,
        voice: str,
        speed: float = 1.0,
        pipeline: TextPipeline | None = None,
        controller_factory: ControllerFactory = PlaybackController,
    ) -> None:
        self._engine = engine
        self._listener = listener
        self._pipeline = pipeline or TextPipeline()
        self._lock = threading.RLock()
        self._state = ReadingState.IDLE
        self._voice = voice
        self._speed = clamp_speed(speed)
        self._document: ReadingDocument | None = None
        self._position = 0
        self._can_resume = False
        self._at_end = False
        self._model_loading = False
        self._doc_loading = False
        self._doc_request = 0
        self._download_cancel: threading.Event | None = None
        self._threads: list[threading.Thread] = []
        self._controller = controller_factory(engine, self, voice=voice, speed=self._speed)

    # ----------------------------------------------------------- properties

    @property
    def state(self) -> ReadingState:
        """Return the current state."""
        with self._lock:
            return self._state

    @property
    def document(self) -> ReadingDocument | None:
        """Return the open document, if any."""
        with self._lock:
            return self._document

    @property
    def position(self) -> int:
        """Return the index of the current sentence."""
        with self._lock:
            return self._position

    @property
    def voice(self) -> str:
        """Return the selected voice id."""
        with self._lock:
            return self._voice

    @property
    def speed(self) -> float:
        """Return the reading speed multiplier."""
        with self._lock:
            return self._speed

    @property
    def is_model_loaded(self) -> bool:
        """Return whether the voice model is ready."""
        return self._engine.is_loaded

    # ----------------------------------------------------------- model

    def missing_model_files(self) -> list[RemoteFile]:
        """Return model files that must be downloaded before the model can load."""
        return self._engine.missing_files()

    def start_model_download(self) -> None:
        """Download missing model files in the background.

        Reports through ``on_download_progress``, then ``on_download_finished`` or
        ``on_download_failed``.
        """
        with self._lock:
            if self._download_cancel is not None:
                return  # Already downloading.
            cancel = self._download_cancel = threading.Event()

        def task() -> None:
            try:
                self._engine.download_missing_files(self._listener.on_download_progress, cancel)
            except DownloadCancelledError:
                self._listener.on_download_failed("The download was cancelled.", cancelled=True)
            except DownloadError as exc:
                self._listener.on_download_failed(exc.user_message, cancelled=False)
            except Exception as exc:
                log.exception("Unexpected download failure")
                self._listener.on_download_failed(f"Unexpected error: {exc}", cancelled=False)
            else:
                self._listener.on_download_finished()
            finally:
                with self._lock:
                    self._download_cancel = None

        self._start_thread("model-download", task)

    def cancel_model_download(self) -> None:
        """Ask a running download to stop."""
        with self._lock:
            if self._download_cancel is not None:
                self._download_cancel.set()

    def discard_model_files(self) -> None:
        """Delete model files that failed to load, so they can be downloaded again."""
        self._engine.discard_model_files()

    def load_model(self) -> None:
        """Load the voice model in the background (state ``LOADING`` meanwhile)."""
        with self._lock:
            if self._engine.is_loaded or self._model_loading:
                return
            self._model_loading = True
            self._transition(ReadingState.LOADING)
        self._start_thread("model-load", self._load_model_task)

    def _load_model_task(self) -> None:
        try:
            self._engine.load()
        except ModelLoadError as exc:
            with self._lock:
                self._model_loading = False
                self._settle()
            self._listener.on_model_error(str(exc))
            return
        except Exception as exc:
            log.exception("Unexpected error loading the voice model")
            with self._lock:
                self._model_loading = False
                self._settle()
            self._listener.on_model_error(f"Unexpected error loading the voice model: {exc}")
            return
        voices = self._engine.voices()
        with self._lock:
            self._model_loading = False
            if self._voice not in {v.id for v in voices}:
                fallback = self._engine.default_voice_id() or self._voice
                log.info("Voice %r unavailable; using %r", self._voice, fallback)
                self._voice = fallback
                self._controller.set_voice(fallback)
            voice = self._voice
            self._settle()
        self._listener.on_model_loaded(voices, voice)

    # ----------------------------------------------------------- documents

    def open_document(self, path: Path) -> None:
        """Open a PDF in the background, stopping any current playback.

        Reports ``on_document_loaded`` or ``on_document_error``. If another document
        is opened before this one finishes loading, this one's result is ignored.
        """
        request = self._begin_open()

        def task() -> None:
            try:
                document = load_pdf(path)
                sentences = tuple(self._pipeline.process_document(document))
                if not sentences:
                    raise NoTextError(path)
                result: ReadingDocument | str = ReadingDocument.from_pdf(document, sentences)
            except PdfError as exc:
                result = exc.user_message
            except Exception as exc:
                log.exception("Unexpected error opening %s", path)
                result = f"Something went wrong while opening this file: {exc}"
            self._finish_open(request, path, result)

        self._start_thread("document-load", task)

    def open_text(self, text: str) -> None:
        """Open pasted or typed text as a document, like :meth:`open_document`."""
        request = self._begin_open()

        def task() -> None:
            try:
                sentences = tuple(self._pipeline.process_text(text))
                result: ReadingDocument | str = (
                    ReadingDocument.from_text(text, sentences)
                    if sentences
                    else "There's no text to read. Paste or type some text first."
                )
            except Exception as exc:
                log.exception("Unexpected error processing pasted text")
                result = f"Something went wrong while preparing this text: {exc}"
            self._finish_open(request, None, result)

        self._start_thread("document-load", task)

    def _begin_open(self) -> int:
        """Stop playback and enter ``LOADING`` for a new document; return its request id."""
        with self._lock:
            self._controller.stop()
            self._can_resume = False
            self._doc_request += 1
            self._doc_loading = True
            self._transition(ReadingState.LOADING)
            return self._doc_request

    def _finish_open(self, request: int, path: Path | None, result: ReadingDocument | str) -> None:
        with self._lock:
            if request != self._doc_request:
                return  # A newer open_document call superseded this one.
            self._doc_loading = False
            if isinstance(result, ReadingDocument):
                self._document = result
                self._position = 0
                self._at_end = False
                self._controller.set_script(result.sentences)
            self._settle()
        if isinstance(result, ReadingDocument):
            log.info("Document ready: %d sentences", result.sentence_count)
            self._listener.on_document_loaded(result)
            self._listener.on_position_changed(0)
        else:
            self._listener.on_document_error(path, result)

    # ----------------------------------------------------------- playback

    def play(self) -> None:
        """Start or resume reading."""
        with self._lock:
            if not self._can_play():
                return
            if self._state is ReadingState.PLAYING:
                return
            if self._state is ReadingState.PAUSED and self._can_resume:
                self._controller.resume()
            else:
                if self._at_end:
                    self._at_end = False
                    self._set_position(0)
                self._controller.play_from(self._position)
            self._can_resume = False
            self._transition(ReadingState.PLAYING)

    def pause(self) -> None:
        """Pause reading; :meth:`play` resumes mid-sentence."""
        with self._lock:
            if self._state is not ReadingState.PLAYING:
                return
            self._controller.pause()
            self._can_resume = True
            self._transition(ReadingState.PAUSED)

    def toggle_play_pause(self) -> None:
        """Pause if reading, otherwise start reading."""
        with self._lock:
            if self._state is ReadingState.PLAYING:
                self.pause()
            else:
                self.play()

    def stop(self) -> None:
        """Stop reading. The current sentence stays selected; play restarts it."""
        with self._lock:
            if self._state not in (ReadingState.PLAYING, ReadingState.PAUSED):
                return
            self._controller.stop()
            self._can_resume = False
            self._transition(ReadingState.READY)

    def next_sentence(self) -> None:
        """Move to the next sentence (keeps reading if currently reading)."""
        with self._lock:
            if self._document is not None:
                self.seek(self._position + 1, play=False)

    def previous_sentence(self) -> None:
        """Move to the previous sentence (keeps reading if currently reading)."""
        with self._lock:
            if self._document is not None:
                self.seek(self._position - 1, play=False)

    def seek(self, index: int, *, play: bool = True) -> None:
        """Jump to sentence ``index``.

        Args:
            index: Target sentence; clamped to the document.
            play: Start reading from there even if currently stopped or paused.
                When False, playback continues only if it was already running.
        """
        with self._lock:
            if self._document is None:
                return
            index = max(0, min(index, self._document.sentence_count - 1))
            self._at_end = False
            self._set_position(index)
            if self._state is ReadingState.PLAYING:
                self._controller.play_from(index)
            elif play and self._can_play():
                self._controller.play_from(index)
                self._can_resume = False
                self._transition(ReadingState.PLAYING)
            elif self._state is ReadingState.PAUSED:
                self._controller.stop()
                self._can_resume = False

    def set_voice(self, voice_id: str) -> None:
        """Change the voice; takes effect from the next sentence."""
        with self._lock:
            self._voice = voice_id
            self._controller.set_voice(voice_id)

    def set_speed(self, speed: float) -> None:
        """Change the speed; takes effect from the next sentence."""
        with self._lock:
            self._speed = clamp_speed(speed)
            self._controller.set_speed(self._speed)

    def preview_voice(self, voice_id: str) -> None:
        """Speak a short sample with ``voice_id``, pausing reading if needed."""
        with self._lock:
            if not self._engine.is_loaded:
                return
            if self._state is ReadingState.PLAYING:
                self._transition(ReadingState.PAUSED)
            self._can_resume = False
            self._controller.preview(PREVIEW_TEXT, voice_id, self._speed)

    def shutdown(self) -> None:
        """Stop playback and background work. Called when the app closes."""
        self.cancel_model_download()
        self._controller.shutdown()
        for thread in self._threads:
            thread.join(timeout=0.5)
        log.info("Session shut down")

    # --------------------------------------------- playback controller events

    def on_sentence_started(self, index: int) -> None:
        """Follow playback with the highlighted position."""
        with self._lock:
            if self._state is not ReadingState.PLAYING:
                return
            self._set_position(index)

    def on_reached_end(self) -> None:
        """Return to ``READY`` when the document has been read to the end."""
        with self._lock:
            if self._state is ReadingState.PLAYING:
                self._at_end = True
                self._transition(ReadingState.READY)

    def on_preview_finished(self) -> None:
        """Nothing to do: the session state was settled when the preview started."""

    def on_playback_error(self, message: str) -> None:
        """Stop and surface the error."""
        with self._lock:
            if self._state in (ReadingState.PLAYING, ReadingState.PAUSED):
                self._can_resume = False
                self._transition(ReadingState.READY)
        self._listener.on_playback_error(message)

    # ----------------------------------------------------------- internals

    def _can_play(self) -> bool:
        return (
            self._document is not None
            and self._engine.is_loaded
            and self._state in (ReadingState.READY, ReadingState.PAUSED, ReadingState.PLAYING)
        )

    def _set_position(self, index: int) -> None:
        if index != self._position:
            self._position = index
            self._listener.on_position_changed(index)

    def _settle(self) -> None:
        """Pick the resting state after a background load finished."""
        if self._model_loading or self._doc_loading:
            target = ReadingState.LOADING
        elif self._engine.is_loaded:
            target = ReadingState.READY
        else:
            target = ReadingState.IDLE
        self._transition(target)

    def _transition(self, target: ReadingState) -> None:
        if target is self._state:
            return
        if target not in _ALLOWED_TRANSITIONS[self._state]:
            log.debug("Ignoring transition %s -> %s", self._state.name, target.name)
            return
        log.debug("State %s -> %s", self._state.name, target.name)
        self._state = target
        self._listener.on_state_changed(target)

    def _start_thread(self, name: str, target: Callable[[], None]) -> None:
        thread = threading.Thread(target=target, name=name, daemon=True)
        self._threads = [t for t in self._threads if t.is_alive()]
        self._threads.append(thread)
        thread.start()
