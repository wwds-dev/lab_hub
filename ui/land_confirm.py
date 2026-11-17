"""The one confirmation before Land starts (spec land-confirm-dialog).

One card per repo (what Land will do, what only you can clear), one Claude Code
panel with one total, and Details holding today's full texts unchanged. All
words come from `lab_hub.land`; this module only lays them out. Every name,
path, branch, process and reason is plain text: they come from git and lsof.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from lab_hub import land

from .progress_window import _label, _plain_tip

WIDTH = 640
SCREEN_SHARE = 0.7  # the cards scroll when taller than this share of the screen
WINDOW_SHARE = 0.9  # and the whole window stays within this share
DETAILS_MIN = 80  # with Details open, it and the cards share the room left,
CARDS_MIN_WITH_DETAILS = 70  # so a short screen still fits (review P2-2)
FOOTNOTE = ("Each step is checked again just before it runs. Nothing is forced. "
            "Cancel leaves everything as it is.")


def _n(count: int, one: str, many: str | None = None) -> str:
    return f"{count} {one if count == 1 else (many or one + 's')}"


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def _pill(text: str, tone: str) -> QLabel:
    pill = _label(text, "runPill")
    pill.setProperty("tone", tone)
    return pill


def headline(todo: list[land.LandPlan]) -> tuple[str, str]:
    """The title and the one sentence under it."""
    if not todo:
        return "Land", "Nothing to land."
    title = f"Land {todo[0].name}" if len(todo) == 1 else f"Land {len(todo)} repos"
    stops = sum(len(p.stops) for p in todo)
    if not stops:
        return title, "Land does all of it; nothing needs you."
    return title, (f"Land does everything it can, then stops at "
                   f"{_n(stops, 'thing')} only you can clear. You can clear "
                   f"{'it' if stops == 1 else 'them'} now and press Land after, or press "
                   "Land and clear " + ("it" if stops == 1 else "them") + " later.")


def details_text(todo: list[land.LandPlan]) -> str:
    """Today's full texts, unchanged, plus every process with its pid."""
    parts = ["\n".join(p.sentence for p in todo)]
    parts += [p.claude_notice for p in todo if p.claude_notice]
    for plan in todo:
        text = plan.detail
        busy = [s for s in plan.stops if s.processes]
        if busy:
            text += "\n\nProcesses:\n" + "\n".join(
                f"{s.target}: {', '.join(s.processes)}" for s in busy)
        parts.append(text)
    return "\n\n".join(parts)


class RepoCard(QFrame):
    """One repo: what Land will do, and what only you can clear."""

    def __init__(self, plan: land.LandPlan, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.plan = plan
        box = QVBoxLayout(self)
        box.setContentsMargins(14, 10, 14, 12)
        box.setSpacing(4)

        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(_label(plan.name, "appName"))
        items = plan.items
        if items:
            head.addWidget(_pill(_n(len(items), "step"), "ok"))
        if plan.stops:
            head.addWidget(_pill(f"stops at {len(plan.stops)}", "warn"))
        head.addStretch(1)
        cost = plan.cost
        if cost.any:
            head.addWidget(_pill(f"Claude Code · up to {land._usd(cost.total_usd)}", "run"))
        box.addLayout(head)

        if items:
            box.addWidget(_label("WILL DO", "sectionTitle"))
            for item in items:
                box.addWidget(_label(f"✓  {_cap(item)}", "", wrap=True))
            if cost.merge:
                tests = "; ".join(cost.tests) or "its test command"
                box.addWidget(_label(f"Tests Lab Hub runs after a Claude Code merge: {tests}",
                                     "hint", wrap=True))
        else:
            box.addWidget(_label("Nothing else to do here until this is cleared.", "hint",
                                 wrap=True))

        self.stop_rows: list[QLabel] = []
        if plan.stops:
            box.addSpacing(4)
            box.addWidget(_label("⚠  ONLY YOU CAN CLEAR", "stateWarn"))
            for view in plan.stop_views:
                where = _label(f"{view.place} · {view.problem}", "runStrong", wrap=True)
                where.setToolTip(_plain_tip(view.full))
                box.addWidget(where)
                self.stop_rows.append(where)
                if view.action:
                    box.addWidget(_label(view.action, "stateWarn", wrap=True))


class ClaudeBox(QFrame):
    """The one Claude Code disclosure, with one total."""

    def __init__(self, panel: land.ClaudePanel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        box = QVBoxLayout(self)
        box.setContentsMargins(14, 10, 14, 12)
        box.setSpacing(4)
        head = QHBoxLayout()
        head.addWidget(_label(panel.title, "runStrong"))
        head.addStretch(1)
        head.addWidget(_label(panel.total, "runStrong"))
        box.addLayout(head)
        for what, amount in panel.lines:
            row = QHBoxLayout()
            row.addWidget(_label(what, "", wrap=True), 1)
            row.addWidget(_label(amount), 0, Qt.AlignmentFlag.AlignTop)
            box.addLayout(row)
        box.addWidget(_label(panel.body, "hint", wrap=True))


class LandConfirmDialog(QDialog):
    """Land, or Cancel. Return presses nothing; Escape cancels (decision 1)."""

    def __init__(self, plans: list[land.LandPlan], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Land")
        self.setModal(True)
        todo = [p for p in plans if not p.nothing]
        idle = [p.name for p in plans if p.nothing]
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 14)
        outer.setSpacing(10)

        title, line = headline(todo)
        self.title = _label(title, "runPercent")
        self.summary = _label(line, "", wrap=True)
        outer.addWidget(self.title)
        outer.addWidget(self.summary)

        holder = QWidget()
        cards = QVBoxLayout(holder)
        cards.setContentsMargins(0, 0, 0, 0)
        cards.setSpacing(10)
        self.cards = [RepoCard(p) for p in todo]
        for card in self.cards:
            cards.addWidget(card)
        cards.addStretch(1)
        self.scroll = QScrollArea()
        self.scroll.setWidget(holder)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(self.scroll, 1)

        self.idle = None
        if idle:
            self.idle = _label("Nothing to land in " + land._and(idle) + ".", "hint", wrap=True)
            outer.addWidget(self.idle)

        panel = land.claude_panel(todo)
        self.claude = ClaudeBox(panel) if panel else None
        if self.claude is not None:
            outer.addWidget(self.claude)

        self.details = QPlainTextEdit(details_text(todo))
        self.details.setObjectName("runLog")
        self.details.setReadOnly(True)
        self.details.setMinimumHeight(DETAILS_MIN)
        self.details.hide()
        outer.addWidget(self.details)

        outer.addWidget(_label(FOOTNOTE, "hint", wrap=True))
        buttons = QHBoxLayout()
        self.toggle = QPushButton("Show details")
        self.toggle.clicked.connect(self._toggle_details)
        self.cancel = QPushButton("Cancel")
        self.cancel.clicked.connect(self.reject)
        self.land = QPushButton("Land" if len(todo) <= 1 else f"Land {len(todo)} repos")
        self.land.setObjectName("primary")
        self.land.clicked.connect(self.accept)
        for button in (self.toggle, self.cancel, self.land):
            button.setAutoDefault(False)
            button.setDefault(False)
        buttons.addWidget(self.toggle)
        buttons.addStretch(1)
        buttons.addWidget(self.cancel)
        buttons.addWidget(self.land)
        outer.addLayout(buttons)
        self._fit()

    def _toggle_details(self) -> None:
        show = self.details.isHidden()
        self.details.setVisible(show)
        self.toggle.setText("Hide details" if show else "Show details")
        # Details takes room from the cards, and the window grows as far as the screen allows.
        self.scroll.setMinimumHeight(min(self._cards_height, CARDS_MIN_WITH_DETAILS) if show
                                     else self._cards_height)
        self.resize(self.width(), min(self.sizeHint().height(),
                                      int(self._screen_height() * WINDOW_SHARE)))

    def _screen_height(self) -> int:
        screen = self.screen()
        return screen.availableGeometry().height() if screen is not None else 900

    def _fit(self) -> None:
        """640 wide; as tall as the cards need, up to a share of the screen."""
        self.setMinimumWidth(WIDTH)
        holder = self.scroll.widget()
        # Word-wrapped labels: ask the layout for its height at the real width
        # (sizeHint ignores height-for-width; review P2-3).
        width = WIDTH - 36 - self.scroll.verticalScrollBar().sizeHint().width()
        layout = holder.layout()
        need = (layout.totalHeightForWidth(width) if layout.hasHeightForWidth()
                else holder.sizeHint().height())
        screen = self._screen_height()
        rest = self.sizeHint().height() - self.scroll.sizeHint().height()
        room = min(int(screen * SCREEN_SHARE), int(screen * WINDOW_SHARE) - rest)
        self._cards_height = min(need, max(160, room))
        self.scroll.setMinimumHeight(self._cards_height)
        self.resize(WIDTH, self.sizeHint().height())
