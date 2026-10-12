"""What every page of tiles shares: the tile, the page, and Refreshable.

The Apps, Websites, Dashboards and Tools pages were built alike on purpose —
the same card, the same grid that drops a column at the same width, a state on
every tile that is re-read rather than remembered, and a poll that runs only
while the page is on screen. This is that sameness written once:

* `Tile` — the card: name and state on one line, a summary, a detail line,
  a row of buttons. `AppCard` and `LinkCard` add only what they show besides.
* `TilePage` — a scrolling column of tile grids, re-flowed on resize and
  polled while visible.
* `Refreshable` — the one interface the window's Refresh (Cmd+R) needs from
  every tab: `refresh()` to look again, `recheck()` to also forget stale
  notices and re-read what is cached.
"""

from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from . import theme
from .widgets import scroll_column

# Slow enough to be invisible in Activity Monitor, quick enough that the card
# is right by the time you have finished reading it.
POLL_MS = 3000

# A tile narrower than this squeezes the summary into a ragged column of
# single words, so the grid drops a column instead of going narrower.
TILE_MIN_WIDTH = 380
SUMMARY_HEIGHT = 52
GRID_MAX_WIDTH = 1500


def arrange_tiles(grids, columns: int) -> None:
    """Re-flow every grid of tiles into `columns` columns.

    Shared by every page of tiles, so each drops a column at the same width.
    """
    for grid, cards in grids:
        for card in cards:
            grid.removeWidget(card)
        for index, card in enumerate(cards):
            grid.addWidget(card, index // columns, index % columns)
        # Equal shares, and no leftover stretch from a wider previous layout
        # holding open an empty column.
        for index in range(grid.columnCount()):
            grid.setColumnStretch(index, 1 if index < columns else 0)


def columns_for(width: int, tiles: int) -> int:
    """How many tiles fit side by side, never more than there are."""
    usable = width - 48  # the column's own margins
    fits = max(1, usable // TILE_MIN_WIDTH)
    return min(tiles or 1, fits)


class Refreshable:
    """A tab the window's Refresh can re-check without knowing what it is.

    `refresh()` is the cheap look — showing the tab, the poll. `recheck()` is
    what Refresh asks for: drop stale notices, re-read anything cached, then
    look. A tab with nothing to re-read keeps the defaults.
    """

    def refresh(self) -> None:
        """Look again at whatever this tab shows."""

    def recheck(self) -> None:
        """Forget what is cached and look again. Refresh (Cmd+R) calls this."""
        self.refresh()


class Tile(QWidget):
    """A card: name and state, a summary, a detail line and a row of buttons.

    Subclasses add their own widgets to `header` (beside the name), `heading`
    (under it), `extra` (under the detail) and `buttons`.
    """

    def __init__(self, name: str, summary: str, parent=None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        frame, self.body = theme.card()
        outer.addWidget(frame)

        # Name and state on one line, the buttons along the bottom. Side by
        # side the tiles are too narrow to keep all three on one row without
        # the summary being squeezed into a column of single words.
        self.header = QHBoxLayout()
        self.header.setSpacing(12)
        self.name = QLabel(name)
        self.name.setObjectName("appName")
        self.state = QLabel()
        self.state.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.header.addWidget(self.name)
        self.header.addStretch(1)
        self.header.addWidget(self.state)

        self.heading = QVBoxLayout()
        self.heading.setSpacing(2)
        self.heading.addLayout(self.header)

        # The tiles sit in a grid, so they must agree on a height; the summaries
        # differ in length and would otherwise give every row a ragged edge.
        self.summary = theme.hint(summary)
        self.summary.setMinimumHeight(SUMMARY_HEIGHT)
        self.summary.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.detail = QLabel()
        self.detail.setObjectName("hint")
        self.detail.setWordWrap(True)
        self.detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.extra = QVBoxLayout()
        self.buttons = QHBoxLayout()
        self.buttons.setSpacing(8)

        self.body.addLayout(self.heading)
        self.body.addWidget(self.summary)
        self.body.addWidget(self.detail)
        self.body.addLayout(self.extra)
        self.body.addLayout(self.buttons)
        # Spare room at the bottom keeps every tile's buttons on the same line,
        # whatever the summary length.
        self.body.addStretch(1)

    def set_state(self, label: str, style: str, tooltip: str = "") -> None:
        self.state.setText(label)
        self.state.setToolTip(tooltip)
        self.restyle(self.state, style)

    @staticmethod
    def restyle(widget, name: str) -> None:
        """A changed objectName only takes effect once the style is re-applied."""
        if widget.objectName() == name:
            return
        widget.setObjectName(name)
        widget.style().unpolish(widget)
        widget.style().polish(widget)


class TilePage(QWidget, Refreshable):
    """A scrolling column of tile grids, polled only while on screen.

    Subclasses add headings and grids (`add_grid`) to `column`, fill the grids
    with `set_tiles`, put page-wide buttons in `buttons`, and call `finish()`
    once everything is in place.
    """

    def __init__(self, poll_ms: int = POLL_MS, parent=None) -> None:
        super().__init__(parent)
        area, self.column = scroll_column(max_width=GRID_MAX_WIDTH)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(area)

        self.grids: list[tuple[QGridLayout, list[QWidget]]] = []
        self.buttons = QHBoxLayout()
        self._columns = 0

        # Something can change without Lab Hub being told, so the state has to
        # be re-read rather than remembered. Only while the page is on screen:
        # polling a page nobody is looking at is pure waste.
        self._poll = QTimer(self)
        self._poll.setInterval(poll_ms)
        self._poll.timeout.connect(self.refresh)

    def add_grid(self) -> QGridLayout:
        grid = QGridLayout()
        grid.setSpacing(16)
        self.column.addLayout(grid)
        self.grids.append((grid, []))
        return grid

    def finish(self) -> None:
        self.buttons.addStretch(1)
        self.column.addLayout(self.buttons)
        self.column.addStretch(1)

    def tiles(self) -> list[QWidget]:
        return [tile for _grid, tiles in self.grids for tile in tiles]

    def set_tiles(self, index: int, tiles: list[QWidget]) -> None:
        """Replace one grid's tiles, dropping the old ones."""
        grid, old = self.grids[index]
        for tile in old:
            grid.removeWidget(tile)
            tile.deleteLater()
        self.grids[index] = (grid, list(tiles))
        self._columns = 0
        self._arrange(columns_for(self.width(), len(self.tiles())))

    def _arrange(self, columns: int) -> None:
        """Lay the tiles out in `columns` columns, if that is a change."""
        if columns == self._columns:
            return
        self._columns = columns
        arrange_tiles(self.grids, columns)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._arrange(columns_for(self.width(), len(self.tiles())))

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        self.refresh()
        self._poll.start()

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().hideEvent(event)
        self._poll.stop()
