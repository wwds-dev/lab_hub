"""The Land confirmation (spec land-confirm-dialog): cards, stops, one Claude Code total."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QLabel

from lab_hub import claude_resolve, land, land_resolve, repo_tidy
from ui.land_confirm import LandConfirmDialog, details_text, headline

LAB = Path("/lab/lab_hub")
NODE = ("node (pid 2971)", "node (pid 3094)", "gk (pid 3114)") + tuple(
    f"zsh (pid {5000 + i})" for i in range(60))


def _act(repo, name, kind, target, detail="", branch="main"):
    return repo_tidy.Action(name, repo, kind, target, "why", branch=branch, detail=detail)


def busy_stop(name, target, processes):
    who = land_resolve._first(list(processes))
    return land_resolve.Stop(name, str(target), f"a process is running in it ({who}): close "
                             "that terminal or session, then Land again", tuple(processes))


def screenshot_plans():
    """The owner's screenshot, 2026-11-17."""
    hub = land.LandPlan(
        "lab_hub", LAB,
        (_act(LAB, "lab_hub", "commit", str(LAB)), _act(LAB, "lab_hub", "delete_branch", "old")),
        claude="/bin/claude", unlanded=4,
        stops=(busy_stop("lab_hub", LAB, NODE),
               busy_stop("lab_hub", LAB / ".claude/worktrees/priceless-moore-a19001",
                         ("disclaimer (pid 71613)", "claude (pid 71614)", "zsh (pid 74406)"))))
    fd = Path("/lab/foundry")
    foundry = land.LandPlan(
        "foundry", fd,
        (_act(fd, "foundry", "commit", str(fd)), _act(fd, "foundry", "push", "master")),
        stops=(busy_stop("foundry", fd, ("zsh (pid 14493)",) * 1 + tuple(
            f"zsh (pid {i})" for i in range(18))),))
    sx = Path("/lab/syndustryx")
    syn = land.LandPlan(
        "syndustryx", sx,
        (_act(sx, "syndustryx", "claude_merge", "feat",
              detail="python3 -m unittest discover -s tests"),
         _act(sx, "syndustryx", "push", "main")),
        claude="/bin/claude",
        stops=(busy_stop("syndustryx", sx / ".claude/worktrees/policy-none-rootcause-686617",
                         ("limactl (pid 86384)", "limactl (pid 86436)", "ssh (pid 86733)")),))
    idle = land.LandPlan("Imprint", Path("/lab/imprint"))
    return [hub, foundry, syn, idle]


# --- the words (Qt-free) -------------------------------------------------
def test_items_are_the_sentence_without_the_stops():
    hub = screenshot_plans()[0]
    assert hub.items == (
        "commit open changes in 1 worktree", "delete 1 landed branch",
        "then merge the 4 other branches not landed yet where they can; Claude Code decides "
        "for any that still cannot land: land it or archive it as a tag")
    assert hub.sentence.startswith("lab_hub: " + ", ".join(hub.items) + ", stop at 2 things")
    assert "60 more" in hub.sentence  # today's text is unchanged


def test_a_busy_stop_is_place_problem_action_with_processes_counted():
    hub = screenshot_plans()[0]
    main, tree = hub.stop_views
    assert main.place == "Main checkout"
    assert main.problem == "63 processes running in it, including node, gk and zsh"
    assert main.action == "Close those terminals or sessions, then Land again."
    assert "pid" not in main.problem and "zsh (pid 5059)" in main.full
    assert tree.place == "Worktree priceless-moore-a19001"
    assert tree.problem == "disclaimer, claude and zsh running in it"


def test_one_process_keeps_the_singular_action():
    stop = busy_stop("r", LAB, ("zsh (pid 1)",))
    view = land.stop_view(stop, LAB)
    assert view.problem == "zsh running in it"
    assert view.action == "Close that terminal or session, then Land again."


@pytest.mark.parametrize("reason,problem,action", [
    ("rebase is in progress: finish or abort it in Terminal", "rebase is in progress",
     "Finish or abort it in Terminal."),
    ("it has unresolved conflicts: resolve them in Terminal", "it has unresolved conflicts",
     "Resolve them in Terminal."),
    ("could not check whether a process is running in it (lsof failed)",
     "could not check whether a process is running in it (lsof failed)", ""),
    ("gitleaks failed: exit 2: bad config", "gitleaks failed: exit 2: bad config", ""),
    ("hook: resolve them in Terminal: then exit 1", "hook: resolve them in Terminal: then exit 1",
     ""),  # a known action inside a reason, not at its end, is not split off
])
def test_only_known_actions_are_split_off(reason, problem, action):
    view = land.stop_view(land_resolve.Stop("r", str(LAB / "w"), reason), LAB)
    assert (view.place, view.problem, view.action) == ("Worktree w", problem, action)


def test_a_path_that_is_no_checkout_names_the_path():
    stop = land_resolve.Stop("r", "/apps/r", "not a git checkout, nor a link to one: "
                             "fix the app's path")
    view = land.stop_view(stop, Path("/apps/r"))
    assert (view.place, view.action) == ("/apps/r", "Fix the app's path.")


def test_one_claude_panel_with_one_total_and_every_fact():
    plans = screenshot_plans()
    panel = land.claude_panel(plans)
    assert panel.title == f"Claude Code (model {claude_resolve.MODEL})"
    assert panel.total == "at most $17 in total"  # 4 x $3 + 4 x $0.50 + 1 x $3
    (merge, m_usd), (triage, t_usd) = panel.lines
    assert merge.startswith("Merge with conflicts: up to 5 branches (1 known to conflict now)")
    assert "at most $3 each" in merge and m_usd == "$15"
    assert "read-only (their log and diff)" in triage and "up to 4" in triage
    assert "at most $0.50 each" in triage and t_usd == "$2"
    for fact in ("goes to Anthropic", "tests itself", "pushed without review",
                 "archived as a tag, never lost", "archive/<branch>/<date>", "never pushed",
                 "restored from Review branches"):
        assert fact in panel.body, fact
    assert [p.cost.total_usd for p in plans[:3]] == [14, 0, 3]


def test_no_claude_no_panel_and_exact_counts_without_up_to():
    plans = screenshot_plans()
    assert land.claude_panel([plans[1]]) is None
    panel = land.claude_panel([plans[2]])
    assert panel.lines[0][0] == "Merge with conflicts: 1 branch, at most $3 each"
    assert panel.total == "at most $3 in total" and "Review branches" not in panel.body


def test_headline_counts_the_stops():
    plans = screenshot_plans()
    title, line = headline(plans[:3])
    assert title == "Land 3 repos" and "stops at 4 things only you can clear" in line
    plain = land.LandPlan("Imprint", LAB, (_act(LAB, "Imprint", "push", "main"),))
    assert headline([plain]) == ("Land Imprint", "Land does all of it; nothing needs you.")


def test_details_keep_todays_texts_and_every_pid():
    plans = screenshot_plans()[:3]
    text = details_text(plans)
    for plan in plans:
        assert plan.sentence in text and plan.detail in text
        if plan.claude_notice:
            assert plan.claude_notice in text
    assert all(p in text for p in NODE)


# --- the dialog ------------------------------------------------------------
@pytest.fixture
def dialog(qapp):
    box = LandConfirmDialog(screenshot_plans())
    yield box
    box.deleteLater()


def test_one_card_per_repo_and_a_line_for_the_idle(dialog):
    assert [c.plan.name for c in dialog.cards] == ["lab_hub", "foundry", "syndustryx"]
    assert dialog.idle.text() == "Nothing to land in Imprint."
    assert dialog.title.text() == "Land 3 repos" and dialog.land.text() == "Land 3 repos"
    assert dialog.claude is not None and dialog.land.objectName() == "primary"
    rows = [r.text() for r in dialog.cards[0].stop_rows]
    assert rows[0] == "Main checkout · 63 processes running in it, including node, gk and zsh"


def test_every_label_is_plain_text(dialog):
    labels = dialog.findChildren(QLabel)
    assert labels and all(lb.textFormat() == Qt.TextFormat.PlainText for lb in labels)


def test_return_presses_nothing_and_escape_cancels(dialog):
    dialog.show()
    QTest.keyClick(dialog, Qt.Key.Key_Return)
    assert dialog.isVisible() and dialog.result() == 0
    QTest.keyClick(dialog, Qt.Key.Key_Escape)
    assert not dialog.isVisible() and dialog.result() == QDialog.DialogCode.Rejected


def test_land_accepts_and_details_toggle(dialog):
    assert dialog.details.isHidden()
    dialog.toggle.click()
    assert not dialog.details.isHidden() and dialog.toggle.text() == "Hide details"
    dialog.land.click()
    assert dialog.result() == QDialog.DialogCode.Accepted
