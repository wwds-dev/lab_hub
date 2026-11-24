"""The live "busy now" line on each tile with a Land button (spec
land-blocker-actions §9.2).

Every few seconds, while the page is visible and no Land is under way, one
`lsof` reading is taken off the UI thread and each repo is checked with Land's
own test. The line only advises: it never blocks Land and never closes anything.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from lab_hub import land, land_resolve

INTERVAL_MS = 5000

Repos = list[tuple[str, Path]]


def check(repos: Repos, listing=None) -> dict[str, str]:
    """{repo name: its busy line ("" when idle)} from one shared lsof reading."""
    if listing is None:
        listing = land_resolve.cwd_listing()
    return {name: land.busy_now(path, listing) for name, path in repos}


class BusyMonitor(QObject):
    """Ticks every INTERVAL_MS; `repos()` names what to look at now, or None to
    skip this tick (page hidden, a Land running). Results come back as `updated`."""

    updated = Signal(object)  # dict[str, str]

    def __init__(self, repos: Callable[[], Repos | None], parent: QObject | None = None,
                 *, checker: Callable[[Repos], dict[str, str]] = check,
                 interval_ms: int = INTERVAL_MS) -> None:
        super().__init__(parent)
        self._repos = repos
        self._checker = checker
        self._result: list = []
        self._thread: threading.Thread | None = None
        self._tick = QTimer(self)
        self._tick.setInterval(interval_ms)
        self._tick.timeout.connect(self.poll)
        self._drain = QTimer(self)
        self._drain.setInterval(100)
        self._drain.timeout.connect(self._collect)

    def start(self) -> None:
        self._tick.start()

    def stop(self) -> None:
        self._tick.stop()

    def poll(self) -> bool:
        """Start one check now; False when one is running or nothing to look at."""
        if self._thread is not None:
            return False
        repos = self._repos()
        if not repos:
            return False
        result = self._result = []

        def work() -> None:
            try:
                result.append(self._checker(repos))
            except Exception:  # noqa: BLE001 - a courtesy line: say nothing
                result.append({})

        self._thread = threading.Thread(target=work, daemon=True, name="lab-hub-busy")
        self._thread.start()
        self._drain.start()
        return True

    def _collect(self) -> None:
        if not self._result:
            return
        self._drain.stop()
        self._thread = None
        self.updated.emit(self._result[0])
