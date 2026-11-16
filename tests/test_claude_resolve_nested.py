"""Tests in the temporary worktree can see the nested repos a fresh worktree lacks.

Spec `docs/specs/land-from-tiles.md` §9 (owner: "approve section 9"). SONAR's
`sonar/macro` and `sonar/playmaker` are gitignored nested repos; Sentinel's
`agents/bug_spray` is a submodule. Real git throughout; the link is made only
for the test run and removed straight after, like the `.venv` link.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from lab_hub import claude_resolve as cr
from lab_hub import repo_tidy as rt

from .test_repo_tidy import commit, lab, sh  # noqa: F401 (fixture)


def worktree(repo: Path, tmp_path: Path, ref: str = "HEAD") -> Path:
    path = tmp_path / "wt"
    sh(repo, "worktree", "add", "-q", "--detach", str(path), ref)
    return path


def nested_repo(parent: Path, rel: str, filename: str = "mod.py", text: str = "VALUE = 1\n") -> Path:
    path = parent / rel
    path.mkdir(parents=True)
    sh(path, "init", "-q", "-b", "main")
    sh(path, "config", "user.name", "t")
    sh(path, "config", "user.email", "t@t")
    commit(path, filename, text)
    return path


def ignore(repo: Path, *names: str) -> None:
    (repo / ".gitignore").write_text("".join(f"{n}\n" for n in names))
    sh(repo, "add", ".gitignore")
    sh(repo, "commit", "-qm", "ignore")


def run(cmd_words, wt: Path, repo: Path):
    """The real test step: link, run, unlink."""
    tmp = cr._Tmp(wt, Path(sh(wt, "rev-parse", "--absolute-git-dir")))
    links: list[Path] = []
    cmd = cr.TestCommand((tuple(cmd_words),), "default")
    return cr._tests(cmd, tmp, repo, cr.Stopper(), lambda _m: None, links), links


IMPORT = ("python3", "-c", "import nested.mod")


def test_a_gitignored_nested_repo_is_copied_in_for_the_tests_and_removed_after(lab, tmp_path):
    ignore(lab, "nested/")
    nested_repo(lab, "nested")
    wt = worktree(lab, tmp_path)
    assert not (wt / "nested").exists()  # what a fresh worktree has
    result, links = run(IMPORT, wt, lab)
    assert result.status == "pass", result.output
    assert not os.path.lexists(wt / "nested")  # gone again
    assert links == []


def test_without_it_the_same_tests_fail_as_sonar_did(lab, tmp_path):
    ignore(lab, "nested/")  # ignored, but the main checkout has no nested repo either
    wt = worktree(lab, tmp_path)
    result, _ = run(IMPORT, wt, lab)
    assert result.status == "fail"
    assert "nested" in result.output


def test_the_link_is_removed_even_when_the_tests_fail(lab, tmp_path):
    ignore(lab, "nested/")
    nested_repo(lab, "nested")
    wt = worktree(lab, tmp_path)
    result, _ = run(("python3", "-c", "raise SystemExit(1)"), wt, lab)
    assert result.status == "fail" and not os.path.lexists(wt / "nested")


def test_two_nested_repos_like_sonars_macro_and_playmaker(lab, tmp_path):
    ignore(lab, "pkg/macro/", "pkg/playmaker/")
    nested_repo(lab, "pkg/macro", "m.py")
    nested_repo(lab, "pkg/playmaker", "p.py")
    wt = worktree(lab, tmp_path)
    links, problem = cr._link_env(lab, wt)
    assert problem == ""
    assert sorted(p.relative_to(wt).as_posix() for p in links) == ["pkg/macro", "pkg/playmaker"]
    assert (wt / "pkg/macro/m.py").exists() and (wt / "pkg/playmaker/p.py").exists()
    cr._unlink(links)
    assert not os.path.lexists(wt / "pkg/macro") and not os.path.lexists(wt / "pkg/playmaker")


def test_a_path_the_merge_tracks_is_refused_not_overwritten(lab, tmp_path):
    """The merge (or Claude) adds tracked files where the checkout keeps a nested repo."""
    ignore(lab, "nested/")
    nested_repo(lab, "nested")
    other = tmp_path / "other"
    sh(tmp_path, "clone", "-q", str(tmp_path / "origin.git"), str(other))
    sh(other, "config", "user.name", "t")
    sh(other, "config", "user.email", "t@t")
    (other / "nested").mkdir()
    (other / "nested" / "planted.py").write_text("print('from the merge')\n")
    sh(other, "add", "-f", "nested/planted.py")
    sh(other, "commit", "-qm", "track a file there")
    sh(other, "push", "-q", "origin", "main")
    sh(lab, "fetch", "-q", "origin")
    wt = worktree(lab, tmp_path, "origin/main")
    assert (wt / "nested" / "planted.py").exists()
    links, problem = cr._link_env(lab, wt)
    assert "nested" in problem and "tracked in the merge" in problem
    assert links == [] and not (wt / "nested").is_symlink()
    assert (wt / "nested" / "planted.py").read_text() == "print('from the merge')\n"


def test_a_leftover_untracked_directory_at_the_path_is_refused_too(lab, tmp_path):
    ignore(lab, "nested/")
    nested_repo(lab, "nested")
    wt = worktree(lab, tmp_path)
    (wt / "nested").mkdir()
    (wt / "nested" / "junk.py").write_text("x = 1\n")  # untracked, not empty
    links, problem = cr._link_env(lab, wt)
    assert "already exists" in problem and not (wt / "nested").is_symlink()
    assert links == []


# ---------------------------------------------------------------- submodules
def submodule_repo(lab, tmp_path):
    sub = nested_repo(tmp_path, "subsrc")
    sh(lab, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(sub), "agents/bug_spray")
    sh(lab, "commit", "-qm", "add submodule")
    return sub


def test_a_submodule_is_initialised_or_linked_so_its_tests_can_collect(lab, tmp_path):
    submodule_repo(lab, tmp_path)
    wt = worktree(lab, tmp_path)
    assert not (wt / "agents/bug_spray/mod.py").exists()  # git leaves it empty
    links, problem = cr._link_env(lab, wt)
    assert problem == ""
    assert (wt / "agents/bug_spray/mod.py").exists()
    cr._unlink(links)
    assert (wt / "agents/bug_spray").is_dir() and not any((wt / "agents/bug_spray").iterdir())


def test_a_changed_gitmodules_never_reaches_the_network(lab, tmp_path, monkeypatch):
    submodule_repo(lab, tmp_path)
    wt = worktree(lab, tmp_path)
    marker = tmp_path / "ran"
    (wt / ".gitmodules").write_text(
        '[submodule "agents/bug_spray"]\n\tpath = agents/bug_spray\n'
        f"\turl = ext::sh -c touch% {marker}\n")
    calls = []
    real = rt.git

    def spy(repo, *args, **kw):
        calls.append(args)
        return real(repo, *args, **kw)

    monkeypatch.setattr(cr.rt, "git", spy)
    links, problem = cr._link_env(lab, wt)
    assert not any("submodule" in a and "update" in a for a in calls)
    assert not marker.exists()
    assert (wt / "agents/bug_spray/mod.py").exists()  # the main checkout's own copy
    cr._unlink(links)


def test_submodule_update_is_run_without_hooks_and_with_only_safe_protocols(lab, tmp_path, monkeypatch):
    submodule_repo(lab, tmp_path)
    wt = worktree(lab, tmp_path)
    seen = []
    real = rt.git
    monkeypatch.setattr(cr.rt, "git", lambda repo, *a, **k: seen.append(a) or real(repo, *a, **k))
    links, _ = cr._link_env(lab, wt)
    update = next(a for a in seen if "submodule" in a and "update" in a)
    assert "core.hooksPath=/dev/null" in update
    assert "protocol.allow=never" in update and "protocol.ext.allow=never" in update
    assert "protocol.https.allow=always" in update and "protocol.git.allow=always" not in update
    assert not any("file" in a and "always" in a for a in update)
    assert "--recursive" in update and "--init" in update
    cr._unlink(links)


def test_nothing_nested_means_no_links_and_no_git_changes(lab, tmp_path):
    wt = worktree(lab, tmp_path)
    before = cr._git_state(lab)
    links, problem = cr._link_env(lab, wt)
    assert links == [] and problem == ""
    assert cr._git_state(lab) == before


def test_the_copy_has_no_git_dir_and_tests_cannot_write_through_to_the_checkout(lab, tmp_path):
    ignore(lab, "nested/")
    nested = nested_repo(lab, "nested")
    wt = worktree(lab, tmp_path)
    links, problem = cr._link_env(lab, wt)
    assert problem == "" and not (wt / "nested" / ".git").exists()
    assert not (wt / "nested").is_symlink()
    (wt / "nested" / "mod.py").write_text("VALUE = 'changed by a test'\n")
    (wt / "nested" / "new.txt").write_text("x")
    assert (nested / "mod.py").read_text() == "VALUE = 1\n"
    assert not (nested / "new.txt").exists()
    assert sh(nested, "status", "--porcelain") == ""  # the checkout's nested repo is untouched
    cr._unlink(links)


def test_a_symlink_inside_the_nested_repo_that_leaves_it_is_not_copied(lab, tmp_path):
    ignore(lab, "nested/")
    nested = nested_repo(lab, "nested")
    secret = tmp_path / "secret.txt"
    secret.write_text("not for tests")
    (nested / "escape").symlink_to(secret)
    (nested / "inside").symlink_to(nested / "mod.py")
    wt = worktree(lab, tmp_path)
    links, problem = cr._link_env(lab, wt)
    assert problem == ""
    assert not os.path.lexists(wt / "nested" / "escape")
    assert (wt / "nested" / "inside").is_symlink()
    cr._unlink(links)


def test_a_nested_repo_that_is_itself_a_symlink_is_not_followed(lab, tmp_path):
    ignore(lab, "nested/")
    real = nested_repo(tmp_path, "elsewhere")
    (lab / "nested").symlink_to(real)
    wt = worktree(lab, tmp_path)
    links, problem = cr._link_env(lab, wt)
    assert problem == "" and links == [] and not os.path.lexists(wt / "nested")
    cr._unlink(links)


@pytest.mark.parametrize("rel, ok", [
    ("sonar/macro", True), ("agents/bug_spray", True),
    (".", False), ("./", False), ("", False), ("/etc", False), ("../x", False),
    ("a/../b", False), (".git/hooks", False), (".GIT/x", False), ("a/.git", False),
    (".venv", False), ("node_modules/x", False), ('"quoted"', False),
])
def test_safe_rel(rel, ok):
    assert cr._safe_rel(rel) is ok


def test_a_successful_submodule_update_initialises_it_in_the_worktree(lab, tmp_path, monkeypatch):
    submodule_repo(lab, tmp_path)
    monkeypatch.setattr(cr, "SUBMODULE_PROTOCOLS", ("file",))  # a local path stands in for the remote
    wt = worktree(lab, tmp_path)
    links, problem = cr._link_env(lab, wt)
    assert problem == ""
    assert (wt / "agents/bug_spray/.git").exists()  # a real initialised submodule, not a copy
    assert (wt / "agents/bug_spray/mod.py").exists()
    assert links == []  # nothing to remove: it is part of the worktree now


def test_a_half_initialised_submodule_is_replaced_by_the_checkouts_copy(lab, tmp_path, monkeypatch):
    submodule_repo(lab, tmp_path)
    wt = worktree(lab, tmp_path)
    real = rt.git

    def fail_half_way(repo, *args, **kw):
        if "submodule" in args and "update" in args:
            (wt / "agents/bug_spray").mkdir(parents=True, exist_ok=True)
            (wt / "agents/bug_spray/.git").write_text("gitdir: /nowhere\n")
            return 1, "", "fatal: could not fetch the pinned commit"
        return real(repo, *args, **kw)

    monkeypatch.setattr(cr.rt, "git", fail_half_way)
    links, problem = cr._link_env(lab, wt)
    assert problem == ""
    assert (wt / "agents/bug_spray/mod.py").exists()  # not left as an empty shell
    assert not (wt / "agents/bug_spray/.git").exists()  # the copy has no .git
    cr._unlink(links)
    assert (wt / "agents/bug_spray").is_dir() and not any((wt / "agents/bug_spray").iterdir())


def test_a_reused_worktree_gets_the_same_result_the_second_time(lab, tmp_path):
    ignore(lab, "nested/")
    nested_repo(lab, "nested")
    wt = worktree(lab, tmp_path)
    for _ in range(2):  # the base run, then the merge run
        result, links = run(IMPORT, wt, lab)
        assert result.status == "pass", result.output
        assert not os.path.lexists(wt / "nested")


def test_a_crash_while_linking_leaves_nothing_behind(lab, tmp_path, monkeypatch):
    (lab / ".venv").mkdir()
    wt = worktree(lab, tmp_path)
    monkeypatch.setattr(cr, "_link_nested", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    tmp = cr._Tmp(wt, Path(sh(wt, "rev-parse", "--absolute-git-dir")))
    links: list[Path] = []
    with pytest.raises(RuntimeError):
        cr._tests(cr.TestCommand((("python3", "-c", "pass"),), "default"), tmp, lab,
                  cr.Stopper(), lambda _m: None, links)
    assert not os.path.lexists(wt / ".venv") and links == []


def test_a_nested_repo_with_a_non_ascii_name_is_found(lab, tmp_path):
    ignore(lab, "café/")
    nested_repo(lab, "café")
    wt = worktree(lab, tmp_path)
    links, problem = cr._link_env(lab, wt)
    assert problem == "" and (wt / "café" / "mod.py").exists()
    cr._unlink(links)


def test_a_tracked_symlink_parent_cannot_send_the_copy_outside_the_worktree(lab, tmp_path):
    ignore(lab, "pkg/inner/")
    nested_repo(lab, "pkg/inner")
    outside = tmp_path / "outside"
    outside.mkdir()
    sh(lab, "checkout", "-q", "-b", "evil")
    # the merge tracks `pkg` as a symlink to a folder outside the worktree
    other = tmp_path / "other"
    sh(tmp_path, "clone", "-q", str(tmp_path / "origin.git"), str(other))
    sh(other, "config", "user.name", "t")
    sh(other, "config", "user.email", "t@t")
    (other / "pkg").symlink_to(outside)
    sh(other, "add", "pkg")
    sh(other, "commit", "-qm", "pkg is a link")
    sh(other, "push", "-q", "origin", "main")
    sh(lab, "fetch", "-q", "origin")
    wt = worktree(lab, tmp_path, "origin/main")
    links, problem = cr._link_env(lab, wt)
    assert problem  # refused: tracked, or outside the worktree
    assert not any(outside.iterdir())
    cr._unlink(links)
