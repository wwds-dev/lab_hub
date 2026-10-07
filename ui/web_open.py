"""Open a web app in the browser once its freshly started server answers.

Shared by the Apps tile and the menu bar, which both start Provisio's server
and both owe the user the tab it was started for. A dev server compiles before
it listens, so opening the address straight after `launch` returns lands on
"can't connect" — and a timer here costs nothing, where waiting on the poll
would open the page up to three seconds late.

One watcher per owner, restarted for each launch, rather than one per launch
that deletes itself: a `deleteLater()` still pending when its parent tile was
destroyed crashed the interpreter (Qt: "shared QObject was deleted directly").
"""

from __future__ import annotations

import time

from PySide6.QtCore import QObject, QTimer, Signal

from lab_hub import launcher

POLL_MS = 500


class OpenWhenServing(QObject):
    """Watches one web app's launches; at most one wait at a time."""

    opened = Signal(str)  # a status line
    gave_up = Signal(str)

    def __init__(self, app: launcher.ExternalApp, parent: QObject) -> None:
        super().__init__(parent)
        self.app = app
        self._deadline = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._check)

    @property
    def waiting(self) -> bool:
        return self._timer.isActive()

    def start(self, timeout: float) -> None:
        """Wait up to `timeout` seconds for it to answer, then open it."""
        self._deadline = time.monotonic() + timeout
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _check(self) -> None:
        if launcher.serving(self.app):
            self._timer.stop()
            try:
                launcher.open_url(self.app.url)
            except launcher.LaunchError as error:
                self.gave_up.emit(f"{self.app.name} is up, but could not be opened: {error}")
            else:
                self.opened.emit(f"Opened {self.app.name} in your browser")
            return
        if time.monotonic() > self._deadline:
            # The tile says *Did not start* on its own schedule; this only
            # stops watching.
            self._timer.stop()
            self.gave_up.emit(f"{self.app.name} did not start serving at {self.app.url}")
