"""Spec docs/specs/land-update-gaps.md: Land never commits a link to a folder
(§3.1), and Update now goes on past a failed rebuild (§3.2, in test_apps_tab)."""

from __future__ import annotations

import os

import pytest

from lab_hub import land_resolve as lr
from lab_hub.launcher import state

from .test_land_resolve import needs_gitleaks, plan_for, quarantine, run  # noqa: F401
from .test_repo_tidy import add_worktree, lab, make_branch, sh  # noqa: F401


def ignore(repo, text):
    (repo / ".gitignore").write_text(text)
    sh(repo, "add", ".gitignore")
    sh(repo, "commit", "-qm", "ignore")


# ------------------------------------------------------------ which links count
def test_a_link_to_a_folder_is_a_folder_link(tmp_path, lab):
    (tmp_path / "real").mkdir()
    os.symlink(tmp_path / "real", lab / "venv")
    assert lr.folder_link(lab, "venv")


def test_a_link_to_a_file_nothing_ignores_is_committed_as_before(tmp_path, lab):
    (tmp_path / "f.txt").write_text("x")
    os.symlink(tmp_path / "f.txt", lab / "f-link")
    assert not lr.folder_link(lab, "f-link")
    assert not lr.folder_link(lab, "a.txt")  # a plain file is never a link


def test_a_link_whose_name_is_ignored_as_a_folder_counts_even_to_a_file(tmp_path, lab):
    # The SONAR case: `.venv/` matches the folder, not the link.
    ignore(lab, ".venv/\n")
    (tmp_path / "f.txt").write_text("x")
    os.symlink(tmp_path / "f.txt", lab / ".venv")
    assert sh(lab, "ls-files", "--others", "--exclude-standard") == ".venv"  # git would add it
    assert lr.folder_link(lab, ".venv")


def test_a_folder_rule_in_a_nested_gitignore_or_info_exclude_counts(tmp_path, lab):
    (lab / "sub").mkdir()
    (lab / "sub" / ".gitignore").write_text("build/\n")
    os.symlink(tmp_path / "nowhere", lab / "sub" / "build")
    assert lr.folder_link(lab, "sub/build")
    exclude = lab / ".git" / "info" / "exclude"
    exclude.parent.mkdir(exist_ok=True)
    exclude.write_text("cache/\n")
    os.symlink(tmp_path / "nowhere", lab / "cache")
    assert lr.folder_link(lab, "cache")
    os.symlink(tmp_path / "nowhere", lab / "other")
    assert not lr.folder_link(lab, "other")  # broken, not a folder, not ignored


def test_a_broken_link_written_as_a_folder_counts(lab):
    os.symlink("../gone/", lab / "gone-dir")
    assert lr.folder_link(lab, "gone-dir")


def test_a_gitignore_that_is_itself_a_link_is_not_read(tmp_path, lab):
    (tmp_path / "rules").write_text("thing/\n")
    os.symlink(tmp_path / "rules", lab / ".gitignore")
    os.symlink(tmp_path / "nowhere", lab / "thing")
    assert not lr.ignored_as_folder(lab, "thing")  # git ignores such a .gitignore too


def test_when_git_cannot_tell_the_link_is_not_committed(tmp_path, lab, monkeypatch):
    os.symlink(tmp_path / "nowhere", lab / "x")
    real = lr.rt.git
    monkeypatch.setattr(lr.rt, "git", lambda repo, *a, **k: (
        (128, "", "boom") if "check-ignore" in a else real(repo, *a, **k)))
    assert lr.folder_link(lab, "x")


# ------------------------------------------------------------ the 17 Nov SONAR case, end to end
@needs_gitleaks
def test_a_venv_link_in_an_agent_worktree_is_ignored_not_committed(lab, tmp_path, quarantine):
    ignore(lab, ".venv/\n/.claude/\n")
    sh(lab, "push", "-q")
    (lab / ".venv" / "bin").mkdir(parents=True)
    (lab / ".venv" / "bin" / "python").write_text("the real venv")
    make_branch(lab, "agent", "g.txt")
    wt = add_worktree(lab, "agent", lab / ".claude" / "worktrees" / "agent")
    os.symlink(lab / ".venv", wt / ".venv")
    (wt / "new.txt").write_text("new work")

    plan = plan_for(lab)
    assert "ignore 1 link to a folder without committing it" in plan.sentence
    step = next(s for s in plan.prep if s.kind == "untracked")
    assert step.links == (".venv",) and ".venv" not in step.files
    assert "ignore links to folders (never committed): .venv" in step.label
    result = run(plan, tmp_path)
    assert result.state == "landed", result

    assert ".venv" not in sh(lab, "ls-files").splitlines()
    assert "/.venv" in sh(lab, "show", "main:.gitignore").splitlines()
    assert (lab / ".venv").is_dir() and not (lab / ".venv").is_symlink()
    assert (lab / ".venv" / "bin" / "python").read_text() == "the real venv"
    assert (lab / "new.txt").read_text() == "new work"
    if wt.exists():
        assert (wt / ".venv").is_symlink()  # left where it was, not quarantined
    assert not quarantine.exists() or not any(quarantine.rglob(".venv"))
    assert "IGNORED link to a folder" in (tmp_path / "land.log").read_text()
    assert lr.open_items(lab) == []


@needs_gitleaks
def test_a_link_that_appears_after_the_preview_is_still_not_committed(lab, tmp_path, quarantine):
    # Previewed as a plain file; by the time Land applies it, it is a folder link.
    make_branch(lab, "agent", "g.txt")
    wt = add_worktree(lab, "agent", tmp_path / "wt")
    (wt / "venv").write_text("a file at preview time")
    plan = plan_for(lab)
    step = next(s for s in plan.prep if s.kind == "untracked")
    assert step.files == ("venv",)
    (wt / "venv").unlink()
    (tmp_path / "real").mkdir()
    os.symlink(tmp_path / "real", wt / "venv")
    ok, what = lr.apply_step(step, tmp_path / "land.log", busy=())
    assert ok, what
    assert "0 committed" in what and "1 link to a folder ignored (venv)" in what
    assert "venv" not in sh(wt, "ls-files").splitlines()
    assert "/venv" in (wt / ".gitignore").read_text().splitlines()


# ------------------------------------------------------------ §3.3 wording
@pytest.mark.parametrize("n, text", [(1, "1 commit further on"), (3, "3 commits further on")])
def test_how_far_behind_reads_right_for_one(n, text):
    assert state.commits_further(n) == text


def test_a_name_starting_with_a_colon_is_not_read_as_pathspec_magic(tmp_path, lab):
    # Review P3-1: ":foo/" was checked as "foo/".
    ignore(lab, ":foo/\n")
    (tmp_path / "f.txt").write_text("x")
    os.symlink(tmp_path / "f.txt", lab / ":foo")
    assert lr.ignored_as_folder(lab, ":foo")
    ignore(lab, "foo/\n")
    assert not lr.ignored_as_folder(lab, ":foo")


def test_a_git_that_cannot_run_counts_as_ignored(tmp_path, lab, monkeypatch):
    # Review P3-2: rt.git turns a spawn error or timeout into rc 1 with the error.
    os.symlink(tmp_path / "nowhere", lab / "x")
    real = lr.rt.git
    monkeypatch.setattr(lr.rt, "git", lambda repo, *a, **k: (
        (1, "", "timed out") if "check-ignore" in a else real(repo, *a, **k)))
    assert lr.ignored_as_folder(lab, "x")


def test_a_gitignore_reached_through_a_swapped_folder_is_not_read(tmp_path, lab):
    # Security P3-3: a parent folder that is now a link to elsewhere.
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / ".gitignore").write_text("thing/\n")
    os.symlink(elsewhere, lab / "sub")
    assert not lr.ignored_as_folder(lab, "sub/thing")


def test_a_link_that_cannot_be_read_is_never_committed(tmp_path, lab, monkeypatch):
    os.symlink(tmp_path / "nowhere", lab / "x")

    def unreadable(path):
        raise OSError("gone")

    monkeypatch.setattr(lr.os, "readlink", unreadable)
    assert lr.folder_link(lab, "x")


def test_a_gitignore_linked_to_a_file_inside_the_repo_is_not_read_either(tmp_path, lab):
    # git 2.32+ does not follow a .gitignore that is a link, wherever it points.
    (lab / "rules.txt").write_text("thing/\n")
    os.symlink("rules.txt", lab / ".gitignore")
    os.symlink(tmp_path / "nowhere", lab / "thing")
    assert sh(lab, "ls-files", "--others", "--exclude-standard").count("thing") == 1
    assert not lr.ignored_as_folder(lab, "thing")


@needs_gitleaks
def test_a_worktree_whose_only_untracked_entry_is_a_folder_link_is_still_tidied(
        lab, tmp_path, quarantine):
    make_branch(lab, "agent", "g.txt")
    wt = add_worktree(lab, "agent", tmp_path / "wt")
    (tmp_path / "real").mkdir()
    os.symlink(tmp_path / "real", wt / "venv")
    plan = plan_for(lab)
    steps = [s for s in plan.prep if s.kind == "untracked"]
    assert len(steps) == 1 and steps[0].links == ("venv",) and steps[0].files == ()
    result = run(plan, tmp_path)
    assert result.state == "landed", result
    assert "/venv" in sh(lab, "show", "main:.gitignore").splitlines()
    assert "venv" not in sh(lab, "ls-files").splitlines()
