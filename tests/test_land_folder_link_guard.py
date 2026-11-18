"""Spec docs/specs/land-folder-link-guard.md: Land stops a branch (or a pull, or
prep's switch) that would put a symlink where the main checkout has a real or
ignored folder, before git replaces it. Real temporary git repos, no git mocks.
"""

from __future__ import annotations

import os

import pytest

from lab_hub import claude_resolve as cr
from lab_hub import land_resolve as lr
from lab_hub import repo_tidy as tidy

from .test_claude_resolve import conflict, stub  # noqa: F401 (fixtures)
from .test_land_resolve import fixed_verdict, plan_for, quarantine, run  # noqa: F401
from .test_repo_tidy import OLD, add_worktree, commit, lab, other_clone, sh  # noqa: F401


def ignore(repo, text, push=True):
    (repo / ".gitignore").write_text(text)
    sh(repo, "add", ".gitignore")
    sh(repo, "commit", "-qm", "ignore")
    if push:
        sh(repo, "push", "-q")


def real_folder(repo, name=".venv"):
    (repo / name / "bin").mkdir(parents=True)
    (repo / name / "bin" / "python").write_text("the real interpreter")


def intact(repo, name=".venv"):
    path = repo / name
    return (not path.is_symlink() and path.is_dir()
            and (path / "bin" / "python").read_text() == "the real interpreter")


def link_branch(repo, tmp_path, branch, rel=".venv", target=None):
    """An agent's worktree whose `git add -A` commits `rel` as a link (the
    SONAR case); the worktree is then removed, the branch stays."""
    wt = tmp_path / f"wt-{branch.replace('/', '-')}"
    sh(repo, "worktree", "add", "-q", "-b", branch, str(wt))
    path = wt / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(target or str(repo / rel), path)
    sh(wt, "add", "-A")
    sh(wt, "commit", "-qm", f"agent work with {rel}")
    sh(repo, "worktree", "remove", str(wt))
    return tidy.tip(repo, branch)


# ------------------------------------------------------------ the SONAR case, end to end
def test_land_stops_a_branch_whose_venv_link_would_replace_the_real_venv(
        lab, tmp_path, quarantine, monkeypatch):
    ignore(lab, ".venv/\n")
    sha = link_branch(lab, tmp_path, "claude/agent")
    assert sh(lab, "ls-tree", "claude/agent", ".venv").startswith("120000 ")
    real_folder(lab)
    main_before = tidy.tip(lab, "main")
    asked = fixed_verdict(monkeypatch, land_it=False)  # Claude must never be asked

    plan = plan_for(lab, claude="/bin/false")
    result = run(plan, tmp_path)

    assert intact(lab), "the real .venv was replaced"
    assert tidy.tip(lab, "main") == main_before
    assert sh(lab, "rev-parse", "refs/remotes/origin/main") == main_before
    assert sh(lab, "ls-remote", "origin", "refs/heads/main").split()[0] == main_before
    assert tidy.tip(lab, "claude/agent") == sha and lr.archives([("repo", lab)]) == []
    assert asked == []
    assert result.state == "not_landed", result
    assert "it adds a link at .venv where this checkout has a real folder" in result.reason
    assert "remove the link from the branch, then Land again" in result.reason


def test_without_claude_the_branch_is_still_a_named_stop(lab, tmp_path, quarantine):
    ignore(lab, ".venv/\n")
    link_branch(lab, tmp_path, "claude/agent")
    real_folder(lab)
    result = run(plan_for(lab, claude=None), tmp_path)
    assert intact(lab) and result.state == "not_landed"
    assert "it adds a link at .venv" in result.reason
    assert "install or sign in to Claude Code" not in result.reason


def test_the_preview_shows_the_branch_as_not_merged(lab, tmp_path):
    ignore(lab, ".venv/\n")
    link_branch(lab, tmp_path, "claude/agent")
    real_folder(lab)
    actions, skips = tidy.plan_repo("repo", lab, (), OLD)
    assert not any(a.kind == "merge" for a in actions)
    [skip] = [s for s in skips if s.target == "claude/agent"]
    assert skip.reason.startswith("not merged: it adds a link at .venv where this checkout "
                                  "has a real folder")


def test_a_name_ignored_as_a_folder_stops_even_without_the_folder(lab, tmp_path):
    ignore(lab, ".venv/\n")
    link_branch(lab, tmp_path, "claude/agent", target="elsewhere")
    assert not os.path.lexists(lab / ".venv")
    _, skips = tidy.plan_repo("repo", lab, (), OLD)
    assert any("a link at .venv a name ignored as a folder here" in s.reason for s in skips)


# ------------------------------------------------------------ each route
def test_the_merge_re_checks_when_the_folder_appeared_after_the_preview(lab, tmp_path):
    link_branch(lab, tmp_path, "feat", rel="data", target="x")
    actions, _ = tidy.plan_repo("repo", lab, (), OLD)
    merge = next(a for a in actions if a.kind == "merge")
    real_folder(lab, "data")
    (lab / ".git" / "info" / "exclude").write_text("data/\n")  # ignored: git would replace it
    done, message = tidy.apply(merge, tmp_path / "log", busy=(), now=OLD)
    assert not done and intact(lab, "data")
    assert message.startswith("skipped — it adds a link at data where this checkout")
    assert cr.blocker_kind(message) == "link"


def test_claudes_fast_forward_is_checked_too(conflict, stub, tmp_path):
    # `cache`, not `.venv`: the Claude merge links the checkout's own .venv in.
    sh(conflict, "checkout", "-q", "feat")
    os.symlink("x", conflict / "cache")
    sh(conflict, "add", "cache")
    sh(conflict, "commit", "-qm", "cache link")
    sh(conflict, "checkout", "-q", "main")
    real_folder(conflict, "cache")
    (conflict / ".git" / "info" / "exclude").write_text("cache/\n")
    main_before = tidy.tip(conflict, "main")
    cmd = cr.test_command(conflict)
    out = cr.resolve(conflict, "main", "feat", tidy.tip(conflict, "feat"), cmd, str(stub),
                     tmp_path / "log", cr.Stopper(), lambda _m: None, root=tmp_path / "resolve")
    assert not out.landed and out.message.startswith("it adds a link at cache")
    assert cr.blocker_kind(f"not landed — {out.message}") == "link"
    assert intact(conflict, "cache") and tidy.tip(conflict, "main") == main_before


def test_a_claude_merge_is_never_started_for_such_a_branch(conflict, stub, tmp_path):
    sh(conflict, "checkout", "-q", "feat")
    os.symlink("x", conflict / "cache")
    sh(conflict, "add", "cache")
    sh(conflict, "commit", "-qm", "cache link")
    sh(conflict, "checkout", "-q", "main")
    real_folder(conflict, "cache")
    actions, skips = tidy.plan_repo("repo", conflict, (), OLD, str(stub))
    assert not any(a.kind == "claude_merge" for a in actions)
    assert any(s.target == "feat" and "a link at cache where this checkout has a real folder"
               in s.reason for s in skips)
    assert not (tmp_path / "calls").exists()


def test_preps_switch_stops_when_the_default_branch_brings_the_link(lab, tmp_path, quarantine):
    ignore(lab, ".venv/\n", push=False)
    os.symlink("x", lab / ".venv")
    sh(lab, "add", ".venv")
    sh(lab, "commit", "-qm", "a link on main")
    sh(lab, "push", "-q")
    sh(lab, "checkout", "-q", "-b", "claude/redesign")
    sh(lab, "rm", "-q", "--cached", ".venv")
    (lab / ".venv").unlink()
    sh(lab, "commit", "-qm", "untrack it here")
    real_folder(lab)
    result = run(plan_for(lab), tmp_path)
    assert intact(lab) and tidy.current_branch(lab) == "claude/redesign"
    assert "main adds a link at .venv where this checkout has a real folder" in result.reason
    assert "remove the link from main, then Land again" in result.reason


def push_link(lab, tmp_path):
    other = other_clone(lab, tmp_path)
    for key, value in (("user.name", "t"), ("user.email", "t@t")):
        sh(other, "config", key, value)
    os.symlink("x", other / ".venv")
    sh(other, "add", ".venv")
    sh(other, "commit", "-qm", "a link from elsewhere")
    sh(other, "push", "-q")
    return other


def test_a_pull_that_brings_the_link_is_not_planned(lab, tmp_path):
    ignore(lab, ".venv/\n")
    push_link(lab, tmp_path)
    sh(lab, "fetch", "-q")
    real_folder(lab)
    actions, skips = tidy.plan_repo("repo", lab, (), OLD)
    assert not any(a.kind == "pull" for a in actions)
    assert any(s.target == "main" and s.reason.startswith(
        "not pulled: origin/main adds a link at .venv where this checkout has a real folder")
        and "remove the link from main on the remote" in s.reason for s in skips)


def test_a_pull_checks_what_it_fetched_before_it_moves(lab, tmp_path):
    ignore(lab, ".venv/\n")
    other = other_clone(lab, tmp_path)
    commit(other, "harmless.txt")
    sh(other, "push", "-q")
    sh(lab, "fetch", "-q")
    real_folder(lab)
    actions, _ = tidy.plan_repo("repo", lab, (), OLD)
    pull = next(a for a in actions if a.kind == "pull")
    os.symlink("x", other / ".venv")  # pushed after the preview
    sh(other, "add", ".venv")
    sh(other, "commit", "-qm", "a link from elsewhere")
    sh(other, "push", "-q")
    main_before = tidy.tip(lab, "main")
    done, message = tidy.apply(pull, tmp_path / "log", busy=(), now=OLD)
    assert not done and message.startswith("not pulled — origin/main adds a link at .venv")
    assert intact(lab) and tidy.tip(lab, "main") == main_before
    assert "NOT PULLED main" in (tmp_path / "log").read_text()


def test_a_plain_pull_still_fast_forwards(lab, tmp_path):
    other = other_clone(lab, tmp_path)
    commit(other, "remote.txt")
    sh(other, "push", "-q")
    sh(lab, "fetch", "-q")
    commit(other, "later.txt")  # pushed after the preview's fetch: the pull fetches it
    sh(other, "push", "-q")
    done, message = tidy.apply(tidy.Action("repo", lab, "pull", "main", "behind"),
                               tmp_path / "log", busy=(), now=OLD)
    assert done, message
    assert (lab / "remote.txt").exists() and (lab / "later.txt").exists()
    assert tidy.ahead_behind(lab) == (0, 0)


# ------------------------------------------------------------ what still lands
def test_a_wanted_link_inside_the_repo_still_lands(lab, tmp_path, quarantine):
    (lab / "docs" / "v1").mkdir(parents=True)
    commit(lab, "docs/v1/index.md")
    sh(lab, "push", "-q")
    link_branch(lab, tmp_path, "feat", rel="docs/latest", target="v1")
    result = run(plan_for(lab), tmp_path)
    assert result.state == "landed", result
    assert (lab / "docs" / "latest").is_symlink()
    assert os.readlink(lab / "docs" / "latest") == "v1"


# ------------------------------------------------------------ the helpers
def test_incoming_links_lists_only_paths_that_become_or_change_links(lab):
    os.symlink("a.txt", lab / "same")
    os.symlink("a.txt", lab / "retarget")
    sh(lab, "add", "same", "retarget")
    sh(lab, "commit", "-qm", "links")
    old = tidy.tip(lab, "main")
    os.symlink("a.txt", lab / "new")
    (lab / "retarget").unlink()
    os.symlink("b.txt", lab / "retarget")
    (lab / "b.txt").unlink(missing_ok=True)
    os.remove(lab / "a.txt")
    os.symlink("same", lab / "a.txt")  # a file that becomes a link
    commit(lab, "plain.txt")
    sh(lab, "add", "-A")
    sh(lab, "commit", "-qm", "more")
    found = dict(lr.incoming_links(lab, old, "HEAD"))
    assert sorted(found) == ["a.txt", "new", "retarget"]
    assert sh(lab, "cat-file", "blob", found["retarget"]) == "b.txt"
    assert lr.incoming_links(lab, old, "no-such-ref") is None


@pytest.mark.parametrize("rel, text, why", [
    ("abs", "/Users/someone/.ssh", "whose target is an absolute path"),
    ("out", "../../elsewhere", "whose target is outside the repo"),
    ("sub/out", "../../x", "whose target is outside the repo"),
    ("slash", "folder/", "whose target ends in /"),
    ("sub/fine", "../a.txt", ""),
])
def test_link_text_is_judged_without_following_it(lab, rel, text, why):
    blob = _blob(lab, text)
    assert lr.link_problem(lab, rel, blob) == why


def _blob(repo, text):
    import subprocess

    return subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=repo, input=text,
                          capture_output=True, text=True, check=True).stdout.strip()


def test_what_is_already_in_the_checkout_decides_first(lab, tmp_path):
    blob = _blob(lab, "x")
    (lab / "folder").mkdir()
    assert lr.link_problem(lab, "folder", blob) == "where this checkout has a real folder"
    (lab / "loose.txt").write_text("local")
    assert lr.link_problem(lab, "loose.txt", blob) == (
        "where this checkout has a file git does not track")
    assert lr.link_problem(lab, "a.txt", blob) == ""  # tracked: git owns it
    os.symlink(str(tmp_path), lab / "linked")
    assert lr.link_problem(lab, "linked/inner", blob) == "behind a link in this checkout"
    os.symlink("a.txt", lab / "loose-link")
    assert lr.link_problem(lab, "loose-link", blob) == (
        "where this checkout has a file git does not track")


def test_the_stop_names_three_paths_and_counts_the_rest(lab, tmp_path):
    old = tidy.tip(lab, "main")
    for name in ("p1", "p2", "p3", "p4", "p5"):
        os.symlink("/abs", lab / name)
    sh(lab, "add", "-A")
    sh(lab, "commit", "-qm", "five links")
    text = lr.link_stop(lab, old, "HEAD")
    assert text == ("it adds a link at p1 whose target is an absolute path; also at p2, p3 "
                    "and 2 more: remove the link from the branch, then Land again")


def test_a_path_with_control_characters_is_shown_safely(lab):
    old = tidy.tip(lab, "main")
    os.symlink("/abs", lab / "bad\nname")
    sh(lab, "add", "-A")
    sh(lab, "commit", "-qm", "odd name")
    text = lr.link_stop(lab, old, "HEAD")
    assert "bad?name" in text and "\n" not in text


def test_git_that_cannot_tell_is_a_stop(lab, monkeypatch):
    assert lr.link_stop(lab, "HEAD", "no-such-ref").startswith(
        "it may add a link that git cannot check")
    assert cr.blocker_kind("skipped — it may add a link that git cannot check") == "link"
    assert lr.merge_link_stop(lab, "main", "no-such-branch").startswith("it may add a link")


def test_a_branch_without_links_passes(lab, tmp_path):
    sh(lab, "checkout", "-q", "-b", "feat")
    commit(lab, "f.txt")
    sh(lab, "checkout", "-q", "main")
    assert lr.merge_link_stop(lab, "main", "feat") == ""
