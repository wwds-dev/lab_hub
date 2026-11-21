"""Spec docs/specs/land-folder-link-guard.md: Land stops a branch (or a pull, or
prep's switch) that would put a symlink where the main checkout has a real or
ignored folder, before git replaces it. Real temporary git repos, no git mocks.
"""

from __future__ import annotations

import os
import subprocess

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
    assert "press Ask Claude… to remove the link from the branch" in result.reason


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
    assert any("a link at .venv, a name ignored as a folder here" in s.reason for s in skips)


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
    assert "press Ask Claude… to remove the link from main" in result.reason


def test_a_switch_link_stop_holds_every_branch_and_archives_none(lab, tmp_path, quarantine,
                                                                 monkeypatch):
    ignore(lab, ".venv/\n", push=False)
    os.symlink("x", lab / ".venv")
    sh(lab, "add", ".venv")
    sh(lab, "commit", "-qm", "a link on main")
    sh(lab, "push", "-q")
    sh(lab, "checkout", "-q", "-b", "feat")
    commit(lab, "f.txt")
    sh(lab, "checkout", "-q", "-b", "claude/redesign")
    sh(lab, "rm", "-q", "--cached", ".venv")
    (lab / ".venv").unlink()
    sh(lab, "commit", "-qm", "untrack it here")
    real_folder(lab)
    asked = fixed_verdict(monkeypatch, land_it=False)
    result = run(plan_for(lab, claude="/bin/false"), tmp_path)
    assert intact(lab) and asked == [] and lr.archives([("repo", lab)]) == []
    assert {"feat", "claude/redesign"} <= set(tidy.local_branches(lab))
    assert "main adds a link at .venv" in result.reason


def test_an_orphan_branch_is_left_to_the_merge_path(lab):
    # Review P3-1: git refuses unrelated histories itself; no misleading link stop.
    sh(lab, "checkout", "-q", "--orphan", "gh-pages")
    sh(lab, "rm", "-rq", "--cached", ".")
    commit(lab, "index.html")
    sh(lab, "checkout", "-q", "-f", "main")
    assert lr.merge_link_stop(lab, "main", "refs/heads/gh-pages") == ""


def test_is_link_stop_reads_only_the_words_before_the_path():
    assert lr.is_link_stop("not pulled — origin/main adds a link at .venv where x")
    assert lr.is_link_stop("failed — main adds a file at .venv where x")
    assert lr.is_link_stop("failed — main may add a link that git cannot check: Land again")
    assert not lr.is_link_stop("failed — could not switch to main: x adds a link at y")
    assert not lr.is_link_stop("not pulled — gitleaks found a secret")


def push_link(lab, tmp_path):
    other = other_clone(lab, tmp_path)
    for key, value in (("user.name", "t"), ("user.email", "t@t")):
        sh(other, "config", key, value)
    os.symlink("x", other / ".venv")
    sh(other, "add", ".venv")
    sh(other, "commit", "-qm", "a link from elsewhere")
    sh(other, "push", "-q")
    return other


def test_a_pull_link_stop_holds_every_branch_and_archives_none(lab, tmp_path, quarantine,
                                                               monkeypatch):
    # Review P1-2: the other branches wait behind the pull; none is triaged.
    ignore(lab, ".venv/\n")
    push_link(lab, tmp_path)
    sh(lab, "fetch", "-q")
    real_folder(lab)
    sh(lab, "checkout", "-q", "-b", "feat")
    commit(lab, "f.txt")
    sh(lab, "checkout", "-q", "main")
    asked = fixed_verdict(monkeypatch, land_it=False)
    result = run(plan_for(lab, claude="/bin/false"), tmp_path)
    assert intact(lab) and asked == [] and lr.archives([("repo", lab)]) == []
    assert "feat" in tidy.local_branches(lab)
    assert result.state == "not_landed"
    assert ("origin/main adds a link at .venv where this checkout has a real folder: press "
            "Ask Claude… to remove the link from main on the remote") in result.reason


def test_land_again_after_the_remote_is_fixed_pulls(lab, tmp_path, quarantine):
    # Review P2-1: the pull is judged on what its own fetch brings, not a stale ref.
    ignore(lab, ".venv/\n")
    other = push_link(lab, tmp_path)
    sh(lab, "fetch", "-q")  # the stale ref still has the link
    real_folder(lab)
    sh(other, "rm", "-q", ".venv")
    sh(other, "commit", "-qm", "remove the link")
    sh(other, "push", "-q")
    result = run(plan_for(lab), tmp_path)
    assert result.state == "landed", result
    assert intact(lab) and tidy.ahead_behind(lab) == (0, 0)


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
def branch_with(repo, tmp_path, branch, links=(), files=()):
    """A branch, made in its own worktree, that adds `links` (path, text)
    and `files` (path, text); returns its tip."""
    wt = tmp_path / f"wt-{branch}"
    sh(repo, "worktree", "add", "-q", "-b", branch, str(wt))
    for rel, text in files:
        (wt / rel).parent.mkdir(parents=True, exist_ok=True)
        (wt / rel).write_bytes(text if isinstance(text, bytes) else text.encode())
    for rel, text in links:
        (wt / rel).parent.mkdir(parents=True, exist_ok=True)
        os.symlink(text, wt / rel)
    sh(wt, "add", "-A")
    sh(wt, "commit", "-qm", "branch")
    sh(repo, "worktree", "remove", "--force", str(wt))
    return tidy.tip(repo, branch)


def _blob(repo, text):
    return subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=repo, input=text,
                          capture_output=True, text=True, check=True).stdout.strip()


def stop(repo, branch):
    return lr.link_stop(repo, "HEAD", f"refs/heads/{branch}")


def test_incoming_lists_new_files_and_paths_that_become_or_change_links(lab):
    os.symlink("a.txt", lab / "same")
    os.symlink("a.txt", lab / "retarget")
    sh(lab, "add", "same", "retarget")
    sh(lab, "commit", "-qm", "links")
    old = tidy.tip(lab, "main")
    os.symlink("a.txt", lab / "new")
    (lab / "retarget").unlink()
    os.symlink("b.txt", lab / "retarget")
    os.remove(lab / "a.txt")
    os.symlink("same", lab / "a.txt")  # a file that becomes a link
    commit(lab, "plain.txt")
    (lab / "same").unlink()
    sh(lab, "add", "-A")
    sh(lab, "commit", "-qm", "more")
    found = {rel: mode for rel, mode, _ in lr.incoming(lab, old, "HEAD")}
    assert found == {"a.txt": "120000", "new": "120000", "plain.txt": "100644",
                     "retarget": "120000"}
    assert lr.incoming(lab, old, "no-such-ref") is None


@pytest.mark.parametrize("links, why", [
    ([("abs", "/Users/someone/.ssh")], "at abs whose target is an absolute path"),
    ([("out", "../../elsewhere")], "at out whose target is outside the repo"),
    ([("sub/out", "../../x")], "at sub/out whose target is outside the repo"),
    ([("slash", "folder/")], "at slash whose target ends in /"),
    ([("hooks", ".git/hooks")], "at hooks whose target is inside .git"),
    ([("hooks", ".GIT/hooks")], "at hooks whose target is inside .git"),
    # Security P2-1: a lexically harmless text that a link in the tree leads out.
    ([("x/l2", ".."), ("l1", "x/l2/..")], "at l1 whose target is outside the repo"),
    ([("x/l2", ".."), ("l1", "X/L2/..")], "at l1 whose target is outside the repo"),
    ([("a", "b"), ("b", "a")], "whose target git cannot follow"),
])
def test_link_text_is_followed_through_the_tree_never_the_disk(lab, tmp_path, links, why):
    branch_with(lab, tmp_path, "feat", links=links)
    assert why in stop(lab, "feat")


def test_a_link_through_a_link_main_already_tracks_is_followed(lab, tmp_path):
    os.symlink("..", lab / "up")
    sh(lab, "add", "up")
    sh(lab, "commit", "-qm", "up")
    branch_with(lab, tmp_path, "feat", links=[("l", "up/x")])
    assert "at l whose target is outside the repo" in stop(lab, "feat")


def test_a_wanted_link_inside_the_repo_passes(lab, tmp_path):
    (lab / "docs").mkdir()
    commit(lab, "docs/v1.md")
    branch_with(lab, tmp_path, "feat", links=[("docs/latest", "v1.md"),
                                               ("top", "docs/../a.txt")])
    assert stop(lab, "feat") == ""


def test_what_is_already_in_the_checkout_decides_first(lab, tmp_path):
    branch_with(lab, tmp_path, "feat", links=[("folder", "a.txt"), ("loose.txt", "a.txt"),
                                               ("linked/inner", "x"), ("loose-link", "a.txt")])
    (lab / "folder").mkdir()
    assert stop(lab, "feat").startswith("it adds a link at folder where this checkout has a "
                                        "real folder")
    os.rmdir(lab / "folder")
    (lab / "loose.txt").write_text("local")
    assert stop(lab, "feat").startswith(
        "it adds a link at loose.txt where this checkout has a file git does not track")
    (lab / "loose.txt").unlink()
    os.symlink(str(tmp_path), lab / "linked")
    assert stop(lab, "feat").startswith("it adds a link at linked/inner behind a link")
    (lab / "linked").unlink()
    os.symlink("a.txt", lab / "loose-link")
    assert stop(lab, "feat").startswith("it adds a link at loose-link where this checkout has "
                                        "a file git does not track")


# ------------------------------------------------------------ security review fixes
def test_a_plain_file_named_like_the_folder_is_stopped_too(lab, tmp_path, quarantine):
    # Security P1-1: `git add -A` adds a `.venv` *file* as readily as a link.
    ignore(lab, ".venv/\n")
    branch_with(lab, tmp_path, "claude/agent", files=[(".venv", "/usr/bin/python3\n")])
    real_folder(lab)
    result = run(plan_for(lab), tmp_path)
    assert intact(lab) and result.state == "not_landed"
    assert ("it adds a file at .venv where this checkout has a real folder: press Ask "
            "Claude… to remove the file from the branch") in result.reason


def test_a_file_named_like_an_ignored_folder_stops_without_the_folder(lab, tmp_path):
    ignore(lab, ".venv/\n")
    branch_with(lab, tmp_path, "feat", files=[(".venv", "x")])
    assert "it adds a file at .venv, a name ignored as a folder here" in stop(lab, "feat")


def test_a_new_file_over_a_local_file_is_left_to_git(lab, tmp_path):
    # §5.1 A: only a folder at the path stops a file; file over file is git's call
    # (it refuses an untracked one itself).
    branch_with(lab, tmp_path, "feat", files=[("notes.txt", "x"), ("sub/deep.txt", "y")])
    (lab / "notes.txt").write_text("mine, untracked")
    assert stop(lab, "feat") == ""


def test_the_switch_stops_when_main_moves_while_it_is_checked(lab, tmp_path, monkeypatch):
    # Security P3-1: the switch goes only to the commit that was checked.
    sh(lab, "checkout", "-q", "-b", "claude/redesign")
    commit(lab, "r.txt")
    other = tidy.tip(lab, "main")
    sh(lab, "checkout", "-q", "main")
    moved = commit(lab, "later.txt")
    sh(lab, "checkout", "-q", "claude/redesign")
    sh(lab, "update-ref", "refs/heads/main", other)
    real = lr.link_stop

    def check_then_move(*a, **k):
        why = real(*a, **k)
        sh(lab, "update-ref", "refs/heads/main", moved)  # a fetch or agent moves main
        return why

    monkeypatch.setattr(lr, "link_stop", check_then_move)
    ok, message = lr.apply_step(lr.Step("repo", lab, "switch", str(lab)), tmp_path / "log")
    assert not ok and "main moved while Land checked it" in message
    assert tidy.current_branch(lab) == "claude/redesign"


def test_the_branchs_own_ignore_rule_counts_too(lab, tmp_path):
    # Security P3-5: the rule and the link arrive together.
    branch_with(lab, tmp_path, "feat", links=[(".venv", "x")], files=[(".gitignore", ".venv/\n")])
    assert "a link at .venv, a name ignored as a folder here" in stop(lab, "feat")


def test_bytes_that_are_not_utf8_are_a_stop_not_a_crash(lab, tmp_path):
    # Security P3-2.
    wt = tmp_path / "wt"
    sh(lab, "worktree", "add", "-q", "-b", "feat", str(wt))
    os.symlink(os.fsdecode(b"tgt\xff"), wt / "odd")
    sh(wt, "add", "-A")
    blob = _blob(wt, "x")  # APFS refuses such a name on disk: index it directly
    subprocess.run([b"git", b"update-index", b"--add", b"--cacheinfo",
                    b"100644," + blob.encode() + b",f\xff"], cwd=wt, check=True)
    sh(wt, "commit", "-qm", "odd bytes")
    sh(lab, "worktree", "remove", "--force", str(wt))
    text = stop(lab, "feat")
    assert "it adds a link at odd whose target git cannot read" in text
    assert lr.merge_link_stop(lab, "main", "refs/heads/feat").startswith("it adds a link at odd")


def test_the_stop_names_three_paths_and_counts_the_rest(lab, tmp_path):
    branch_with(lab, tmp_path, "five", links=[(f"p{i}", "/abs") for i in range(1, 6)])
    assert stop(lab, "five") == (
        "it adds a link at p1 whose target is an absolute path; also at p2, p3 "
        "and 2 more: press Ask Claude… to remove the link from the branch")
    branch_with(lab, tmp_path, "four", links=[(f"q{i}", "/abs") for i in range(1, 5)])
    assert "; also at q2, q3 and 1 more:" in stop(lab, "four")
    branch_with(lab, tmp_path, "three", links=[(f"r{i}", "/abs") for i in range(1, 4)])
    assert "; also at r2, r3: press Ask Claude… to remove" in stop(lab, "three")


@pytest.mark.parametrize("name, shown", [
    ("bad\nname", "bad?name"),
    ("rtl\u202eexe.txt", "rtl?exe.txt"),
    ("zero\u200bwidth", "zero?width"),
    ("line\u2028sep", "line?sep"),
])
def test_a_path_is_shown_without_control_or_format_characters(lab, tmp_path, name, shown):
    branch_with(lab, tmp_path, "feat", links=[(name, "/abs")])
    text = stop(lab, "feat")
    assert f"at {shown} " in text and name not in text


def test_many_links_cost_a_few_git_calls_not_one_each(lab, tmp_path, monkeypatch):
    # Security P2-2: 500 links once took 79 s.
    branch_with(lab, tmp_path, "many", links=[(f"d/l{i}", f"../a.txt") for i in range(300)])
    calls = []
    real = lr._git_bytes
    monkeypatch.setattr(lr, "_git_bytes", lambda *a, **k: calls.append(a[1]) or real(*a, **k))
    assert stop(lab, "many") == ""
    assert len(calls) <= 6, calls


def test_git_that_cannot_tell_is_a_stop(lab):
    assert lr.link_stop(lab, "HEAD", "no-such-ref").startswith(
        "it may add a link that git cannot check")
    assert cr.blocker_kind("skipped — it may add a link that git cannot check") == "link"
    assert cr.blocker_kind("skipped — it adds a file at .venv where") == "link"
    assert lr.merge_link_stop(lab, "main", "refs/heads/no-such").startswith("it may add a link")


def test_a_branch_without_links_passes(lab, tmp_path):
    sh(lab, "checkout", "-q", "-b", "feat")
    commit(lab, "f.txt")
    sh(lab, "checkout", "-q", "main")
    assert lr.merge_link_stop(lab, "main", "refs/heads/feat") == ""
