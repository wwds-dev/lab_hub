"""One running copy, enforced with a local socket.

A lock file would say "something already holds this" and nothing more, which
leaves the second launch with no better option than an error dialog. A socket
carries a message, so the copy that loses the race can ask the one already
running to come to the front — which is what a user double-clicking the Dock
icon actually wants.
"""

from __future__ import annotations

import os

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

# Per-user: two accounts on one Mac each get their own instance.
KEY = f"lab-hub-{os.getuid()}"

CONNECT_TIMEOUT_MS = 300


class SingleInstance(QObject):
    """Owns the socket. `activated` fires when another launch is turned away."""

    activated = Signal()

    def __init__(self, key: str = KEY, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._key = key
        self._server: QLocalServer | None = None

    def acquire(self) -> bool:
        """True if this process may run; False if another copy took the call."""
        socket = QLocalSocket()
        socket.connectToServer(self._key)
        if socket.waitForConnected(CONNECT_TIMEOUT_MS):
            socket.write(b"activate")
            socket.waitForBytesWritten(CONNECT_TIMEOUT_MS)
            socket.disconnectFromServer()
            return False

        # Nothing is listening. A crash leaves the socket file behind, and
        # listen() refuses to bind over it, so clear it before trying.
        QLocalServer.removeServer(self._key)

        self._server = QLocalServer(self)
        if not self._server.listen(self._key):
            # Cannot guard — sandboxing, a full /tmp, a permissions oddity.
            # Starting unguarded beats refusing to start at all.
            self._server = None
            return True

        self._server.newConnection.connect(self._on_connection)
        return True

    def release(self) -> None:
        if self._server is not None:
            self._server.close()
            QLocalServer.removeServer(self._key)
            self._server = None

    def _on_connection(self) -> None:
        connection = self._server.nextPendingConnection() if self._server else None
        if connection is not None:
            connection.disconnectFromServer()
            connection.deleteLater()
        self.activated.emit()
