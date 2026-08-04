"""Running a tool off the GUI thread.

One worker type serves every tool: a tool is just a callable taking a Reporter,
so the thread does not need to know which one it is running.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QThread, Signal

from lab_hub.tools import Cancelled, Reporter, Result


class SignalReporter(Reporter):
    """A Reporter that forwards to Qt signals and honours a stop flag.

    Signals emitted from the worker thread are delivered queued to the window's
    thread, which is what makes it safe to touch widgets in the slots.
    """

    def __init__(self, worker: "JobWorker") -> None:
        self._worker = worker

    def log(self, message: str) -> None:
        self._worker.log_line.emit(message)

    def progress(self, done: int, total: int) -> None:
        self._worker.progressed.emit(done, total)

    def checkpoint(self) -> None:
        if self._worker.stopping:
            raise Cancelled


class JobWorker(QThread):
    log_line = Signal(str)
    progressed = Signal(int, int)
    succeeded = Signal(str)  # summary line
    failed = Signal(str)  # error message
    stopped = Signal()

    def __init__(self, job: Callable[[Reporter], Result], parent=None) -> None:
        super().__init__(parent)
        self._job = job
        self.stopping = False

    def stop(self) -> None:
        self.stopping = True

    def run(self) -> None:  # noqa: D102 - QThread override
        try:
            result = self._job(SignalReporter(self))
        except Cancelled:
            self.stopped.emit()
        except Exception as error:  # noqa: BLE001 - surfaced in the UI, not swallowed
            self.failed.emit(str(error))
        else:
            self.succeeded.emit(result.summary())
