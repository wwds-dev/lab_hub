"""The question at the top of the Apps page: a project is in the lab folder that
the page does not list yet (spec `apps-discovery` §4.2, §12.1).

One card, one row per suggestion, never a dialog: Launch, Land and the poll keep
working while it is up. A row is the project's name (and its folder, when the
README title differs from it), the README's first sentence, and three buttons.
The words and tooltips are the owner-approved ones (§7); everything read from the project (name, sentence, reasons) is plain text.

The banner only asks. It emits which suggestion was answered how; `AppsTab`
does the writing, the rescan, and tells the banner what is left.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from lab_hub import discovery

from . import theme
from .widgets import ElidedLabel, discard_widget, plain_tip

MAX_ROWS = 3  # then "and N more" (design 12.1.4); answering a row reveals the next

LEAD_IN = "New project in your lab folder:"
ADD_TEXT = "Add to Apps"
NOT_NOW_TEXT = "Not now"
NEVER_TEXT = "Never for this folder"
ADD_TIP = "Give it a tile here. Nothing is started or changed in the project."
NOT_NOW_TIP = "Ask again in 14 days."
NEVER_TIP = "Do not ask about this folder again. You can undo this in Settings."


def _plain(label: QLabel, style: str) -> QLabel:
    label.setObjectName(style)
    label.setTextFormat(Qt.TextFormat.PlainText)  # file content, never markup
    return label


def _wrapped(label: QLabel) -> QLabel:
    """Wraps at spaces and never sets the row's minimum width. A wrapped label's
    minimum is its longest unbroken word, and a README sentence or an OS error
    can hold a 200-character one (a URL, a path): clipped is better than a page
    that scrolls sideways (the failure `apps_tab.py`'s tile comments record)."""
    label.setWordWrap(True)
    label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    return label


class _Row(QFrame):
    """One suggestion: lead-in and name, the sentence, the three buttons, and a
    line for a failure to save the answer."""

    def __init__(self, suggestion: discovery.Suggestion, first: bool, last: bool,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.suggestion = suggestion
        name = suggestion.name
        # Rows after the first are told apart by a rule above them (the same
        # 1px `border` line the Land window's rows use).
        if not first:
            self.setObjectName("runRow")
        # A README title can say anything, so the folder is shown beside it
        # when the two differ (ignoring case): "Shopfront HQ (shopfront)".
        shows_folder = suggestion.folder.casefold() != name.casefold()
        self.setAccessibleName(
            f"New project: {name} ({suggestion.folder})" if shows_folder else f"New project: {name}")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0 if first else theme.SPACE_M, 0, 0 if last else theme.SPACE_M)
        outer.setSpacing(theme.SPACE_S)

        line = QHBoxLayout()
        line.setSpacing(6)
        lead = _plain(QLabel(LEAD_IN), "hint")
        self.name = ElidedLabel(name)
        self.name.setObjectName("appName")
        line.addWidget(lead)
        self.folder: ElidedLabel | None = None
        if shows_folder:
            # Next to the name, not at the far edge. An ElidedLabel is plain text.
            self.folder = ElidedLabel(f"({suggestion.folder})")
            self.folder.setObjectName("hint")
            line.addWidget(self.name)
            line.addWidget(self.folder)
            line.addStretch(1)
        else:
            line.addWidget(self.name, 1)
        outer.addLayout(line)

        # No README text, no second line (the fixed fallback is not a sentence
        # the project wrote).
        self.sentence: QLabel | None = None
        if suggestion.summary and suggestion.summary != discovery.FALLBACK_SUMMARY:
            self.sentence = _wrapped(_plain(QLabel(suggestion.summary), "hint"))
            outer.addWidget(self.sentence)

        buttons = QHBoxLayout()
        buttons.setSpacing(theme.SPACE_S)
        self.add_button = self._button(ADD_TEXT, ADD_TIP, name)
        self.add_button.setObjectName("primary")
        self.not_now_button = self._button(NOT_NOW_TEXT, NOT_NOW_TIP, name)
        self.never_button = self._button(NEVER_TEXT, NEVER_TIP, name)
        for button in (self.add_button, self.not_now_button, self.never_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        outer.addLayout(buttons)

        self.error = _wrapped(_plain(QLabel(), "stateBad"))
        self.error.hide()
        outer.addWidget(self.error)

    @staticmethod
    def _button(text: str, tip: str, name: str) -> QPushButton:
        button = QPushButton(text)
        # No default button and no shortcut: a stray Return must not answer a
        # project (design 12.1.7).
        button.setAutoDefault(False)
        button.setDefault(False)
        button.setToolTip(tip)
        button.setAccessibleName(f"{text}, {name}")  # the visible label first
        button.setAccessibleDescription(tip)
        return button

    def show_error(self, text: str) -> None:
        self.error.setText(text)
        self.error.setToolTip(plain_tip(text) if text else "")  # whole, if the line is cut
        self.error.setVisible(bool(text))


class SuggestionBanner(QWidget):
    add_requested = Signal(object)  # a discovery.Suggestion
    not_now_requested = Signal(object)
    never_requested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        frame, self._body = theme.card()
        outer.addWidget(frame)
        self._items: tuple[discovery.Suggestion, ...] = ()
        self.rows: list[_Row] = []
        self._more: QLabel | None = None
        self.hide()  # absent when there is nothing to ask: no card, no gap

    @property
    def suggestions(self) -> tuple[discovery.Suggestion, ...]:
        return self._items

    def set_suggestions(self, items: tuple[discovery.Suggestion, ...]) -> bool:
        """Show these. Rebuilds only when the set changed, so a button the
        keyboard is on is never replaced under it (design 12.1.9). Returns
        whether it rebuilt."""
        items = tuple(items)
        if items == self._items:
            return False
        self._clear()
        self._items = items
        shown = items[:MAX_ROWS]
        for index, suggestion in enumerate(shown):
            row = _Row(suggestion, index == 0, index == len(shown) - 1 and len(items) <= MAX_ROWS)
            row.add_button.clicked.connect(lambda _c=False, s=suggestion: self.add_requested.emit(s))
            row.not_now_button.clicked.connect(
                lambda _c=False, s=suggestion: self.not_now_requested.emit(s))
            row.never_button.clicked.connect(
                lambda _c=False, s=suggestion: self.never_requested.emit(s))
            self._body.addWidget(row)
            self.rows.append(row)
        if len(items) > MAX_ROWS:
            self._more = _plain(QLabel(f"and {len(items) - MAX_ROWS} more"), "hint")
            self._body.addWidget(self._more)
        self.setVisible(bool(items))
        return True

    def _clear(self) -> None:
        for row in self.rows:
            discard_widget(self._body, row)
        self.rows = []
        if self._more is not None:
            discard_widget(self._body, self._more)
            self._more = None

    def row_for(self, folder: str) -> _Row | None:
        return next((row for row in self.rows if row.suggestion.folder == folder), None)

    def show_error(self, folder: str, text: str) -> None:
        """Say why an answer could not be saved: under that row, which stays,
        with focus on its Add button."""
        row = self.row_for(folder)
        if row is None:
            return
        row.show_error(text)
        row.add_button.setFocus()

    def focus_row(self, index: int) -> bool:
        """Focus the Add button of row `index`, or the last row if there are
        fewer. False when no row is left."""
        if not self.rows:
            return False
        self.rows[min(index, len(self.rows) - 1)].add_button.setFocus()
        return True
