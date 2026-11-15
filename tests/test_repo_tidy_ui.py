"""Resolve… and Review branches… windows, on real temporary git repos."""

from __future__ import annotations

import time

from PySide6.QtCore import Qt

from lab_hub import repo_tidy

from .test_repo_tidy import OLD, commit, lab, sh, squash_land  # noqa: F401 (fixture)


def _pump_until(predicate, timeout_s=20.0):
    from PySide6.QtWidgets import QApplication

    deadline = time.monotonic() + timeout_s
    while not predicate() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    return predicate()


def test_cleanup_applies_only_the_ticked_actions(qapp, lab, tmp_path, monkeypatch):
    from ui.repo_tidy_dialogs import CleanupDialog

    monkeypatch.setattr(repo_tidy, "log_path", lambda: tmp_path / "tidy.log")
    monkeypatch.setattr(repo_tidy.time, "time", lambda: OLD)
    squash_land(lab, "keep", "k.txt")
    squash_land(lab, "drop", "d.txt")

    dialog = CleanupDialog([("repo", lab)])
    # Two landed branches, and main is two commits ahead of origin: a push.
    assert _pump_until(lambda: dialog._list.count() == 3)
    assert dialog.apply_button.isEnabled()
    for i in range(dialog._list.count()):
        item = dialog._list.item(i)
        if "drop" not in item.text():
            item.setCheckState(Qt.CheckState.Unchecked)
    dialog.apply_button.click()
    assert _pump_until(lambda: dialog.apply_button.isHidden())

    assert dialog.changed
    branches = repo_tidy.local_branches(lab)
    assert "keep" in branches and "drop" not in branches
    assert repo_tidy.ahead_behind(lab) == (2, 0)  # the unticked push did not run
    dialog.reject()


def test_cleanup_with_nothing_safe_offers_no_apply(qapp, lab):
    from ui.repo_tidy_dialogs import CleanupDialog

    dialog = CleanupDialog([("repo", lab)])
    assert _pump_until(lambda: "Nothing is safe" in dialog._status.text())  # level, clean repo
    assert not dialog.apply_button.isEnabled()
    dialog.reject()


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


def test_the_repo_report_offers_both_buttons(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from .test_hygiene import _drop, _row, _tab, _write

    _write(tmp_path, [_row(tmp_path, "a", ["1 branch not merged into main"])])
    tab, _ = _tab(qapp, tmp_path, monkeypatch, check_builds=True)
    seen = {}
    monkeypatch.setattr(QMessageBox, "exec", lambda self: seen.update(
        labels={b.text() for b in self.buttons()}))
    tab.show_repo_report()
    assert {"Resolve…", "Review branches…", "Close"} <= seen["labels"]
    _drop(tab)


def test_cleanup_cannot_be_closed_while_applying(qapp, lab, tmp_path, monkeypatch):
    import threading

    from ui.repo_tidy_dialogs import CleanupDialog

    monkeypatch.setattr(repo_tidy, "log_path", lambda: tmp_path / "tidy.log")
    gate = threading.Event()
    real_apply = repo_tidy.apply
    monkeypatch.setattr(repo_tidy, "apply", lambda a, *k, **kw: (gate.wait(10), real_apply(a, *k, **kw))[1])
    squash_land(lab, "drop", "d.txt")
    dialog = CleanupDialog([("repo", lab)])
    assert _pump_until(lambda: dialog.apply_button.isEnabled())
    dialog.apply_button.click()
    assert not dialog.close_button.isEnabled()
    dialog.reject()
    assert dialog._applying  # the close was refused
    assert "Still applying" in dialog._status.text()
    gate.set()
    assert _pump_until(lambda: not dialog._applying)
    assert dialog.close_button.isEnabled() and dialog.changed
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
