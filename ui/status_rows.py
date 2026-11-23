"""The status rows under a tile's version (spec tile-status-rows).

One row per fact, each with a coloured symbol and plain words. Only the symbol
carries colour, so a tile with three things to say no longer reads as one long
yellow warning.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .widgets import plain_tip

# kind -> (symbol, style of the symbol). Text glyphs, so no icon assets.
KINDS = {
    "update": ("↓", "statusAccent"),
    "land": ("⇄", "stateWarn"),
    "uncommitted": ("✎", "stateWarn"),
    "unreadable": ("✕", "stateBad"),
    "clean": ("✓", "stateOk"),
}


LINK = "check-builds"


@dataclass(frozen=True)
class Row:
    kind: str
    text: str
    tip: str = ""
    link: bool = False  # the update row's "Check builds"


def update_text(behind: int) -> str:
    if behind <= 0:
        return "Installed build is older than its source"
    return f"Installed build is {behind} commit{'' if behind == 1 else 's'} old"


class StatusRows(QWidget):
    """A small stack of rows; empty when there is nothing with evidence to say."""

    link_clicked = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(0, 2, 0, 2)
        self.layout_.setSpacing(2)
        self.rows: tuple[Row, ...] = ()
        self.link_available = False
        self.hide()

    def set_rows(self, rows: list[Row] | tuple[Row, ...]) -> None:
        rows = tuple(rows)
        if rows == self.rows:
            return  # the poll calls this every three seconds; no rebuild for nothing
        self.rows = rows
        self._rebuild()

    def set_link_available(self, available: bool) -> None:
        if available != self.link_available:
            self.link_available = available
            self._rebuild()

    def texts(self) -> list[str]:
        return [row.text for row in self.rows]

    def _rebuild(self) -> None:
        while self.layout_.count():
            item = self.layout_.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)  # gone at once, not on the next event loop turn
                widget.deleteLater()
        for row in self.rows:
            self.layout_.addWidget(self._row_widget(row))
        self.setVisible(bool(self.rows))

    def _row_widget(self, row: Row) -> QWidget:
        symbol_text, style = KINDS[row.kind]
        box = QWidget()
        line = QHBoxLayout(box)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(6)
        symbol = QLabel(symbol_text)
        symbol.setObjectName(style)
        symbol.setAccessibleName(row.kind)
        symbol.setAlignment(Qt.AlignmentFlag.AlignTop)
        text = QLabel(row.text)
        text.setObjectName("statusText")
        text.setWordWrap(True)  # a long count wraps instead of widening the tile
        text.setTextFormat(Qt.TextFormat.PlainText)  # counts come from a report file
        if row.tip:
            box.setToolTip(plain_tip(row.tip))
        line.addWidget(symbol, 0, Qt.AlignmentFlag.AlignTop)
        words = QVBoxLayout()
        words.setContentsMargins(0, 0, 0, 0)
        words.setSpacing(0)
        words.addWidget(text)
        if row.link and self.link_available:
            # On its own short line: beside wrapped words it squeezed them and
            # the row was drawn a line too short.
            link = QLabel(f'<a href="{LINK}">Check builds</a>')
            link.setObjectName("statusLink")
            link.setTextFormat(Qt.TextFormat.RichText)
            link.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse
                                         | Qt.TextInteractionFlag.LinksAccessibleByKeyboard)
            link.setCursor(Qt.CursorShape.PointingHandCursor)
            link.setToolTip("Open Check builds to rebuild and reinstall it")
            link.linkActivated.connect(lambda _href: self.link_clicked.emit())
            words.addWidget(link)
        line.addLayout(words, 1)
        return box
