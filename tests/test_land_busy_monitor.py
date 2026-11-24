"""Spec land-blocker-actions §9: Close it… on the confirmation card, the live
busy line on each tile, and the Land all → Check builds order note. Real git
repos for the busy test; the close itself is replaced (the real close is
covered in test_land_blocker_actions)."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from lab_hub import land, land_resolve, launcher, repo_tidy
from ui import busy_monitor
from ui.land_confirm import CLOSE_HINT, LandConfirmDialog

from .test_land_confirm import busy_stop


def _repo(path: Path) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    (path / ".gitignore").write_text(".claude/worktrees/\n")  # as the lab's repos do
    subprocess.run(["git", "-C", str(path), "add", ".gitignore"], check=True)
    subprocess.run(["git", "-C", str(path), "-c", "user.name=t", "-c", "user.email=t@t",
                    "commit", "-q", "-m", "first"], check=True)
    return path


def _worktree(repo: Path, name: str, dirty: bool = True) -> Path:
    """A worktree; `dirty` gives it open work (an uncommitted file), so Land looks at it."""
    wt = repo / ".claude" / "worktrees" / name
    subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q", "-b", name, str(wt)],
                   check=True)
    if dirty:
        (wt / "work.txt").write_text("open work\n")
    return wt


def _dirty(path: Path) -> Path:
    (path / "wip.txt").write_text("open work\n")
    return path


# --- 9.2 the busy line (no Qt) ------------------------------------------------
def test_idle_repo_has_no_line(tmp_path):
    repo = _repo(tmp_path / "app")
    assert land.busy_now(repo, [("zsh", "1", tmp_path)]) == ""


def test_lsof_unknown_says_nothing(tmp_path):
    repo = _repo(tmp_path / "app")
    assert land.busy_now(repo, None) == ""
    assert land.busy_now(repo, []) == ""


def test_busy_worktree_is_named_with_its_processes(tmp_path):
    repo = _repo(tmp_path / "app")
    wt = _worktree(repo, "happy-dubinsky-48c27c")
    listing = [("pytest", "11", wt), ("claude", "12", wt / "src"), ("pytest", "13", wt)]
    line = land.busy_now(repo, listing, own_pid=99)
    assert line == ("Busy now: pytest and claude in worktree happy-dubinsky-48c27c. "
                    "Landing not recommended until they finish.")


def test_main_checkout_and_worktree_are_told_apart(tmp_path):
    repo = _dirty(_repo(tmp_path / "app"))
    wt = _worktree(repo, "merge-main")
    line = land.busy_now(repo, [("zsh", "1", repo), ("python3.11", "2", wt)], own_pid=99)
    assert "zsh in main checkout" in line and "python3.11 in worktree merge-main" in line
    # A process in the worktree is not also counted on the main checkout.
    assert line.count("python3.11") == 1


def test_shell_in_a_clean_checkout_is_not_busy(tmp_path):
    """Land does not stop at a worktree with no open work, so neither does the
    line: a Terminal left open in a clean checkout never 'finishes' (review P2-2)."""
    repo = _repo(tmp_path / "app")
    wt = _worktree(repo, "clean", dirty=False)
    assert land.busy_now(repo, [("zsh", "1", repo), ("zsh", "2", wt)], own_pid=99) == ""
    _dirty(repo)
    assert "zsh in main checkout" in land.busy_now(repo, [("zsh", "1", repo)], own_pid=99)


def test_lab_hub_itself_never_counts(tmp_path):
    repo = _dirty(_repo(tmp_path / "app"))
    assert land.busy_now(repo, [("Lab Hub", str(os.getpid()), repo)]) == ""


def test_line_agrees_with_lands_own_stop(tmp_path):
    """The tile line and Land's stop use the same test: busy for one is busy for both."""
    repo = _repo(tmp_path / "app")
    wt = _worktree(repo, "w")
    listing = [("pytest", "5", wt)]
    trees = repo_tidy.worktrees(repo)
    target = next(t for t in trees if t.path.name == "w")
    assert land_resolve.processes_in(target, trees, listing) == ["pytest (pid 5)"]
    assert "pytest in worktree w" in land.busy_now(repo, listing, own_pid=99)


def test_check_uses_one_listing_for_all_repos(tmp_path, monkeypatch):
    a, b = _repo(tmp_path / "a"), _dirty(_repo(tmp_path / "b"))
    calls = []
    monkeypatch.setattr(land_resolve, "cwd_listing",
                        lambda: calls.append(1) or [("zsh", "7", b)])
    got = busy_monitor.check([("a", a), ("b", b)])
    assert calls == [1]
    assert got["a"] == "" and "zsh in main checkout" in got["b"]


# --- 9.2 the monitor (Qt) -----------------------------------------------------
def _wait(cond, ms=3000):
    end = time.monotonic() + ms / 1000
    while not cond() and time.monotonic() < end:
        QTest.qWait(20)
    return cond()


def test_monitor_skips_when_nothing_to_look_at(qapp):
    looked = []
    mon = busy_monitor.BusyMonitor(lambda: None, checker=lambda r: looked.append(r) or {})
    assert mon.poll() is False and looked == []


def test_monitor_reports_off_the_ui_thread(qapp):
    got = []
    mon = busy_monitor.BusyMonitor(lambda: [("x", Path("/x"))],
                                   checker=lambda repos: {"x": "Busy now: zsh"})
    mon.updated.connect(got.append)
    assert mon.poll() is True
    assert mon.poll() is False  # one check at a time
    assert _wait(lambda: got) and got == [{"x": "Busy now: zsh"}]


def test_tile_shows_the_line_only_with_a_land_button(qapp, tmp_path, monkeypatch):
    from ui.apps_tab import AppCard

    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "none")
    card = AppCard(launcher.ExternalApp("a", "A", "a", "main.py", "s"))
    card.set_busy("Busy now: zsh in main checkout.")
    assert card.busy_line.isHidden()  # no work to land, no Land button: no line

    class Row:
        name, path, needs_attention, land_count = "a", tmp_path, True, 1
        error, badge, branch, detail = "", "1 commit to land", "main", "d"

    card.refresh_hygiene(Row())
    assert not card.busy_line.isHidden()
    assert card.busy_line.text() == "Busy now: zsh in main checkout."
    card.set_landing("Looking…")
    assert card.busy_line.isHidden()  # Land's own steps are not "busy"
    card.set_landing(None)
    card.set_busy("")
    assert card.busy_line.isHidden()


# --- 9.1 Close it… on the confirmation card -----------------------------------
def _busy_plan(tmp_path):
    wt = tmp_path / "app" / ".claude" / "worktrees" / "w"
    return land.LandPlan("app", tmp_path / "app", (), (),
                         stops=(busy_stop("app", wt, ("pytest (pid 11)", "zsh (pid 12)")),))


def _texts(widget):
    return [lab.text() for lab in widget.findChildren(QLabel)]


def test_no_button_without_a_confirm(qapp, tmp_path):
    box = LandConfirmDialog([_busy_plan(tmp_path)])
    assert box.cards[0].close_button is None
    assert CLOSE_HINT not in _texts(box)


def test_card_offers_close_it_with_the_not_recommended_line(qapp, tmp_path):
    box = LandConfirmDialog([_busy_plan(tmp_path)], confirm_close=lambda *a: False)
    card = box.cards[0]
    assert card.close_button is not None and card.close_button.text() == "Close it…"
    assert CLOSE_HINT in _texts(card)
    assert "not recommended" in CLOSE_HINT


def test_cancel_closes_nothing(qapp, tmp_path):
    closed = []
    box = LandConfirmDialog([_busy_plan(tmp_path)], confirm_close=lambda *a: False,
                            closer=lambda plan, stops: closed.append(stops) or (None, ""))
    box.cards[0].close_button.click()
    QTest.qWait(50)
    assert closed == [] and not box.closing and box.land.isEnabled()


def test_confirm_closes_then_shows_the_new_plan(qapp, tmp_path):
    plan = _busy_plan(tmp_path)
    after = land.LandPlan("app", plan.path, (repo_tidy.Action(
        "app", plan.path, "push", "main", "why", branch="main"),), ())
    asked, closed = [], []

    def closer(p, stops):
        closed.append(stops)
        return after, ""

    box = LandConfirmDialog([plan], confirm_close=lambda *a: asked.append(a) or True,
                            closer=closer)
    old = box.cards[0]
    old.close_button.click()
    assert not box.land.isEnabled()  # no Land while the close runs
    assert _wait(lambda: not box.closing)
    assert asked and asked[0][0] == "app" and len(asked[0][2]) == 1
    assert closed and closed[0] == old.busy
    assert box.cards[0] is not old and box.cards[0].plan is after
    assert box.cards[0].close_button is None
    assert box.land.isEnabled()


def test_still_running_stays_on_the_card(qapp, tmp_path):
    box = LandConfirmDialog([_busy_plan(tmp_path)], confirm_close=lambda *a: True,
                            closer=lambda p, s: (None, "zsh (pid 12) ignored the request"))
    card = box.cards[0]
    card.close_button.click()
    assert _wait(lambda: not box.closing)
    assert box.cards[0] is card and card.close_button.isEnabled()
    assert card.close_state.text() == "Still running: zsh (pid 12) ignored the request"


def test_a_new_process_is_listed_in_the_next_confirm(qapp, tmp_path):
    """Still running with a different pid: the next Close it… confirms and
    closes that one, not the one already gone (review P2-1)."""
    plan = _busy_plan(tmp_path)
    wt = plan.stops[0].target
    left = (busy_stop("app", wt, ("pytest (pid 230)",)),)
    asked = []
    box = LandConfirmDialog([plan], confirm_close=lambda *a: asked.append(a[2]) or True,
                            closer=lambda p, s: (None, "pytest (pid 230) is running", left))
    card = box.cards[0]
    card.close_button.click()
    assert _wait(lambda: not box.closing)
    card.close_button.click()
    assert _wait(lambda: not box.closing)
    assert asked[1][0].processes == ("pytest (pid 230)",)


def test_an_error_is_not_called_still_running(qapp, tmp_path):
    def boom(p, s):
        raise OSError("git failed")

    box = LandConfirmDialog([_busy_plan(tmp_path)], confirm_close=lambda *a: True, closer=boom)
    card = box.cards[0]
    card.close_button.click()
    assert not box.cancel.isEnabled()  # no Cancel that does nothing (review P3-5)
    assert _wait(lambda: not box.closing)
    assert card.close_state.text() == "Could not close: OSError: git failed"
    assert box.cancel.isEnabled()


def test_close_and_look_keeps_what_is_left(tmp_path, monkeypatch):
    from ui import land_confirm

    plan = _busy_plan(tmp_path)
    monkeypatch.setattr(land_resolve, "close_processes", lambda repo, folder, listed:
                        land_resolve.Closed(left=("pytest (pid 230)",)))
    got, why, left = land_confirm.close_and_look(plan, plan.stops)
    assert got is None and "pytest (pid 230)" in why
    assert left[0].processes == ("pytest (pid 230)",) and left[0].target == plan.stops[0].target


def test_nothing_left_moves_the_repo_to_the_idle_line(qapp, tmp_path):
    other = land.LandPlan("b", tmp_path / "b", (repo_tidy.Action(
        "b", tmp_path / "b", "push", "main", "why", branch="main"),), ())
    box = LandConfirmDialog([_busy_plan(tmp_path), other], confirm_close=lambda *a: True,
                            closer=lambda p, s: (land.LandPlan("app", p.path), ""))
    box.cards[0].close_button.click()
    assert _wait(lambda: not box.closing)
    assert [c.plan.name for c in box.cards] == ["b"]
    assert box.idle.text() == "Nothing to land in app."


def test_escape_waits_for_a_running_close(qapp, tmp_path):
    import threading
    gate = threading.Event()
    box = LandConfirmDialog([_busy_plan(tmp_path)], confirm_close=lambda *a: True,
                            closer=lambda p, s: gate.wait(5) and (None, "x"))
    box.cards[0].close_button.click()
    box.reject()
    assert box.result() == 0 and box.closing  # not closed mid-close
    gate.set()
    assert _wait(lambda: not box.closing)


# --- 9.3 the order note -------------------------------------------------------
def test_order_note_sits_with_land_all_and_check_builds(qapp, tmp_path, monkeypatch):
    from lab_hub import config
    from ui.apps_tab import ORDER_NOTE, AppsTab

    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "none")
    apps = (launcher.ExternalApp("a", "A", "a", "main.py", "s"),)
    tab = AppsTab(config.Settings(), apps, "Apps", "intro", check_builds=True)
    assert ORDER_NOTE == "Run Land all first, then Check builds."
    assert ORDER_NOTE in _texts(tab)
    buttons = {b.text(): b for b in tab.findChildren(QPushButton)}
    assert "Land all first" in buttons["Check builds"].toolTip()
    assert "Land all first" in tab.land_all_button.toolTip()
    without = AppsTab(config.Settings(), apps, "Apps", "intro")
    assert ORDER_NOTE not in _texts(without)
    QApplication.processEvents()
