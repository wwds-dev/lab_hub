"""The one confirmation before Land starts (spec land-confirm-dialog).

One card per repo (what Land will do, what only you can clear), one Claude Code
panel with one total, and Details holding today's full texts unchanged. All
words come from `lab_hub.land`; this module only lays them out. Every name,
path, branch, process and reason is plain text: they come from git and lsof.
"""

from __future__ import annotations

import threading
from pathlib import Path
from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
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

from lab_hub import land, land_resolve

from .progress_window import _label, _plain_tip

WIDTH = 640
SCREEN_SHARE = 0.7  # the cards scroll when taller than this share of the screen
WINDOW_SHARE = 0.9  # and the whole window stays within this share
DETAILS_MIN = 80  # with Details open, it and the cards share the room left,
CARDS_MIN_WITH_DETAILS = 70  # so a short screen still fits (review P2-2)
CLOSE_HINT = ("Best: wait until they finish, then Land again. Close it… ends them now "
              "(not recommended).")
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


def headline(todo: list[land.LandPlan], offered: int = 0) -> tuple[str, str]:
    """The title and the one sentence under it. `offered`: how many repo cards
    the dialog shows; with cards but none ticked, it asks for a tick."""
    if not todo:
        if offered:
            return "Nothing chosen", "Tick a repo to land it."
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


class _Head(QWidget):
    """A card's header line; a click on it toggles the card's box."""

    clicked = Signal()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if (event.button() == Qt.MouseButton.LeftButton
                and self.rect().contains(event.position().toPoint())):  # review P3-8
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class RepoCard(QFrame):
    """One repo: what Land will do, and what only you can clear. With
    `choosable`, a tick box (on) leaves the repo in or out of this Land."""

    choice_changed = Signal()
    close_requested = Signal()

    def __init__(self, plan: land.LandPlan, parent: QWidget | None = None,
                 choosable: bool = False, can_close: bool = False) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.plan = plan
        box = QVBoxLayout(self)
        box.setContentsMargins(14, 10, 14, 12)
        box.setSpacing(4)

        self.head = _Head()
        head = QHBoxLayout(self.head)
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(8)
        self.check = None
        if choosable:
            self.check = QCheckBox()
            self.check.setChecked(True)
            self.check.setAccessibleName(f"Land {plan.name}")
            self.check.setToolTip(_plain_tip(f"Untick to leave {plan.name} out of this Land"))
            self.check.toggled.connect(self._toggled)
            self.head.clicked.connect(self.check.toggle)
            head.addWidget(self.check)
        self.name = _label(plan.name, "appName")
        head.addWidget(self.name)
        self._in_pills: list[QWidget] = []
        items = plan.items
        if items:
            self._in_pills.append(_pill(_n(len(items), "step"), "ok"))
        if plan.stops:
            self._in_pills.append(_pill(f"stops at {len(plan.stops)}", "warn"))
        for pill in self._in_pills:
            head.addWidget(pill)
        self.left_out = _pill("Left out", "muted")
        self.left_out.hide()
        head.addWidget(self.left_out)
        head.addStretch(1)
        cost = plan.cost
        if cost.any:
            pill = _pill(f"Claude Code · up to {land._usd(cost.total_usd)}", "run")
            self._in_pills.append(pill)
            head.addWidget(pill)
        box.addWidget(self.head)
        self.body = QWidget()
        box.addWidget(self.body)
        box = QVBoxLayout(self.body)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)

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
        self.close_button: QPushButton | None = None
        self.busy = land.busy_stops(plan.stops) if can_close else ()
        if plan.stops:
            box.addSpacing(4)
            box.addWidget(_label("⚠  ONLY YOU CAN CLEAR", "stateWarn"))
            for stop, view in zip(plan.stops, plan.stop_views):
                where = _label(f"{view.place} · {view.problem}", "runStrong", wrap=True)
                where.setToolTip(_plain_tip(view.full))
                box.addWidget(where)
                self.stop_rows.append(where)
                if any(stop is s for s in self.busy):
                    # The card's own Close it… (spec land-blocker-actions §9.1).
                    box.addWidget(_label(CLOSE_HINT, "stateWarn", wrap=True))
                elif view.action:
                    box.addWidget(_label(view.action, "stateWarn", wrap=True))
            if self.busy:
                line = QHBoxLayout()
                self.close_state = _label("", "hint", wrap=True)
                self.close_state.hide()  # until a close runs or is held
                line.addWidget(self.close_state, 1)
                line.addStretch(0)
                self.close_button = QPushButton("Close it…")
                self.close_button.setAutoDefault(False)
                self.close_button.setToolTip(_plain_tip(
                    "Ends the processes listed above (you confirm first). Not recommended "
                    "while a test run, build or Claude Code session is still working."))
                self.close_button.clicked.connect(lambda _=False: self.close_requested.emit())
                line.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignTop)
                box.addLayout(line)

    @property
    def chosen(self) -> bool:
        return self.check is None or self.check.isChecked()

    def _toggled(self, on: bool) -> None:
        """Out: folded to its header, dimmed, "Left out" (decision 4)."""
        self.body.setVisible(on)
        for pill in self._in_pills:
            pill.setVisible(on)
        self.left_out.setVisible(not on)
        self.name.setEnabled(on)
        # The app stylesheet's text colour beats the disabled palette (review P2-1).
        self.name.setObjectName("appName" if on else "hint")
        self.name.style().unpolish(self.name)
        self.name.style().polish(self.name)
        self.setProperty("out", "false" if on else "true")
        self.style().unpolish(self)
        self.style().polish(self)
        self.choice_changed.emit()


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


def close_and_look(plan: land.LandPlan,
                   stops: tuple[land_resolve.Stop, ...]) -> tuple:
    """Close it… from a card (worker thread): close the confirmed processes
    (spec §3.2 rules), then look at the repo again. (new plan, "", ()) when the
    stops are gone, else (None, what is still running, the stops left with the
    processes still there), as `Lander._cleared` does (review P2-1)."""
    left = []
    for stop in stops:
        done = land_resolve.close_processes(plan.path, Path(stop.target), stop.processes)
        if not done.clear:
            left.append(land_resolve.Stop(plan.name, stop.target, done.reason, done.left))
    if left:
        return None, land.plain_reason(left[0].reason), tuple(left)
    return land.make_plan(plan.name, plan.path), "", ()


class LandConfirmDialog(QDialog):
    """Land, or Cancel. Return presses nothing; Escape cancels (decision 1).

    `confirm_close(name, repo, stops, parent) -> bool` asks before a card's
    Close it… ends anything; without it, cards show no Close it…. `closer` does
    the closing off the UI thread (tests replace it)."""

    def __init__(self, plans: list[land.LandPlan], parent: QWidget | None = None,
                 confirm_close: Callable[..., bool] | None = None,
                 closer: Callable[..., tuple] = close_and_look) -> None:
        super().__init__(parent)
        self._confirm_close = confirm_close
        self._closer = closer
        self._closing: tuple | None = None  # (card, [result]) while a close runs
        self._poll = QTimer(self)
        self._poll.setInterval(100)
        self._poll.timeout.connect(self._close_done)
        self.setWindowTitle("Land")
        self.setModal(True)
        todo = [p for p in plans if not p.nothing]
        idle = [p.name for p in plans if p.nothing]
        self._todo = todo
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 14)
        outer.setSpacing(10)

        title, line = headline(todo)
        self.title = _label(title, "runPercent")
        self.summary = _label(line, "", wrap=True)
        outer.addWidget(self.title)
        outer.addWidget(self.summary)

        holder = QWidget()
        self._cards_box = cards = QVBoxLayout(holder)
        cards.setContentsMargins(0, 0, 0, 0)
        cards.setSpacing(10)
        choosable = len(todo) > 1
        self.cards = [self._card(p, choosable) for p in todo]
        for card in self.cards:
            cards.addWidget(card)
        cards.addStretch(1)
        self.scroll = QScrollArea()
        self.scroll.setWidget(holder)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(self.scroll, 1)

        self._idle = idle
        self.idle = _label("", "hint", wrap=True)
        outer.addWidget(self.idle)
        self._show_idle()

        # The Claude Code box sits here; _sync replaces it as the choice changes.
        self._claude_at = outer.count()
        self._outer = outer
        self.claude = None
        panel = land.claude_panel(todo)
        if panel:
            self.claude = ClaudeBox(panel)
            outer.insertWidget(self._claude_at, self.claude)

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

    def _card(self, plan: land.LandPlan, choosable: bool) -> RepoCard:
        card = RepoCard(plan, choosable=choosable, can_close=self._confirm_close is not None)
        card.choice_changed.connect(self._sync)
        if card.close_button is not None:
            card.close_requested.connect(lambda c=card: self.close_card(c))
        return card

    def _show_idle(self) -> None:
        self.idle.setText("Nothing to land in " + land._and(self._idle) + "." if self._idle else "")
        self.idle.setVisible(bool(self._idle))

    # -- Close it… on a card (spec land-blocker-actions §9.1) -------------------
    def close_card(self, card: RepoCard) -> None:
        """Warn, then close that card's busy processes off the UI thread."""
        if self._closing is not None or self._confirm_close is None or not card.busy:
            return
        plan = card.plan
        if not self._confirm_close(plan.name, plan.path, card.busy, self):
            return
        result: list = []

        def work() -> None:
            try:
                result.append(self._closer(plan, card.busy))
            except Exception as exc:  # noqa: BLE001 - the card must say something
                result.append((None, f"{type(exc).__name__}: {exc}", None))

        self._closing = (card, result)
        card.close_button.setEnabled(False)
        card.close_state.setText("Closing, then looking at the repo again…")
        card.close_state.show()
        self._restyle(card.close_state, "hint")
        self.land.setEnabled(False)
        self.cancel.setEnabled(False)  # it would wait for the close anyway (review P3-5)
        threading.Thread(target=work, daemon=True, name="lab-hub-close-it").start()
        self._poll.start()

    @property
    def closing(self) -> bool:
        return self._closing is not None

    def _close_done(self) -> None:
        if self._closing is None or not self._closing[1]:
            return
        self._poll.stop()
        (card, result), self._closing = self._closing, None
        self.cancel.setEnabled(True)
        plan, why, left = (tuple(result[0]) + ((),))[:3]
        if plan is None:
            if left:  # the next confirm lists what is running now (review P2-1)
                card.busy = land.busy_stops(left) or card.busy
            card.close_button.setEnabled(True)
            card.close_state.setText(f"Could not close: {why}" if left is None
                                     else f"Still running: {why}")
            self._restyle(card.close_state, "stateBad")
            self._sync()
            return
        at = self.cards.index(card)
        self._cards_box.removeWidget(card)
        card.hide()
        card.deleteLater()
        if plan.nothing:
            self.cards.pop(at)
            self._idle.append(plan.name)
            self._show_idle()
        else:
            new = self._card(plan, card.check is not None)
            if card.check is not None and not card.check.isChecked():
                new.check.setChecked(False)
            self.cards[at] = new
            self._cards_box.insertWidget(at, new)
        self._sync()

    @staticmethod
    def _restyle(widget: QWidget, name: str) -> None:
        widget.setObjectName(name)
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def reject(self) -> None:  # noqa: D102 - Escape or Cancel: not while a close runs
        if self._closing is None:
            super().reject()

    def accept(self) -> None:  # noqa: D102
        if self._closing is None:
            super().accept()

    def chosen(self) -> list[land.LandPlan]:
        """The ticked repos, in plan order: what Land runs (spec land-pick-and-time)."""
        return [card.plan for card in self.cards if card.chosen]

    def _sync(self) -> None:
        """Everything that counts or sums follows the ticked repos only, so the
        Claude Code disclosure covers exactly the repos that will run."""
        chosen = self.chosen()
        title, line = headline(chosen, len(self.cards))
        self.title.setText(title)
        self.summary.setText(line)
        if self.claude is not None:
            self._outer.removeWidget(self.claude)
            self.claude.hide()
            self.claude.deleteLater()
            self.claude = None
        panel = land.claude_panel(chosen)
        if panel:
            self.claude = ClaudeBox(panel)
            self._outer.insertWidget(self._claude_at, self.claude)
        self.details.setPlainText(details_text(chosen))
        self.land.setText("Land" if len(chosen) <= 1 else f"Land {len(chosen)} repos")
        self.land.setEnabled(bool(chosen) and self._closing is None)
        self._refit()

    def _refit(self) -> None:
        """Folded cards give their room back (review P3-5)."""
        self._fit()
        if not self.details.isHidden():
            self.scroll.setMinimumHeight(min(self._cards_height, CARDS_MIN_WITH_DETAILS))

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
