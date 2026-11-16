"""Lab Hub's QApplication.

Exists for one reason: the app must never install a Python event filter on the
application object. Such a filter sees every event to every object, and PySide
builds a Python wrapper for each receiver, including QtWebEngine's internal
objects while they are still being constructed. Identifying the type of a
half-built object segfaulted the app as soon as a dashboard web view opened
(`sbk_o_eventFilter` -> `getWrapperForQObject` -> `Shiboken::Graph::identifyType`).

Overriding `event()` here instead only runs Python for events addressed to the
application object itself, which is all the Dock-quit guard needs. The swipe
gesture filter is installed per widget instead (`ui/swipe.py`).
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication


class LabHubApplication(QApplication):
    def __init__(self, argv: list[str]) -> None:
        super().__init__(argv)
        # Called with each QEvent.Quit; returns True when it handled (refused) the quit.
        self.quit_handler: Callable[[QEvent], bool] | None = None

    def event(self, event: QEvent) -> bool:  # noqa: D401 - Qt override
        if event.type() == QEvent.Type.Quit and self.quit_handler is not None and self.quit_handler(event):
            return True
        return super().event(event)
