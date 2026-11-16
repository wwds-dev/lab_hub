"""Land on the tiles and the page, on real temporary git repos.

Spec `docs/specs/land-from-tiles.md`: success measures 1-7. The confirmation
box is replaced (it blocks); everything else, the worker thread included, runs
for real. A step Claude Code or a repo's tests would decide is replaced at
`repo_tidy.apply`, as in `test_land.py`.
"""

from __future__ import annotations

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


def test_the_confirmation_is_one_sentence_per_repo_with_the_claude_disclosure(qapp, tmp_path, monkeypatch):
    from pathlib import Path

    from lab_hub import claude_resolve

    action = repo_tidy.Action("sonar", Path("/x"), "claude_merge", "feat", "conflicts",
                              branch="master", detail="pytest -q")
    plan = land.LandPlan("sonar", Path("/x"), (action,), (), "/bin/claude")
    assert plan.sentence == ("sonar: merge 1 branch into master "
                             "(1 with Claude Code resolving conflicts).")
    tab = tab_for(qapp, tmp_path, ["repo"], monkeypatch)
    seen = {}

    def fake_exec(self):
        seen.update(text=self.text(), info=self.informativeText(), detail=self.detailedText(),
                    labels=[b.text() for b in self.buttons() if b.text() in ("Land", "Cancel")],
                    default=self.defaultButton().text())
        return 0

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    assert tab.confirm_land([plan]) is False  # nothing clicked
    assert seen["text"] == plan.sentence
    assert "Anthropic" in seen["info"] and claude_resolve.MODEL in seen["info"]
    assert "Resolve conflicts with Claude" in seen["detail"]
    assert set(seen["labels"]) == {"Land", "Cancel"} and seen["default"] == "Cancel"
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
