"""The Tools tab's landing page: every tool as a tile.

The same tile page as Apps, Websites and Dashboards — one grid and a
poll that runs only while the page is on screen — over two kinds of tool:

* the built-in ones (Convert Textfiles, Narrator, Prepare Images) run inside Lab
  Hub, so their tile says whether one is working right now and **Open** goes to
  its page under Tools in the sidebar;
* the standalone ones (Unblock Tracker, Backstage) get the Apps tab's own tile,
  so Launch, *Running*, *Bring to front* and the version behave exactly as they
  do there. Their own pages stay as they were — Backstage's still carries its
  Check build — so this is a second way in, inside the same tab.

A built-in tool's state is only what can be known without asking it to do
anything: *Running* while a job is going, *Needs Calibre* when Convert Textfiles
has no `ebook-convert` to call, and otherwise just *Built in*. Narrator's keys
and ffmpeg are checked when it starts, and claiming *Ready* before that would
be a guess.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget

from lab_hub import config, launcher
from lab_hub.tools import convert

from . import theme
from .apps_tab import AppCard, AppSource, resolve_apps
from .links_tab import LinkCard
from .tiles import POLL_MS, TilePage, columns_for


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


class ToolsOverview(TilePage):
    """Tiles for every tool; Open moves the tab strip, Launch starts an app."""

    launched = Signal(str)
    start_failed = Signal(str)

    def __init__(
        self,
        settings: config.Settings,
        tools: list[BuiltInTool],
        apps: AppSource,
        open_page: Callable[[QWidget], None],
        parent=None,
    ) -> None:
        super().__init__(POLL_MS, parent)
        self.settings = settings
        self.tools = tools
        self._apps_source = apps
        self._apps_shown: tuple[launcher.ExternalApp, ...] | None = None

        self.column.addWidget(theme.section_title("Tools"))
        self.column.addWidget(
            theme.hint(
                "The built-in tools run inside Lab Hub — Open shows the tool, and "
                "Tools in the sidebar brings you back here. Unblock Tracker and Backstage are apps of their "
                "own and launch in their own window."
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
        self.grid = self.add_grid()
        self._sync_apps()
        self._arrange(1)
        self.finish()

        self.refresh()

    @property
    def cards(self) -> list[QWidget]:
        return self.tiles()

    def _sync_apps(self) -> None:
        """Rebuild the app tiles when the registered list has changed."""
        wanted = resolve_apps(self._apps_source)
        if wanted == self._apps_shown:
            return
        # The built-in tiles are kept; only the app cards are replaced.
        for card in self.app_cards:
            self.grid.removeWidget(card)
            card.deleteLater()
        self.app_cards = []
        for app in wanted:
            card = AppCard(app)
            card.launched.connect(self.launched)
            card.start_failed.connect(self.start_failed)
            self.app_cards.append(card)
        self._apps_shown = wanted
        self.grids[0] = (self.grid, [*self.tool_tiles, *self.app_cards])
        self._columns = 0
        self._arrange(columns_for(self.width(), len(self.cards)))

    def apply_settings(self, settings: config.Settings) -> None:
        self.settings = settings
        self.recheck()

    def recheck(self) -> None:
        self._sync_apps()
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
