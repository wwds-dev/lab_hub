"""Resolve and Review branches, on real temporary git repos (no git mocks).

Spec `docs/specs/repo-tidy.md`, section 5: one test per guard.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

from lab_hub import repo_tidy as tidy

OLD = time.time() + 10 * 24 * 3600  # "now", ten days after the fixtures were made


def sh(cwd: Path, *args: str) -> str:
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True, env=env).stdout.strip()


def commit(repo: Path, name: str, text: str = "x") -> str:
    (repo / name).write_text(text)
    sh(repo, "add", name)
    sh(repo, "commit", "-qm", f"add {name}")
    return sh(repo, "rev-parse", "HEAD")


@pytest.fixture
def lab(tmp_path):
    """A clone of a bare origin, on main, level with it."""
    origin = tmp_path / "origin.git"
    sh(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    repo = tmp_path / "repo"
    sh(tmp_path, "clone", "-q", str(origin), str(repo))
    sh(repo, "checkout", "-q", "-b", "main")
    sh(repo, "config", "user.name", "t")
    sh(repo, "config", "user.email", "t@t")
    commit(repo, "a.txt")
    sh(repo, "push", "-q", "-u", "origin", "main")
    sh(repo, "remote", "set-head", "origin", "main")
    return repo


def kinds(plan: tidy.Plan) -> set[tuple[str, str]]:
    return {(a.kind, a.target) for a in plan.actions}


def run_plan(repo: Path, now: float = OLD, busy=()) -> tidy.Plan:
    actions, skips = tidy.plan_repo("repo", repo, busy, now)
    return tidy.Plan(tuple(actions), tuple(skips))


def squash_land(repo: Path, branch: str, name: str) -> None:
    """A branch whose change reached main as a different commit (squash merge)."""
    sh(repo, "checkout", "-q", "-b", branch)
    commit(repo, name, "same")
    sh(repo, "checkout", "-q", "main")
    commit(repo, name, "same")


# ---------------------------------------------------------------- landed
def test_a_squash_landed_branch_is_deleted_and_logged(lab, tmp_path):
    squash_land(lab, "feat", "b.txt")
    plan = run_plan(lab)
    assert ("delete_branch", "feat") in kinds(plan)

    log = tmp_path / "tidy.log"
    action = next(a for a in plan.actions if a.target == "feat")
    sha = action.sha
    assert tidy.apply(action, log, busy=(), now=OLD) == (True, "done")
    assert "feat" not in tidy.local_branches(lab)
    assert f"branch feat {sha}" in log.read_text()


def test_a_branch_with_unlanded_work_is_never_planned(lab):
    sh(lab, "checkout", "-q", "-b", "wip")
    commit(lab, "c.txt")
    sh(lab, "checkout", "-q", "main")
    assert ("delete_branch", "wip") not in kinds(run_plan(lab))
    assert [r.branch for r in tidy.unlanded([("repo", lab)])] == ["wip"]


def test_the_default_branch_is_never_planned(lab):
    assert not any(a.target == "main" and a.kind == "delete_branch"
                   for a in run_plan(lab).actions)


def test_a_branch_that_moved_after_the_preview_is_skipped(lab, tmp_path):
    squash_land(lab, "feat", "b.txt")
    action = next(a for a in run_plan(lab).actions if a.target == "feat")
    sh(lab, "checkout", "-q", "feat")
    commit(lab, "new.txt")
    sh(lab, "checkout", "-q", "main")
    done, msg = tidy.apply(action, tmp_path / "log", busy=(), now=OLD)
    assert not done and "moved" in msg
    assert "feat" in tidy.local_branches(lab)


# ------------------------------------------------------------- worktrees
def add_worktree(repo: Path, branch: str, where: Path) -> Path:
    sh(repo, "worktree", "add", "-q", str(where), branch)
    return where


def test_a_clean_worktree_on_a_landed_branch_goes_first_then_the_branch(lab, tmp_path):
    squash_land(lab, "feat", "b.txt")
    wt = add_worktree(lab, "feat", tmp_path / "wt")
    plan = run_plan(lab)
    order = [(a.kind, a.target) for a in plan.actions]
    assert order.index(("remove_worktree", str(wt))) < order.index(("delete_branch", "feat"))
    for action in plan.actions:
        assert tidy.apply(action, tmp_path / "log", busy=(), now=OLD)[0]
    assert not wt.exists()
    assert "feat" not in tidy.local_branches(lab)


def test_a_worktree_with_untracked_files_stays(lab, tmp_path):
    squash_land(lab, "feat", "b.txt")
    wt = add_worktree(lab, "feat", tmp_path / "wt")
    (wt / "scratch.txt").write_text("mine")
    plan = run_plan(lab)
    assert ("remove_worktree", str(wt)) not in kinds(plan)
    assert ("delete_branch", "feat") not in kinds(plan)  # still checked out there
    assert any("uncommitted or untracked" in s.reason for s in plan.skipped)


def test_a_worktree_with_a_process_in_it_stays(lab, tmp_path):
    squash_land(lab, "feat", "b.txt")
    wt = add_worktree(lab, "feat", tmp_path / "wt")
    plan = run_plan(lab, busy=(wt / "sub",))
    assert ("remove_worktree", str(wt)) not in kinds(plan)
    assert any("process is running" in s.reason for s in plan.skipped)


def test_busy_dirs_sees_a_real_process(tmp_path):
    proc = subprocess.Popen(["sleep", "30"], cwd=tmp_path)
    try:
        assert tidy.in_use(tmp_path, tidy.busy_dirs())
    finally:
        proc.kill()


def test_a_recent_agent_worktree_stays_but_an_old_one_goes(lab):
    squash_land(lab, "feat", "b.txt")
    wt = add_worktree(lab, "feat", lab / ".claude" / "worktrees" / "feat")
    sh(lab, "update-index", "--refresh")
    assert ("remove_worktree", str(wt)) not in kinds(run_plan(lab, now=time.time()))
    assert ("remove_worktree", str(wt)) in kinds(run_plan(lab, now=OLD))


def test_a_locked_worktree_stays(lab, tmp_path):
    squash_land(lab, "feat", "b.txt")
    wt = add_worktree(lab, "feat", tmp_path / "wt")
    sh(lab, "worktree", "lock", str(wt))
    assert ("remove_worktree", str(wt)) not in kinds(run_plan(lab))


def test_a_detached_worktree_goes_only_when_its_commit_is_in_main(lab, tmp_path):
    inside = tmp_path / "inside"
    sh(lab, "worktree", "add", "-q", "--detach", str(inside), "main")
    sh(inside, "checkout", "-q", "--detach")
    outside = tmp_path / "outside"
    sh(lab, "worktree", "add", "-q", "--detach", str(outside), "main")
    commit(outside, "only-here.txt")
    planned = kinds(run_plan(lab))
    assert ("remove_worktree", str(inside)) in planned
    assert ("remove_worktree", str(outside)) not in planned


def test_the_main_checkout_is_never_removed(lab):
    """Even when it sits on a branch that has landed."""
    squash_land(lab, "feat", "b.txt")
    sh(lab, "checkout", "-q", "feat")
    plan = run_plan(lab)
    assert not any(a.kind == "remove_worktree" for a in plan.actions)
    assert ("delete_branch", "feat") not in kinds(plan)
    assert any("own checkout" in s.reason for s in plan.skipped)


# ------------------------------------------------------------------ sync
def other_clone(lab: Path, tmp_path: Path) -> Path:
    origin = sh(lab, "remote", "get-url", "origin")
    other = tmp_path / "other"
    sh(tmp_path, "clone", "-q", origin, str(other))
    return other


def test_only_behind_and_clean_is_fast_forwarded(lab, tmp_path):
    other = other_clone(lab, tmp_path)
    commit(other, "remote.txt")
    sh(other, "push", "-q")
    sh(lab, "fetch", "-q")
    plan = run_plan(lab)
    assert ("pull", "main") in kinds(plan)
    action = next(a for a in plan.actions if a.kind == "pull")
    assert tidy.apply(action, tmp_path / "log", busy=(), now=OLD)[0]
    assert (lab / "remote.txt").exists()


def test_behind_with_uncommitted_changes_is_not_pulled(lab, tmp_path):
    other = other_clone(lab, tmp_path)
    commit(other, "remote.txt")
    sh(other, "push", "-q")
    sh(lab, "fetch", "-q")
    (lab / "a.txt").write_text("edited")
    plan = run_plan(lab)
    assert ("pull", "main") not in kinds(plan)
    assert any("would diverge" in s.reason for s in plan.skipped)


def test_only_ahead_is_pushed(lab, tmp_path):
    commit(lab, "local.txt")
    plan = run_plan(lab)
    assert ("push", "main") in kinds(plan)
    action = next(a for a in plan.actions if a.kind == "push")
    assert tidy.apply(action, tmp_path / "log", busy=(), now=OLD)[0]
    assert tidy.ahead_behind(lab) == (0, 0)


def test_a_push_is_refused_when_the_remote_moved_since_the_preview(lab, tmp_path):
    commit(lab, "local.txt")
    action = next(a for a in run_plan(lab).actions if a.kind == "push")
    other = other_clone(lab, tmp_path)
    commit(other, "remote.txt")
    sh(other, "push", "-q")
    done, msg = tidy.apply(action, tmp_path / "log", busy=(), now=OLD)
    assert not done and "diverged" in msg
    assert tidy.ahead_behind(lab) == (1, 1)  # nothing was pushed


def test_diverged_is_neither_pulled_nor_pushed(lab, tmp_path):
    other = other_clone(lab, tmp_path)
    commit(other, "remote.txt")
    sh(other, "push", "-q")
    commit(lab, "local.txt")
    sh(lab, "fetch", "-q")
    plan = run_plan(lab)
    assert not {k for k, _ in kinds(plan)} & {"pull", "push"}
    assert any("diverged" in s.reason for s in plan.skipped)


def test_a_checkout_on_another_branch_is_not_synced(lab):
    commit(lab, "local.txt")
    sh(lab, "checkout", "-q", "-b", "side")
    plan = run_plan(lab)
    assert ("push", "main") not in kinds(plan)
    assert any("not main" in s.reason for s in plan.skipped)


# ---------------------------------------------------------------- review
def unlanded_wip(lab: Path) -> tidy.BranchInfo:
    sh(lab, "checkout", "-q", "-b", "wip")
    commit(lab, "c.txt")
    commit(lab, "d.txt")
    sh(lab, "checkout", "-q", "main")
    (row,) = tidy.unlanded([("repo", lab)])
    return row


def test_review_lists_ahead_count_and_subject(lab):
    row = unlanded_wip(lab)
    assert (row.branch, row.ahead, row.subject) == ("wip", 2, "add d.txt")
    assert tidy.commit_subjects(row)[0].endswith("add d.txt")


def test_review_delete_logs_the_tip_for_restoring(lab, tmp_path):
    row = unlanded_wip(lab)
    log = tmp_path / "log"
    done, msg = tidy.delete_branch(row, log)
    assert done and row.sha in msg
    assert f"branch wip {row.sha}" in log.read_text()
    sh(lab, "branch", "wip", row.sha)  # the restore line works
    assert tidy.tip(lab, "wip") == row.sha


def test_review_delete_refuses_a_moved_or_checked_out_branch(lab, tmp_path):
    row = unlanded_wip(lab)
    wt = add_worktree(lab, "wip", tmp_path / "wt")
    assert not tidy.delete_branch(row, tmp_path / "log")[0]
    sh(lab, "worktree", "remove", str(wt))
    sh(lab, "checkout", "-q", "wip")
    commit(lab, "e.txt")
    sh(lab, "checkout", "-q", "main")
    done, msg = tidy.delete_branch(row, tmp_path / "log")
    assert not done and "moved" in msg


def test_review_remove_worktree_keeps_the_branch(lab, tmp_path):
    sh(lab, "checkout", "-q", "-b", "wip")
    commit(lab, "c.txt")
    sh(lab, "checkout", "-q", "main")
    add_worktree(lab, "wip", tmp_path / "wt")
    (row,) = tidy.unlanded([("repo", lab)])
    assert tidy.remove_worktree(row, tmp_path / "log", busy=())[0]
    assert "wip" in tidy.local_branches(lab)
    assert not (tmp_path / "wt").exists()


def test_review_remove_worktree_refuses_a_dirty_one(lab, tmp_path):
    sh(lab, "checkout", "-q", "-b", "wip")
    commit(lab, "c.txt")
    sh(lab, "checkout", "-q", "main")
    wt = add_worktree(lab, "wip", tmp_path / "wt")
    (wt / "c.txt").write_text("edited")
    (row,) = tidy.unlanded([("repo", lab)])
    done, msg = tidy.remove_worktree(row, tmp_path / "log", busy=())
    assert not done and "uncommitted" in msg
    assert wt.exists()


# ------------------------------------------------------- review findings
def test_a_worktree_with_ignored_files_stays(lab, tmp_path):
    """git worktree remove deletes ignored files without asking (P1)."""
    (lab / ".gitignore").write_text(".env\n__pycache__/\n")
    sh(lab, "add", ".gitignore")
    sh(lab, "commit", "-qm", "ignore")
    squash_land(lab, "feat", "b.txt")
    wt = add_worktree(lab, "feat", tmp_path / "wt")
    (wt / "__pycache__").mkdir()
    (wt / "__pycache__" / "x.pyc").write_text("")
    assert ("remove_worktree", str(wt)) in kinds(run_plan(lab))  # regenerable only
    (wt / ".env").write_text("KEY=secret")
    plan = run_plan(lab)
    assert ("remove_worktree", str(wt)) not in kinds(plan)
    assert any(".env" in s.reason for s in plan.skipped)


def test_a_paused_rebase_keeps_its_worktree(lab, tmp_path):
    wt = tmp_path / "wt"
    sh(lab, "worktree", "add", "-q", "--detach", str(wt), "main")
    gitdir = Path(sh(wt, "rev-parse", "--absolute-git-dir"))
    (gitdir / "rebase-merge").mkdir()
    plan = run_plan(lab)
    assert ("remove_worktree", str(wt)) not in kinds(plan)
    assert any("rebase is in progress" in s.reason for s in plan.skipped)


def test_without_lsof_no_worktree_is_removed(lab, tmp_path):
    squash_land(lab, "feat", "b.txt")
    wt = add_worktree(lab, "feat", tmp_path / "wt")
    plan = run_plan(lab, busy=None)
    assert ("remove_worktree", str(wt)) not in kinds(plan)
    assert any("could not check" in s.reason for s in plan.skipped)


def test_busy_dirs_fails_closed(monkeypatch):
    monkeypatch.setattr(tidy.shutil, "which", lambda *_a, **_k: None)
    assert tidy.busy_dirs() is None
    assert tidy.in_use(Path("/anything"), None)


def test_ahead_with_uncommitted_changes_is_pushed_only_after_its_commit(lab, tmp_path):
    commit(lab, "local.txt")
    (lab / "a.txt").write_text("edited")
    plan = run_plan(lab)
    order = [a.kind for a in plan.actions]
    assert order.index("commit") < order.index("push")
    push = next(a for a in plan.actions if a.kind == "push")
    done, msg = tidy.apply(push, tmp_path / "log", busy=(), now=OLD)
    assert not done and "uncommitted" in msg  # the commit was unticked


def test_a_default_branch_not_tracking_origin_is_not_synced(lab, tmp_path):
    commit(lab, "local.txt")
    sh(lab, "branch", "--unset-upstream")
    plan = run_plan(lab)
    assert ("push", "main") not in kinds(plan)


def test_no_log_no_delete_and_a_backup_ref_keeps_the_commits(lab, tmp_path):
    row = unlanded_wip(lab)
    blocked = tmp_path / "file"
    blocked.write_text("")
    done, msg = tidy.delete_branch(row, blocked / "log")  # parent is a file
    assert not done and "log" in msg
    assert tidy.tip(lab, "wip") == row.sha

    assert tidy.delete_branch(row, tmp_path / "log")[0]
    assert sh(lab, "rev-parse", f"{tidy.BACKUP_PREFIX}{row.sha}") == row.sha


def test_the_log_flattens_newlines_and_is_private(tmp_path):
    log = tmp_path / "log"
    assert tidy._log("one\nremote: forged line", log)
    assert len(log.read_text().splitlines()) == 1
    assert oct(log.stat().st_mode & 0o777) == "0o600"


def test_git_ignores_an_inherited_git_dir(lab, tmp_path, monkeypatch):
    other = tmp_path / "decoy"
    sh(tmp_path, "init", "-q", str(other))
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    assert tidy.default_branch(lab) == "main"


def test_lsof_seeing_nothing_counts_as_failure(monkeypatch):
    class R:
        stdout = ""
    monkeypatch.setattr(tidy.subprocess, "run", lambda *a, **k: R())
    assert tidy.busy_dirs() is None


def test_a_default_branch_tracking_another_branch_is_not_pushed(lab):
    sh(lab, "push", "-q", "origin", "main:other")
    sh(lab, "fetch", "-q")
    sh(lab, "branch", "-u", "origin/other")
    commit(lab, "local.txt")
    plan = run_plan(lab)
    assert ("push", "main") not in kinds(plan)
    assert any("does not track origin/main" in s.reason for s in plan.skipped)


def test_delete_only_removes_the_branch_at_the_planned_tip(lab, tmp_path):
    sh(lab, "checkout", "-q", "-b", "wip")
    old = commit(lab, "c.txt")
    commit(lab, "d.txt")
    sh(lab, "checkout", "-q", "main")
    done, _ = tidy._delete_branch_at(lab, "wip", old, tmp_path / "log", "test")
    assert not done
    assert "wip" in tidy.local_branches(lab)


# ------------------------------------------------------------- commit
def test_tracked_changes_are_committed_and_then_pushed(lab, tmp_path):
    (lab / "a.txt").write_text("edited")
    (lab / "secret.env").write_text("KEY=1")  # untracked: never added
    plan = run_plan(lab)
    order = [(a.kind, a.target) for a in plan.actions]
    assert order.index(("commit", str(lab))) < order.index(("push", "main"))
    assert any("1 untracked file" in s.reason for s in plan.skipped)
    for action in plan.actions:
        assert tidy.apply(action, tmp_path / "log", busy=(), now=OLD)[0], action
    assert tidy.ahead_behind(lab) == (0, 0)
    assert "secret.env" not in sh(lab, "ls-files")
    assert (lab / "secret.env").exists()
    assert sh(lab, "log", "-1", "--format=%s").startswith("Lab Hub: commit open work")


def test_a_push_without_its_commit_is_refused(lab, tmp_path):
    (lab / "a.txt").write_text("edited")
    push = next(a for a in run_plan(lab).actions if a.kind == "push")
    done, msg = tidy.apply(push, tmp_path / "log", busy=(), now=OLD)
    assert not done and "uncommitted" in msg


def test_behind_with_changes_is_committed_but_not_pushed(lab, tmp_path):
    other = other_clone(lab, tmp_path)
    commit(other, "remote.txt")
    sh(other, "push", "-q")
    sh(lab, "fetch", "-q")
    (lab / "a.txt").write_text("edited")
    planned = kinds(run_plan(lab))
    assert ("commit", str(lab)) in planned
    assert not {k for k, _ in planned} & {"push", "pull"}


def test_untracked_only_is_not_committed(lab):
    (lab / "new.txt").write_text("x")
    assert not any(a.kind == "commit" for a in run_plan(lab).actions)


def test_a_conflict_or_paused_rebase_is_not_committed(lab, tmp_path):
    (lab / "a.txt").write_text("edited")
    gitdir = Path(sh(lab, "rev-parse", "--absolute-git-dir"))
    (gitdir / "rebase-merge").mkdir()
    plan = run_plan(lab)
    assert not any(a.kind == "commit" for a in plan.actions)
    assert any("rebase is in progress" in s.reason for s in plan.skipped)


def test_a_detached_head_is_not_committed(lab):
    sh(lab, "checkout", "-q", "--detach")
    (lab / "a.txt").write_text("edited")
    assert not any(a.kind == "commit" for a in run_plan(lab).actions)


def test_a_busy_or_recent_agent_worktree_is_not_committed(lab, tmp_path):
    sh(lab, "branch", "wip")
    wt = lab / ".claude" / "worktrees" / "wip"
    sh(lab, "worktree", "add", "-q", str(wt), "wip")
    (wt / "a.txt").write_text("agent edit")
    assert ("commit", str(wt)) not in kinds(run_plan(lab, now=time.time()))
    assert ("commit", str(wt)) not in kinds(run_plan(lab, busy=(wt,)))
    assert ("commit", str(wt)) in kinds(run_plan(lab, now=OLD))


def test_a_commit_is_skipped_when_the_branch_changed(lab, tmp_path):
    (lab / "a.txt").write_text("edited")
    action = next(a for a in run_plan(lab).actions if a.kind == "commit")
    sh(lab, "checkout", "-q", "-b", "other")
    done, msg = tidy.apply(action, tmp_path / "log", busy=(), now=OLD)
    assert not done and "no longer on main" in msg


def test_unresolved_conflicts_are_not_committed(lab):
    """A conflicted stash apply leaves unmerged files and no MERGE_HEAD."""
    (lab / "a.txt").write_text("mine")
    sh(lab, "stash", "push", "-q", "-m", "test-conflict")
    commit(lab, "a.txt", "theirs")
    subprocess.run(["git", "stash", "apply", "-q"], cwd=lab, capture_output=True)
    assert tidy.has_conflicts(lab)
    plan = run_plan(lab)
    assert not any(a.kind == "commit" for a in plan.actions)
    assert any("unresolved conflicts" in s.reason for s in plan.skipped)
