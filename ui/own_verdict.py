"""Lab Hub's own build verdict, computed off the UI thread.

Spec `docs/specs/apps-discovery.md` §13.4, ADR 0007. The line on Lab Hub's tile
("up to date", "N commits older than its source") is `self_update.self_status`,
the same row Check builds shows. It costs git (about 170-200 ms on a warm repo,
nothing cached), so it is not run on the three-second poll or on the GUI thread:
one daemon thread runs it when the Apps page starts or Refresh asks, and the
result comes back as a Qt signal on the UI thread, drained from a queue by a
timer. The shape is `ui/lander.py`'s.

The thread touches no Qt object and no registry state. It calls `self_status`
and puts one frozen result on the queue; everything else happens here, on the
GUI thread.
"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from lab_hub import self_update


@dataclass(frozen=True)
class OwnResult:
    """What one run found: the row, or why there is none."""

    row: self_update.BuildStatus | None = None
    error: str | None = None


class OwnVerdict(QObject):
    ready = Signal(object)  # an OwnResult

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._events: queue.SimpleQueue = queue.SimpleQueue()
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._drain)
        self._thread: threading.Thread | None = None
        # A request that came in while one was running: the latest root wins,
        # and a burst of Refreshes costs one extra run, not one each.
        self._again: Path | None = None
        self._closed = False

    @property
    def busy(self) -> bool:
        return self._thread is not None

    def request(self, lab_root: Path) -> None:
        """Compute the verdict, or note that it must be computed again."""
        if self._closed:
            return
        if self._thread is not None:
            self._again = Path(lab_root)
            return
        self._start(Path(lab_root))

    def shutdown(self) -> None:
        """The app is quitting: stop watching. The daemon thread needs no join."""
        self._closed = True
        self._again = None
        self._timer.stop()

    # -- worker side --------------------------------------------------------
    def _start(self, lab_root: Path) -> None:
        thread = threading.Thread(
            target=self._work, args=(lab_root,), daemon=True, name="lab-hub-own-verdict"
        )
        try:
            thread.start()
        except RuntimeError as exc:  # no thread could be made: stay idle, say why
            self.ready.emit(OwnResult(error=str(exc) or type(exc).__name__))
            return
        # After a start that worked, so a failed one never leaves it "busy". The
        # worker only puts on the queue; `_drain` runs on this thread, later.
        self._thread = thread
        self._timer.start()

    def _work(self, lab_root: Path) -> None:
        result = OwnResult(error="the check stopped before it finished")
        try:
            result = OwnResult(row=self_update.self_status(lab_root))
        except Exception as exc:  # noqa: BLE001 - the tile shows version only, whatever went wrong
            result = OwnResult(error=str(exc) or type(exc).__name__)
        finally:
            # Whatever ended the run, the page gets an answer and is not left
            # "busy" for ever.
            self._events.put(result)

    # -- UI side ------------------------------------------------------------
    def _drain(self) -> None:
        while True:
            try:
                result = self._events.get_nowait()
            except queue.Empty:
                return
            self._thread = None
            if self._closed:
                continue
            again, self._again = self._again, None
            if again is not None:
                self._start(again)  # before the signal: a slot may request too
            else:
                self._timer.stop()
            self.ready.emit(result)
