"""Land takes minutes, and says why anything stays open (spec `docs/specs/land-fast.md`).

Real temporary git repos and the Claude Code stub from `test_claude_resolve`; the
repo's test command is `python3 check.py`, which fails while a tracked .txt file
says BAD. A test run is counted by the progress line `run_tests` writes for it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lab_hub import claude_resolve as cr
from lab_hub import land, land_resolve as lr, repo_tidy as tidy

from .test_claude_resolve import (  # noqa: F401 (fixtures)
    APP_CONTEXT, CHECK, claude_calls, conflict, stub, unchanged,
)
from .test_land_resolve import fixed_verdict, quarantine  # noqa: F401 (fixture)
from .test_repo_tidy import OLD, commit, lab, sh  # noqa: F401 (fixture)


def write(repo: Path, name: str, text: str) -> None:
    (repo / name).parent.mkdir(parents=True, exist_ok=True)
    commit(repo, name, text)


def branch_from_base(repo: Path, name: str, base: str, files: dict[str, str]) -> None:
    sh(repo, "checkout", "-q", "-b", name, base)
    for path, text in files.items():
        write(repo, path, text)
    sh(repo, "checkout", "-q", "main")


def resolve(repo: Path, stub, tmp_path, branch: str):
    lines: list[str] = []
    out = cr.resolve(repo, "main", branch, tidy.tip(repo, branch), cr.test_command(repo),
                     str(stub), tmp_path / "log", cr.Stopper(), lines.append,
                     root=tmp_path / "resolve")
    return out, sum(line.startswith("  Tests: ") for line in lines), lines


@pytest.fixture
def tested(lab):
    """A repo with a test command and c.txt on main, pushed; returns the base sha."""
    (lab / "docs" / "foundry").mkdir(parents=True)
    (lab / "docs" / "foundry" / "app-context.md").write_text(APP_CONTEXT)
    (lab / "check.py").write_text(CHECK)
    sh(lab, "add", "docs", "check.py")
    sh(lab, "commit", "-qm", "tests")
    commit(lab, "c.txt", "base\n")
    write(lab, ".claude/commands/ship-feature.md", "v1\n")
    write(lab, ".claude/settings.json", "{}\n")
    sh(lab, "push", "-q")
    return lab


# ------------------------------------------------------------ 3.1 tested commits
def test_a_landed_merge_is_not_tested_again_as_the_next_base(tested, stub, tmp_path):
    base = tidy.tip(tested, "main")
    branch_from_base(tested, "feat", base, {"c.txt": "base\ntheirs\n"})
    branch_from_base(tested, "feat2", base, {"c.txt": "base\nsecond\n"})
    commit(tested, "c.txt", "base\nours\n")

    first, runs1, _ = resolve(tested, stub, tmp_path, "feat")
    assert first.landed, first.message
    assert runs1 == 2  # main first, then the merge
    second, runs2, lines = resolve(tested, stub, tmp_path, "feat2")
    assert second.landed, second.message
    assert runs2 == 1, lines  # only the merge: main is the commit just tested
    assert not any("running the tests on main first" in line for line in lines)


def test_a_new_commit_on_main_after_a_landing_is_tested_again(tested, stub, tmp_path):
    base = tidy.tip(tested, "main")
    branch_from_base(tested, "feat", base, {"c.txt": "base\ntheirs\n"})
    branch_from_base(tested, "feat2", base, {"c.txt": "base\nsecond\n"})
    commit(tested, "c.txt", "base\nours\n")
    assert resolve(tested, stub, tmp_path, "feat")[0].landed
    commit(tested, "d.txt", "someone else's commit\n")
    out, runs, _ = resolve(tested, stub, tmp_path, "feat2")
    assert out.landed and runs == 2


# ------------------------------------------------------------ 3.2 failing base
def test_a_failing_main_is_tested_once_per_land(tested, stub, tmp_path):
    base = tidy.tip(tested, "main")
    branch_from_base(tested, "feat", base, {"c.txt": "base\ntheirs\n"})
    branch_from_base(tested, "feat2", base, {"c.txt": "base\nsecond\n"})
    commit(tested, "c.txt", "base\nours\n")
    commit(tested, "z.txt", "BAD\n")
    main0 = tidy.tip(tested, "main")

    first, runs1, _ = resolve(tested, stub, tmp_path, "feat")
    second, runs2, _ = resolve(tested, stub, tmp_path, "feat2")
    assert not first.landed and runs1 == 1
    assert not second.landed and runs2 == 0
    assert second.message == first.message and cr.blocker_kind(second.message) == "base"
    assert claude_calls(tmp_path) == 0 and tidy.tip(tested, "main") == main0
    log = (tmp_path / "log").read_text()
    assert log.count("CLAUDE start feat2") == 1 and log.count("CLAUDE not landed feat2") == 1

    cr.forget_base_failures(tested)  # a new Land
    third, runs3, _ = resolve(tested, stub, tmp_path, "feat2")
    assert not third.landed and runs3 == 1


def test_a_failing_main_names_its_error_even_under_a_long_tail():
    output = "RuntimeError: Patch is already started\n" + "noise line\n" * 200
    reason = cr.base_fail_reason("main", "fail", output)
    assert "RuntimeError: Patch is already started" in reason and "(they fail)" in reason
    assert cr.base_fail_reason("main", "env", "python not found").endswith("python not found")


def test_forgetting_failures_leaves_other_repos_alone(tmp_path):
    cr._BASE_FAILED[(str(tmp_path / "a"), "1" * 40, "t")] = "why"
    cr._BASE_FAILED[(str(tmp_path / "b"), "1" * 40, "t")] = "why"
    cr.forget_base_failures(tmp_path / "a")
    assert (str(tmp_path / "b"), "1" * 40, "t") in cr._BASE_FAILED
    assert (str(tmp_path / "a"), "1" * 40, "t") not in cr._BASE_FAILED
    cr.forget_base_failures(tmp_path / "b")


# ------------------------------------------------------------ 3.3 protected files
@pytest.mark.parametrize("name, owned, protected", [
    (".claude/commands/ship-feature.md", True, False),
    (".claude/agents/engineer.md", True, False),
    (".claude/settings.json", False, True),
    (".claude/hooks/pre.sh", False, True),
    (".Claude/Settings.json", False, True),
    ("sub/.claude/commands/x.md", False, True),
    ("docs/claude/notes.md", False, False),
    ("c.txt", False, False),
    (".claudeignore", False, False),
])
def test_which_files_are_protected_and_which_are_foundrys(name, owned, protected):
    assert cr.foundry_owned(name) is owned
    assert cr.protected(name) is protected


def test_a_protected_conflict_costs_no_test_and_no_claude(tested, stub, tmp_path):
    base = tidy.tip(tested, "main")
    branch_from_base(tested, "feat", base, {".claude/settings.json": '{"a": 1}\n'})
    write(tested, ".claude/settings.json", '{"b": 2}\n')
    main0, feat0 = tidy.tip(tested, "main"), tidy.tip(tested, "feat")
    out, runs, _ = resolve(tested, stub, tmp_path, "feat")
    assert not out.landed and runs == 0 and claude_calls(tmp_path) == 0
    assert cr.blocker_kind(out.message) == "protected"
    assert ".claude/settings.json" in out.message and "press Ask Claude…" in out.message
    assert "by hand" not in out.message
    unchanged(tested, main0, feat0, tmp_path / "resolve")


def test_a_foundry_file_conflict_takes_mains_copy_without_claude(tested, stub, tmp_path):
    base = tidy.tip(tested, "main")
    branch_from_base(tested, "feat", base, {".claude/commands/ship-feature.md": "branch\n",
                                            "f.txt": "feature\n"})
    write(tested, ".claude/commands/ship-feature.md", "v2 from foundry\n")
    out, runs, lines = resolve(tested, stub, tmp_path, "feat")
    assert out.landed, out.message
    assert claude_calls(tmp_path) == 0 and runs == 2
    assert sh(tested, "show", "main:.claude/commands/ship-feature.md") == "v2 from foundry"
    assert sh(tested, "show", "main:f.txt") == "feature"
    assert any("main's copy" in line and "ship-feature.md" in line for line in lines)


def test_claude_gets_only_the_conflicts_that_are_not_foundrys(tested, stub, tmp_path):
    base = tidy.tip(tested, "main")
    branch_from_base(tested, "feat", base, {".claude/agents/engineer.md": "branch\n",
                                            "c.txt": "base\ntheirs\n"})
    write(tested, ".claude/agents/engineer.md", "foundry\n")
    commit(tested, "c.txt", "base\nours\n")
    out, _, _ = resolve(tested, stub, tmp_path, "feat")
    assert out.landed, out.message
    prompt = (tmp_path / "calls").read_text()
    assert "c.txt" in prompt and "engineer.md" not in prompt
    assert sh(tested, "show", "main:.claude/agents/engineer.md") == "foundry"


def test_a_foundry_file_main_deleted_stays_deleted(tested, stub, tmp_path):
    base = tidy.tip(tested, "main")
    branch_from_base(tested, "feat", base, {".claude/commands/ship-feature.md": "branch\n"})
    sh(tested, "rm", "-q", ".claude/commands/ship-feature.md")
    sh(tested, "commit", "-qm", "foundry dropped the command")
    out, _, _ = resolve(tested, stub, tmp_path, "feat")
    assert out.landed, out.message
    assert ".claude/commands/ship-feature.md" not in sh(tested, "ls-tree", "-r", "--name-only",
                                                       "main")


# ------------------------------------------------------------ Land's stops
def _fake_merges(monkeypatch, message_for):
    """Every Claude merge fails with `message_for(branch)`; the rest is real git."""
    real = tidy.apply
    tried = []

    def apply(action, *a, **kw):
        if action.kind == "claude_merge":
            tried.append(action.target)
            return False, "not landed — " + message_for(action.target)
        return real(action, *a, **kw)

    monkeypatch.setattr(tidy, "apply", apply)
    monkeypatch.setattr(cr, "test_command", lambda repo: type(
        "C", (), {"display": "true", "note": "", "source": "default"})())
    monkeypatch.setattr(cr, "conflicted_files", lambda *a: ["a.txt"])
    monkeypatch.setattr(cr, "timeout_note", lambda repo: "")
    return tried


def _two_conflicting(lab):
    sh(lab, "checkout", "-q", "-b", "feat")
    commit(lab, "a.txt", "theirs")
    sh(lab, "checkout", "-q", "-b", "feat2", "main")
    commit(lab, "a.txt", "theirs too")
    sh(lab, "checkout", "-q", "main")
    commit(lab, "a.txt", "ours")
    sh(lab, "push", "-q", "origin", "main")


def _land(lab, tmp_path):
    plan = land.make_plan("repo", lab, claude="/bin/false", busy=(), now=OLD)
    return land.land(plan, log=tmp_path / "land.log", busy=(), now=OLD)


def test_a_failing_main_is_one_stop_and_its_branches_stay(lab, tmp_path, quarantine,
                                                        monkeypatch):
    _two_conflicting(lab)
    asked = fixed_verdict(monkeypatch, land_it=False)
    why = cr.base_fail_reason("main", "fail",
                              "Traceback\nRuntimeError: Patch is already started")
    tried = _fake_merges(monkeypatch, lambda _b: why)
    result = _land(lab, tmp_path)
    assert sorted(tried) == ["feat", "feat2"] and asked == []
    assert result.state == "not_landed" and result.archived == 0
    assert result.reason.startswith("main's own tests fail in a clean copy")
    assert result.reason.endswith(": press Ask Claude… to fix them")
    assert "RuntimeError: Patch is already started" in result.reason
    [stop] = [n for n in result.notes if "own tests" in n]
    assert "feat" in stop and "feat2" in stop
    assert {"feat", "feat2"} <= set(tidy.local_branches(lab)) and lr.archives([("repo", lab)]) == []


def test_a_protected_conflict_is_a_stop_per_branch_and_is_never_archived(
        lab, tmp_path, quarantine, monkeypatch):
    _two_conflicting(lab)
    asked = fixed_verdict(monkeypatch, land_it=True)
    _fake_merges(monkeypatch, lambda b: cr.protected_reason([".claude/settings.json"]))
    result = _land(lab, tmp_path)
    assert asked == [] and result.archived == 0 and result.state == "not_landed"
    stops = [n for n in result.notes if ".claude/settings.json" in n]
    assert len(stops) == 2 and any("feat2" in s for s in stops)
    assert result.reason == lr.PROTECTED_STOP


def test_other_failures_still_go_to_triage(lab, tmp_path, quarantine, monkeypatch):
    _two_conflicting(lab)
    asked = fixed_verdict(monkeypatch, land_it=False)
    _fake_merges(monkeypatch, lambda b: "the tests fail after Claude's fix: x")
    result = _land(lab, tmp_path)
    assert sorted(b for b, _ in asked) == ["feat", "feat2"] and result.archived == 2


def test_a_land_forgets_its_repos_old_base_failures(lab, tmp_path):
    key = (str(lab), "1" * 40, "t")
    cr._BASE_FAILED[key] = "old"
    land.land(land.make_plan("repo", lab, claude=None, busy=(), now=OLD),
              log=tmp_path / "land.log", busy=(), now=OLD)
    assert key not in cr._BASE_FAILED


# ------------------------------------------------------------ 3.5 a merge that turned into a conflict
def test_a_plain_merge_an_earlier_merge_made_conflict_gets_a_claude_merge(
        lab, tmp_path, quarantine, monkeypatch):
    commit(lab, "a.txt", "base\n")
    sh(lab, "push", "-q", "origin", "main")
    sh(lab, "checkout", "-q", "-b", "feat")
    commit(lab, "a.txt", "base\none\n")
    sh(lab, "checkout", "-q", "-b", "feat2", "main")
    commit(lab, "a.txt", "base\ntwo\n")
    sh(lab, "checkout", "-q", "main")
    fixed_verdict(monkeypatch, land_it=False)
    tried = _fake_merges(monkeypatch, lambda b: "the tests fail after Claude's fix: x")
    plan = land.make_plan("repo", lab, claude="/bin/false", busy=(), now=OLD)
    assert [a.kind for a in plan.actions if a.target == "feat2"][0] == "merge"
    land.land(plan, log=tmp_path / "land.log", busy=(), now=OLD)
    assert tried == ["feat2"]  # planned as a plain merge, then given to Claude once


# ------------------------------------------------------------ review and security fixes
BODY = "".join(f"{i}\n" for i in range(1, 31))  # long enough for git to see a rename


def test_a_rename_into_a_foundry_folder_is_a_stop_not_a_deletion(tested, stub, tmp_path):
    """Review P1: main edits docs/x.md, the branch moves it to .claude/commands/."""
    write(tested, "docs/x.md", BODY)
    sh(tested, "push", "-q")
    base = tidy.tip(tested, "main")
    sh(tested, "checkout", "-q", "-b", "feat", base)
    (tested / ".claude" / "commands").mkdir(parents=True, exist_ok=True)
    sh(tested, "mv", "docs/x.md", ".claude/commands/x.md")
    (tested / ".claude" / "commands" / "x.md").write_text(BODY.replace("15\n", "15 branch\n"))
    sh(tested, "commit", "-qam", "move it")
    sh(tested, "checkout", "-q", "main")
    write(tested, "docs/x.md", BODY.replace("15\n", "15 main\n"))
    main0, feat0 = tidy.tip(tested, "main"), tidy.tip(tested, "feat")
    out, _, _ = resolve(tested, stub, tmp_path, "feat")
    assert not out.landed and cr.blocker_kind(out.message) == "protected", out.message
    unchanged(tested, main0, feat0, tmp_path / "resolve")


def test_in_foundry_itself_its_commands_are_never_taken_from_main(tested, stub, tmp_path):
    """Security P2: without Foundry's app-context the command files are source."""
    sh(tested, "rm", "-q", "docs/foundry/app-context.md")
    sh(tested, "commit", "-qm", "not an installed app")
    assert not cr.protected(".claude/commands/x.md", foundry_app=True)
    assert cr.protected(".claude/commands/x.md", foundry_app=False)
    assert not cr.foundry_app(tested, tidy.tip(tested, "main"))


def test_only_the_start_of_a_message_names_a_blocker():
    quoted = "the tests fail after Claude's fix: " + cr.base_fail_reason("main", "fail", "x")
    assert cr.blocker_kind("not landed — " + quoted) == ""
    assert cr.blocker_kind("not landed — Claude: CANNOT RESOLVE: " +
                           cr.protected_reason(["a"])) == ""
    assert cr.blocker_kind("not landed — " + cr.protected_reason(["a"])) == "protected"
    assert cr.blocker_kind(cr.base_fail_reason("main", "env", "x")) == "base"


def test_a_merge_fixed_in_a_second_round_is_tested_again_as_the_next_base(
        tested, stub, tmp_path):
    """Review P3-5: the fix round's copy is not clean, so it is not a base pass."""
    base = tidy.tip(tested, "main")
    branch_from_base(tested, "feat", base, {"c.txt": "base\ntheirs\n"})
    branch_from_base(tested, "feat2", base, {"c.txt": "base\nsecond\n"})
    commit(tested, "c.txt", "base\nours\n")
    stub.set_mode("bad_then_fix")
    first, _, _ = resolve(tested, stub, tmp_path, "feat")
    assert first.landed, first.message
    second, runs, _ = resolve(tested, stub, tmp_path, "feat2")
    assert second.landed and runs == 2


def test_a_stop_found_while_triage_lands_a_branch_is_not_archived(
        lab, tmp_path, quarantine, monkeypatch):
    """Review P2: _land_one can meet a stop after `blockers()` first ran."""
    _two_conflicting(lab)
    fixed_verdict(monkeypatch, land_it=True)
    _fake_merges(monkeypatch, lambda b: "the tests fail after Claude's fix: x")

    def land_one(self, info):
        self.blocked[(info.branch, info.sha)] = ("protected", "main",
                                                  cr.protected_reason([".claude/hooks/x"]))
        return False

    monkeypatch.setattr(land._Run, "_land_one", land_one)
    result = _land(lab, tmp_path)
    assert result.archived == 0 and {"feat", "feat2"} <= set(tidy.local_branches(lab))
    assert sum(".claude/hooks/x" in n for n in result.notes) == 2
