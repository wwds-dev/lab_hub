"""Stand-ins for the things a test should not really create."""

from __future__ import annotations


class FakeTray:
    """A menu bar item that records instead of drawing.

    `MainWindow` only ever asks a tray to notify or hide, and only ever tests
    it for None, so this is the whole contract.
    """

    def __init__(self) -> None:
        self.notices: list[tuple[str, str]] = []
        self.hidden = False

    def notify(self, title: str, message: str) -> None:
        self.notices.append((title, message))

    def hide(self) -> None:
        self.hidden = True


class RecordingReporter:
    """Collects what a tool reports, and can cancel it partway through."""

    def __init__(self, cancel_after: int | None = None) -> None:
        self.lines: list[str] = []
        self.progress_calls: list[tuple[int, int]] = []
        self.checkpoints = 0
        self._cancel_after = cancel_after

    def log(self, message: str) -> None:
        self.lines.append(message)

    def progress(self, done: int, total: int) -> None:
        self.progress_calls.append((done, total))

    def checkpoint(self) -> None:
        from lab_hub.tools import Cancelled

        self.checkpoints += 1
        if self._cancel_after is not None and self.checkpoints > self._cancel_after:
            raise Cancelled

    @property
    def text(self) -> str:
        return "\n".join(self.lines)
