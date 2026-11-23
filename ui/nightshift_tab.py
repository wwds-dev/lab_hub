"""Nightshift: tonight's armed run, the tasks, past runs, the track record and notices.

Reads Foundry's Nightshift state (`lab_hub.nightshift`, spec `nightshift-panel`) and runs
the owner commands through `tools/nightshift.py`. Never writes Nightshift's files itself.

Threads: every read runs on a one-shot `SnapshotReader`, every command on a
`CommandWorker`; the UI thread only renders. A command is stopped by killing its child
process, never the thread. `shutdown()` waits for both.
"""

from __future__ import annotations

import html
import signal
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QThread, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from lab_hub import config
from lab_hub import nightshift as ns
from lab_hub.tools.convert import calibre

from . import theme
from .tiles import Refreshable
from .widgets import scroll_column

POLL_MS = 5000
COMMAND_CAP_MS = 30 * 60 * 1000
STOP_GRACE_S = 20  # after SIGINT, how long the CLI gets to unload the model and clean up
SHUTDOWN_GRACE_S = 5
SHUTDOWN_WAIT_MS = 15000
OUTPUT_LIMIT = 4000  # lines kept in the output box
DASH = "—"


def _child_env() -> dict[str, str]:
    """The child's environment: PyInstaller's library paths undone, and Python's output
    unbuffered so the lines arrive as they are printed, not all at the end."""
    env = calibre.subprocess_env()
    env["PYTHONUNBUFFERED"] = "1"
    return env


# --- threads ---------------------------------------------------------------------------------------
# Threads are not parented to the page: a page destroyed while one runs (a window closed
# without shutdown()) would otherwise destroy a running QThread, which aborts the process.
# They are held here until they finish, then deleted.
_LIVE: set[QThread] = set()


def _keep(thread: QThread) -> None:
    _LIVE.add(thread)

    def done() -> None:
        _LIVE.discard(thread)
        thread.deleteLater()

    thread.finished.connect(done)


class SnapshotReader(QThread):
    """Reads the state folder once and hands back a Snapshot."""

    ready = Signal(object)

    def __init__(self, settings: config.Settings, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings

    def run(self) -> None:  # noqa: D102 - QThread override
        foundry = None
        try:
            # Finding the lab root stats the disk, so it happens here too, not on the UI thread.
            foundry = ns.locate(self._settings.resolved_lab_root())
            snap = ns.read_state(foundry)
        except Exception as error:  # noqa: BLE001 - shown on the page, never swallowed
            snap = ns.Snapshot(foundry, None, errors=(f"Could not read Nightshift's state: {error}",))
        self.ready.emit(snap)


class CommandWorker(QThread):
    """Runs one nightshift.py command, no shell, and streams its output."""

    line = Signal(str)
    done = Signal(int)  # exit code; -1 when it could not start

    def __init__(self, foundry: Path, args: list[str], python_exe: str | None = None, parent=None) -> None:
        super().__init__(parent)
        self.foundry = foundry
        self.args = args  # already through ns.command_args
        self.python_exe = python_exe
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self.killed = False
        self._grace = STOP_GRACE_S

    def kill(self, grace: float = STOP_GRACE_S) -> None:
        """Ask the CLI to stop (SIGINT, so its `finally` blocks unload the model and stop the
        server), then kill it if it is still there after `grace` seconds. The thread then ends
        on its own; it is never terminated."""
        with self._lock:
            self.killed = True
            self._grace = grace
            proc = self._proc
        if proc is not None:
            self._interrupt(proc, grace)

    @staticmethod
    def _interrupt(proc: subprocess.Popen, grace: float) -> None:
        if proc.poll() is not None:
            return
        try:
            proc.send_signal(signal.SIGINT)
        except OSError:
            return

        def hard() -> None:
            if proc.poll() is None:
                proc.kill()

        timer = threading.Timer(grace, hard)
        timer.daemon = True
        timer.start()

    def run(self) -> None:  # noqa: D102 - QThread override
        try:
            argv = [self.python_exe or ns.python() or "", str(self.foundry / "tools" / "nightshift.py"), *self.args]
            if not argv[0]:
                raise OSError("no python3 found in /opt/homebrew/bin, /usr/local/bin or /usr/bin")
            proc = subprocess.Popen(
                argv, cwd=self.foundry, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, text=True, errors="replace", env=_child_env(),
            )
        except OSError as error:
            self.line.emit(f"Could not start: {error}")
            self.done.emit(-1)
            return
        with self._lock:
            self._proc = proc
            killed, grace = self.killed, self._grace
        if killed:
            self._interrupt(proc, grace)
        assert proc.stdout is not None
        for text in proc.stdout:
            self.line.emit(text.rstrip("\n"))
        self.done.emit(proc.wait())


# --- text -----------------------------------------------------------------------------------------
def esc(value) -> str:
    if value is None or value == "":
        return DASH
    return html.escape(str(value))


def num(value, unit: str = "") -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return DASH
    return f"{value:g}{unit}"


def _items(value) -> list:
    return value if isinstance(value, list) else []


def memory_html(mem) -> str:
    if not isinstance(mem, dict):
        return "<p>Memory: not checked.</p>"
    verdict = "enough" if mem.get("ok") is True else "short" if mem.get("ok") is False else "unknown"
    out = [
        f"<p><b>Memory: {verdict}.</b> Needed {num(mem.get('need_gb'), ' GB')} "
        f"(model {esc(mem.get('model'))}, file {num(mem.get('file_gb'), ' GB')}, "
        f"context cache {num(mem.get('cache_gb'), ' GB')}, buffer {num(mem.get('buffer_gb'), ' GB')}); "
        f"available {num(mem.get('available_gb'), ' GB')}; "
        f"compressed {num(_round(mem.get('compressor_gb')), ' GB')}, swap {num(_round(mem.get('swap_used_gb')), ' GB')}"
        + (f"; short by {num(mem.get('short_gb'), ' GB')}" if isinstance(mem.get("short_gb"), (int, float)) and mem.get("short_gb") else "")
        + ".</p>"
    ]
    if mem.get("why"):
        out.append(f"<p>{esc(mem.get('why'))}</p>")
    close = [c for c in _items(mem.get("close")) if isinstance(c, list) and len(c) == 2]
    if close:
        apps = ", ".join(f"{esc(name)} ({num(gb, ' GB')})" for name, gb in close)
        out.append(f"<p>Apps to close: {apps}.</p>")
    return "".join(out)


def _round(value):
    return round(value, 1) if isinstance(value, (int, float)) and not isinstance(value, bool) else value


def gate_html(prestart) -> str:
    """The pre-start gate as the run record holds it."""
    if not isinstance(prestart, dict):
        return "<p>No pre-start gate recorded.</p>"
    out = []
    if "ok" in prestart:
        out.append(f"<p><b>Gate: {'passed' if prestart.get('ok') is True else 'blocked'}.</b></p>")
    out.append(memory_html(prestart.get("memory")))
    load = prestart.get("load")
    if isinstance(load, dict):
        out.append(f"<p><b>Task load:</b> {esc(load.get('why'))} "
                   f"({num(load.get('total_min'), ' min')} of {num(load.get('window_min'), ' min')}).</p>")
    preds = prestart.get("predictions")
    if isinstance(preds, dict) and preds:
        rows = []
        for tid, p in preds.items():
            if not isinstance(p, dict):
                rows.append(f"<li>{esc(tid)}: unreadable prediction</li>")
                continue
            q3 = " · <b>lossy quant (Q3)</b>" if p.get("lossy_quant") else ""
            reasons = "".join(f"<li>{esc(r)}</li>" for r in _items(p.get("reasons")))
            hints = "".join(f"<li>Fix: {esc(h)}</li>" for h in _items(p.get("hints")))
            rows.append(f"<li><b>{esc(tid)}</b>: predicted {esc(p.get('band'))} {num(p.get('score'))}"
                        f"{'' if p.get('armable', True) else ' · cannot be armed'}{q3}"
                        f"<ul>{reasons}{hints}</ul></li>")
        out.append("<p><b>Per task</b></p><ul>" + "".join(rows) + "</ul>")
    blockers, warnings = _items(prestart.get("blockers")), _items(prestart.get("warnings"))
    if blockers:
        out.append("<p><b>Blockers</b></p><ul>" + "".join(f"<li>{esc(b)}</li>" for b in blockers) + "</ul>")
    if warnings:
        out.append("<p><b>Warnings</b></p><ul>" + "".join(f"<li>{esc(w)}</li>" for w in warnings) + "</ul>")
    return "".join(out)


def window_text(window) -> str:
    if not isinstance(window, dict):
        return DASH
    return (f"{esc(window.get('start'))} to {esc(window.get('end'))}, "
            f"memory re-check {esc(window.get('recheck'))}")


def tonight_html(snap: ns.Snapshot) -> str:
    out = []
    if snap.stops:
        names = {"STOP_AFTER_TASK": "stop after the running task", "STOP_NOW": "stop now"}
        out.append("<p><b>Stop requested:</b> " + ", ".join(names.get(s, s) for s in snap.stops) + ".</p>")
    if snap.armed is None:
        latest = next((r for r in snap.runs if isinstance(r, ns.Run)), None)
        # Nightshift removes armed.json when the night starts, so a running night is found here.
        if latest is not None and latest.get("state") == "running":
            tasks = ", ".join(esc(t) for t in _items(latest.get("tasks"))) or DASH
            out.append(f"<p><b>Running now:</b> run {esc(latest.run_id)}, started {esc(latest.get('started'))}. "
                       f"Tasks: {tasks}. Window: {window_text(latest.get('window'))}.</p>")
            out.append(gate_html(latest.get("prestart")))
            return "".join(out)
        out.append("<p><b>Nothing armed for tonight.</b></p>")
        if latest is not None and latest.get("prestart") is not None:
            out.append(f"<p>Latest gate, from run {esc(latest.run_id)} ({esc(latest.get('state'))}"
                       f"{', dry run' if latest.get('dry_run') else ''}):</p>")
            out.append(gate_html(latest.get("prestart")))
        return "".join(out)
    if isinstance(snap.armed, ns.Unreadable):
        out.append(f"<p><b>armed.json is unreadable:</b> {esc(snap.armed.reason)}</p>")
        return "".join(out)
    run = snap.armed_run
    out.append(f"<p><b>Armed:</b> run {esc(snap.armed.get('run_id'))}, armed {esc(snap.armed.get('armed_at'))}.</p>")
    if isinstance(run, ns.Unreadable):
        out.append(f"<p><b>Its run record is unreadable:</b> {esc(run.reason)}</p>")
        return "".join(out)
    if run is None:
        return "".join(out)
    tasks = ", ".join(esc(t) for t in _items(run.get("tasks"))) or DASH
    out.append(f"<p>State {esc(run.get('state'))}. Tasks: {tasks}. Window: {window_text(run.get('window'))}.</p>")
    out.append(gate_html(run.get("prestart")))
    recheck = run.get("recheck")
    if isinstance(recheck, dict):
        out.append(f"<p><b>Re-check at {esc(recheck.get('ts'))}</b></p>" + memory_html(recheck))
    return "".join(out)


def abort_text(abort) -> str:
    if not isinstance(abort, dict):
        return ""
    return f"{abort.get('rule') or '?'}: {abort.get('why') or ''}".strip()


def _grade(value) -> str:
    if not isinstance(value, dict):
        return DASH
    return f"{value.get('band') or DASH} {num(value.get('score'))}"


def task_row(rec: ns.TaskRecord | ns.Unreadable) -> list[str]:
    if isinstance(rec, ns.Unreadable):
        return [rec.path.parent.name, "unreadable", rec.reason] + [""] * 8
    settings = rec.get("settings") if isinstance(rec.get("settings"), dict) else {}
    quant = settings.get("quant") or DASH
    if settings.get("lossy_quant"):
        quant = f"{quant} (lossy)"
    verdict = rec.get("verdict")
    verdict_text = verdict.get("verdict") if isinstance(verdict, dict) else ""
    return [
        rec.get("task_id"),
        rec.get("status"),
        _grade(rec.get("result")),
        _grade(rec.get("prediction")),
        num(rec.get("gap")),
        num(rec.get("retries")),
        settings.get("model") or DASH,
        quant,
        rec.get("branch") or DASH,
        verdict_text or DASH,
        rec.get("status_reason") or "",
    ]


TASK_COLUMNS = ("Task", "Status", "Grade", "Predicted", "Gap", "Retries", "Model", "Quant", "Branch",
                "Verdict", "Reason")


def run_label(run: ns.Run | ns.Unreadable) -> list[str]:
    if isinstance(run, ns.Unreadable):
        return [run.path.parent.name, "unreadable", "", "", run.reason]
    return [run.run_id, run.get("state"), "yes" if run.get("dry_run") else "",
            str(len(_items(run.get("tasks")))), abort_text(run.get("abort"))]


RUN_COLUMNS = ("Run", "State", "Dry run", "Tasks", "Abort")
TASK_SPEC_COLUMNS = ("", "Task", "Title", "Type", "App", "Estimate", "Approved")
def track_rule_text(cfg: dict) -> str:
    w, a, d = cfg.get("window"), cfg.get("allowed"), cfg.get("daytime_below")
    return (f"Per task type over the last {w} results with a verdict: {a} or more accepted is Allowed, "
            f"under {d} is daytime only, in between is Watch. With fewer than {w} it is Building, or "
            f"daytime only once it can no longer reach {d}.")


TRACK_LABELS = {"allowed": "Allowed", "building": "Building", "watch": "Watch", "daytime_only": "Daytime only"}


def _table(columns) -> QTableWidget:
    table = QTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels(list(columns))
    table.verticalHeader().hide()
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    table.horizontalHeader().setStretchLastSection(True)
    table.setMinimumHeight(120)
    return table


def _fill(table: QTableWidget, rows: list[list[str]]) -> None:
    table.setRowCount(len(rows))
    table.setVisible(bool(rows))  # an empty table says nothing; the note under it does
    for r, row in enumerate(rows):
        for c, text in enumerate(row):
            item = QTableWidgetItem("" if text is None else str(text))
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(r, c, item)


def _rich(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.RichText)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


# --- the page -------------------------------------------------------------------------------------
class NightshiftTab(QWidget, Refreshable):
    """The Nightshift page under Tools."""

    command_finished = Signal(object)  # exit code

    def __init__(self, settings: config.Settings, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.snapshot: ns.Snapshot | None = None
        self._reader: SnapshotReader | None = None
        self._read_again = False
        self.worker: CommandWorker | None = None
        self._ticked: set[str] = set()
        self._selected_run: str | None = None
        # Hooks the tests replace: asking before a command, and opening a file.
        self.confirm: Callable[[str, str], bool] = self._ask
        self.open_file: Callable[[Path], None] = lambda p: QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))
        self.python_exe: str | None = None
        self._foundry: Path | None = None  # from the last snapshot; found off the UI thread
        self.last_exit: int | None = None

        area, column = scroll_column()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(area)

        # Commands
        head, head_layout = theme.card()
        head_layout.addWidget(theme.section_title("Nightshift"))
        head_layout.addWidget(theme.hint(
            "A local model works through tasks you approved, at night, each on its own branch. "
            "This page reads what Nightshift wrote and runs its owner commands; it changes nothing itself."
        ))
        self.where = theme.hint("")
        head_layout.addWidget(self.where)
        row1, row2 = QHBoxLayout(), QHBoxLayout()
        self.plan_button = self._button(row1, "Plan ticked", lambda: self.run_command("plan", *self.ticked()))
        self.arm_button = self._button(row1, "Arm ticked", self._arm)
        self.disarm_button = self._button(row1, "Disarm", self._disarm)
        self.dry_button = self._button(row1, "Dry run", lambda: self.run_command("dry-run"))
        row1.addStretch(1)
        self.stop_after_button = self._button(row2, "Stop after this task", lambda: self.run_command("stop", "--after"))
        self.stop_now_button = self._button(row2, "Stop now", self._stop_now)
        self.stop_clear_button = self._button(row2, "Clear stop", lambda: self.run_command("stop", "--clear"))
        self.cancel_button = self._button(row2, "Cancel command", self.cancel_command)
        self.cancel_button.setEnabled(False)
        row2.addStretch(1)
        head_layout.addLayout(row1)
        head_layout.addLayout(row2)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setMaximumBlockCount(OUTPUT_LIMIT)
        self.output.setPlaceholderText("Command output appears here.")
        self.output.setMinimumHeight(140)
        head_layout.addWidget(self.output)
        self.exit_label = theme.hint("")
        head_layout.addWidget(self.exit_label)
        column.addWidget(head)

        # Tonight
        card, layout = theme.card()
        layout.addWidget(theme.section_title("Tonight"))
        self.tonight = _rich()
        layout.addWidget(self.tonight)
        column.addWidget(card)

        # Tasks
        card, layout = theme.card()
        layout.addWidget(theme.section_title("Tasks"))
        layout.addWidget(theme.hint("Tick tasks for Plan and Arm. Only you set approved = true in a task file."))
        self.tasks_table = _table(TASK_SPEC_COLUMNS)
        self.tasks_table.itemChanged.connect(self._tick_changed)
        layout.addWidget(self.tasks_table)
        self.tasks_empty = theme.hint("")
        layout.addWidget(self.tasks_empty)
        column.addWidget(card)

        # Runs
        card, layout = theme.card()
        layout.addWidget(theme.section_title("Runs"))
        self.runs_table = _table(RUN_COLUMNS)
        self.runs_table.itemSelectionChanged.connect(self._run_selected)
        layout.addWidget(self.runs_table)
        self.runs_empty = theme.hint("")
        layout.addWidget(self.runs_empty)
        self.run_detail = _rich()
        layout.addWidget(self.run_detail)
        self.run_tasks = _table(TASK_COLUMNS)
        self.run_tasks.itemSelectionChanged.connect(self._update_task_buttons)
        layout.addWidget(self.run_tasks)
        files = QHBoxLayout()
        self.morning_button = self._button(files, "Open MORNING.md", self._open_morning)
        self.file_buttons = {
            name: self._button(files, f"Open {name}", lambda _=False, n=name: self._open_task_file(n))
            for name in ns.TASK_FILES
        }
        files.addStretch(1)
        layout.addLayout(files)
        verdict = QHBoxLayout()
        self.note = QLineEdit()
        self.note.setPlaceholderText("Note for the verdict (optional)")
        verdict.addWidget(self.note, 1)
        self.accept_button = self._button(verdict, "Accept", lambda: self._verdict("accept"))
        self.reject_button = self._button(verdict, "Reject", lambda: self._verdict("reject"))
        layout.addLayout(verdict)
        column.addWidget(card)

        # Track record
        card, layout = theme.card()
        layout.addWidget(theme.section_title("Track record"))
        self.track_rule = theme.hint(track_rule_text(dict(ns.TRACK_DEFAULTS)))
        layout.addWidget(self.track_rule)
        self.track_table = _table(("Type", "Status", "Accepted", "Mean gap"))
        layout.addWidget(self.track_table)
        self.track_note = theme.hint("")
        layout.addWidget(self.track_note)
        column.addWidget(card)

        # Notices
        card, layout = theme.card()
        layout.addWidget(theme.section_title("Notices"))
        self.notices_table = _table(("Time", "Kind", "Run", "Message"))
        layout.addWidget(self.notices_table)
        self.notices_note = theme.hint("")
        layout.addWidget(self.notices_note)
        column.addWidget(card)
        column.addStretch(1)

        self.timer = QTimer(self)
        self.timer.setInterval(POLL_MS)
        self.timer.timeout.connect(self.refresh)
        self.cap = QTimer(self)
        self.cap.setSingleShot(True)
        self.cap.setInterval(COMMAND_CAP_MS)
        self.cap.timeout.connect(self._over_cap)
        self._update_buttons()

    # --- plumbing ---------------------------------------------------------------------------------
    def _button(self, row: QHBoxLayout, text: str, slot) -> QPushButton:
        button = QPushButton(text)
        button.clicked.connect(slot)
        row.addWidget(button)
        return button

    def _ask(self, title: str, text: str) -> bool:
        answer = QMessageBox.question(self, title, text)
        return answer == QMessageBox.StandardButton.Yes

    def foundry(self) -> Path | None:
        """The Foundry folder as the last read found it (no disk access here)."""
        return self._foundry

    def apply_settings(self, settings: config.Settings) -> None:
        self.settings = settings
        self._foundry = None
        self.snapshot = None
        self._update_buttons()
        self.refresh()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        self.timer.start()
        self.read_now()

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().hideEvent(event)
        self.timer.stop()

    # --- reading ----------------------------------------------------------------------------------
    def refresh(self) -> None:
        """Look again, but only while the page is on screen (the poll, Refresh, a command)."""
        if self.isVisible():
            self.read_now()

    def read_now(self) -> None:
        """Start a read off the UI thread; a read already going is not doubled."""
        if self._reader is not None:
            self._read_again = True
            return
        self._reader = SnapshotReader(self.settings)
        self._reader.ready.connect(self.show_snapshot)
        self._reader.finished.connect(self._reader_done)
        _keep(self._reader)
        self._reader.start()

    def _reader_done(self) -> None:
        self._reader = None
        if self._read_again:
            self._read_again = False
            self.read_now()

    def show_snapshot(self, snap: ns.Snapshot) -> None:
        if snap == self.snapshot:
            return
        self.snapshot = snap
        self._foundry = snap.foundry
        if snap.errors:
            self.where.setText(" ".join(snap.errors))
        elif snap.foundry is None:
            lab_root = self.settings.lab_root or "the lab root"
            self.where.setText(f"No Foundry folder with tools/nightshift.py under {lab_root}.")
        elif not snap.exists:
            self.where.setText(f"Nightshift has written nothing yet: no {snap.state}.")
        else:
            self.where.setText(f"Reading {snap.state}")
        self.tonight.setText(tonight_html(snap) if snap.exists else "<p>Nothing to show yet.</p>")
        self._show_tasks(snap)
        self._show_runs(snap)
        self._show_track(snap)
        self._show_notices(snap)
        self._update_buttons()

    def _show_tasks(self, snap: ns.Snapshot) -> None:
        table = self.tasks_table
        table.blockSignals(True)
        table.setRowCount(len(snap.tasks))
        known = set()
        for r, spec in enumerate(snap.tasks):
            tick = QTableWidgetItem()
            if isinstance(spec, ns.Unreadable):
                tick.setFlags(Qt.ItemFlag.NoItemFlags)
                cells = [spec.path.stem, f"unreadable: {spec.reason}", "", "", "", ""]
            else:
                known.add(spec.task_id)
                tick.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
                tick.setCheckState(Qt.CheckState.Checked if spec.task_id in self._ticked else Qt.CheckState.Unchecked)
                tick.setData(Qt.ItemDataRole.UserRole, spec.task_id)
                cells = [spec.task_id, spec.title or DASH, spec.task_type or DASH, spec.app or DASH,
                         num(spec.estimate_min, " min"), "yes" if spec.approved else "no"]
            table.setItem(r, 0, tick)
            for c, text in enumerate(cells, start=1):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(r, c, item)
        self._ticked &= known
        table.setVisible(bool(snap.tasks))
        table.blockSignals(False)
        if not snap.exists:
            self.tasks_empty.setText("")
        else:
            self.tasks_empty.setText("" if snap.tasks else "No task files in tasks/ yet. You write them; see Foundry's docs/nightshift.md.")

    def _tick_changed(self, item: QTableWidgetItem) -> None:
        task_id = item.data(Qt.ItemDataRole.UserRole)
        if item.column() != 0 or not task_id:
            return
        if item.checkState() == Qt.CheckState.Checked:
            self._ticked.add(task_id)
        else:
            self._ticked.discard(task_id)
        self._update_buttons()

    def ticked(self) -> list[str]:
        order = [s.task_id for s in (self.snapshot.tasks if self.snapshot else ()) if isinstance(s, ns.TaskSpec)]
        return [t for t in order if t in self._ticked]

    def tick(self, *task_ids: str) -> None:
        """Tick tasks by id (what clicking the boxes does)."""
        for r in range(self.tasks_table.rowCount()):
            item = self.tasks_table.item(r, 0)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) in task_ids:
                item.setCheckState(Qt.CheckState.Checked)

    def _show_runs(self, snap: ns.Snapshot) -> None:
        keep = self._selected_run
        self.runs_table.blockSignals(True)
        _fill(self.runs_table, [run_label(r) for r in snap.runs])
        self.runs_table.blockSignals(False)
        self.runs_empty.setText("" if snap.runs or not snap.exists else "No runs yet.")
        ids = [r.run_id if isinstance(r, ns.Run) else r.path.parent.name for r in snap.runs]
        row = ids.index(keep) if keep in ids else (0 if ids else -1)
        if row >= 0:
            self.runs_table.selectRow(row)
        self._run_selected()

    def selected_run(self) -> ns.Run | ns.Unreadable | None:
        if not self.snapshot:
            return None
        rows = self.runs_table.selectionModel().selectedRows()
        if not rows or rows[0].row() >= len(self.snapshot.runs):
            return None
        return self.snapshot.runs[rows[0].row()]

    def select_run(self, run_id: str) -> None:
        for r in range(self.runs_table.rowCount()):
            if self.runs_table.item(r, 0).text() == run_id:
                self.runs_table.selectRow(r)
                return

    def _run_selected(self) -> None:
        run = self.selected_run()
        self._selected_run = None if run is None else (run.run_id if isinstance(run, ns.Run) else run.path.parent.name)
        if run is None:
            self.run_detail.setText("")
            _fill(self.run_tasks, [])
        elif isinstance(run, ns.Unreadable):
            self.run_detail.setText(f"<p><b>Unreadable run record</b> {esc(run.path)}: {esc(run.reason)}</p>")
            _fill(self.run_tasks, [])
        else:
            parts = [f"<p><b>{esc(run.run_id)}</b>: {esc(run.get('state'))}"
                     f"{' (dry run)' if run.get('dry_run') else ''}; started {esc(run.get('started'))}, "
                     f"finished {esc(run.get('finished'))}.</p>"]
            if abort_text(run.get("abort")):
                parts.append(f"<p><b>Aborted:</b> {esc(abort_text(run.get('abort')))}</p>")
            checks = [c for c in _items(run.get("checks")) if isinstance(c, dict)]
            if checks:
                parts.append("<p><b>Dry-run checks</b></p><ul>" + "".join(
                    f"<li>{'pass' if c.get('ok') else 'FAIL'}: {esc(c.get('name'))}"
                    f"{' (' + esc(c.get('detail')) + ')' if c.get('detail') else ''}</li>" for c in checks) + "</ul>")
            if not run.tasks:
                parts.append("<p>No task records in this run.</p>")
                if run.get("prestart") is not None:
                    parts.append(gate_html(run.get("prestart")))
            self.run_detail.setText("".join(parts))
            _fill(self.run_tasks, [task_row(t) for t in run.tasks])
        self._update_task_buttons()

    def selected_task(self) -> ns.TaskRecord | None:
        run = self.selected_run()
        if not isinstance(run, ns.Run):
            return None
        rows = self.run_tasks.selectionModel().selectedRows()
        if not rows or rows[0].row() >= len(run.tasks):
            return None
        rec = run.tasks[rows[0].row()]
        return rec if isinstance(rec, ns.TaskRecord) else None

    def select_task(self, task_id: str) -> None:
        for r in range(self.run_tasks.rowCount()):
            if self.run_tasks.item(r, 0).text() == task_id:
                self.run_tasks.selectRow(r)
                return

    def _show_track(self, snap: ns.Snapshot) -> None:
        self.track_rule.setText(track_rule_text(snap.track_cfg))
        _fill(self.track_table, [
            [t["task_type"], TRACK_LABELS.get(t["status"], t["status"]), f"{t['accepted']} of {t['total']}",
             num(t["mean_gap"])] for t in snap.track
        ])
        note = "" if snap.track or not snap.exists else "No graded tasks yet."
        if snap.track_unreadable:
            note += f" {snap.track_unreadable} line(s) of track.jsonl are unreadable."
        self.track_note.setText(note.strip())

    def _show_notices(self, snap: ns.Snapshot) -> None:
        _fill(self.notices_table, [[n.ts or DASH, n.kind or DASH, n.run_id or DASH, n.message or DASH]
                                   for n in snap.notices])
        note = "" if snap.notices or not snap.exists else "No notices."
        if snap.notices_unreadable:
            note += f" {snap.notices_unreadable} line(s) of notices.jsonl are unreadable."
        self.notices_note.setText(note.strip())

    # --- buttons ----------------------------------------------------------------------------------
    def is_running(self) -> bool:
        return self.worker is not None

    def _update_buttons(self) -> None:
        ready = self.foundry() is not None and not self.is_running()
        ticked = bool(self._ticked)
        self.plan_button.setEnabled(ready and ticked)
        self.arm_button.setEnabled(ready and ticked)
        for button in (self.disarm_button, self.dry_button, self.stop_after_button, self.stop_now_button,
                       self.stop_clear_button):
            button.setEnabled(ready)
        self.cancel_button.setEnabled(self.is_running())
        self._update_task_buttons()

    def _update_task_buttons(self) -> None:
        run = self.selected_run()
        self.morning_button.setEnabled(isinstance(run, ns.Run) and run.morning is not None)
        rec = self.selected_task()
        for name, button in self.file_buttons.items():
            button.setEnabled(rec is not None and name in rec.files)
        # Only a task that finished on its branch, in a night that is over: a failed task is
        # already rejected by Nightshift, and accepting it would count against the track rule.
        can_judge = (rec is not None and rec.get("status") == "done" and isinstance(run, ns.Run)
                     and not run.get("dry_run") and run.get("state") in ("finished", "aborted")
                     and self.foundry() is not None and not self.is_running())
        self.accept_button.setEnabled(can_judge)
        self.reject_button.setEnabled(can_judge)

    def _open_morning(self) -> None:
        run = self.selected_run()
        if isinstance(run, ns.Run) and run.morning is not None:
            self.open_file(run.morning)

    def _open_task_file(self, name: str) -> None:
        rec = self.selected_task()
        if rec is not None and name in rec.files:
            self.open_file(rec.files[name])

    def _arm(self) -> None:
        tasks = self.ticked()
        if self.confirm("Arm tonight", f"Arm Nightshift for tonight with: {', '.join(tasks)}?\n"
                                       "The pre-start gate runs first; nothing is armed if it fails."):
            self.run_command("arm", *tasks)

    def _disarm(self) -> None:
        if self.confirm("Disarm", "Disarm tonight's run?"):
            self.run_command("disarm")

    def _stop_now(self) -> None:
        if self.confirm("Stop now", "Stop the night now? The running task is reverted."):
            self.run_command("stop", "--now")

    def _verdict(self, verdict: str) -> None:
        run, rec = self.selected_run(), self.selected_task()
        if not isinstance(run, ns.Run) or rec is None:
            return
        if verdict == "reject" and not self.confirm(
                "Reject", f"Reject {rec.get('task_id')} of run {run.run_id}? It counts against the track record."):
            return
        if self.run_command("verdict", run.run_id, rec.get("task_id"), verdict, note=self.note.text().strip()):
            self.note.clear()

    # --- commands ---------------------------------------------------------------------------------
    def run_command(self, sub: str, *args: str, note: str = "") -> bool:
        """Start `nightshift.py <sub> <args>` off the UI thread. False if refused or busy."""
        if self.is_running():
            return False
        foundry = self.foundry()
        if foundry is None:
            self.exit_label.setText("No Foundry folder with Nightshift was found.")
            return False
        try:
            cli_args = ns.command_args(sub, *args, note=note)
        except ns.Refused as error:
            self.exit_label.setText(f"Not run: {error}")
            return False
        self.output.clear()
        self.output.appendPlainText("$ nightshift.py " + " ".join(cli_args))
        self.exit_label.setText("Running…")
        self.worker = CommandWorker(foundry, cli_args, self.python_exe)
        _keep(self.worker)
        self.worker.line.connect(self.output.appendPlainText)
        self.worker.done.connect(self._command_done)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()
        self.cap.start()
        self._update_buttons()
        return True

    def _command_done(self, code: int) -> None:
        self.last_exit = code
        killed = self.worker is not None and self.worker.killed
        self.exit_label.setText(f"exit {code}" + (" (cancelled)" if killed else ""))
        self.output.appendPlainText(f"exit {code}")

    def _worker_finished(self) -> None:
        self.worker = None
        self.cap.stop()
        self._update_buttons()
        self.read_now()
        self.command_finished.emit(self.last_exit)

    def cancel_command(self) -> None:
        if self.worker is not None:
            self.worker.kill()

    def _over_cap(self) -> None:
        if self.worker is not None:
            self.output.appendPlainText(f"Stopped after {COMMAND_CAP_MS // 60000} minutes.")
            self.worker.kill()

    def busy_reason(self) -> str | None:
        return "A Nightshift command is running" if self.is_running() else None

    def shutdown(self) -> None:
        """Stop polling, end a running command's child and wait for both threads."""
        self.timer.stop()
        self.cap.stop()
        if self.worker is not None:
            self.worker.kill(SHUTDOWN_GRACE_S)
            self.worker.wait(SHUTDOWN_WAIT_MS)
        if self._reader is not None:
            self._reader.wait(SHUTDOWN_WAIT_MS)
