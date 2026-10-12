"""The left-hand navigation that replaced the top tab row.

It drives the window's page stacks rather than owning any pages: each entry
names a stack and a page in it, and clicking the entry shows that page. A child
entry (a Tools page) belongs to the stack its parent's page *is*, so picking
one shows the child inside the parent. Children are listed only while their
parent is the open page — the Tools list folds away when you leave Tools.

The selection follows the stacks, not the other way round: a swipe, a tile's
Open button or a test can change a page directly, and the sidebar catches up
from the stacks' own `currentChanged`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QEvent, QSize
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import theme


@dataclass(eq=False)
class _Entry:
    title: str
    stack: QStackedWidget
    page: QWidget
    button: QPushButton
    glyph: str | None
    parent: _Entry | None = None
    children: list[_Entry] = field(default_factory=list)


class Sidebar(QFrame):
    def __init__(self, title: str, subtitle: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(theme.SIDEBAR_WIDTH)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SPACE_M, theme.SPACE_XL, theme.SPACE_M, theme.SPACE_M)
        layout.setSpacing(2)

        heading = QLabel(title)
        heading.setObjectName("sidebarTitle")
        layout.addWidget(heading)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName("sidebarVersion")
            layout.addWidget(sub)
        layout.addSpacing(theme.SPACE_L)

        self._nav = QVBoxLayout()
        self._nav.setContentsMargins(0, 0, 0, 0)
        self._nav.setSpacing(2)
        layout.addLayout(self._nav)
        layout.addStretch(1)

        self._footer = QVBoxLayout()
        self._footer.setContentsMargins(0, 0, 0, 0)
        self._footer.setSpacing(theme.SPACE_XS)
        layout.addLayout(self._footer)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._entries: list[_Entry] = []
        self._stacks: list[QStackedWidget] = []
        self._icon_buttons: list[tuple[QPushButton, str]] = []

    # -- building ------------------------------------------------------------

    def add_page(
        self,
        title: str,
        stack: QStackedWidget,
        page: QWidget,
        glyph: str | None = None,
        under: QWidget | None = None,
    ) -> QPushButton:
        """List `page` (already in `stack`). `under` makes it a child entry."""
        parent = self._entry_for(under) if under is not None else None
        button = QPushButton(title)
        button.setObjectName("navChild" if parent else "navItem")
        button.setCheckable(True)
        button.setAutoDefault(False)
        button.setFlat(True)
        entry = _Entry(title, stack, page, button, glyph, parent)
        if parent is not None:
            parent.children.append(entry)
            # After the parent's last child, so the group stays together.
            anchor = parent.children[-2].button if len(parent.children) > 1 else parent.button
            self._nav.insertWidget(self._nav.indexOf(anchor) + 1, button)
        else:
            self._nav.addWidget(button)
        if glyph:
            self._icon_buttons.append((button, glyph))
            self._paint_icon(button, glyph)
        self._group.addButton(button)
        button.clicked.connect(lambda _checked=False, e=entry: self._open(e))
        self._entries.append(entry)

        if stack not in self._stacks:
            self._stacks.append(stack)
            stack.currentChanged.connect(self.sync)
        self.sync()
        return button

    def add_footer(self, widget: QWidget, glyph: str | None = None) -> None:
        if glyph and isinstance(widget, QPushButton):
            self._icon_buttons.append((widget, glyph))
            self._paint_icon(widget, glyph)
        self._footer.addWidget(widget)

    # -- reading -------------------------------------------------------------

    def _entry_for(self, page: QWidget) -> _Entry | None:
        return next((e for e in self._entries if e.page is page), None)

    def title_of(self, page: QWidget) -> str:
        entry = self._entry_for(page)
        return entry.title if entry else ""

    def titles(self, stack: QStackedWidget) -> list[str]:
        """The listed titles of a stack's pages, in the stack's own order."""
        return [self.title_of(stack.widget(i)) for i in range(stack.count())]

    def button_for(self, page: QWidget) -> QPushButton | None:
        entry = self._entry_for(page)
        return entry.button if entry else None

    def current_title(self) -> str:
        checked = self._group.checkedButton()
        return checked.text() if checked else ""

    # -- behaviour -----------------------------------------------------------

    def _open(self, entry: _Entry) -> None:
        # Inner first, so the outer change lands on the right child page.
        entry.stack.setCurrentWidget(entry.page)
        if entry.parent is not None:
            entry.parent.stack.setCurrentWidget(entry.parent.page)
        self.sync()

    def sync(self, *_args) -> None:
        """Check the entry for what is on screen; show only the open group."""
        selected: _Entry | None = None
        for entry in self._entries:
            if entry.parent is not None:
                continue
            is_open = entry.stack.currentWidget() is entry.page
            for child in entry.children:
                child.button.setVisible(is_open)
            if entry.children:
                entry.button.setProperty("open", is_open)
                entry.button.style().unpolish(entry.button)
                entry.button.style().polish(entry.button)
            if not is_open:
                continue
            selected = entry
            for child in entry.children:
                if child.stack.currentWidget() is child.page:
                    selected = child
        if selected is not None:
            selected.button.setChecked(True)

    def _paint_icon(self, button: QPushButton, glyph: str) -> None:
        button.setIcon(theme.nav_icon(glyph))
        button.setIconSize(QSize(18, 18))

    def changeEvent(self, event) -> None:  # noqa: N802 - Qt override
        # A theme switch repaints the icons in the new palette's colours.
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.StyleChange):
            for button, glyph in self._icon_buttons:
                self._paint_icon(button, glyph)
        super().changeEvent(event)
