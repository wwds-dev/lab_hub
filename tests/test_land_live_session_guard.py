"""Land leaves files alone that a session may still be editing (audit H1).

Spec `docs/specs/land-live-session-guard.md`. Real temporary git repos, no git
mocks. The rule looks at file times, so each test sets the times it needs.
"""

from __future__ import annotations

import os
import time

import pytest

from lab_hub import land, land_resolve as lr, repo_tidy as rt

from .test_repo_tidy import add_worktree, commit, lab, make_branch, sh  # noqa: F401


@pytest.fixture(autouse=True)
def quiet_time(no_quiet_time, monkeypatch):
    monkeypatch.setattr(rt, "QUIET_MINUTES", 15)


def age(path, minutes: float) -> float:
    """Set a file's (or folder's) time to `minutes` ago and return that time."""
    at = time.time() - minutes * 60
    os.utime(path, (at, at), follow_symlinks=False)
    return at


def main_tree(repo):
    return next(w for w in rt.worktrees(repo) if w.main)


# ------------------------------------------------------------- the rule itself
def test_a_file_changed_minutes_ago_is_named_with_its_age_and_the_wait(lab):
    (lab / "a.txt").write_text("half an edit")
    age(lab / "a.txt", 3.5)
    reason = rt.settling(lab)
    assert reason.startswith("a.txt changed 3 minutes ago: a session may still be working here.")
    assert "Try again in 12 minutes, or commit it yourself" in reason


def test_a_file_changed_seconds_ago_reads_less_than_a_minute(lab):
    (lab / "a.txt").write_text("half an edit")
    reason = rt.settling(lab)
    assert "a.txt changed less than a minute ago" in reason and "Try again in 15 minutes" in reason


def test_one_minute_is_singular(lab):
    (lab / "a.txt").write_text("y")
    at = age(lab / "a.txt", 1)
    reason = rt.settling(lab, now=at + 14 * 60 + 30)
    assert "changed 14 minutes ago" in reason and "Try again in 1 minute," in reason
    assert "changed 1 minute ago" in rt.settling(lab, now=at + 60)


def test_a_file_older_than_the_quiet_time_is_left_to_land(lab):
    (lab / "a.txt").write_text("finished edit")
    age(lab / "a.txt", 16)
    assert rt.settling(lab) == ""


def test_the_quiet_time_ends_exactly_at_fifteen_minutes(lab):
    (lab / "a.txt").write_text("y")
    at = age(lab / "a.txt", 60)
    assert rt.settling(lab, now=at + 15 * 60 - 1) != ""
    assert rt.settling(lab, now=at + 15 * 60) == ""


def test_the_newest_changed_file_decides(lab):
    commit(lab, "b.txt")
    (lab / "a.txt").write_text("old edit")
    (lab / "b.txt").write_text("new edit")
    age(lab / "a.txt", 40)
    age(lab / "b.txt", 2)
    assert rt.settling(lab).startswith("b.txt changed 2 minutes ago")
    age(lab / "b.txt", 30)
    assert rt.settling(lab) == ""


def test_an_untracked_file_counts(lab):
    (lab / "notes").mkdir()
    (lab / "notes" / "draft.md").write_text("x")
    age(lab / "notes", 60)
    assert rt.settling(lab).startswith("notes/draft.md changed less than a minute ago")
    age(lab / "notes" / "draft.md", 20)
    assert rt.settling(lab) == ""


def test_a_deleted_file_is_timed_by_the_folder_it_left(lab):
    (lab / "a.txt").unlink()          # the delete updates the folder's time
    assert rt.settling(lab).startswith("a.txt changed less than a minute ago")
    age(lab, 20)
    assert rt.settling(lab) == ""


def test_a_renamed_file_counts_once_under_its_new_name(lab):
    sh(lab, "mv", "a.txt", "b.txt")
    assert rt._open_files(lab) == ["b.txt"]


def test_a_file_a_little_ahead_of_the_clock_counts_as_just_changed(lab):
    (lab / "a.txt").write_text("y")
    age(lab / "a.txt", -0.5)
    assert "a.txt changed less than a minute ago" in rt.settling(lab)


def test_a_file_dated_well_in_the_future_says_so_and_still_stops(lab):
    (lab / "a.txt").write_text("y")
    age(lab / "a.txt", -600)
    assert rt.settling(lab).startswith("a.txt is dated in the future")


def test_a_rename_git_only_intends_to_add_does_not_hide_the_next_file(lab):
    """Review P2 (2026-11-20): ` R new<NUL>old` has its R in the second letter.
    Missing it swallowed the next entry, so a fresh edit went unexamined."""
    commit(lab, "README.md")
    commit(lab, "zz.txt")
    (lab / "README.md").rename(lab / "renamed.md")
    sh(lab, "add", "-N", "renamed.md")
    (lab / "zz.txt").write_text("half an edit")
    assert sorted(rt._open_files(lab)) == ["renamed.md", "zz.txt"]
    age(lab / "renamed.md", 60)
    age(lab, 60)
    assert rt.settling(lab).startswith("zz.txt changed less than a minute ago")


def test_a_clean_worktree_is_never_settling(lab):
    assert rt.settling(lab) == ""


def test_zero_quiet_minutes_turns_the_rule_off(lab, monkeypatch):
    (lab / "a.txt").write_text("y")
    monkeypatch.setattr(rt, "QUIET_MINUTES", 0)
    assert rt.settling(lab) == ""


# ------------------------------------------------------------------ fail closed
def test_it_fails_closed_when_git_cannot_list_the_files(tmp_path):
    assert rt.settling(tmp_path / "not-a-repo") == "could not list its changed files"


def test_it_fails_closed_above_the_file_limit(lab, monkeypatch):
    for name in ("x.md", "y.md"):
        (lab / name).write_text("x")
        age(lab / name, 60)
    assert rt.settling(lab) == ""
    monkeypatch.setattr(rt, "SETTLING_MAX_FILES", 1)
    assert rt.settling(lab).startswith("it has more than 1 changed files")


def test_it_fails_closed_when_a_files_time_cannot_be_read(lab, monkeypatch):
    (lab / "a.txt").write_text("y")
    age(lab / "a.txt", 60)
    monkeypatch.setattr(rt, "_changed_at", lambda root, rel: None)
    assert rt.settling(lab) == "could not read when a.txt last changed"


def test_a_time_that_cannot_be_read_is_none(tmp_path):
    assert rt._changed_at(tmp_path / "gone", "a.txt") is None


# ------------------------------------------- where Land and Resolve ask the rule
def test_the_main_checkout_is_not_committed_while_a_file_is_fresh(lab):
    """The gap the audit found: nobody tested the main checkout at all."""
    (lab / "a.txt").write_text("half an edit")
    wt = main_tree(lab)
    assert "a.txt changed less than a minute ago" in rt.commit_blocker(lab, wt, ())
    assert "a.txt changed" in rt.commit_blocker(lab, wt, (), land_mode=True)
    age(lab / "a.txt", 20)
    assert rt.commit_blocker(lab, wt, ()) == ""


def test_a_linked_worktree_with_no_process_inside_is_not_committed_either(lab, tmp_path):
    make_branch(lab, "feat", "f.txt")
    wt_path = add_worktree(lab, "feat", tmp_path / "wt")
    (wt_path / "f.txt").write_text("half an edit")
    wt = next(w for w in rt.worktrees(lab) if not w.main)
    assert "f.txt changed" in rt.commit_blocker(lab, wt, (), land_mode=True)
    age(wt_path / "f.txt", 20)
    assert rt.commit_blocker(lab, wt, (), land_mode=True) == ""


def test_resolve_skips_the_commit_and_says_why(lab):
    (lab / "a.txt").write_text("half an edit")
    actions, skips = rt.plan_repo("repo", lab, (), time.time())
    assert not [a for a in actions if a.kind == "commit"]
    assert any("1 changed file not committed: a.txt changed" in s.reason for s in skips)


def test_lands_prep_stops_at_a_fresh_file_and_takes_no_step(lab):
    (lab / "a.txt").write_text("half an edit")
    (lab / "loose.md").write_text("x")
    steps, stops = lr.prep("repo", lab, ())
    assert steps == []
    assert [s.target for s in stops] == [str(lab)]
    assert "changed less than a minute ago: a session may still be working here" in stops[0].reason


def test_land_does_not_commit_or_push_a_repo_with_a_fresh_edit(lab, tmp_path):
    (lab / "a.txt").write_text("half an edit")
    head = sh(lab, "rev-parse", "HEAD")
    plan = land.make_plan("repo", lab, busy=(), now=time.time())
    result = land.land(plan, log=tmp_path / "land.log", busy=(), now=time.time())
    assert result.state == "not_landed" and "a.txt changed" in result.reason
    assert sh(lab, "rev-parse", "HEAD") == head == sh(lab, "rev-parse", "origin/main")
    assert (lab / "a.txt").read_text() == "half an edit"


def test_land_commits_and_pushes_once_the_edit_has_settled(lab, tmp_path):
    (lab / "a.txt").write_text("finished edit")
    age(lab / "a.txt", 20)
    plan = land.make_plan("repo", lab, busy=(), now=time.time())
    result = land.land(plan, log=tmp_path / "land.log", busy=(), now=time.time())
    assert result.state == "landed", result
    assert sh(lab, "log", "-1", "--format=%s").startswith("Lab Hub: commit open work")
    assert sh(lab, "rev-parse", "HEAD") == sh(lab, "rev-parse", "origin/main")


# --------------------------------------------- Land's own writes are not a session's
def test_a_deletion_is_not_blamed_on_a_session_after_lab_hubs_own_write(lab):
    """Review P2 (2026-11-20): a deleted file is timed by its folder, and Land's
    untracked step changes that folder's time."""
    (lab / "a.txt").unlink()
    age(lab, 20)
    assert rt.settling(lab) == ""
    (lab / "moved-by-land.tmp").write_text("x")      # what a quarantine move does to the folder
    (lab / "moved-by-land.tmp").unlink()
    assert rt.settling(lab).startswith("a.txt changed less than a minute ago")
    rt.note_own_write(lab)
    assert rt.settling(lab) == ""


def test_a_deletion_after_lab_hubs_own_write_still_counts(lab):
    commit(lab, "b.txt")
    rt.note_own_write(lab)
    rt._OWN_WRITES[rt._own_key(lab)] -= 120          # Land wrote two minutes ago
    (lab / "b.txt").unlink()                          # a session deletes a file now
    assert rt.settling(lab).startswith("b.txt changed less than a minute ago")


def test_lab_hubs_own_write_never_excuses_a_changed_file(lab):
    (lab / "a.txt").write_text("half an edit")
    rt.note_own_write(lab)
    assert rt.settling(lab).startswith("a.txt changed less than a minute ago")


def test_land_gets_through_its_own_untracked_step_with_an_old_deletion(lab, tmp_path,
                                                                     monkeypatch):
    """The whole flow with the rule on: quarantine, .gitignore, commit, push."""
    monkeypatch.setattr(lr, "QUARANTINE_ROOT", tmp_path / "quarantine")
    commit(lab, "old.md")
    sh(lab, "push", "-q")
    (lab / "old.md").unlink()
    (lab / ".env").write_text("A=1\n")
    age(lab / ".env", 20)
    age(lab, 20)
    now = time.time()
    plan = land.make_plan("repo", lab, busy=(), now=now)
    result = land.land(plan, log=tmp_path / "land.log", busy=(), now=now)
    assert result.state == "landed", result
    assert "old.md" not in sh(lab, "ls-files").splitlines()
    assert sh(lab, "rev-parse", "HEAD") == sh(lab, "rev-parse", "origin/main")


def test_lands_prep_stops_at_a_fresh_file_in_a_linked_worktree_only(lab, tmp_path):
    make_branch(lab, "feat", "f.txt")
    wt = add_worktree(lab, "feat", tmp_path / "wt")
    (wt / "f.txt").write_text("half an edit")
    _, stops = lr.prep("repo", lab, ())
    assert [s.target for s in stops] == [str(wt)]
    assert "f.txt changed less than a minute ago" in stops[0].reason
