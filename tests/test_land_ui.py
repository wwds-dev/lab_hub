"""Land on the tiles and the page, on real temporary git repos.

Spec `docs/specs/land-from-tiles.md`: success measures 1-7. The confirmation
box is replaced (it blocks); everything else, the worker thread included, runs
for real. A step Claude Code or a repo's tests would decide is replaced at
`repo_tidy.apply`, as in `test_land.py`.
"""

from __future__ import annotations

import re

import threading
import time

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

from lab_hub import config, launcher, land, repo_tidy
from lab_hub.land import LandResult

from .test_hygiene import _drop, _row, _write
from .test_repo_tidy import commit, lab, make_branch, sh  # noqa: F401 (fixture)


@pytest.fixture(autouse=True)
def no_real_claude(monkeypatch):
    from lab_hub import claude_resolve

    monkeypatch.setattr(claude_resolve, "availability", lambda: (None, "Claude Code not found"))
    monkeypatch.setattr(repo_tidy, "busy_dirs", lambda: ())


def pump(predicate, timeout_s=20.0):
    deadline = time.monotonic() + timeout_s
    while not predicate() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    return predicate()


def tab_for(qapp, root, names, monkeypatch, **kwargs):
    from ui.apps_tab import AppsTab

    monkeypatch.setattr(launcher, "APPLICATIONS", root / "none")
    apps = tuple(launcher.ExternalApp(n, n.upper(), n, "main.py", "s") for n in names)
    tab = AppsTab(config.Settings(lab_root=str(root)), apps, "Apps", "intro", **kwargs)
    return tab


def second_repo(tmp_path, name):
    sh(tmp_path, "clone", "-q", str(tmp_path / "origin.git"), str(tmp_path / name))
    repo = tmp_path / name
    sh(repo, "config", "user.name", "t")
    sh(repo, "config", "user.email", "t@t")
    return repo


def has_work(tmp_path, lab_repo):
    make_branch(lab_repo, "feat", "f.txt")
    _write(tmp_path, [_row(tmp_path, "repo", ["1 branch not merged into main"])])


def test_land_shows_only_on_a_tile_with_work_and_check_repos_is_gone(qapp, tmp_path, lab, monkeypatch):
    has_work(tmp_path, lab)
    (tmp_path / "other").mkdir()
    tab = tab_for(qapp, tmp_path, ["repo", "other"], monkeypatch, check_builds=True)
    tab.refresh()
    repo_card, other_card = tab.cards
    assert not repo_card.land_button.isHidden() and repo_card.land_button.text() == "Land"
    assert other_card.land_button.isHidden()
    labels = {b.text() for b in tab.findChildren(QPushButton)}
    assert "Check repos" not in labels
    assert "Land all (1)" in labels
    assert "Press Land" in repo_card.hygiene.toolTip()
    _drop(tab)


def test_land_all_is_the_launchpads_only(qapp, tmp_path, lab, monkeypatch):
    has_work(tmp_path, lab)
    tab = tab_for(qapp, tmp_path, ["repo"], monkeypatch)
    assert tab.land_all_button is None
    assert not [b for b in tab.findChildren(QPushButton) if b.text().startswith("Land all")]
    _drop(tab)


def test_land_confirms_once_then_lands_and_says_so_on_the_tile(qapp, tmp_path, lab, monkeypatch):
    has_work(tmp_path, lab)
    tab = tab_for(qapp, tmp_path, ["repo"], monkeypatch)
    tab.refresh()
    card = tab.cards[0]
    asked = []
    tab.confirm_land = lambda plans: asked.append([p.sentence for p in plans]) or True

    card.land_button.click()
    assert card.land_button.text() == "Landing…" and not card.land_button.isEnabled()
    assert pump(lambda: card.outcome.text() == "Landed")

    assert len(asked) == 1 and "merge 1 branch into main" in asked[0][0]
    assert (lab / "f.txt").exists() and repo_tidy.ahead_behind(lab) == (0, 0)
    assert card.land_button.text() == "Land" and not tab.lander.busy
    assert card.outcome.objectName() == "stateOk"
    _drop(tab)


def test_cancelling_the_confirmation_changes_nothing(qapp, tmp_path, lab, monkeypatch):
    has_work(tmp_path, lab)
    tab = tab_for(qapp, tmp_path, ["repo"], monkeypatch)
    tab.refresh()
    card = tab.cards[0]
    tab.confirm_land = lambda plans: False
    card.land_button.click()
    assert pump(lambda: not tab.lander.busy)
    assert not (lab / "f.txt").exists() and "feat" in repo_tidy.local_branches(lab)
    assert card.land_button.text() == "Land" and card.land_button.isEnabled()
    assert card.outcome.isHidden()
    _drop(tab)


def test_a_failure_is_one_plain_sentence_on_the_tile_not_a_log(qapp, tmp_path, lab, monkeypatch):
    has_work(tmp_path, lab)
    monkeypatch.setattr(repo_tidy, "apply", lambda *a, **k: (False, (
        "not landed — no Claude run: the tests don't pass on master itself\n"
        "sonar/core.py:29: in <module>\nImportError: cannot import name 'macro' from 'sonar'")))
    tab = tab_for(qapp, tmp_path, ["repo"], monkeypatch)
    tab.refresh()
    card = tab.cards[0]
    tab.confirm_land = lambda plans: True
    card.land_button.click()
    assert pump(lambda: card.outcome.text().startswith("Not landed: "))
    assert "cannot import name 'macro'" in card.outcome.text()
    assert "\n" not in card.outcome.text()
    assert card.outcome.objectName() == "stateBad"
    assert card.land_button.isEnabled()  # try again once it is fixed
    _drop(tab)


def test_a_branch_land_cannot_take_gets_a_review_link(qapp, tmp_path, lab, monkeypatch):
    make_branch(lab, "feat", "a.txt", "theirs")
    commit(lab, "a.txt", "ours")
    sh(lab, "push", "-q", "origin", "main")
    _write(tmp_path, [_row(tmp_path, "repo", ["1 branch not merged into main"])])
    tab = tab_for(qapp, tmp_path, ["repo"], monkeypatch)
    tab.refresh()
    card = tab.cards[0]
    tab.confirm_land = lambda plans: True
    card.land_button.click()
    assert pump(lambda: not card.review_button.isHidden())
    assert "1 branch needs your decision" in card.review_button.text()
    assert card.outcome.text().startswith("Not landed: ")
    _drop(tab)


def test_land_all_lands_every_repo_and_carries_on_past_a_failure(qapp, tmp_path, lab, monkeypatch):
    make_branch(lab, "feat", "f.txt")
    other = second_repo(tmp_path, "other")
    make_branch(other, "feat2", "g.txt")
    _write(tmp_path, [_row(tmp_path, "repo", ["1 branch not merged into main"]),
                      _row(tmp_path, "other", ["1 branch not merged into main"])])
    real = repo_tidy.apply

    def apply(action, *a, **k):
        if action.repo_name == "repo":
            return False, "failed — remote said no"
        return real(action, *a, **k)

    monkeypatch.setattr(repo_tidy, "apply", apply)
    tab = tab_for(qapp, tmp_path, ["repo", "other"], monkeypatch, check_builds=True)
    tab.refresh()
    assert tab.land_all_button.text() == "Land all (2)"
    asked, summary = [], []
    tab.confirm_land = lambda plans: asked.append(len(plans)) or True
    tab.show_land_summary = lambda results: summary.append(results)
    tab.land_all_button.click()
    assert pump(lambda: bool(summary))
    assert asked == [2]  # one confirmation for both
    results = {r.name: r for r in summary[0]}
    assert results["repo"].state == "not_landed" and "remote said no" in results["repo"].reason
    assert results["other"].state == "landed" and (other / "g.txt").exists()
    assert tab.cards[0].outcome.text().startswith("Not landed: ")
    assert tab.cards[1].outcome.text() == "Landed"
    _drop(tab)


def test_every_land_is_off_while_one_runs_and_stop_is_offered(qapp, tmp_path, lab, monkeypatch):
    make_branch(lab, "feat", "f.txt")
    other = second_repo(tmp_path, "other")
    make_branch(other, "feat2", "g.txt")
    _write(tmp_path, [_row(tmp_path, "repo", ["1 branch not merged into main"]),
                      _row(tmp_path, "other", ["1 branch not merged into main"])])
    gate = threading.Event()
    real = repo_tidy.apply
    monkeypatch.setattr(repo_tidy, "apply", lambda *a, **k: gate.wait(10) and real(*a, **k))
    tab = tab_for(qapp, tmp_path, ["repo", "other"], monkeypatch, check_builds=True)
    tab.refresh()
    first, second = tab.cards
    tab.confirm_land = lambda plans: True
    first.land_button.click()
    assert pump(lambda: tab.lander.running)
    assert not second.land_button.isEnabled() and not tab.land_all_button.isEnabled()
    assert not tab.stop_land_button.isHidden()
    gate.set()
    assert pump(lambda: not tab.lander.busy)
    assert tab.stop_land_button.isHidden() and second.land_button.isEnabled()
    _drop(tab)


def test_the_same_repo_cannot_be_landed_twice(qapp, tmp_path, lab, monkeypatch):
    has_work(tmp_path, lab)
    tab = tab_for(qapp, tmp_path, ["repo"], monkeypatch, check_builds=True)
    tab.refresh()
    assert land.claim(lab)
    try:
        tab.refresh()
        assert not tab.cards[0].land_button.isEnabled()
        assert tab.land_all_button.text() == "Land all" and not tab.land_all_button.isEnabled()
    finally:
        land.release(lab)
    _drop(tab)


def test_the_confirmation_is_one_card_per_repo_with_the_claude_disclosure(qapp, tmp_path, monkeypatch):
    from pathlib import Path

    from lab_hub import claude_resolve
    from ui.land_confirm import LandConfirmDialog

    action = repo_tidy.Action("sonar", Path("/x"), "claude_merge", "feat", "conflicts",
                              branch="master", detail="pytest -q")
    plan = land.LandPlan("sonar", Path("/x"), (action,), (), "/bin/claude")
    assert plan.sentence == ("sonar: merge 1 branch into master "
                             "(1 with Claude Code resolving conflicts).")
    tab = tab_for(qapp, tmp_path, ["repo"], monkeypatch)
    seen = {}

    def fake_exec(self):
        seen.update(title=self.title.text(), cards=len(self.cards),
                    claude=self.claude is not None, details=self.details.toPlainText(),
                    land=self.land.text(), default=[b.isDefault() or b.autoDefault()
                                                    for b in (self.toggle, self.cancel, self.land)])
        return 0

    monkeypatch.setattr(LandConfirmDialog, "exec", fake_exec)
    assert tab.confirm_land([plan]) == []  # nothing clicked: nothing to land
    assert seen["title"] == "Land sonar" and seen["cards"] == 1 and seen["claude"]
    assert plan.sentence in seen["details"] and "Anthropic" in seen["details"]
    assert claude_resolve.MODEL in seen["details"]
    assert "Resolve conflicts with Claude" in seen["details"]
    assert seen["land"] == "Land" and seen["default"] == [False, False, False]
    monkeypatch.setattr(LandConfirmDialog, "exec", lambda self: 1)
    assert tab.confirm_land([plan]) == [plan]  # Land: the plans to run
    _drop(tab)


def test_the_outcome_lines():
    assert LandResult("r", "landed").line == "Landed"
    assert LandResult("r", "nothing").line == "Nothing to land"
    assert LandResult("r", "not_landed", "it was stopped").line == "Not landed: it was stopped"


# ---------------------------------------------------------------- review findings
def _gated(monkeypatch):
    gate = threading.Event()
    real = repo_tidy.apply
    monkeypatch.setattr(repo_tidy, "apply", lambda *a, **k: gate.wait(10) and real(*a, **k))
    return gate


def test_a_hygiene_refresh_mid_land_does_not_lose_the_outcome(qapp, tmp_path, lab, monkeypatch):
    has_work(tmp_path, lab)
    gate = _gated(monkeypatch)
    tab = tab_for(qapp, tmp_path, ["repo"], monkeypatch)
    tab.refresh()
    card = tab.cards[0]
    tab.confirm_land = lambda plans: True
    card.land_button.click()
    assert pump(lambda: tab.lander.running)
    card.refresh_hygiene(None)  # the report was rewritten and the repo is not in it
    gate.set()
    assert pump(lambda: card.outcome.text() == "Landed")
    _drop(tab)


def test_a_rebuilt_tile_mid_land_gets_the_outcome(qapp, tmp_path, lab, monkeypatch):
    has_work(tmp_path, lab)
    gate = _gated(monkeypatch)
    tab = tab_for(qapp, tmp_path, ["repo"], monkeypatch)
    tab.refresh()
    old = tab.cards[0]
    tab.confirm_land = lambda plans: True
    old.land_button.click()
    assert pump(lambda: tab.lander.running)
    tab._shown = []  # the app list changed: the tiles are rebuilt
    tab._sync_cards()
    tab.refresh()
    new = tab.cards[0]
    assert new is not old
    gate.set()
    assert pump(lambda: new.outcome.text() == "Landed")
    _drop(tab)


def test_stop_from_the_page_stops_the_run(qapp, tmp_path, lab, monkeypatch):
    has_work(tmp_path, lab)
    gate = _gated(monkeypatch)
    tab = tab_for(qapp, tmp_path, ["repo"], monkeypatch)
    tab.refresh()
    tab.confirm_land = lambda plans: True
    tab.cards[0].land_button.click()
    assert pump(lambda: tab.lander.running)
    tab.stop_land_button.click()
    assert tab.lander._stopper.stopped
    gate.set()
    assert pump(lambda: not tab.lander.busy)
    assert tab.cards[0].outcome.text().startswith("Not landed: ")
    _drop(tab)


def test_a_second_land_while_one_runs_is_ignored(qapp, tmp_path, lab, monkeypatch):
    make_branch(lab, "feat", "f.txt")
    other = second_repo(tmp_path, "other")
    make_branch(other, "feat2", "g.txt")
    _write(tmp_path, [_row(tmp_path, "repo", ["1 branch not merged into main"]),
                      _row(tmp_path, "other", ["1 branch not merged into main"])])
    gate = _gated(monkeypatch)
    tab = tab_for(qapp, tmp_path, ["repo", "other"], monkeypatch)
    tab.refresh()
    first, second = tab.cards
    tab.confirm_land = lambda plans: True
    first.land_button.click()
    assert pump(lambda: tab.lander.running)
    tab.land_card(second)  # called directly, as a double click might
    assert second.outcome.isHidden() and "Looking" not in second.outcome.text()
    gate.set()
    assert pump(lambda: not tab.lander.busy)
    assert not (other / "g.txt").exists()
    _drop(tab)


def test_cancel_puts_back_what_the_tile_said_before(qapp, tmp_path, lab, monkeypatch):
    has_work(tmp_path, lab)
    tab = tab_for(qapp, tmp_path, ["repo"], monkeypatch)
    tab.refresh()
    card = tab.cards[0]
    card.show_outcome(LandResult("repo", "not_landed", "tests fail", remaining=1))
    tab.confirm_land = lambda plans: False
    card.land_button.click()
    assert pump(lambda: not tab.lander.busy)
    assert card.outcome.text() == "Not landed: tests fail"
    assert not card.review_button.isHidden() and not card.terminal_button.isHidden()
    _drop(tab)


def test_not_landed_offers_open_in_terminal_and_landed_does_not(qapp, tmp_path, lab, monkeypatch):
    has_work(tmp_path, lab)
    opened = []
    monkeypatch.setattr(launcher, "open_terminal", lambda path: opened.append(path))
    tab = tab_for(qapp, tmp_path, ["repo"], monkeypatch)
    tab.refresh()
    card = tab.cards[0]
    card.show_outcome(LandResult("repo", "not_landed", "the remote said no"))
    assert not card.terminal_button.isHidden()
    card.terminal_button.click()
    assert opened == [lab.resolve()]
    card.show_outcome(LandResult("repo", "landed"))
    assert card.terminal_button.isHidden()
    _drop(tab)


def test_git_output_is_shown_as_typed_not_as_markup(qapp, tmp_path, lab, monkeypatch):
    from PySide6.QtCore import Qt

    has_work(tmp_path, lab)
    tab = tab_for(qapp, tmp_path, ["repo"], monkeypatch)
    tab.refresh()
    card = tab.cards[0]
    card.show_outcome(LandResult("repo", "not_landed", "failed <b>x</b>", notes=("<i>y</i>",)))
    assert card.outcome.textFormat() == Qt.TextFormat.PlainText
    assert card.outcome.text() == "Not landed: failed <b>x</b>"
    assert "&lt;i&gt;y&lt;/i&gt;" in card.outcome.toolTip()
    assert card.hygiene.textFormat() == Qt.TextFormat.PlainText
    _drop(tab)


def test_a_confirmation_that_raises_leaves_no_tile_stuck(qapp, tmp_path, lab, monkeypatch):
    has_work(tmp_path, lab)
    tab = tab_for(qapp, tmp_path, ["repo"], monkeypatch)
    tab.refresh()
    card = tab.cards[0]

    def boom(plans):
        raise RuntimeError("dialog failed")

    tab.confirm_land = boom
    card.land_button.click()
    assert pump(lambda: not tab.lander.busy and card.land_button.text() == "Land")
    assert card.outcome.isHidden() and card.land_button.isEnabled()
    _drop(tab)


def test_a_check_that_is_running_when_land_ends_is_repeated(qapp, tmp_path, lab, monkeypatch):
    has_work(tmp_path, lab)
    tab = tab_for(qapp, tmp_path, ["repo"], monkeypatch)
    tab._hygiene_proc = object()  # a check is in flight
    tab.refresh_repos()
    assert tab._recheck_after is False  # an ordinary refresh does not queue another
    tab.refresh_repos(force=True)  # Land just finished: the in-flight one is stale
    assert tab._recheck_after is True
    tab._hygiene_proc = None
    _drop(tab)


def test_refresh_forgets_the_last_outcome(qapp, tmp_path, lab, monkeypatch):
    has_work(tmp_path, lab)
    tab = tab_for(qapp, tmp_path, ["repo"], monkeypatch)
    tab.refresh()
    card = tab.cards[0]
    card.show_outcome(LandResult("repo", "landed"))
    assert not card.outcome.isHidden()
    tab.recheck()
    assert card.outcome.isHidden()
    _drop(tab)


def test_quitting_mid_land_stops_the_run_and_waits_for_it(qapp, tmp_path, lab, monkeypatch):
    has_work(tmp_path, lab)
    gate = _gated(monkeypatch)
    tab = tab_for(qapp, tmp_path, ["repo"], monkeypatch)
    tab.refresh()
    tab.confirm_land = lambda plans: True
    tab.cards[0].land_button.click()
    assert pump(lambda: tab.lander.running)
    threading.Timer(0.3, gate.set).start()
    tab.lander.shutdown(wait_s=5)
    assert tab.lander._stopper.stopped
    assert tab.lander._thread is None or not tab.lander._thread.is_alive()
    _drop(tab)


def test_land_all_called_directly_skips_a_repo_already_landing(qapp, tmp_path, lab, monkeypatch):
    has_work(tmp_path, lab)
    tab = tab_for(qapp, tmp_path, ["repo"], monkeypatch, check_builds=True)
    tab.refresh()
    assert land.claim(lab)
    try:
        tab.land_all()
        assert not tab.lander.busy and tab.cards[0].outcome.isHidden()
    finally:
        land.release(lab)
    _drop(tab)


def test_land_on_a_tile_with_nothing_to_land_does_nothing(qapp, tmp_path, lab, monkeypatch):
    _write(tmp_path, [_row(tmp_path, "repo")])  # in the report, but clean
    tab = tab_for(qapp, tmp_path, ["repo"], monkeypatch)
    tab.refresh()
    card = tab.cards[0]
    tab.land_card(card)
    assert not tab.lander.busy and card.outcome.isHidden()
    _drop(tab)


# ---------------------------------------------------------------- the Land window
# Spec `progress-windows` §2.1, §8.3, §8.12.
def test_the_land_window_opens_after_the_confirmation_and_follows_a_two_repo_land(
        qapp, tmp_path, lab, monkeypatch):
    from lab_hub import durations

    make_branch(lab, "feat", "f.txt")
    other = second_repo(tmp_path, "other")
    make_branch(other, "feat2", "g.txt")
    _write(tmp_path, [_row(tmp_path, "repo", ["1 branch not merged into main"]),
                      _row(tmp_path, "other", ["1 branch not merged into main"])])
    tab = tab_for(qapp, tmp_path, ["repo", "other"], monkeypatch, check_builds=True)
    tab.refresh()
    opened_at_confirm = []
    tab.confirm_land = lambda plans: opened_at_confirm.append(tab.land_window) or True
    summary = []
    real_summary = tab.show_land_summary
    tab.show_land_summary = lambda results: summary.append(results) or real_summary(results)
    tab.land_all_button.click()
    assert pump(lambda: tab.land_window is not None)
    assert opened_at_confirm == [None]  # nothing opened before the owner said yes
    window = tab.land_window
    assert window.isVisible()
    assert [r.name.text() for r in window.rows] == ["repo", "other"]
    assert pump(lambda: bool(summary))
    window.draw()
    snap = window.model.snapshot()
    # Both clones push to one origin, so the second push may be refused: the
    # window says whatever the results say.
    results = summary[0]
    landed = sum(r.state == "landed" for r in results)
    assert snap.percent == 100 and not snap.live
    assert snap.outcome == f"Landed {landed} of 2 repos."
    assert window.header.outcome.text() == snap.outcome
    assert [r.pill.text().startswith("Landed") for r in window.rows] == [
        r.state == "landed" and not r.remaining for r in results]
    assert window.stop_button.isHidden() and window.hide_button.text() == "Close"
    history = durations.load()
    assert "repo:repo" in history and "repo:other" in history
    assert "merge" in history["repo:repo"]
    _drop(tab)


def test_land_all_with_a_failure_says_so_in_the_window_not_a_box(qapp, tmp_path, lab, monkeypatch):
    make_branch(lab, "feat", "f.txt")
    other = second_repo(tmp_path, "other")
    make_branch(other, "feat2", "g.txt")
    _write(tmp_path, [_row(tmp_path, "repo", ["1 branch not merged into main"]),
                      _row(tmp_path, "other", ["1 branch not merged into main"])])
    real = repo_tidy.apply
    monkeypatch.setattr(repo_tidy, "apply", lambda action, *a, **k: (
        (False, "failed — remote said <b>no</b>") if action.repo_name == "repo"
        else real(action, *a, **k)))
    boxes = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: boxes.append(self.text()))
    tab = tab_for(qapp, tmp_path, ["repo", "other"], monkeypatch, check_builds=True)
    tab.refresh()
    tab.confirm_land = lambda plans: True
    tab.land_all_button.click()
    assert pump(lambda: tab.land_window is not None and not tab.land_window.model.live)
    window = tab.land_window
    window.draw()
    assert boxes == []  # the window's end state replaced the Land all box
    assert window.header.outcome.text() == "Landed 1 of 2 repos."
    assert "repo: Not landed: remote said <b>no</b>" in window.header.details.text()
    # Its steps ran, so its time follows the bare status (spec land-pick-and-time item 9).
    assert re.fullmatch(r"Needs you · \d+:\d\d", window.rows[0].pill.text())
    assert window.rows[0].reason.text() == "remote said <b>no</b>"
    from PySide6.QtCore import Qt

    assert window.rows[0].reason.textFormat() == Qt.TextFormat.PlainText
    assert "repo: → not done: failed — remote said <b>no</b>" in window.output.text()
    _drop(tab)


def test_hide_keeps_landing_show_progress_brings_it_back_and_its_stop_stops(
        qapp, tmp_path, lab, monkeypatch):
    has_work(tmp_path, lab)
    gate = _gated(monkeypatch)
    tab = tab_for(qapp, tmp_path, ["repo"], monkeypatch)
    tab.refresh()
    tab.confirm_land = lambda plans: True
    tab.cards[0].land_button.click()
    assert pump(lambda: tab.lander.running and tab.land_window is not None)
    window = tab.land_window
    assert not tab.show_land_button.isHidden()
    window.hide_button.click()
    assert not window.isVisible() and tab.lander.running  # hiding is not stopping
    tab.show_land_button.click()
    assert window.isVisible()
    window.close()  # the red button: also only hides
    assert not window.isVisible() and tab.lander.running
    tab.show_land_button.click()
    window.stop_button.click()
    assert tab.lander._stopper.stopped
    assert not window.stop_button.isEnabled()
    gate.set()
    assert pump(lambda: not tab.lander.busy)
    assert tab.show_land_button.isHidden()
    assert tab.cards[0].outcome.text().startswith("Not landed: ")
    _drop(tab)


def test_a_single_land_ends_with_its_tile_line_in_the_window(qapp, tmp_path, lab, monkeypatch):
    has_work(tmp_path, lab)
    tab = tab_for(qapp, tmp_path, ["repo"], monkeypatch)
    tab.refresh()
    tab.confirm_land = lambda plans: True
    tab.cards[0].land_button.click()
    assert pump(lambda: tab.cards[0].outcome.text() == "Landed")
    window = tab.land_window
    window.draw()
    assert window.header.outcome.text() == "repo: Landed"
    assert window.header.title.text() == "Land finished · repo"
    _drop(tab)


def test_cancelling_the_confirmation_opens_no_window(qapp, tmp_path, lab, monkeypatch):
    has_work(tmp_path, lab)
    tab = tab_for(qapp, tmp_path, ["repo"], monkeypatch)
    tab.refresh()
    tab.confirm_land = lambda plans: False
    tab.cards[0].land_button.click()
    assert pump(lambda: not tab.lander.busy)
    assert tab.land_window is None and tab.show_land_button.isHidden()
    _drop(tab)


def test_a_later_land_that_opens_no_window_leaves_the_finished_one_alone(
        qapp, tmp_path, lab, monkeypatch):
    """Review P2-2: a single-tile Land with nothing to do opens no window, but
    used to feed the previous run's finished window (its row turned "Nothing
    to land", its outcome was overwritten) and Show progress showed it."""
    has_work(tmp_path, lab)
    tab = tab_for(qapp, tmp_path, ["repo"], monkeypatch)
    tab.refresh()
    tab.confirm_land = lambda plans: True
    tab.cards[0].land_button.click()
    assert pump(lambda: tab.cards[0].outcome.text() == "Landed")
    window = tab.land_window
    window.draw()

    def state():
        return (window.header.outcome.text(), [r.pill.text() for r in window.rows],
                window.output.text())

    before = state()
    assert before[0] == "repo: Landed"
    # The report still says the repo needs attention; there is nothing left to land.
    assert pump(lambda: tab._hygiene_proc is None)
    _write(tmp_path, [_row(tmp_path, "repo", ["1 branch not merged into main"])])
    tab.refresh()
    tab.cards[0].land_button.click()
    assert pump(lambda: tab.lander.running)
    show_hidden_while_running = tab.show_land_button.isHidden()
    assert pump(lambda: not tab.lander.busy)
    window.draw()
    assert tab.land_window is window
    assert state() == before
    assert show_hidden_while_running
    _drop(tab)


def test_land_all_lands_only_the_ticked_repos(qapp, tmp_path, lab, monkeypatch):
    """Spec land-pick-and-time items 3-5: a left-out repo is not run and its
    tile goes back at once; the window and the run log count the run only."""
    from lab_hub import durations

    make_branch(lab, "feat", "f.txt")
    other = second_repo(tmp_path, "other")
    make_branch(other, "feat2", "g.txt")
    _write(tmp_path, [_row(tmp_path, "repo", ["1 branch not merged into main"]),
                      _row(tmp_path, "other", ["1 branch not merged into main"])])
    tab = tab_for(qapp, tmp_path, ["repo", "other"], monkeypatch, check_builds=True)
    tab.refresh()
    ran = []

    def confirm(plans):
        return [p for p in plans if p.name == "other"]

    tab.confirm_land = confirm
    real_run = tab.lander.run
    tab.lander.run = lambda plans: ran.append([p.name for p in plans]) or real_run(plans)
    tab.land_all_button.click()
    assert pump(lambda: tab.land_window is not None and not tab.land_window.model.live)
    assert ran == [["other"]]
    assert (other / "g.txt").exists() and not (lab / "f.txt").exists()
    assert "repo" not in tab._landing_cards
    assert tab.cards[0].outcome.text() == ""  # never landed, nothing to say
    assert tab.cards[1].outcome.text() == "Landed"
    window = tab.land_window
    window.draw()
    assert [r.name.text() for r in window.rows] == ["other"]
    assert window.header.title.text() == "Land finished · other"
    assert [(r.repos, r.landed) for r in durations.load_runs()] == [(1, 1)]
    _drop(tab)


def test_true_from_the_confirmation_still_means_every_repo(qapp, tmp_path, lab, monkeypatch):
    make_branch(lab, "feat", "f.txt")
    other = second_repo(tmp_path, "other")
    make_branch(other, "feat2", "g.txt")
    _write(tmp_path, [_row(tmp_path, "repo", ["1 branch not merged into main"]),
                      _row(tmp_path, "other", ["1 branch not merged into main"])])
    tab = tab_for(qapp, tmp_path, ["repo", "other"], monkeypatch, check_builds=True)
    tab.refresh()
    ran = []
    tab.confirm_land = lambda plans: True
    real_run = tab.lander.run
    tab.lander.run = lambda plans: ran.append(sorted(p.name for p in plans)) or real_run(plans)
    tab.land_all_button.click()
    assert pump(lambda: tab.land_window is not None and not tab.land_window.model.live)
    assert ran == [["other", "repo"]]
    _drop(tab)


def test_an_empty_choice_is_a_cancel(qapp, tmp_path, lab, monkeypatch):
    has_work(tmp_path, lab)
    tab = tab_for(qapp, tmp_path, ["repo"], monkeypatch)
    tab.refresh()
    tab.confirm_land = lambda plans: []
    tab.cards[0].land_button.click()
    assert pump(lambda: not tab.lander.busy)
    assert tab.land_window is None and tab._landing_cards == {}
    assert tab.cards[0].land_button.isEnabled()
    _drop(tab)


# --- review findings (docs/audit/land-pick-and-time-review.md) ---------------
def _planned_tab(qapp, tmp_path, monkeypatch):
    tab = tab_for(qapp, tmp_path, ["repo"], monkeypatch)
    ran, windows = [], []
    tab.lander.run = lambda plans: ran.append([p.name for p in plans]) or True
    tab._open_land_window = lambda plans: windows.append([p.name for p in plans])
    return tab, ran, windows


def test_a_partial_choice_keeps_the_nothing_to_land_rows_in_plan_order(qapp, tmp_path,
                                                                       monkeypatch):
    from .test_land_confirm import screenshot_plans

    tab, ran, windows = _planned_tab(qapp, tmp_path, monkeypatch)
    plans = screenshot_plans()  # lab_hub, foundry, syndustryx, Imprint (nothing to land)
    tab.confirm_land = lambda ps: [p for p in ps if p.name == "foundry"]
    tab._land_planned(plans)
    assert ran == [["foundry", "Imprint"]] and windows == ran  # review P2-2
    tab.confirm_land = lambda ps: []
    tab._land_planned(screenshot_plans())
    assert ran == [["foundry", "Imprint"]]  # Cancel runs nothing, not even Imprint
    _drop(tab)


def test_land_all_narrowed_to_one_repo_still_opens_the_window(qapp, tmp_path, monkeypatch):
    from pathlib import Path

    from lab_hub import land_resolve

    tab, ran, windows = _planned_tab(qapp, tmp_path, monkeypatch)
    stop_only = land.LandPlan("a", Path("/a"), stops=(
        land_resolve.Stop("a", "/a", "a process is running in it: close that terminal"),))
    other = land.LandPlan("b", Path("/b"), stops=(
        land_resolve.Stop("b", "/b", "a process is running in it: close that terminal"),))
    tab.confirm_land = lambda ps: [stop_only]
    tab._land_planned([stop_only, other])
    assert ran == [["a"]] and windows == [["a"]]  # review P3-6: it came from Land all
    _drop(tab)


def test_the_real_dialog_choice_is_what_runs_and_what_is_disclosed(qapp, tmp_path,
                                                                   monkeypatch):
    """Spec §6 mitigation, end to end (review P3-9)."""
    from ui.land_confirm import LandConfirmDialog

    from .test_land_confirm import screenshot_plans

    tab, ran, windows = _planned_tab(qapp, tmp_path, monkeypatch)
    seen = {}

    def exec_(self):
        for card in self.cards:
            if card.plan.cost.any:  # untick both repos that may use Claude Code
                card.check.setChecked(False)
        seen["claude"] = self.claude
        seen["details"] = self.details.toPlainText()
        return QDialog.DialogCode.Accepted

    from PySide6.QtWidgets import QDialog

    monkeypatch.setattr(LandConfirmDialog, "exec", exec_)
    tab._land_planned(screenshot_plans())
    assert seen["claude"] is None and "Anthropic" not in seen["details"]
    assert ran == [["foundry", "Imprint"]]
    _drop(tab)
