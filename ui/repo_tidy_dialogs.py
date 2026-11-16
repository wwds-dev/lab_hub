"""Review branches…: the branches Land left for the owner to decide.

Spec `docs/specs/repo-tidy.md` (sections 4, 10) and `docs/specs/land-from-tiles.md`.
The Resolve window that used to sit beside it is gone: landing is the tile's
Land button (`ui/apps_tab.py`, `lab_hub/land.py`). All git work here runs on a
worker thread (`_Background`); the window only shows results.
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from lab_hub import claude_resolve, launcher, repo_tidy

Repos = list[tuple[str, Path]]


class _Background:
    """Run one function at a time off the UI thread; call back on the UI thread."""

    def __init__(self, owner: QWidget) -> None:
        self._pool = ThreadPoolExecutor(max_workers=1)
        self._timer = QTimer(owner)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._poll)
        self._pending: list[tuple[Future, Callable]] = []

    @property
    def busy(self) -> bool:
        return bool(self._pending)

    def run(self, fn: Callable, done: Callable) -> None:
        self._pending.append((self._pool.submit(fn), done))
        self._timer.start()

    def _poll(self) -> None:
        # Drop finished work before calling back, so a callback sees `busy`
        # as it will be after it returns (and may start new work).
        finished = [(f, d) for f, d in self._pending if f.done()]
        self._pending = [(f, d) for f, d in self._pending if not f.done()]
        if not self._pending:
            self._timer.stop()
        for future, done in finished:
            exc = future.exception()
            done(None if exc else future.result(), exc)

    def shutdown(self) -> None:
        self._timer.stop()
        self._pool.shutdown(wait=False, cancel_futures=True)


def _buttons(*buttons: QPushButton) -> QHBoxLayout:
    row = QHBoxLayout()
    row.addStretch(1)
    for b in buttons:
        row.addWidget(b)
    return row


COLUMNS = ("Repo", "Branch", "Ahead", "Last commit", "Subject", "Worktree", "Last Resolve")


def last_resolve(rows: list[repo_tidy.BranchInfo]) -> dict[int, str]:
    """{row: why the last Resolve did not land it}, only while the branch is
    still at the commit that Resolve tried (section 12.4)."""
    from lab_hub import claude_resolve

    tries = claude_resolve.last_tries()
    out = {}
    for i, r in enumerate(rows):
        t = tries.get((str(r.repo), r.branch))
        if t and r.sha and (t.sha.startswith(r.sha) or r.sha.startswith(t.sha)):
            out[i] = f"{t.when[:10]}: {t.reason}"
    return out


class ReviewDialog(QDialog):
    """Every branch with unlanded work, and what you can do with one."""

    def __init__(self, repos: Repos, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Review branches")
        self.changed = False
        self._repos = repos
        self._rows: list[repo_tidy.BranchInfo] = []
        self._worktree_note: dict[int, str] = {}
        self._subjects: dict[int, list[str]] = {}
        self._recent: dict[int, bool] = {}
        self._tries: dict[int, str] = {}
        self._last = ""  # what the last action did, kept across a reload
        self._bg = _Background(self)

        layout = QVBoxLayout(self)
        self._status = QLabel("Reading branches…")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.Stretch)
        self.table.setMinimumSize(860, 360)
        self.table.itemSelectionChanged.connect(self._selection)
        layout.addWidget(self.table)
        self._hint = QLabel("")
        self._hint.setObjectName("hint")
        self._hint.setWordWrap(True)
        layout.addWidget(self._hint)

        self.terminal_button = QPushButton("Open in Terminal")
        self.terminal_button.clicked.connect(self._terminal)
        self.delete_button = QPushButton("Delete branch…")
        self.delete_button.clicked.connect(self._delete)
        self.worktree_button = QPushButton("Remove worktree…")
        self.worktree_button.clicked.connect(self._remove_worktree)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        layout.addLayout(_buttons(self.terminal_button, self.delete_button,
                                  self.worktree_button, close))
        self._selection()
        self.reload()

    # -------------------------------------------------------------- data
    def reload(self) -> None:
        repos = self._repos

        def work():
            rows = repo_tidy.unlanded(repos)
            busy = repo_tidy.busy_dirs()
            notes = {i: repo_tidy.worktree_status(r, busy) for i, r in enumerate(rows)}
            subjects = {i: repo_tidy.commit_subjects(r) for i, r in enumerate(rows)}
            recent = {i: bool(r.worktree) and repo_tidy.recent_agent_worktree(
                r.repo, Path(r.worktree)) for i, r in enumerate(rows)}
            return rows, notes, subjects, recent, last_resolve(rows)

        self._bg.run(work, self._loaded)
        self._selection()

    def _loaded(self, result, exc) -> None:
        if result is None:
            self._status.setText(f"Could not read the branches: {exc}")
            return
        self._rows, self._worktree_note, self._subjects, self._recent, self._tries = result
        self.table.setRowCount(len(self._rows))
        for i, r in enumerate(self._rows):
            tried = self._tries.get(i, "")
            for col, text in enumerate((r.repo_name, r.branch, str(r.ahead), r.date,
                                        r.subject, r.worktree or "none", tried)):
                item = QTableWidgetItem(text)
                if col == len(COLUMNS) - 1 and text:
                    item.setToolTip(text)
                self.table.setItem(i, col, item)
        self.table.resizeColumnsToContents()
        n = len(self._rows)
        summary = (
            f"{n} branch{'es' if n != 1 else ''} with work not in the default branch. "
            "Resolve… lands what it safely can; \"Last Resolve\" says why it did not "
            "land one. Open a branch in Terminal to land it by hand, or delete what you "
            "no longer want." if n else "Every branch has landed."
        )
        self._status.setText(f"{self._last}\n{summary}" if self._last else summary)
        self._selection()

    def selected(self) -> repo_tidy.BranchInfo | None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows or rows[0].row() >= len(self._rows):
            return None
        return self._rows[rows[0].row()]

    def _selection(self) -> None:
        row = self.selected()
        busy = self._bg.busy
        self.terminal_button.setEnabled(row is not None and not busy)
        self.delete_button.setEnabled(row is not None and not row.worktree and not busy)
        note = self._worktree_note.get(self._rows.index(row), "") if row else ""
        self.worktree_button.setEnabled(row is not None and bool(row.worktree)
                                        and not note and not busy)
        if row is None:
            self._hint.setText("Pick a branch.")
        elif row.worktree and note:
            self._hint.setText(f"Its worktree stays: {note}. Delete is off while it "
                               "is checked out there.")
        elif row.worktree:
            self._hint.setText("Remove the worktree first to delete the branch.")
        else:
            self._hint.setText("")

    # ----------------------------------------------------------- actions
    def _terminal(self) -> None:
        row = self.selected()
        if row is not None:
            launcher.open_terminal(row.location)

    def _confirm(self, title: str, text: str, detail: str) -> bool:
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(text)
        box.setInformativeText(detail)
        go = box.addButton(title, QMessageBox.ButtonRole.DestructiveRole)
        cancel = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)
        box.setEscapeButton(cancel)
        box.exec()
        return box.clickedButton() is go

    def _delete(self) -> None:
        row = self.selected()
        if row is None:
            return
        subjects = self._subjects.get(self._rows.index(row), [])
        more = row.ahead - len(subjects)
        detail = "\n".join(subjects + ([f"… and {more} more"] if more > 0 else []))
        detail += (f"\n\nThese {row.ahead} commit{'s' if row.ahead != 1 else ''} are not in "
                   f"{row.default}. The branch's tip is written to "
                   f"{repo_tidy.log_path()} and kept under {repo_tidy.BACKUP_PREFIX}, "
                   "so it can be restored.")
        if not self._confirm("Delete branch",
                             f"Delete {row.branch} in {row.repo_name}?", detail):
            return
        self._run(lambda: repo_tidy.delete_branch(row))

    def _remove_worktree(self) -> None:
        row = self.selected()
        if row is None:
            return
        warn = ""
        if self._recent.get(self._rows.index(row)):
            warn = (f"\n\nIt was used in the last {repo_tidy.RECENT_HOURS} hours: an "
                    "agent session may still be working in it.")
        if not self._confirm(
            "Remove worktree",
            f"Remove the worktree of {row.branch}?",
            f"{row.worktree}\n\nIt has no uncommitted, untracked or ignored files "
            f"worth keeping. The branch and its commits stay.{warn}",
        ):
            return
        self._run(lambda: repo_tidy.remove_worktree(row))

    def _run(self, fn) -> None:
        self._status.setText("Working…")
        self._bg.run(fn, lambda result, exc: self._after(
            *(result if result is not None else (False, f"failed — {exc}"))))
        self._selection()

    def _after(self, ok: bool, message: str) -> None:
        self.changed = self.changed or ok
        self._last = message[:1].upper() + message[1:]
        self._status.setText(self._last)
        self._selection()
        if ok:
            self.reload()

    def done(self, result: int) -> None:  # noqa: D401 - Qt override
        self._bg.shutdown()
        super().done(result)
