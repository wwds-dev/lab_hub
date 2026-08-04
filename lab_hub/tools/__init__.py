"""The integrated tools: ported from standalone scripts, now callable.

Each tool is a plain function taking its inputs as arguments and a `Reporter`
for output. Nothing here imports Qt — the tools stay testable and runnable from
a shell, and the UI layer is the only part that knows about widgets.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class Cancelled(Exception):
    """Raised inside a tool when the user asks it to stop."""


class Reporter:
    """How a running tool talks to whatever is driving it.

    The default implementation prints, which is what `main.py --selftest` and
    any shell use gets. The UI subclasses it to marshal onto the GUI thread.
    """

    def log(self, message: str) -> None:
        print(message)

    def progress(self, done: int, total: int) -> None:
        """Report position. total <= 0 means "unknown length"."""

    def checkpoint(self) -> None:
        """Called between items; raise Cancelled here to stop the run."""


@dataclass
class Result:
    """What a tool did, summarised for the status line."""

    processed: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = [f"{self.processed} processed"]
        if self.skipped:
            parts.append(f"{self.skipped} skipped")
        if self.failed:
            parts.append(f"{self.failed} failed")
        return ", ".join(parts)


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".tiff", ".bmp"}
