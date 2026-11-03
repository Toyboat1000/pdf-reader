"""Windows media controls: media keys, headset buttons, and the Windows media panel.

Windows shows what is playing (title, app, cover) in the volume flyout and on the
lock screen, and sends play, pause, next, and previous from keyboards and
headphones to the app that is playing. A desktop app reaches these System Media
Transport Controls through a ``MediaPlayer`` whose automatic handling is turned
off, so the app decides what each button does.

Everything degrades quietly: if the controls are unavailable, nothing happens.
"""

import asyncio
import logging
import threading
from collections.abc import Callable
from enum import Enum
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class MediaCommand(Enum):
    """A button pressed on a keyboard, headset, or in the Windows media panel."""

    PLAY = "play"
    PAUSE = "pause"
    STOP = "stop"
    NEXT = "next"
    PREVIOUS = "previous"


class PlaybackStatus(Enum):
    """What the media panel shows the app is doing."""

    CLOSED = "closed"
    STOPPED = "stopped"
    PLAYING = "playing"
    PAUSED = "paused"


class MediaControls:
    """Shows the open document in the Windows media panel and receives media keys.

    Args:
        on_command: Called with each pressed button, on a Windows thread (not the
            UI thread).
    """

    def __init__(self, on_command: Callable[[MediaCommand], None]) -> None:
        self._on_command = on_command
        self._controls: Any = None
        self._player: Any = None
        self._token: Any = None
        self._lock = threading.Lock()
        self._track = 0  # Bumped per track, so a slow cover load can't show a stale cover.
        try:
            self._setup()
        except Exception:
            log.info("Windows media controls are unavailable", exc_info=True)
            self._controls = None

    @property
    def available(self) -> bool:
        """Return whether Windows media controls are working."""
        return self._controls is not None

    def _setup(self) -> None:
        from winrt.windows.media import MediaPlaybackType
        from winrt.windows.media.playback import MediaPlayer

        player = MediaPlayer()
        # Off: otherwise Windows would route the buttons to this (empty) player.
        player.command_manager.is_enabled = False
        controls = player.system_media_transport_controls
        controls.is_play_enabled = True
        controls.is_pause_enabled = True
        controls.is_stop_enabled = True
        controls.is_next_enabled = True
        controls.is_previous_enabled = True
        controls.is_enabled = False  # Until a document is open.
        controls.display_updater.type = MediaPlaybackType.MUSIC
        self._token = controls.add_button_pressed(self._button_pressed)
        self._player = player
        self._controls = controls
        log.info("Windows media controls ready")

    def _button_pressed(self, _sender: Any, args: Any) -> None:
        from winrt.windows.media import SystemMediaTransportControlsButton as Button

        commands = {
            Button.PLAY: MediaCommand.PLAY,
            Button.PAUSE: MediaCommand.PAUSE,
            Button.STOP: MediaCommand.STOP,
            Button.NEXT: MediaCommand.NEXT,
            Button.PREVIOUS: MediaCommand.PREVIOUS,
        }
        try:
            command = commands.get(args.button)
            if command is not None:
                self._on_command(command)
        except Exception:
            log.exception("Error handling a media button")

    def set_track(self, title: str, artist: str, cover: Path | None = None) -> None:
        """Show ``title`` (and ``artist``, ``cover``) as what is playing."""
        controls = self._controls
        if controls is None:
            return
        with self._lock:
            self._track += 1
            track = self._track
        try:
            updater = controls.display_updater
            updater.music_properties.title = title
            updater.music_properties.artist = artist
            updater.thumbnail = None
            updater.update()
            controls.is_enabled = True
        except Exception:
            log.warning("Could not update the media panel", exc_info=True)
            return
        if cover is not None and cover.is_file():
            # Loading a file through WinRT is asynchronous; keep it off the caller's thread.
            threading.Thread(
                target=self._load_cover, args=(cover, track), name="media-cover", daemon=True
            ).start()

    def _load_cover(self, cover: Path, track: int) -> None:
        try:
            from winrt.windows.storage import StorageFile
            from winrt.windows.storage.streams import RandomAccessStreamReference

            async def open_file() -> Any:
                return await StorageFile.get_file_from_path_async(str(cover))

            file = asyncio.run(open_file())
            with self._lock:
                if track != self._track or self._controls is None:
                    return
                updater = self._controls.display_updater
                updater.thumbnail = RandomAccessStreamReference.create_from_file(file)
                updater.update()
        except Exception:
            log.debug("Could not show the cover in the media panel", exc_info=True)

    def set_status(self, status: PlaybackStatus) -> None:
        """Show whether reading is playing, paused, or stopped."""
        controls = self._controls
        if controls is None:
            return
        try:
            from winrt.windows.media import MediaPlaybackStatus

            controls.playback_status = {
                PlaybackStatus.CLOSED: MediaPlaybackStatus.CLOSED,
                PlaybackStatus.STOPPED: MediaPlaybackStatus.STOPPED,
                PlaybackStatus.PLAYING: MediaPlaybackStatus.PLAYING,
                PlaybackStatus.PAUSED: MediaPlaybackStatus.PAUSED,
            }[status]
        except Exception:
            log.warning("Could not update the media status", exc_info=True)

    def close(self) -> None:
        """Remove the app from the media panel and stop receiving buttons."""
        controls = self._controls
        with self._lock:
            self._controls = None
        if controls is None:
            return
        try:
            controls.remove_button_pressed(self._token)
            controls.is_enabled = False
            controls.display_updater.clear_all()
        except Exception:
            log.debug("Error closing media controls", exc_info=True)
        self._player = None
