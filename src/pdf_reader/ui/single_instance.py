"""Keep one copy of the app running: a second launch hands its document to the first.

Opening a file from Explorer while the app is open then adds a tab to the open
window, instead of starting a second copy that would compete for the speakers and
overwrite the first one's saved reading positions.

The copies talk over a local pipe that only the current Windows user can open.
"""

import getpass
import hashlib
import logging

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from pdf_reader.config.constants import APP_NAME

log = logging.getLogger(__name__)

_CONNECT_MS = 500
_WRITE_MS = 1000


def _server_name() -> str:
    user = hashlib.sha256(getpass.getuser().encode()).hexdigest()[:12]
    return f"{APP_NAME.replace(' ', '')}-{user}"


class SingleInstance(QObject):
    """Detects a running copy, or becomes the running copy and listens for others."""

    message_received = Signal(str)
    """Another launch asked to open this (a file path or web address; "" = just show)."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._name = _server_name()
        self._server: QLocalServer | None = None

    def send_to_running(self, message: str) -> bool:
        """Pass ``message`` to a copy that is already running. Returns whether one was."""
        socket = QLocalSocket()
        socket.connectToServer(self._name)
        if not socket.waitForConnected(_CONNECT_MS):
            return False
        socket.write((message + "\n").encode("utf-8"))
        socket.flush()
        socket.waitForBytesWritten(_WRITE_MS)
        # Wait for the running copy to confirm, so the message isn't lost as this exits.
        confirmed = socket.waitForReadyRead(_WRITE_MS)
        socket.disconnectFromServer()
        log.info("Handed %r to the running copy (confirmed: %s)", message, confirmed)
        return True

    def listen(self) -> None:
        """Become the running copy: accept documents from later launches."""
        server = QLocalServer(self)
        # Only this Windows user may connect.
        server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        if not server.listen(self._name):
            # A copy that crashed can leave its pipe name behind; take it over.
            QLocalServer.removeServer(self._name)
            if not server.listen(self._name):
                log.warning("Single-instance listener unavailable: %s", server.errorString())
                return
        server.newConnection.connect(self._accept)
        self._server = server

    def _accept(self) -> None:
        assert self._server is not None
        while (socket := self._server.nextPendingConnection()) is not None:
            # The other copy sends one line and waits for "ok": read it right away.
            if not socket.canReadLine():
                socket.waitForReadyRead(_WRITE_MS)
            message = None
            if socket.canReadLine():
                line = bytes(socket.readLine().data()).decode("utf-8", "replace")
                message = line.rstrip("\n")[:4096]
                socket.write(b"ok\n")
                socket.flush()
                socket.waitForBytesWritten(_WRITE_MS)
            socket.disconnected.connect(socket.deleteLater)
            socket.disconnectFromServer()
            if message is not None:
                self.message_received.emit(message)
