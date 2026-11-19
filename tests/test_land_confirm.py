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


def _golden_plan():
    act = (lambda kind, target, detail="": _act(LAB, "lab_hub", kind, target, detail))
    return land.LandPlan(
        "lab_hub", LAB,
        (act("commit", str(LAB)), act("delete_branch", "old"),
         act("claude_merge", "feat", "pytest -q"), act("push", "main")),
        claude="/bin/claude", unlanded=2,
        stops=(land_resolve.Stop("lab_hub", str(LAB / "w"),
                                 "it has unresolved conflicts: resolve them in Terminal"),))


def test_sentence_and_notice_are_byte_identical_to_before():
    """Golden texts from the parent of 4072f72 (review P3-6)."""
    plan = _golden_plan()
    assert plan.sentence == (
        "lab_hub: commit open changes in 1 worktree, merge 1 branch into main (1 with Claude "
        "Code resolving conflicts), push main to origin, delete 1 landed branch, then merge "
        "the 2 other branches not landed yet where they can; Claude Code decides for any that "
        "still cannot land: land it or archive it as a tag, stop at 1 thing only you can "
        "clear: lab_hub: /lab/lab_hub/w — it has unresolved conflicts: resolve them in "
        "Terminal.")
    assert plan.claude_notice == (
        "up to 3 branches may be sent (1 known to conflict now) to Claude Code (model "
        f"{claude_resolve.MODEL}, at most $3 each, $9 in total). Code from this repo goes to "
        "Anthropic, as in any Claude Code session. Lab Hub runs the repo's tests itself "
        "(pytest -q); a merge that passes them lands and is pushed without review. A branch "
        "that fails is archived as a tag, never lost.\n\nA branch that still does not land is "
        "sent to Claude Code read-only (its log and diff, at most $0.50 each, $1.00 for 2 "
        "branches at most). An archived branch is kept as a local tag archive/<branch>/<date>, "
        "never pushed, and can be restored from Review branches.")


@pytest.mark.parametrize("claude,merges,unlanded", [
    (None, 0, 3),            # no Claude Code: triage disclosed, nothing merged by it
    ("/bin/claude", 2, 0),   # known conflicts only
    ("/bin/claude", 0, 2),   # only possible merges, plus triage
    ("/bin/claude", 1, 2),   # both
    (None, 0, 0),            # nothing for Claude Code: no panel
])
def test_the_panel_total_is_the_old_notices_amounts(claude, merges, unlanded):
    """Review P2-1: the one total is the old merge total plus the old triage amount."""
    acts = tuple(_act(LAB, "r", "claude_merge", f"b{i}", detail="pytest -q")
                 for i in range(merges)) + (_act(LAB, "r", "push", "main"),)
    plan = land.LandPlan("r", LAB, acts, claude=claude, unlanded=unlanded)
    old = plan.claude_notice
    panel = land.claude_panel([plan, plan])  # two repos alike: amounts add up
    assert (panel is None) == (not plan.cost.any)  # security review P3-2
    if not old:
        assert panel is None
        return
    later = unlanded if claude else 0
    n = merges + later
    expected = 2 * (n * claude_resolve.BUDGET_USD + unlanded * land_resolve.TRIAGE_BUDGET_USD)
    assert panel.total == f"at most {land._usd(expected)} in total"
    if n:
        assert f"${n * claude_resolve.BUDGET_USD:.0f} in total" in old
        assert ("up to" in panel.lines[0][0]) == bool(later) == ("up to" in old)
        assert f"({2 * merges} known to conflict now)" in panel.lines[0][0] or not later
        for fact in ("goes to Anthropic", "pushed without review",
                     "archived as a tag, never lost"):
            assert fact in old and fact in panel.body
    if unlanded:
        assert "read-only" in old and "read-only" in panel.lines[-1][0]
        for fact in ("archive/<branch>/<date>", "never pushed", "restored from Review branches"):
            assert fact in old and fact in panel.body


def test_the_main_checkout_through_a_link_is_still_the_main_checkout(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "link").symlink_to(real)
    stop = land_resolve.Stop("r", str(tmp_path / "link"), "it has unresolved conflicts: "
                             "resolve them in Terminal")
    assert land.stop_view(stop, real).place == "Main checkout"


def test_headline_counts_the_stops():
    plans = screenshot_plans()
    title, line = headline(plans[:3])
    assert title == "Land 3 repos" and "stops at 4 things only you can clear" in line
    plain = land.LandPlan("Imprint", LAB, (_act(LAB, "Imprint", "push", "main"),))
    assert headline([plain]) == ("Land Imprint", "Land does all of it; nothing needs you.")
    assert headline([]) == ("Land", "Nothing to land.")


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
    from ui.land_confirm import FOOTNOTE

    pills = [[lb.text() for lb in card.findChildren(QLabel, "runPill") if lb.isVisibleTo(card)]
             for card in dialog.cards]
    assert pills == [["3 steps", "stops at 2", "Claude Code · up to $14"],
                     ["2 steps", "stops at 1"],
                     ["2 steps", "stops at 1", "Claude Code · up to $3"]]  # QA P3
    texts = [lb.text() for lb in dialog.findChildren(QLabel)]
    assert FOOTNOTE in texts and not any("(pid " in s for s in texts)  # pids: Details only
    assert dialog.width() >= 640 and dialog.minimumWidth() == 640
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


def test_a_tooltip_shows_markup_as_text(qapp):
    plan = land.LandPlan("r", LAB, (_act(LAB, "r", "push", "main"),), stops=(
        land_resolve.Stop("r", str(LAB / "w"), "<b>bold</b> branch: resolve them in Terminal"),))
    box = LandConfirmDialog([plan])
    tip = box.cards[0].stop_rows[0].toolTip()
    assert tip.startswith("<qt>") and "&lt;b&gt;bold&lt;/b&gt;" in tip and "<b>" not in tip
    box.deleteLater()


def test_details_round_trip_stays_on_the_screen(qapp):
    """Review P2-2: opening Details grows the window but keeps it on the screen; the
    cards give up their room. (90% is the aim; on a short screen the disclosure text,
    which must stay visible, can need a little more.)"""
    plans = screenshot_plans() * 4  # many cards: the cards scroll
    box = LandConfirmDialog(plans)
    box.show()
    screen = box._screen_height()
    closed = box.height()
    assert closed <= screen * 0.9 + 1 and box.scroll.minimumHeight() <= screen * 0.7
    box.toggle.click()
    assert not box.details.isHidden() and box.height() <= screen
    assert box.scroll.minimumHeight() <= 70
    box.toggle.click()
    assert box.details.isHidden() and box.scroll.minimumHeight() == box._cards_height
    box.close()
    box.deleteLater()


def test_the_cards_area_fits_wrapped_text_at_its_real_width(qapp):
    """Review P2-3: the height asked for matches the cards laid out at that width."""
    long = "a process is running in it: close that terminal or session, then Land again"
    stops = tuple(land_resolve.Stop("r", str(LAB / f"w{i}" / ("deep-folder-" * 6)), long,
                                    tuple(f"proc{j} (pid {j})" for j in range(9)))
                  for i in range(3))
    plan = land.LandPlan("r", LAB, (_act(LAB, "r", "push", "main"),), stops=stops)
    box = LandConfirmDialog([plan])
    box.show()
    qapp.processEvents()
    holder = box.scroll.widget()
    laid_out = holder.layout().totalHeightForWidth(box.scroll.viewport().width())
    assert abs(box._cards_height - laid_out) <= 24
    box.close()
    box.deleteLater()


def test_repeated_process_names_say_how_many():
    """Review P3-5."""
    stop = busy_stop("r", LAB, ("limactl (pid 1)", "limactl (pid 2)", "ssh (pid 3)"))
    view = land.stop_view(stop, LAB)
    assert view.problem == "3 processes running in it: limactl and ssh"
    assert view.action == "Close those terminals or sessions, then Land again."
    two = land.stop_view(busy_stop("r", LAB, ("zsh (pid 1)", "zsh (pid 2)")), LAB)
    assert two.problem == "2 processes running in it: zsh"


def test_same_named_worktrees_name_their_parent():
    """Review P3-4."""
    reason = "it has unresolved conflicts: resolve them in Terminal"
    plan = land.LandPlan("r", LAB, (_act(LAB, "r", "push", "main"),), stops=(
        land_resolve.Stop("r", str(LAB / ".claude/worktrees/fix"), reason),
        land_resolve.Stop("r", "/elsewhere/fix", reason),
        land_resolve.Stop("r", str(LAB / ".claude/worktrees/other"), reason)))
    assert [v.place for v in plan.stop_views] == [
        "Worktree worktrees/fix", "Worktree elsewhere/fix", "Worktree other"]


def test_at_most_three_names_are_named():
    """QA P3: the cap on names when there are more than three processes."""
    procs = tuple(f"{n} (pid {i})" for i, n in enumerate(["a", "b", "c", "d", "e"]))
    view = land.stop_view(busy_stop("r", LAB, procs), LAB)
    assert view.problem == "5 processes running in it, including a, b and c"


# --- land-pick-and-time: a tick box per repo ---------------------------------
def _card(dialog, name):
    return next(c for c in dialog.cards if c.plan.name == name)


def _visible_claude(dialog):
    from ui.land_confirm import ClaudeBox

    return [b for b in dialog.findChildren(ClaudeBox) if b.isVisibleTo(dialog)]


def test_every_card_has_a_ticked_box_and_one_card_has_none(qapp, dialog):
    assert all(c.check is not None and c.check.isChecked() for c in dialog.cards)
    assert _card(dialog, "foundry").check.accessibleName() == "Land foundry"
    assert dialog.chosen() == [c.plan for c in dialog.cards]
    plan = screenshot_plans()[0]
    one = LandConfirmDialog([plan])
    assert one.cards[0].check is None and one.chosen() == [plan]
    one.deleteLater()


def test_unticking_folds_the_card_and_everything_counts_the_rest(dialog):
    card = _card(dialog, "foundry")
    card.check.setChecked(False)
    assert card.body.isHidden() and not card.left_out.isHidden()
    assert not card.name.isEnabled()
    assert [p.name for p in dialog.chosen()] == ["lab_hub", "syndustryx"]
    chosen = dialog.chosen()
    assert (dialog.title.text(), dialog.summary.text()) == headline(chosen, 3)
    assert dialog.title.text() == "Land 2 repos" and dialog.land.text() == "Land 2 repos"
    assert dialog.details.toPlainText() == details_text(chosen)
    assert "foundry" not in dialog.details.toPlainText()
    card.check.setChecked(True)
    assert not card.body.isHidden() and card.left_out.isHidden()
    assert dialog.land.text() == "Land 3 repos"


def test_the_claude_panel_covers_exactly_the_ticked_repos(dialog):
    whole = land.claude_panel(dialog.chosen()).total
    _card(dialog, "syndustryx").check.setChecked(False)
    assert dialog.claude.findChildren(QLabel)[1].text() == \
        land.claude_panel(dialog.chosen()).total != whole
    _card(dialog, "lab_hub").check.setChecked(False)  # foundry alone uses no Claude Code
    assert dialog.claude is None and _visible_claude(dialog) == []
    for name in ("lab_hub", "syndustryx"):
        _card(dialog, name).check.setChecked(True)
    assert len(_visible_claude(dialog)) == 1 and dialog.claude is _visible_claude(dialog)[0]


def test_the_chosen_set_reads_as_a_dialog_built_from_it_alone(qapp, dialog):
    plans = screenshot_plans()
    _card(dialog, "foundry").check.setChecked(False)
    alone = LandConfirmDialog([p for p in plans if p.name != "foundry"])

    def words(box):
        claude = [lb.text() for lb in box.claude.findChildren(QLabel)] if box.claude else []
        return (box.title.text(), box.summary.text(), box.land.text(),
                box.details.toPlainText(), claude)

    assert words(dialog) == words(alone)
    alone.deleteLater()


def test_none_ticked_disables_land_until_one_is(dialog):
    for card in dialog.cards:
        card.check.setChecked(False)
    assert dialog.title.text() == "Nothing chosen"
    assert dialog.summary.text() == "Tick a repo to land it."
    assert not dialog.land.isEnabled() and dialog.claude is None
    assert dialog.chosen() == []
    dialog.cards[1].check.setChecked(True)
    assert dialog.land.isEnabled() and dialog.title.text() == "Land foundry"
    assert dialog.land.text() == "Land"


def test_a_click_on_the_header_toggles_and_return_still_presses_nothing(dialog):
    dialog.show()
    card = _card(dialog, "foundry")
    QTest.mouseClick(card.head, Qt.MouseButton.LeftButton)
    assert not card.check.isChecked()
    QTest.mouseClick(card.head, Qt.MouseButton.LeftButton)
    assert card.check.isChecked()
    card.check.setChecked(False)
    QTest.keyClick(dialog, Qt.Key.Key_Return)
    assert dialog.isVisible() and dialog.result() == 0
    dialog.land.click()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert [p.name for p in dialog.chosen()] == ["lab_hub", "syndustryx"]


# --- review findings (docs/audit/land-pick-and-time-review.md) ---------------
def test_a_left_out_name_takes_the_hint_style_and_gets_it_back(dialog):
    card = _card(dialog, "foundry")
    card.check.setChecked(False)
    assert card.name.objectName() == "hint"  # P2-1: the stylesheet colour, not the palette
    card.check.setChecked(True)
    assert card.name.objectName() == "appName"


def test_an_unticked_card_is_dimmed_by_a_stylesheet_rule(dialog):
    from ui import theme
    card = _card(dialog, "foundry")
    card.check.setChecked(False)
    assert card.property("out") == "true"
    card.check.setChecked(True)
    assert card.property("out") == "false"
    for pal in (theme.GRAPHITE, theme.PAPER):
        assert 'QFrame#card[out="true"]' in theme.stylesheet(pal)


def test_a_press_dragged_off_the_header_does_not_toggle(dialog):
    from PySide6.QtCore import QPoint

    dialog.show()
    card = _card(dialog, "foundry")
    QTest.mousePress(card.head, Qt.MouseButton.LeftButton, pos=QPoint(5, 5))
    QTest.mouseRelease(card.head, Qt.MouseButton.LeftButton,
                       pos=QPoint(5, card.head.height() + 40))  # P3-8
    assert card.check.isChecked()


def test_folding_cards_gives_their_room_back(qapp, dialog):
    dialog.show()
    before = dialog.scroll.minimumHeight()
    for name in ("lab_hub", "syndustryx"):
        _card(dialog, name).check.setChecked(False)
    assert dialog.scroll.minimumHeight() < before  # P3-5
    for name in ("lab_hub", "syndustryx"):
        _card(dialog, name).check.setChecked(True)
    assert dialog.scroll.minimumHeight() >= before  # ticked again: the room comes back


# --- verify follow-up (docs/audit/land-pick-and-time-qa.md G4, G8) -----------
def test_an_unticked_card_hides_its_step_stop_and_claude_pills(dialog):
    dialog.show()
    card = _card(dialog, "syndustryx")  # steps, a stop and a Claude Code merge
    assert len(card._in_pills) >= 3
    assert all(p.isVisibleTo(card) for p in card._in_pills)
    card.check.setChecked(False)
    assert not any(p.isVisibleTo(card) for p in card._in_pills)  # G4
    assert card.left_out.isVisibleTo(card)
    card.check.setChecked(True)
    assert all(p.isVisibleTo(card) for p in card._in_pills)


def test_space_toggles_the_tick_box(dialog):
    dialog.show()
    card = _card(dialog, "foundry")
    card.check.setFocus()
    QTest.keyClick(card.check, Qt.Key.Key_Space)
    assert not card.check.isChecked()
    QTest.keyClick(card.check, Qt.Key.Key_Space)
    assert card.check.isChecked()  # G8


def test_cancel_still_works_with_nothing_ticked(dialog):
    dialog.show()
    for card in dialog.cards:
        card.check.setChecked(False)
    assert dialog.cancel.isEnabled()
    rejected = []
    dialog.rejected.connect(lambda: rejected.append(True))
    dialog.cancel.click()
    assert rejected == [True] and not dialog.isVisible()  # G8
