"""The Tools tab's landing page: every tool as a tile.

The same tile page as Apps, Websites and Dashboards — one grid, Re-check, and a
poll that runs only while the page is on screen — over two kinds of tool:

* the built-in ones (Convert Files, Narrator, Prepare Images) run inside Lab
  Hub, so their tile says whether one is working right now and **Open** goes to
  its page in the tab strip above;
* the standalone ones (Unblock Tracker, Backstage) get the Apps tab's own tile,
  so Launch, *Running*, *Bring to front* and the version behave exactly as they
  do there. Their own pages stay as they were — Backstage's still carries its
  Check build — so this is a second way in, inside the same tab.

A built-in tool's state is only what can be known without asking it to do
anything: *Running* while a job is going, *Needs Calibre* when Convert Files
has no `ebook-convert` to call, and otherwise just *Built in*. Narrator's keys
and ffmpeg are checked when it starts, and claiming *Ready* before that would
be a guess.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from lab_hub import config, launcher
from lab_hub.tools import convert

from . import theme
from .apps_tab import GRID_MAX_WIDTH, POLL_MS, AppCard, arrange_tiles, columns_for
from .links_tab import LinkCard
from .widgets import scroll_column


@dataclass(frozen=True)
class BuiltInTool:
    """A tool that runs inside Lab Hub, and how to read its state."""

    name: str
    summary: str
    page: QWidget
    # (label, style, detail) — read fresh on every refresh.
    state: Callable[[], tuple[str, str, str]]


IDLE = ("Built in", "hint")
RUNNING = ("Running", "stateOk")


def convert_state(page) -> tuple[str, str, str]:
    if page.run_panel.is_running():
        return (*RUNNING, "Converting now.")
    binary = convert.converter_path()
    if binary is None:
        return ("Needs Calibre", "stateWarn", convert.INSTALL_HINT)
    return (*IDLE, f"Using Calibre at {binary}")


def running_or_idle(is_running: Callable[[], bool], busy: str) -> Callable[[], tuple[str, str, str]]:
    def state() -> tuple[str, str, str]:
        return (*RUNNING, busy) if is_running() else (*IDLE, "")
    return state


class ToolsOverview(QWidget):
    """Tiles for every tool; Open moves the tab strip, Launch starts an app."""

    launched = Signal(str)
    start_failed = Signal(str)

    def __init__(
        self,
        settings: config.Settings,
        tools: list[BuiltInTool],
        apps: tuple[launcher.ExternalApp, ...],
        open_page: Callable[[QWidget], None],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.tools = tools

        area, column = scroll_column(max_width=GRID_MAX_WIDTH)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(area)

        column.addWidget(theme.section_title("Tools"))
        column.addWidget(
            theme.hint(
                "The built-in tools run inside Lab Hub — Open goes to their page "
                "above. Unblock Tracker and Backstage are apps of their own and "
                "launch in their own window."
            )
        )

        self.tool_tiles: list[LinkCard] = []
        for tool in tools:
            tile = LinkCard(tool.name, tool.summary, "Open")
            # The state already says *Built in*; a second line saying it again
            # would also set these tiles out of line with the app tiles.
            tile.meta.hide()
            tile.reveal_button.hide()
            tile.open_requested.connect(lambda page=tool.page: open_page(page))
            self.tool_tiles.append(tile)

        self.app_cards: list[AppCard] = []
        for app in apps:
            card = AppCard(app)
            card.launched.connect(self.launched)
            card.start_failed.connect(self.start_failed)
            self.app_cards.append(card)

        self.cards: list[QWidget] = [*self.tool_tiles, *self.app_cards]
        self.grid = QGridLayout()
        self.grid.setSpacing(16)
        column.addLayout(self.grid)
        self._columns = 0
        self._arrange(1)

        refresh = QPushButton("Re-check")
        refresh.setToolTip("Look again at what is running and installed")
        refresh.clicked.connect(self.recheck)
        self.recheck_button = refresh
        row = QHBoxLayout()
        row.addWidget(refresh)
        row.addStretch(1)
        column.addLayout(row)
        column.addStretch(1)

        self._poll = QTimer(self)
        self._poll.setInterval(POLL_MS)
        self._poll.timeout.connect(self.refresh)

        self.refresh()

    def _arrange(self, columns: int) -> None:
        if columns == self._columns:
            return
        self._columns = columns
        arrange_tiles([(self.grid, self.cards)], columns)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._arrange(columns_for(self.width(), len(self.cards)))

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        self.refresh()
        self._poll.start()

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().hideEvent(event)
        self._poll.stop()

    def apply_settings(self, settings: config.Settings) -> None:
        self.settings = settings
        self.recheck()

    def recheck(self) -> None:
        lab_root = self.settings.resolved_lab_root()
        for card in self.app_cards:
            card.forget_failure()
            card.refresh_version(lab_root)
        self.refresh()

    def refresh(self) -> None:
        for tool, tile in zip(self.tools, self.tool_tiles):
            label, style, detail = tool.state()
            tile.set_state(label, style, detail)
            tile.detail.setText(detail)
        lab_root = self.settings.resolved_lab_root()
        table = launcher.process_table()  # one snapshot, shared by every card
        for card in self.app_cards:
            card.refresh(lab_root, table)
