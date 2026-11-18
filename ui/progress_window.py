"""The Land and Check builds progress windows: one layout, two windows.

Spec `docs/specs/progress-windows.md` §8.6-8.8; design `progress-windows-mockup.html`.
A header (title, moving dots, last activity; percent, what is happening,
elapsed / time left / done around; the bar; counts), one row per repo or app
with its stage track, the running row opened into its steps, and the live
output folded away underneath.

The widgets decide nothing: `lab_hub.progress` holds the numbers and words, and
these render its `Snapshot`. Events only touch the model; a single-shot 100 ms
timer renders the latest snapshot (at most 10 times a second) and a 500 ms tick
moves the dots and the clocks while the window is visible and the run is live.

Everything shown that came from a repo, git, Claude Code or a build script is
plain text: labels are `Qt.TextFormat.PlainText` and output goes through
`QPlainTextEdit.appendPlainText`, after ANSI codes and control characters are
stripped (`progress.plain`).
"""

from __future__ import annotations

import html
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QEventLoop, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from lab_hub import durations, handoff, progress

from . import theme

RENDER_MS = 100
TICK_MS = 500
ICON_W, NAME_W, STATUS_W = 22, 130, 150


def _label(text: str = "", name: str = "", wrap: bool = False) -> QLabel:
    """A label that shows its text as typed: names, reasons and output are not markup."""
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    if name:
        widget.setObjectName(name)
    widget.setWordWrap(wrap)
    return widget


_TONE_NAME = {"ok": "stateOk", "run": "stateRun", "warn": "stateWarn", "bad": "stateBad",
              "muted": "hint", "wait": "hint", "": ""}


def _plain_tip(text: str) -> str:
    """A tooltip that shows `text` as typed: Qt reads a tooltip that looks
    like HTML as rich text, and app names come from apps.toml."""
    return "<qt>" + html.escape(text).replace("\n", "<br>") + "</qt>"


def _set_name(widget: QWidget, name: str) -> None:
    if widget.objectName() != name:
        widget.setObjectName(name)
        widget.style().unpolish(widget)
        widget.style().polish(widget)


def _set_prop(widget: QWidget, prop: str, value: str) -> None:
    if widget.property(prop) != value:
        widget.setProperty(prop, value)
        widget.style().unpolish(widget)
        widget.style().polish(widget)


def _set_text(widget: QLabel, text: str) -> None:
    if widget.text() != text:
        widget.setText(text)


def land_n(count: int) -> str:
    return f"{count} branch" if count == 1 else f"{count} branches"


def _clear(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item.widget() is not None:
            item.widget().hide()  # gone now, not at the next turn of the event loop
            item.widget().deleteLater()
        elif item.layout() is not None:
            _clear(item.layout())


# ----------------------------------------------------------------------
# Small painted pieces: the moving dots and a row's state icon
# ----------------------------------------------------------------------
class Dots(QWidget):
    """Three dots, one brighter in turn: the window is working, not frozen."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.phase = 0
        self.live = True
        self.setFixedSize(26, 12)

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt override)
        if not self.live:
            return
        p = theme.active()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        for i in range(3):
            colour = QColor(p.accent)
            colour.setAlphaF(1.0 if i == self.phase else 0.3)
            painter.setBrush(colour)
            lift = 2 if i == self.phase else 0
            painter.drawEllipse(QPointF(5 + i * 8, 7 - lift), 2.5, 2.5)
        painter.end()


class StateIcon(QWidget):
    """A row's or a step's state: a turning arc while it runs, else a mark."""

    def __init__(self, size: int = 16, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.kind = "waiting"
        self.phase = 0
        self.setFixedSize(size, size)

    def set_kind(self, kind: str, phase: int = 0) -> None:
        if (kind, phase if kind == "running" else 0) != (self.kind, self.phase):
            self.kind, self.phase = kind, phase if kind == "running" else 0
            self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt override)
        p = theme.active()
        colour = {"running": p.accent, "done": p.ok, "needs": p.warn, "failed": p.bad,
                  "terminal": p.warn, "skipped": p.idle}.get(self.kind, p.faint)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = self.width()
        box = QRectF(2, 2, s - 4, s - 4)
        pen = QPen(QColor(colour), 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        if self.kind == "running":
            painter.drawArc(box, -self.phase * 45 * 16, 270 * 16)
        elif self.kind == "done":
            painter.drawEllipse(box)
            painter.drawPolyline([QPointF(s * .30, s * .52), QPointF(s * .45, s * .66),
                                  QPointF(s * .70, s * .38)])
        elif self.kind in ("needs", "failed"):
            painter.drawEllipse(box)
            painter.drawLine(QPointF(s / 2, s * .28), QPointF(s / 2, s * .58))
            painter.drawPoint(QPointF(s / 2, s * .72))
        elif self.kind == "terminal":
            painter.drawRoundedRect(box, 2, 2)
            painter.drawPolyline([QPointF(s * .28, s * .38), QPointF(s * .42, s * .5),
                                  QPointF(s * .28, s * .62)])
            painter.drawLine(QPointF(s * .50, s * .66), QPointF(s * .70, s * .66))
        elif self.kind == "unknown":
            painter.drawEllipse(box)
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, "?")
        elif self.kind == "nothing":
            painter.drawLine(QPointF(s * .3, s / 2), QPointF(s * .7, s / 2))
        else:  # waiting, skipped
            painter.drawEllipse(box)
        painter.end()


# ----------------------------------------------------------------------
# Header
# ----------------------------------------------------------------------
class Header(QFrame):
    """Title, dots and last activity; percent, what is going on and the times;
    the bar; the counts; and at the end, the outcome."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("runHeader")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(theme.SPACE_L, theme.SPACE_M, theme.SPACE_L, theme.SPACE_M)
        outer.setSpacing(theme.SPACE_S)

        top = QHBoxLayout()
        self.title = _label("", "runTitle")
        self.dots = Dots()
        self.activity = _label("", "hint")
        top.addWidget(self.title)
        top.addWidget(self.dots)
        top.addStretch(1)
        top.addWidget(self.activity)
        outer.addLayout(top)
        self._outer = outer

        line = QHBoxLayout()
        line.setSpacing(theme.SPACE_S)
        self.percent = _label("", "runPercent")
        self.subtitle = _label("", "hint", wrap=True)
        self.times = _label("", "hint")
        line.addWidget(self.percent, 0, Qt.AlignmentFlag.AlignBaseline)
        line.addWidget(self.subtitle, 1, Qt.AlignmentFlag.AlignBaseline)
        line.addWidget(self.times, 0, Qt.AlignmentFlag.AlignBaseline)
        outer.addLayout(line)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        outer.addWidget(self.bar)

        self.counts = QHBoxLayout()
        self.counts.setSpacing(theme.SPACE_M + 2)
        self._count_labels: list[QLabel] = []
        outer.addLayout(self.counts)

        self.outcome = _label("", "runStrong", wrap=True)
        self.details = _label("", "hint", wrap=True)
        outer.addWidget(self.outcome)
        outer.addWidget(self.details)
        self.outcome.hide()
        self.details.hide()

    def add_below_title(self, widget: QWidget) -> None:
        """Check builds' step header sits under the title line, as in the mockup."""
        self._outer.insertWidget(1, widget)

    def draw(self, snap: progress.Snapshot, phase: int) -> None:
        _set_text(self.title, snap.title)
        self.dots.live = snap.live and snap.started
        self.dots.phase = phase % 3
        self.dots.setVisible(self.dots.live)
        self.dots.update()
        _set_text(self.activity, snap.activity)
        _set_name(self.activity, "stateWarn" if snap.stale else "hint")
        self.activity.setVisible(bool(snap.activity))

        self.percent.setVisible(snap.started)
        self.bar.setVisible(snap.started)
        self.times.setVisible(snap.started and snap.live)
        _set_text(self.percent, f"{snap.percent}%")
        self.bar.setValue(snap.percent)
        _set_text(self.subtitle, snap.subtitle)
        _set_name(self.subtitle, "hint" if snap.started else "runStrong")
        parts = [f"{snap.elapsed} elapsed"] if snap.elapsed else []
        if snap.left:
            parts.append(snap.left)
        if snap.done_around:
            parts.append(f"done around {snap.done_around}")
        _set_text(self.times, " · ".join(parts))
        _set_name(self.times, "stateWarn" if snap.overrun else "hint")

        if len(self._count_labels) != len(snap.counts):
            _clear(self.counts)
            self._count_labels = []
            for text, tone in snap.counts:
                lbl = _label(text, _TONE_NAME.get(tone, "hint"))
                self._count_labels.append(lbl)
                self.counts.addWidget(lbl)
            self.counts.addStretch(1)
        for lbl, (text, tone) in zip(self._count_labels, snap.counts):
            _set_text(lbl, text)
            _set_name(lbl, _TONE_NAME.get(tone, "hint"))

        _set_text(self.outcome, snap.outcome)
        _set_name(self.outcome, _TONE_NAME.get(snap.outcome_tone, "") or "runStrong")
        self.outcome.setVisible(bool(snap.outcome))
        _set_text(self.details, "\n".join(snap.details))
        self.details.setVisible(bool(snap.details))


# ----------------------------------------------------------------------
# Rows
# ----------------------------------------------------------------------
class StepList(QFrame):
    """The running row's steps: finished ones with their time, the running
    one with its own timer and bar, then what is still to come."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("stepList")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(theme.SPACE_M, theme.SPACE_S, theme.SPACE_M,
                                        theme.SPACE_S)
        self._layout.setSpacing(4)
        self._lines: list[tuple[StateIcon, QLabel, QProgressBar, QLabel]] = []
        self.then = _label("", "hint", wrap=True)
        self._layout.addWidget(self.then)

    def draw(self, steps: tuple[progress.StepView, ...], then: str, phase: int) -> None:
        if len(steps) != len(self._lines):
            for icon, text, bar, timer in self._lines:
                for w in (icon, text, bar, timer):
                    w.hide()
                    w.deleteLater()
            self._layout.removeWidget(self.then)
            _clear(self._layout)
            self._lines = []
            for _step in steps:
                row = QHBoxLayout()
                row.setSpacing(theme.SPACE_S)
                icon = StateIcon(14)
                col = QVBoxLayout()
                col.setSpacing(3)
                text = _label("", "", wrap=True)
                text.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
                bar = QProgressBar()
                bar.setRange(0, 1000)
                bar.setTextVisible(False)
                bar.setFixedHeight(4)
                col.addWidget(text)
                col.addWidget(bar)
                timer = _label("", "hint")
                row.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
                row.addLayout(col, 1)
                row.addWidget(timer, 0, Qt.AlignmentFlag.AlignTop)
                self._layout.addLayout(row)
                self._lines.append((icon, text, bar, timer))
            self._layout.addWidget(self.then)
        for (icon, text, bar, timer), step in zip(self._lines, steps):
            icon.set_kind({progress.FAILED: "failed", progress.SKIPPED: "skipped"}.get(
                step.state, step.state), phase)
            _set_text(text, step.label.strip())
            _set_text(timer, step.time)
            _set_name(timer, "stateRun" if step.state == progress.RUNNING else "hint")
            bar.setVisible(step.fraction is not None)
            if step.fraction is not None:
                bar.setValue(int(step.fraction * 1000))
        _set_text(self.then, then)
        self.then.setVisible(bool(then))


class Row(QFrame):
    """One repo or app: icon, name, stage track (or its verdict in words),
    status pill, a reason line, and for the running row its steps."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("runRow")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, theme.SPACE_S, 0, theme.SPACE_S)
        outer.setSpacing(4)
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(6)
        self.grid.setVerticalSpacing(3)
        self.grid.setColumnMinimumWidth(0, ICON_W)
        self.grid.setColumnMinimumWidth(1, NAME_W)
        for col in range(2, 6):
            self.grid.setColumnStretch(col, 1)
        self.grid.setColumnMinimumWidth(6, STATUS_W)
        self.icon = StateIcon(16)
        self.name = _label("", "runStrong")
        self.name.setFixedWidth(NAME_W)
        self.detail = _label("", "hint", wrap=True)
        self.pill = _label("", "runPill")
        self.pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.grid.addWidget(self.icon, 0, 0)
        self.grid.addWidget(self.name, 0, 1)
        self.grid.addWidget(self.detail, 0, 2, 1, 4)
        self.grid.addWidget(self.pill, 0, 6,
                            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        self.chips: list[QFrame] = []
        self.notes: list[QLabel] = []
        outer.addLayout(self.grid)
        self.reason = _label("", "stateWarn", wrap=True)
        self.reason.setContentsMargins(ICON_W + 6, 0, 0, 0)
        outer.addWidget(self.reason)
        self.steps = StepList()
        wrap = QHBoxLayout()
        wrap.setContentsMargins(ICON_W + 6, 4, 0, 0)
        wrap.addWidget(self.steps)
        outer.addLayout(wrap)
        self.steps.hide()

    def _build_track(self, count: int) -> None:
        for w in self.chips + self.notes:
            self.grid.removeWidget(w)
            w.hide()
            w.deleteLater()
        self.chips, self.notes = [], []
        span = 4 // count if count else 0
        for i in range(count):
            chip = QFrame()
            chip.setObjectName("stageChip")
            chip.setProperty("state", "waiting")
            note = _label("", "hint")
            self.grid.addWidget(chip, 0, 2 + i * span, 1, span)
            self.grid.addWidget(note, 1, 2 + i * span, 1, span)
            self.chips.append(chip)
            self.notes.append(note)

    def draw(self, view: progress.RowView, phase: int) -> None:
        self.icon.set_kind(view.icon, phase)
        _set_text(self.name, view.name)
        if len(view.stages) != len(self.chips):
            self._build_track(len(view.stages))
        for chip, note, stage in zip(self.chips, self.notes, view.stages):
            state = stage.state
            if state == progress.RUNNING and phase % 2:
                state = "pulse"
            _set_prop(chip, "state", state)
            chip.setToolTip(stage.label)
            text = f"{stage.label} · {stage.note}" if stage.note else stage.label
            _set_text(note, text)
            _set_name(note, {progress.DONE: "stateOk", progress.RUNNING: "stateRun",
                             progress.FAILED: "stateBad"}.get(stage.state, "hint"))
            note.setVisible(view.stage_notes)
        self.detail.setVisible(not view.stages and bool(view.detail))
        _set_text(self.detail, view.detail)
        _set_text(self.pill, view.status)
        _set_prop(self.pill, "tone", view.tone or "muted")
        self.pill.setVisible(bool(view.status))
        _set_text(self.reason, view.reason)
        _set_name(self.reason, _TONE_NAME.get(view.reason_tone, "hint") or "hint")
        self.reason.setVisible(bool(view.reason))
        self.steps.setVisible(view.expanded and bool(view.steps or view.then))
        if self.steps.isVisibleTo(self):
            self.steps.draw(view.steps, view.then, phase)


class OutputPane(QWidget):
    """The live output, folded away until asked for. Plain text only, the last
    5000 lines."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.toggle = QPushButton("▸ Live output")
        self.toggle.setObjectName("disclosure")
        self.toggle.setCheckable(True)
        self.toggle.toggled.connect(self._toggled)
        self.log = QPlainTextEdit()
        self.log.setObjectName("runLog")
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(progress.OUTPUT_KEEP)
        self.log.setMinimumHeight(120)
        self.log.setMaximumHeight(200)  # the rows keep the room
        self.log.hide()
        layout.addWidget(self.toggle, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.log)

    def _toggled(self, on: bool) -> None:
        self.toggle.setText(("▾ " if on else "▸ ") + "Live output")
        self.log.setVisible(on)

    def append(self, lines: list[str]) -> None:
        for line in lines:
            self.log.appendPlainText(line)
        if lines:
            bar = self.log.verticalScrollBar()
            bar.setValue(bar.maximum())

    def text(self) -> str:
        return self.log.toPlainText()


# ----------------------------------------------------------------------
# What both windows share
# ----------------------------------------------------------------------
class _Run:
    """The render and tick timers, and the rows. Mixed into a QWidget/QDialog."""

    def _setup_run(self, clock, wall) -> None:
        self.clock, self.wall = clock, wall
        self.model: progress.RunModel | None = None
        self.phase = 0
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(RENDER_MS)
        self._render_timer.timeout.connect(self.draw)
        self._tick = QTimer(self)
        self._tick.setInterval(TICK_MS)
        self._tick.timeout.connect(self._on_tick)
        self.renders = 0  # for tests: how many times the widgets were updated

    def _build_body(self, layout: QVBoxLayout, column_heads: tuple[str, ...] = ()) -> None:
        self.header = Header()
        layout.addWidget(self.header)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(theme.SPACE_L, theme.SPACE_S, theme.SPACE_L, 4)
        body_layout.setSpacing(0)
        if column_heads:
            heads = QGridLayout()
            heads.setHorizontalSpacing(6)
            heads.setColumnMinimumWidth(0, ICON_W)
            heads.setColumnMinimumWidth(1, NAME_W)
            heads.setColumnMinimumWidth(6, STATUS_W)
            for col in range(2, 6):
                heads.setColumnStretch(col, 1)
            for col, text in enumerate(column_heads):
                lbl = _label(text, "hint")
                if col == 6:
                    lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
                heads.addWidget(lbl, 0, col)
            body_layout.addLayout(heads)
        self._rows_box = QVBoxLayout()
        self._rows_box.setSpacing(0)
        body_layout.addLayout(self._rows_box)
        self.current_line = _label("", "hint", wrap=True)
        self.current_line.setContentsMargins(0, theme.SPACE_S, 0, 0)
        self.current_line.hide()
        body_layout.addWidget(self.current_line)
        body_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(body)
        scroll.setMinimumHeight(160)
        self.scroll = scroll
        layout.addWidget(scroll, 1)
        self.output = OutputPane()
        out_wrap = QHBoxLayout()
        out_wrap.setContentsMargins(theme.SPACE_L, 0, theme.SPACE_L, theme.SPACE_S)
        out_wrap.addWidget(self.output)
        layout.addLayout(out_wrap)
        self.rows: list[Row] = []

    def _reset_rows(self) -> None:
        for row in self.rows:
            self._rows_box.removeWidget(row)
            row.hide()
            row.deleteLater()
        self.rows = [Row() for _ in self.model.rows]
        for row in self.rows:
            self._rows_box.addWidget(row)

    def changed(self) -> None:
        """The model moved: render within 100 ms, once, if anyone can see it."""
        if self.isVisible() and not self._render_timer.isActive():
            self._render_timer.start()

    def _on_tick(self) -> None:
        # The dots and clocks move through the same throttle as events do.
        self.phase += 1
        if self.model is not None:
            self.model.dirty = True
        self.changed()

    def _sync_tick(self, snap: progress.Snapshot | None = None) -> None:
        # Nothing moves at Check builds' Review step: no tick until work starts.
        live = (self.model is not None and self.model.live and self.isVisible()
                and (snap is None or snap.started))
        if live and not self._tick.isActive():
            self._tick.start()
        elif not live:
            self._tick.stop()

    def draw(self) -> None:
        if self.model is None:
            return
        self._render_timer.stop()
        snap = self.model.snapshot()
        self.renders += 1
        self.header.draw(snap, self.phase)
        for row, view in zip(self.rows, snap.rows):
            row.draw(view, self.phase)
        _set_text(self.current_line, ("✓  " + snap.current_line + "   — newest builds")
                  if snap.current_line else "")
        self.current_line.setVisible(bool(snap.current_line))
        self.output.append(self.model.take_output())
        self._after_render(snap)
        self._sync_tick(snap)

    def _after_render(self, snap: progress.Snapshot) -> None:
        pass

    # -- Ask Claude (spec claude-handoff §9) ----------------------------------
    def _make_handoff_button(self) -> QPushButton:
        """Ask Claude…: never the default; shown only while a row qualifies."""
        button = QPushButton("Ask Claude…")
        button.setAutoDefault(False)
        button.hide()
        button.clicked.connect(lambda _=False: self.handoff_requested.emit())
        self.ask_claude_button = button
        # What Ask Claude did, where it can be read at any step (review P2-3).
        self.handoff_note = _label("", "hint", wrap=True)
        self.handoff_note.hide()
        self.handoff_paths: dict = {}  # row name -> its folder (or None)
        self.handoff_commands: dict = {}  # row name -> the command the window shows
        self._handoff_open = False  # the step allows it (Review, Done, Land's end)
        self._handoff_busy = ""  # set by the page: the job now running
        return button

    def handoff_rows(self) -> list[progress.RowView]:
        """The rows on screen that Lab Hub could not clear, in their own words."""
        if self.model is None or not self._handoff_open:
            return []
        return [r for r in self.model.snapshot().rows if handoff.qualifies(r)]

    def set_handoff_busy(self, busy: str) -> None:
        self._handoff_busy = busy
        self.refresh_handoff()

    def refresh_handoff(self) -> None:
        rows = self.handoff_rows()
        button = self.ask_claude_button
        button.setVisible(bool(rows))
        button.setEnabled(bool(rows) and not self._handoff_busy)
        if self._handoff_busy:
            tip = f"Not now: {self._handoff_busy}."
        else:
            n = len(rows)
            tip = (f"Open a Claude Code session per repo for the {n} row"
                   f"{'' if n == 1 else 's'} Lab Hub could not clear. Each session is paid; "
                   "you confirm first.")
        button.setToolTip(_plain_tip(tip))

    def show_handoff_note(self, line: str) -> None:
        """Say what Ask Claude did, under the rows, and in the live output."""
        self.handoff_note.setText(line)
        self.handoff_note.show()
        if self.model is not None:
            self.model.on_output(line)
            self.changed()

    def _shown(self) -> None:
        if self.model is not None:
            self.draw()

    def _hidden(self) -> None:
        self._render_timer.stop()
        self._tick.stop()


# ----------------------------------------------------------------------
# Land
# ----------------------------------------------------------------------
class LandWindow(QWidget, _Run):
    """Land and Land all, as it happens. Not modal: closing it only hides it
    and landing goes on; the page's Show progress brings it back."""

    stop_requested = Signal()
    handoff_requested = Signal()

    def __init__(self, parent: QWidget | None = None, *, clock=time.monotonic,
                 wall=datetime.now) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setObjectName("runWindow")  # a top-level QWidget: the theme paints it
        self.setWindowTitle("Land")
        self._setup_run(clock, wall)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        heads = ("", "Repo") + tuple(label for _k, label in progress.LAND_STAGES) + ("Status",)
        self._build_body(layout, heads)
        footer = QFrame()
        footer.setObjectName("runFooter")
        buttons = QHBoxLayout(footer)
        buttons.setContentsMargins(theme.SPACE_L, theme.SPACE_S, theme.SPACE_L, theme.SPACE_S)
        self.note = _label("Closing this window doesn't stop landing.", "hint")
        self.hide_button = QPushButton("Hide")
        self.hide_button.clicked.connect(self.close)
        self.stop_button = QPushButton("Stop landing")
        self.stop_button.setObjectName("danger")
        self.stop_button.setToolTip("End the running Claude Code or test run and skip "
                                    "everything after it. Work already landed stays landed.")
        self.stop_button.clicked.connect(self._stop)
        buttons.addWidget(self.note)
        buttons.addWidget(self._make_handoff_button())
        buttons.addWidget(self.handoff_note, 1)
        buttons.addStretch(1)  # keeps Hide and Stop right while the note is hidden
        buttons.addWidget(self.hide_button)
        buttons.addWidget(self.stop_button)
        layout.addWidget(footer)
        self.resize(720, 560)

    # -- driven by AppsTab from the Lander's signals --------------------------
    def start(self, plans) -> None:
        self.model = progress.LandModel(plans, durations.load(), clock=self.clock,
                                        wall=self.wall)
        self.results: dict[str, object] = {}
        self.handoff_paths = {progress.plain(p.name): p.path for p in plans}
        self._handoff_open = False
        self.refresh_handoff()
        self._reset_rows()
        self.stop_button.setEnabled(True)
        self.stop_button.setText("Stop landing")
        self.stop_button.show()
        self.note.setText("Closing this window doesn't stop landing.")
        self.hide_button.setText("Hide")
        self.show()
        self.raise_()
        self.draw()

    def on_progress(self, name: str, line: str) -> None:
        if self.model is None:
            return
        text = line.strip()
        if text:
            # Step labels already start with the repo's name; other lines get it.
            self.model.on_output(text if text.startswith(f"{name}: ") else f"{name}: {text}")
            self.changed()

    def on_step(self, event) -> None:
        if self.model is None:
            return
        self.model.on_step(event)
        if event.phase == "end" and event.outcome == "done":
            durations.record(durations.subject("repo", event.repo), event.kind,
                             event.at - event.started)
        self.changed()

    def on_repo_done(self, name: str, result) -> None:
        if self.model is None:
            return
        self.results[progress.plain(name)] = result
        self.model.on_repo_done(name, result)
        self.changed()

    def finish(self, results, line: str | None = None, details: tuple[str, ...] = ()) -> None:
        """The end state. Without `line`, one repo's outcome in its own words."""
        if self.model is None:
            return
        if line is None:
            if len(results) == 1:
                line = f"{results[0].name}: {results[0].line}"
            else:
                landed = sum(1 for r in results if r.state == "landed")
                line = f"Landed {landed} of {len(results)} repos."
        bad = any(r.state != "landed" for r in results)
        self.model.finish(line, "warn" if bad else "ok", details)
        self.stop_button.hide()
        self.note.setText("")
        self.hide_button.setText("Close")
        self._handoff_open = True
        self.refresh_handoff()
        if self.isVisible():
            self.draw()

    def handoff_rows(self) -> list[progress.RowView]:
        """As shown, plus a landed row's archived branches, which only its
        tile line names (spec claude-handoff §1)."""
        if self.model is None or not self._handoff_open:
            return []
        rows = []
        for view in self.model.snapshot().rows:
            result = self.results.get(view.name)
            if result is not None and getattr(result, "stopped", False):
                continue  # the owner stopped it: not Claude's to finish (review P2-1)
            archived = getattr(result, "archived", 0) if result is not None else 0
            if view.icon == "done" and archived:
                view = progress.RowView(view.name, view.icon, status=result.line,
                                        reason="kept as local archive/<branch>/<date> "
                                               "tags; Review branches can restore them")
            elif archived and handoff.qualifies(view):  # review P3-6
                view = progress.RowView(
                    view.name, view.icon, status=view.status,
                    reason=f"{view.reason} · {land_n(archived)} archived".lstrip(" ·"))
            if handoff.qualifies(view):
                rows.append(view)
        return rows

    def _stop(self) -> None:
        self.stop_requested.emit()
        self.stop_button.setEnabled(False)
        self.stop_button.setText("Stopping…")

    def showEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().showEvent(event)
        self._shown()

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().hideEvent(event)
        self._hidden()

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt override)
        return QSize(720, 560)


# ----------------------------------------------------------------------
# Check builds
# ----------------------------------------------------------------------
STEPS = ("Check", "Review", "Update", "Done")


class StepHeader(QFrame):
    """Check, Review, Update, Done: where the window is."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("runSteps")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, theme.SPACE_XS, 24, theme.SPACE_XS)
        self._marks: list[QLabel] = []
        self._names: list[QLabel] = []
        for i, name in enumerate(STEPS):
            col = QVBoxLayout()
            col.setSpacing(3)
            mark = _label(str(i + 1), "runPill")
            mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
            mark.setFixedSize(26, 22)
            label = _label(name, "hint")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            col.addWidget(mark, 0, Qt.AlignmentFlag.AlignHCenter)
            col.addWidget(label, 0, Qt.AlignmentFlag.AlignHCenter)
            layout.addLayout(col)
            if i < len(STEPS) - 1:
                line = QFrame()
                line.setFrameShape(QFrame.Shape.HLine)
                line.setObjectName("runFooter")
                layout.addWidget(line, 1, Qt.AlignmentFlag.AlignTop)
            self._marks.append(mark)
            self._names.append(label)

    def set_step(self, current: int) -> None:
        for i, (mark, name) in enumerate(zip(self._marks, self._names)):
            if i < current or (i == current == len(STEPS) - 1):
                _set_text(mark, "✓")
                _set_prop(mark, "tone", "ok")
                _set_name(name, "stateOk")
            elif i == current:
                _set_text(mark, str(i + 1))
                _set_prop(mark, "tone", "run")
                _set_name(name, "stateRun")
            else:
                _set_text(mark, str(i + 1))
                _set_prop(mark, "tone", "muted")
                _set_name(name, "hint")


class BuildCheckWindow(QDialog, _Run):
    """Check builds: the report as rows (Review), the rebuild as it happens
    (Update), and how it went (Done). Application-modal, as the box was.

    Review offers exactly the box's buttons under the same conditions; `ask()`
    returns the one pressed, and `show_build_report` does what it did before.
    Cancel stops a rebuild and keeps the window open at Done. Escape, the red
    button and `done()` close it, and end a rebuild that has not ended first:
    a build is never left running, or started, with nothing watching.
    """

    closed = Signal()
    # Copy commands on the Update step: the commands, for the page to copy.
    # A signal rather than a stored callback: a closure over the page kept on
    # this child window would free the page while the window is being deleted.
    copy_requested = Signal(list)
    handoff_requested = Signal()

    def __init__(self, view: progress.BuildCheckView, lab_root: Path | None = None,
                 parent: QWidget | None = None, *, clock=time.monotonic,
                 wall=datetime.now) -> None:
        super().__init__(parent)
        self.setWindowTitle("Check builds")
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.view = view
        self.lab_root = lab_root
        self.choice: str | None = None
        self._restart_refused = False  # Lab Hub's own build was skipped
        self._restart_built = False  # Lab Hub's own build ran and passed
        self._ask_loop: QEventLoop | None = None
        self._rebuild = None  # ui.rebuild.Rebuild, while one runs
        self._setup_run(clock, wall)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.steps = StepHeader()
        self._build_body(layout)
        self.header.add_below_title(self.steps)
        self.output.hide()

        footer = QFrame()
        footer.setObjectName("runFooter")
        self._buttons = QHBoxLayout(footer)
        self._buttons.setContentsMargins(theme.SPACE_L, theme.SPACE_S, theme.SPACE_L,
                                         theme.SPACE_S)
        layout.addWidget(footer)

        self._review: list[QPushButton] = []
        update = copy = terminal = folder = None
        if view.show_update:
            update = self._review_button("Update now")
        if view.show_copy:
            copy = self._review_button("Copy commands")
        if view.show_terminal:
            terminal = self._review_button("Copy and open Terminal")
        if view.folders:
            folder = self._review_button("Open in Terminal")
            folder.setToolTip(_plain_tip("Open a Terminal window in the project folder of "
                                         + view.folder_names))
        self.close_button = self._review_button("Close")
        self.update_button = update
        for button in (copy, terminal, folder):
            if button is not None:
                self._buttons.addWidget(button)
        self._buttons.addWidget(self._make_handoff_button())
        self._buttons.addWidget(self.handoff_note, 1)
        self._buttons.addStretch(1)  # keeps Close and Update now right
        self._buttons.addWidget(self.close_button)
        if update is not None:
            update.setObjectName("primary")
            update.setDefault(True)
            self._buttons.addWidget(update)
        else:
            self.close_button.setDefault(True)

        # The Update step's buttons: copy (stays open) and Cancel, which becomes Close.
        self.update_copy = QPushButton("Copy commands")
        self.update_copy.clicked.connect(self._copy)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("danger")
        self.cancel_button.clicked.connect(self._cancel_or_close)
        self.update_copy.hide()
        self.cancel_button.hide()
        self._buttons.insertWidget(0, self.update_copy)
        self._buttons.addWidget(self.cancel_button)

        self.model = progress.BuildModel(view, durations.load(), clock=clock, wall=wall)
        self._reset_rows()
        self.steps.set_step(1)
        self._handoff_open = True  # Review
        self.refresh_handoff()
        self.resize(720, 520)
        self.draw()

    def _copy(self) -> None:
        view = self.view
        self.copy_requested.emit(list(view.commands + view.by_hand + view.forward))

    # -- the message box's interface, which the tests and the caller use -------
    def text(self) -> str:
        return self.view.headline

    def informativeText(self) -> str:  # noqa: N802 (QMessageBox's name)
        return self.view.info

    def buttons(self) -> list[QPushButton]:
        return list(self._review)

    def _review_button(self, text: str) -> QPushButton:
        button = QPushButton(text)
        button.setAutoDefault(False)
        button.clicked.connect(lambda _=False, t=text: self._chose(t))
        self._review.append(button)
        return button

    def _chose(self, text: str) -> None:
        self.choice = None if text == "Close" else text
        if text != "Update now":
            self.done(0 if text == "Close" else 1)
        if self._ask_loop is not None:
            self._ask_loop.quit()

    def ask(self) -> str | None:
        """Show the report and wait for a Review button (or a close). Returns its
        label, or None for Close, Escape or the red button."""
        self.choice = None
        self.show()
        self.raise_()
        loop = QEventLoop()
        self._ask_loop = loop
        self.finished.connect(loop.quit)
        try:
            loop.exec()
        finally:
            self.finished.disconnect(loop.quit)
            self._ask_loop = None
        return self.choice

    # -- driven by ui.rebuild.Rebuild -----------------------------------------
    def _key(self, command: str) -> str | None:
        app = self.view.app_for(command)
        return app.key if app is not None else None

    def attach(self, rebuild) -> None:
        self._rebuild = rebuild

    def begin_update(self) -> None:
        for button in self._review:
            button.hide()
        self._handoff_open = False  # Update: the rows are still moving
        self.refresh_handoff()
        self.update_copy.setVisible(self.view.show_copy)
        self.cancel_button.setText("Cancel")
        self.cancel_button.show()
        self.cancel_button.setDefault(True)
        self.output.show()
        self.steps.set_step(2)
        self.model.start_update()
        self.draw()

    def command_started(self, command: str) -> None:
        key = self._key(command)
        if key is not None:
            self.model.start_command(key)
        self.model.on_output(f"$ {command}")
        self.changed()

    def command_held(self, command: str, reason: str | None, repeat: bool = False) -> None:
        if repeat:
            self.model.touch()
            self.changed()
            return
        key = self._key(command)
        if key is not None:
            self.model.hold(key, reason)
        if reason:
            self.model.on_output(f"[waiting — {reason}]")
        self.changed()

    def command_refused(self, command: str, reason: str) -> None:
        """A held command will not run: skipped (the run goes on) or, when its
        check failed, the end of the run."""
        key = self._key(command)
        if key is not None:
            self.model.refuse(key, reason)
        if command == getattr(self.view, "restarts", None):
            self._restart_refused = True
        self.model.on_output(f"[not run — {reason}]")
        self.changed()

    def command_output(self, command: str, line: str) -> None:
        self.model.on_build_output(self._key(command), line)
        self.changed()

    def say(self, line: str) -> None:
        self.model.on_output(line)
        self.changed()

    def command_finished(self, command: str, ok: bool, cancelled: bool = False,
                         code: int | None = 0) -> None:
        key = self._key(command)
        if key is not None:
            self.model.end_command(key, ok, cancelled, code)
        if ok and command == getattr(self.view, "restarts", None):
            self._restart_built = True
        self.changed()

    def verified(self, command: str, version: str) -> dict[str, float]:
        key = self._key(command)
        samples = self.model.verified(key, version) if key is not None else {}
        self.changed()
        return samples

    def name_for(self, command: str) -> str:
        """The app a command rebuilds, for the output and the end line."""
        app = self.view.app_for(command)
        if app is not None:
            return app.name
        return command if len(command) <= 60 else command[:59] + "…"

    def update_ended(self, how: str, failed: tuple[str, ...] = (), total: int = 0) -> None:
        line, tone = {
            "cancelled": ("Cancelled. Some apps may still be out of date.", "warn"),
            "failed": ("A rebuild failed — see the live output.", "bad"),
        }.get(how, ("Done. Every app was rebuilt and reinstalled.", "ok"))
        if how == "failed" and failed:
            # The run went on past them (spec land-update-gaps §3.2).
            names = ", ".join(self.name_for(c) for c in failed)
            total = max(total, len(failed))
            line = (f"{len(failed)} of {total} rebuild{'' if total == 1 else 's'} failed: "
                    f"{names}. See the live output.")
        restarts = getattr(self.view, "restarts", None)
        # After a failed run, only when Lab Hub's own build ran and passed.
        restart = (bool(restarts) and not self._restart_refused
                   and (how == "done" or (how == "failed" and self._restart_built)))
        if restart and how == "failed":
            line += (" Lab Hub's own build passed: it restarts to install it when you "
                     "close this window.")
        elif how == "failed" and failed and self._restart_refused:
            line += " Lab Hub itself was not rebuilt; its row says why."
        elif restart:
            line = ("Built and tested. Lab Hub restarts to install the new build "
                    "when you close this window.")
        elif how == "done" and self._restart_refused:
            line, tone = "Done. Lab Hub itself was not rebuilt; its row says why.", "warn"
        self.model.finish(line, tone)
        self.steps.set_step(3)
        self.cancel_button.setText("Close and restart" if restart else "Close")
        _set_name(self.cancel_button, "")  # nothing left to cancel: an ordinary Close
        if how == "failed":
            self.output.toggle.setChecked(True)
        self._handoff_open = True  # Done
        self.refresh_handoff()
        if self.isVisible():
            self.draw()

    def output_text(self) -> str:
        """Everything shown in the live output, including lines not yet rendered."""
        pending = self.model.take_output()
        self.output.append(pending)
        return self.output.text()

    # -- closing: every route ends a rebuild that has not ended first --------
    def _rebuild_live(self) -> bool:
        return self._rebuild is not None and not self._rebuild.ended

    def _cancel_or_close(self) -> None:
        """Cancel stops the rebuild and leaves the window at Done, its button
        now Close, so the rows and the outcome can be read (spec §2.5, §8.7)."""
        if self._rebuild_live():
            self._rebuild.cancel()
        else:
            self.reject()

    def done(self, code: int) -> None:
        # Every way of closing ends here: Escape and the red button through
        # reject(), Close, and the caller. A rebuild that has not ended is
        # cancelled first (a running build killed, or one not yet started
        # never started), so nothing runs with no window to watch it.
        if self._rebuild_live():
            self._rebuild.cancel()
        super().done(code)
        self.closed.emit()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().showEvent(event)
        self._shown()

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().hideEvent(event)
        self._hidden()
