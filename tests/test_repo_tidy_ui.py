"""The Review branches… window, on real temporary git repos."""

from __future__ import annotations

import time

import pytest

from PySide6.QtCore import Qt

from lab_hub import repo_tidy

from .test_repo_tidy import OLD, commit, lab, sh, squash_land  # noqa: F401 (fixture)


@pytest.fixture(autouse=True)
def no_real_claude(monkeypatch):
    """Never start the real Claude Code from a window test."""
    from lab_hub import claude_resolve

    monkeypatch.setattr(claude_resolve, "availability", lambda: (None, "Claude Code not found"))


def _pump_until(predicate, timeout_s=20.0):
    from PySide6.QtWidgets import QApplication

    deadline = time.monotonic() + timeout_s
    while not predicate() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    return predicate()


def test_review_deletes_a_confirmed_branch_and_reloads(qapp, lab, tmp_path, monkeypatch):
    from ui.repo_tidy_dialogs import ReviewDialog

    monkeypatch.setattr(repo_tidy, "log_path", lambda: tmp_path / "tidy.log")
    sh(lab, "checkout", "-q", "-b", "wip")
    commit(lab, "c.txt")
    sh(lab, "checkout", "-q", "main")

    dialog = ReviewDialog([("repo", lab)])
    assert _pump_until(lambda: dialog.table.rowCount() == 1)
    assert not dialog.delete_button.isEnabled()  # nothing selected yet
    dialog.table.selectRow(0)
    assert dialog.delete_button.isEnabled()
    assert not dialog.worktree_button.isEnabled()  # it has no worktree

    asked = []
    monkeypatch.setattr(dialog, "_confirm", lambda *a: asked.append(a) or True)
    dialog.delete_button.click()
    assert _pump_until(lambda: dialog.table.rowCount() == 0)
    assert "add c.txt" in asked[0][2]
    assert dialog.changed
    assert "restore with: git" in dialog._status.text()
    dialog.reject()


def test_review_keeps_delete_off_while_the_branch_has_a_worktree(qapp, lab, tmp_path):
    from ui.repo_tidy_dialogs import ReviewDialog

    sh(lab, "checkout", "-q", "-b", "wip")
    commit(lab, "c.txt")
    sh(lab, "checkout", "-q", "main")
    sh(lab, "worktree", "add", "-q", str(tmp_path / "wt"), "wip")
    (tmp_path / "wt" / "c.txt").write_text("edited")

    dialog = ReviewDialog([("repo", lab)])
    assert _pump_until(lambda: dialog.table.rowCount() == 1)
    dialog.table.selectRow(0)
    assert not dialog.delete_button.isEnabled()
    assert not dialog.worktree_button.isEnabled()  # uncommitted work in it
    assert "uncommitted" in dialog._hint.text()
    dialog.reject()


def test_review_remove_worktree_warns_about_a_recent_agent_worktree(qapp, lab, monkeypatch, tmp_path):
    from ui.repo_tidy_dialogs import ReviewDialog

    monkeypatch.setattr(repo_tidy, "log_path", lambda: tmp_path / "tidy.log")
    sh(lab, "checkout", "-q", "-b", "wip")
    commit(lab, "c.txt")
    sh(lab, "checkout", "-q", "main")
    wt = lab / ".claude" / "worktrees" / "wip"
    sh(lab, "worktree", "add", "-q", str(wt), "wip")

    dialog = ReviewDialog([("repo", lab)])
    assert _pump_until(lambda: dialog.table.rowCount() == 1)
    dialog.table.selectRow(0)
    assert dialog.worktree_button.isEnabled()
    asked = []
    monkeypatch.setattr(dialog, "_confirm", lambda *a: asked.append(a) or True)
    dialog.worktree_button.click()
    assert _pump_until(lambda: not wt.exists() and dialog.changed)
    assert "agent session may still be working" in asked[0][2]
    assert "wip" in repo_tidy.local_branches(lab)
    dialog.reject()


def test_review_fills_the_last_resolve_column(qapp, lab, tmp_path, monkeypatch):
    from ui import repo_tidy_dialogs as dialogs

    monkeypatch.setattr(repo_tidy, "log_path", lambda: tmp_path / "tidy.log")
    monkeypatch.setattr(dialogs, "last_resolve", lambda rows: {0: "2026-11-16: no Claude run"})
    sh(lab, "checkout", "-q", "-b", "wip")
    commit(lab, "c.txt")
    sh(lab, "checkout", "-q", "main")
    dialog = dialogs.ReviewDialog([("repo", lab)])
    assert _pump_until(lambda: dialog.table.rowCount() == 1)
    col = dialogs.COLUMNS.index("Last Resolve")
    assert dialog.table.horizontalHeaderItem(col).text() == "Last Resolve"
    assert dialog.table.item(0, col).text() == "2026-11-16: no Claude run"
    assert dialog.table.item(0, col).toolTip() == "2026-11-16: no Claude run"
    assert dialog.table.item(0, col - 1).text() == "none"  # the worktree column
    assert "merges nothing" not in dialog._status.text()
    dialog.reject()
