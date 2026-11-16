"""Resolve wastes nothing on branches it cannot land (spec `docs/specs/repo-tidy.md`
section 12): a work folder without spaces, a clean copy after the first test run,
`DELETE:` for modify/delete conflicts, and the last reason per branch."""

from __future__ import annotations

from pathlib import Path

import pytest

from lab_hub import claude_resolve as cr
from lab_hub import repo_tidy as tidy

from .test_claude_resolve import (  # noqa: F401 (fixtures)
    APP_CONTEXT, CHECK, _land_result, conflict, plan, run_all, stub, unchanged,
)
from .test_repo_tidy import OLD, commit, lab, sh  # noqa: F401 (fixture)


def test_the_work_root_has_no_whitespace(tmp_path, monkeypatch):
    assert not any(c.isspace() for c in str(cr.work_root()))
    spaced = tmp_path / "Home Folder"
    monkeypatch.setattr(cr.Path, "home", classmethod(lambda cls: spaced))
    root = cr.work_root()
    assert not any(c.isspace() for c in str(root)) and "LabHub" in str(root)


def test_the_copy_is_clean_before_the_merge(conflict, stub, tmp_path):
    """A test run on main that leaves a file behind does not leak into the merge."""
    (conflict / "check.py").write_text(
        CHECK.replace("sys.exit(", 'pathlib.Path("junk.txt").write_text("x")\nsys.exit(', 1))
    sh(conflict, "commit", "-qam", "tests leave junk")
    sh(conflict, "push", "-q")
    _a, ok, msg = _land_result(conflict, stub, tmp_path)
    assert ok, msg
    assert "junk.txt" not in sh(conflict, "ls-tree", "-r", "--name-only", "main")


@pytest.fixture
def mod_delete(lab):
    """main deletes d.txt; feat changes it (and both change c.txt)."""
    (lab / "docs" / "foundry").mkdir(parents=True)
    (lab / "docs" / "foundry" / "app-context.md").write_text(APP_CONTEXT)
    (lab / "check.py").write_text(CHECK)
    sh(lab, "add", "docs", "check.py")
    sh(lab, "commit", "-qm", "tests")
    commit(lab, "c.txt", "base\n")
    commit(lab, "d.txt", "old\n")
    sh(lab, "push", "-q")
    sh(lab, "checkout", "-q", "-b", "feat")
    commit(lab, "c.txt", "base\ntheirs\n")
    commit(lab, "d.txt", "old\nchanged\n")
    sh(lab, "checkout", "-q", "main")
    commit(lab, "c.txt", "base\nours\n")
    sh(lab, "rm", "-q", "d.txt")
    sh(lab, "commit", "-qm", "drop d.txt")
    sh(lab, "push", "-q")
    return lab


def test_claude_can_delete_a_file_one_side_deleted(mod_delete, stub, tmp_path):
    stub.set_mode("delete:d.txt")
    lines: list[str] = []
    results = run_all(plan(mod_delete, stub), stub, tmp_path / "log", lines=lines)
    _a, ok, msg = next(r for r in results if r[0].kind == "claude_merge")
    assert ok, msg
    tree = sh(mod_delete, "ls-tree", "-r", "--name-only", "main")
    assert "d.txt" not in tree and "c.txt" in tree
    assert any("Deleted as Claude asked: d.txt" in line for line in lines)


@pytest.mark.parametrize("names, why", [
    ("c.txt", "both sides keep it"),
    ("check.py", "not in the conflict"),
    ("../d.txt", "not in the conflict"),
    ("d.txt,check.py", "not in the conflict"),
])
def test_a_deletion_outside_the_rule_is_refused(mod_delete, stub, tmp_path, names, why):
    stub.set_mode("delete:" + names)
    main0, feat0 = tidy.tip(mod_delete, "main"), tidy.tip(mod_delete, "feat")
    _a, ok, msg = _land_result(mod_delete, stub, tmp_path)
    assert not ok and why in msg, msg
    unchanged(mod_delete, main0, feat0, tmp_path / "resolve")


def test_without_a_deletion_the_changed_file_stays(mod_delete, stub, tmp_path):
    _a, ok, msg = _land_result(mod_delete, stub, tmp_path)
    assert ok, msg
    assert "d.txt" in sh(mod_delete, "ls-tree", "-r", "--name-only", "main")


def test_requested_deletions_are_read_from_the_reply():
    text = "Done.\nDELETE: a/b.txt\n`DELETE: c d.txt`\nnot DELETE: x\n  DELETE:e.txt  "
    assert cr.requested_deletions(text) == ["a/b.txt", "c d.txt", "e.txt"]
    assert cr.requested_deletions("Merged both.") == []


def test_the_merge_prompt_explains_delete():
    assert "DELETE: <path>" in cr.merge_prompt("feat", "main", ["d.txt"])


A, B = "a" * 40, "b" * 40


def test_last_tries_reads_the_log(tmp_path):
    log = tmp_path / "log"
    log.write_text(
        f"2026-11-16T10:00:00 CLAUDE start feat at {A} into main at {B} in /lab/repo one\n"
        "2026-11-16T10:01:00 CLAUDE not landed feat in /lab/repo one: the tests fail "
        "(cost $0.20, 3 turns)\n"
        f"2026-11-16T10:02:00 CLAUDE start gone at {A} into main at {B} in /lab/x\n"
        "2026-11-16T10:03:00 CLAUDE not landed gone in /lab/x: Claude: CANNOT RESOLVE: no "
        "(cost $0.10, 1 turns)\n"
        f"2026-11-16T11:00:00 CLAUDE start gone at {A} into main at {B} in /lab/x\n"
        f"2026-11-16T11:01:00 CLAUDE landed gone at {A} into main as {B} in /lab/x "
        "(tests: t; cost $0.10, 1 turns)\n"
        "2026-11-16T12:00:00 CLAUDE not landed orphan in /lab/x: no start line\n"
    )
    assert cr.last_tries(log) == {
        ("/lab/repo one", "feat"): cr.LastTry(A, "2026-11-16T10:00:00", "the tests fail")}
    assert cr.last_tries(tmp_path / "missing") == {}


def test_a_real_run_is_found_by_last_tries(conflict, stub, tmp_path):
    commit(conflict, "z.txt", "BAD\n")
    sh(conflict, "push", "-q")
    _land_result(conflict, stub, tmp_path)
    tries = cr.last_tries(tmp_path / "log")
    t = tries[(str(conflict), "feat")]
    assert t.sha == tidy.tip(conflict, "feat") and "no Claude run" in t.reason


def test_review_shows_why_the_last_resolve_left_a_branch(tmp_path, monkeypatch):
    from ui import repo_tidy_dialogs as dialogs

    log = tmp_path / "log"
    monkeypatch.setattr(tidy, "log_path", lambda: log)
    rows = [tidy.BranchInfo("r", Path("/lab/r"), "feat", "main", A, 1, "d", "s", ""),
            tidy.BranchInfo("r", Path("/lab/r"), "moved", "main", "c" * 40, 1, "d", "s", "")]
    log.write_text(
        f"2026-11-16T10:00:00 CLAUDE start feat at {A} into main at {B} in /lab/r\n"
        "2026-11-16T10:01:00 CLAUDE not landed feat in /lab/r: no Claude run: pytest missing "
        "(cost $0.00, 0 turns)\n"
        f"2026-11-16T10:00:00 CLAUDE start moved at {'d' * 40} into main at {B} in /lab/r\n"
        "2026-11-16T10:01:00 CLAUDE not landed moved in /lab/r: old reason (cost $0.00, 0 turns)\n"
    )
    assert dialogs.last_resolve(rows) == {0: "2026-11-16: no Claude run: pytest missing"}


def test_a_tracked_file_the_main_tests_rewrite_is_not_merged(conflict, stub, tmp_path):
    commit(conflict, "snap.txt", "orig\n")
    (conflict / "check.py").write_text(
        CHECK.replace("sys.exit(", 'pathlib.Path("snap.txt").write_text("rewritten\\n")\nsys.exit(', 1))
    sh(conflict, "commit", "-qam", "tests rewrite a snapshot")
    sh(conflict, "push", "-q")
    _a, ok, msg = _land_result(conflict, stub, tmp_path)
    assert ok, msg
    assert sh(conflict, "show", "main:snap.txt") == "orig"


def test_a_deletion_is_literal_not_a_glob(lab, stub, tmp_path):
    """`DELETE: d[x].txt` removes that file, not dx.txt too."""
    (lab / "docs" / "foundry").mkdir(parents=True)
    (lab / "docs" / "foundry" / "app-context.md").write_text(APP_CONTEXT)
    (lab / "check.py").write_text(CHECK)
    sh(lab, "add", "docs", "check.py")
    sh(lab, "commit", "-qm", "tests")
    commit(lab, "c.txt", "base\n")
    commit(lab, "d[x].txt", "old\n")
    commit(lab, "dx.txt", "keep\n")
    sh(lab, "push", "-q")
    sh(lab, "checkout", "-q", "-b", "feat")
    commit(lab, "c.txt", "base\ntheirs\n")
    commit(lab, "d[x].txt", "old\nchanged\n")
    sh(lab, "checkout", "-q", "main")
    commit(lab, "c.txt", "base\nours\n")
    sh(lab, "rm", "-q", "--", ":(literal)d[x].txt")
    sh(lab, "commit", "-qm", "drop")
    sh(lab, "push", "-q")
    stub.set_mode("delete:d[x].txt")
    _a, ok, msg = _land_result(lab, stub, tmp_path)
    assert ok, msg
    tree = sh(lab, "ls-tree", "-r", "--name-only", "main")
    assert "dx.txt" in tree and "d[x].txt" not in tree


def test_a_repeated_deletion_line_is_fine(mod_delete, stub, tmp_path):
    stub.set_mode("delete:d.txt,d.txt")
    _a, ok, msg = _land_result(mod_delete, stub, tmp_path)
    assert ok, msg


def test_a_landed_line_clears_only_its_own_repo(tmp_path):
    log = tmp_path / "log"
    log.write_text(
        f"2026-11-16T10:00:00 CLAUDE start feat at {A} into main at {B} in /lab/x\n"
        "2026-11-16T10:01:00 CLAUDE not landed feat in /lab/x: why (cost $0.10, 1 turns)\n"
        f"2026-11-16T11:00:00 CLAUDE start feat at {A} into main at {B} in /lab/x y\n"
        f"2026-11-16T11:01:00 CLAUDE landed feat at {A} into main as {B} in /lab/x y "
        "(tests: t; cost $0.10, 1 turns)\n"
    )
    assert list(cr.last_tries(log)) == [("/lab/x", "feat")]


def test_main_is_tested_once_per_tip(conflict, stub, tmp_path):
    """A second branch into the same main tip reuses the first pass."""
    stub.set_mode("cannot")  # Claude gives up, so main stays where it is
    cmd = cr.test_command(conflict)

    def run():
        lines: list[str] = []
        out = cr.resolve(conflict, "main", "feat", tidy.tip(conflict, "feat"), cmd, str(stub),
                         tmp_path / "log", cr.Stopper(), lines.append, root=tmp_path / "resolve")
        assert not out.landed and "they disagree" in out.message
        return sum("running the tests on main first" in line for line in lines)

    assert run() == 1
    assert run() == 0
    commit(conflict, "z.txt", "main moved\n")
    assert run() == 1  # a new tip is tested again
