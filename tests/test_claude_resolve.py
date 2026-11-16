"""Resolve conflicts with Claude (spec `docs/specs/repo-tidy.md` section 11).

Real temporary git repos; Claude Code is a stub script that edits files the
way the test tells it (STUB_MODE) and prints stream-json like the real CLI.
The repo's test command is `python3 check.py`, which fails while any tracked
file contains the word BAD.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest

from lab_hub import claude_resolve as cr
from lab_hub import repo_tidy as tidy

from .test_repo_tidy import OLD, add_worktree, commit, lab, sh  # noqa: F401 (fixture)

STUB = r'''#!{python}
import json, os, pathlib, sys, time
mode = os.environ.get("STUB_MODE") or pathlib.Path(os.environ["STUB_MODE_FILE"]).read_text().strip()
calls = pathlib.Path(os.environ["STUB_CALLS"])
calls.write_text(calls.read_text() + json.dumps(sys.argv[1:]) + "\n" if calls.exists() else json.dumps(sys.argv[1:]) + "\n")
if "--version" in sys.argv:
    print("2.1.304 (Claude Code)"); sys.exit(0)
if sys.argv[1:3] == ["auth", "status"]:
    print(json.dumps({{"loggedIn": mode != "signed_out"}})); sys.exit(0)
round_no = calls.read_text().count('"-p"')
def emit(**e): print(json.dumps(e), flush=True)
def resolve(text, keep="both"):
    out, side = [], None
    for line in text.splitlines():
        if line.startswith("<<<<<<<"): side = "ours"; continue
        if line.startswith("=======") and side: side = "theirs"; continue
        if line.startswith(">>>>>>>"): side = None; continue
        out.append(line)
    return "\n".join(out) + "\n"
cwd = pathlib.Path.cwd()
conflicted = [p for p in cwd.glob("*.txt") if "<<<<<<<" in p.read_text()]
for p in conflicted:
    emit(type="assistant", message={{"content": [{{"type": "tool_use", "name": "Edit", "input": {{"file_path": str(p)}}}}]}})
if mode == "error":
    print("boom", file=sys.stderr); sys.exit(1)
if mode == "sleep":
    time.sleep(60)
if mode == "cannot":
    emit(type="result", subtype="success", is_error=False, result="Both sides rename it.\nCANNOT RESOLVE: they disagree on the API", total_cost_usd=0.1, num_turns=2); sys.exit(0)
for p in conflicted:
    text = p.read_text()
    if mode in ("leave", "bad_then_cheat", "bad_then_newfile") and not (mode != "leave" and round_no == 1):
        continue
    new = resolve(text)
    if mode == "bad" or (mode == "bad_then_fix" and round_no == 1):
        new += "BAD\n"
    p.write_text(new)
if mode == "bad_then_fix" and round_no == 2:
    for p in cwd.glob("*.txt"):
        p.write_text(p.read_text().replace("BAD\n", ""))
if mode == "dotgit":
    main_git = pathlib.Path(os.environ["STUB_MAIN_GIT"])
    (cwd / ".git").write_text(f"gitdir: {{main_git}}\n")
if mode == "venv":
    (cwd / ".venv" / "bin").mkdir(parents=True)
    (cwd / ".venv" / "bin" / "python").write_text("#!/bin/sh\nexit 0\n")
if mode == "ignored":
    (cwd / "local.cfg").write_text("x\n")
if mode == "bad_then_cheat" and round_no == 1:
    for p in conflicted: p.write_text(p.read_text() + "BAD\n")
if mode == "bad_then_cheat" and round_no == 2:
    (cwd / "check.py").write_text("pass\n")
if mode == "bad_then_newfile" and round_no == 1:
    for p in conflicted: p.write_text(p.read_text() + "BAD\n")
if mode == "bad_then_newfile" and round_no == 2:
    (cwd / "helper.txt").write_text("x\n")
if mode == "outside":
    (cwd / "a.txt").write_text("sneaky\n")
if mode == "newfile":
    (cwd / "extra.txt").write_text("new\n")
emit(type="result", subtype="success", is_error=False, result="Merged both.", total_cost_usd=0.42, num_turns=3)
'''

CHECK = """import pathlib, subprocess, sys
files = subprocess.run(["git", "ls-files"], capture_output=True, text=True).stdout.split()
sys.exit(1 if any("BAD" in pathlib.Path(f).read_text() for f in files if f.endswith(".txt") and pathlib.Path(f).exists()) else 0)
"""

APP_CONTEXT = """# App context

## Commands
- Install deps: `<cmd>`
- Run tests: `python3 check.py` (one mode)
"""


@pytest.fixture
def stub(tmp_path, monkeypatch):
    path = tmp_path / "bin" / "claude"
    path.parent.mkdir()
    path.write_text(STUB.format(python=sys.executable))
    path.chmod(0o755)
    mode_file = tmp_path / "stub-mode"
    mode_file.write_text("both")
    monkeypatch.setenv("STUB_MODE_FILE", str(mode_file))
    monkeypatch.setenv("STUB_CALLS", str(tmp_path / "calls"))
    # The child gets `claude_env()`; keep the stub's controls in it.
    real = cr.claude_env
    monkeypatch.setattr(cr, "claude_env", lambda: {**real(),
                                                    "STUB_MODE_FILE": str(mode_file),
                                                    "STUB_CALLS": str(tmp_path / "calls"),
                                                    "STUB_MAIN_GIT": str(tmp_path / "repo" / ".git")})
    monkeypatch.setattr(cr, "work_root", lambda: tmp_path / "resolve")
    monkeypatch.setenv("STUB_MAIN_GIT", str(tmp_path / "repo" / ".git"))

    return Stub(path, mode_file)


class Stub:
    def __init__(self, path: Path, mode_file: Path) -> None:
        self.path, self.mode_file = path, mode_file

    def __str__(self) -> str:
        return str(self.path)

    def set_mode(self, mode: str) -> None:
        self.mode_file.write_text(mode)


@pytest.fixture
def conflict(lab):
    """main and feat both change c.txt; the repo has a test command."""
    (lab / "docs" / "foundry").mkdir(parents=True)
    (lab / "docs" / "foundry" / "app-context.md").write_text(APP_CONTEXT)
    (lab / "check.py").write_text(CHECK)
    sh(lab, "add", "docs", "check.py")
    sh(lab, "commit", "-qm", "tests")
    commit(lab, "c.txt", "base\n")
    sh(lab, "push", "-q")
    sh(lab, "checkout", "-q", "-b", "feat")
    commit(lab, "c.txt", "base\ntheirs\n")
    sh(lab, "checkout", "-q", "main")
    commit(lab, "c.txt", "base\nours\n")
    sh(lab, "push", "-q")
    return lab


def plan(repo: Path, claude, busy=(), now=OLD) -> tidy.Plan:
    actions, skips = tidy.plan_repo("repo", repo, busy, now, str(claude) if claude else None)
    return tidy.Plan(tuple(actions), tuple(skips))


def claude_action(p: tidy.Plan) -> tidy.Action:
    return next(a for a in p.actions if a.kind == "claude_merge")


def run_all(p: tidy.Plan, claude, log: Path, stop=None, lines=None):
    out = []
    for a in p.actions:
        out.append((a, *tidy.apply(a, log, busy=(), now=OLD, claude=str(claude),
                                   progress=(lines.append if lines is not None else None),
                                   stop=stop)))
    return out


def unchanged(repo: Path, main_sha: str, feat_sha: str, root: Path) -> None:
    assert tidy.tip(repo, "main") == main_sha
    assert tidy.tip(repo, "feat") == feat_sha
    assert tidy.tracked_clean(repo) and not tidy.paused_operation(repo)
    assert not root.exists() or not any(root.iterdir()), "temporary worktree left behind"
    assert len(tidy.worktrees(repo)) == 1


# ---------------------------------------------------------------- planning
def test_a_conflicting_branch_is_offered_to_claude_with_its_test_command(conflict, stub):
    p = plan(conflict, stub)
    a = claude_action(p)
    assert a.target == "feat" and a.branch == "main"
    assert "conflicts in 1 file" in a.reason and "python3 check.py" in a.reason
    assert a.detail == "python3 check.py"
    assert ("delete_branch", "feat") in {(x.kind, x.target) for x in p.actions}
    assert ("push", "main") in {(x.kind, x.target) for x in p.actions}


def test_without_claude_a_conflict_stays_for_a_person(conflict):
    p = plan(conflict, None)
    assert not any(a.kind == "claude_merge" for a in p.actions)
    assert any("Claude Code not found" in s.reason for s in p.skipped)


def test_without_a_test_command_a_conflict_is_not_offered(conflict, stub):
    sh(conflict, "rm", "-q", "docs/foundry/app-context.md", "check.py")
    sh(conflict, "commit", "-qm", "no tests")
    sh(conflict, "push", "-q")
    p = plan(conflict, stub)
    assert not any(a.kind == "claude_merge" for a in p.actions)
    assert any("no test command" in s.reason for s in p.skipped)


def test_a_busy_or_recent_branch_worktree_is_not_offered(conflict, stub, tmp_path):
    wt = add_worktree(conflict, "feat", tmp_path / "wt")
    assert not any(a.kind == "claude_merge" for a in plan(conflict, stub, busy=(wt,)).actions)
    assert any(a.kind == "claude_merge" for a in plan(conflict, stub).actions)
    sh(conflict, "worktree", "remove", str(wt))
    recent = conflict / ".claude" / "worktrees" / "feat"
    sh(conflict, "worktree", "add", "-q", str(recent), "feat")
    assert not any(a.kind == "claude_merge"
                   for a in plan(conflict, stub, now=time.time()).actions)


# ---------------------------------------------------------------- apply
def test_success_lands_a_merge_of_both_tips_and_tidies(conflict, stub, tmp_path):
    main0, feat0 = tidy.tip(conflict, "main"), tidy.tip(conflict, "feat")
    log = tmp_path / "tidy.log"
    lines: list[str] = []
    results = run_all(plan(conflict, stub), stub, log, lines=lines)
    assert all(ok for _a, ok, _m in results), results
    head = tidy.tip(conflict, "main")
    assert sh(conflict, "rev-parse", "HEAD^1") == main0
    assert sh(conflict, "rev-parse", "HEAD^2") == feat0
    assert (conflict / "c.txt").read_text() == "base\nours\ntheirs\n"
    assert "feat" not in tidy.local_branches(conflict)
    assert tidy.ahead_behind(conflict) == (0, 0)  # pushed
    assert sh(conflict, "rev-parse", "origin/main") == head
    text = log.read_text()
    assert "CLAUDE landed feat" in text and "$0.42" in text and "3 turns" in text
    assert any("Claude: Edit c.txt" in line for line in lines)
    assert any("$0.42, 3 turns" in m for _a, _ok, m in results)
    assert not any((tmp_path / "resolve").iterdir())
    assert len(tidy.worktrees(conflict)) == 1


def test_claude_is_run_headless_with_file_tools_only(conflict, stub, tmp_path):
    run_all(plan(conflict, stub), stub, tmp_path / "log")
    calls = [json.loads(line) for line in (tmp_path / "calls").read_text().splitlines()]
    argv = next(c for c in calls if "-p" in c)
    for flag in ("--restricted", "--safe-mode", "--strict-mcp-config",
                 "--no-session-persistence"):
        assert flag in argv
    assert argv[argv.index("--tools") + 1] == "Read,Edit,Write,Glob,Grep"
    assert argv[argv.index("--permission-prompts") + 1] == "none"
    assert argv[argv.index("--max-budget-usd") + 1] == "3.00"
    assert argv[argv.index("--model") + 1] == "sonnet"
    assert "bypassPermissions" not in argv and "--dangerously-skip-permissions" not in argv


def test_failing_tests_twice_change_nothing(conflict, stub, tmp_path):
    stub.set_mode("bad")
    main0, feat0 = tidy.tip(conflict, "main"), tidy.tip(conflict, "feat")
    results = run_all(plan(conflict, stub), stub, tmp_path / "log")
    a, ok, msg = next(r for r in results if r[0].kind == "claude_merge")
    assert not ok and "tests fail" in msg
    unchanged(conflict, main0, feat0, tmp_path / "resolve")
    assert (tmp_path / "calls").read_text().count('"-p"') == 2  # one fix round


def test_a_fix_round_that_makes_the_tests_pass_lands(conflict, stub, tmp_path):
    stub.set_mode("bad_then_fix")
    results = run_all(plan(conflict, stub), stub, tmp_path / "log")
    assert next(r for r in results if r[0].kind == "claude_merge")[1], results
    assert "BAD" not in (conflict / "c.txt").read_text()
    assert "fix round" in (tmp_path / "log").read_text()


def test_a_default_branch_that_already_fails_is_named(conflict, stub, tmp_path):
    stub.set_mode("bad")
    commit(conflict, "z.txt", "BAD\n")  # main itself fails check.py
    sh(conflict, "push", "-q")
    _a, ok, msg = next(r for r in run_all(plan(conflict, stub), stub, tmp_path / "log")
                       if r[0].kind == "claude_merge")
    assert not ok and "main already fails these tests" in msg


@pytest.mark.parametrize("mode, why", [
    ("error", "Claude Code failed"),
    ("cannot", "they disagree on the API"),
    ("leave", "conflict markers are left"),
    ("outside", "outside the conflict: a.txt"),
    ("newfile", "outside the conflict: extra.txt"),
])
def test_a_bad_claude_run_changes_nothing(conflict, stub, tmp_path, mode, why):
    stub.set_mode(mode)
    main0, feat0 = tidy.tip(conflict, "main"), tidy.tip(conflict, "feat")
    results = run_all(plan(conflict, stub), stub, tmp_path / "log")
    _a, ok, msg = next(r for r in results if r[0].kind == "claude_merge")
    assert not ok and why in msg, msg
    unchanged(conflict, main0, feat0, tmp_path / "resolve")
    assert "CLAUDE not landed" in (tmp_path / "log").read_text()


def test_a_branch_that_moved_after_the_preview_is_not_sent(conflict, stub, tmp_path):
    p = plan(conflict, stub)
    sh(conflict, "checkout", "-q", "feat")
    commit(conflict, "late.txt")
    sh(conflict, "checkout", "-q", "main")
    ok, msg = tidy.apply(claude_action(p), tmp_path / "log", busy=(), now=OLD, claude=str(stub))
    assert not ok and "moved" in msg
    assert not (tmp_path / "calls").exists() or '"-p"' not in (tmp_path / "calls").read_text()


def test_a_default_branch_that_moves_while_claude_works_is_not_landed(conflict, stub, tmp_path,
                                                                      monkeypatch):
    p = plan(conflict, stub)
    real = cr.run_tests

    def tests_then_move(*args, **kw):
        result = real(*args, **kw)
        commit(conflict, "meanwhile.txt")
        return result

    monkeypatch.setattr(cr, "run_tests", tests_then_move)
    ok, msg = tidy.apply(claude_action(p), tmp_path / "log", busy=(), now=OLD, claude=str(stub))
    moved = tidy.tip(conflict, "main")
    assert not ok and "moved while Claude worked" in msg
    assert sh(conflict, "log", "-1", "--format=%s") == "add meanwhile.txt"
    assert tidy.tip(conflict, "main") == moved


def test_a_busy_worktree_at_apply_time_is_skipped(conflict, stub, tmp_path):
    wt = add_worktree(conflict, "feat", tmp_path / "wt")
    p = plan(conflict, stub)
    ok, msg = tidy.apply(claude_action(p), tmp_path / "log", busy=(wt,), now=OLD,
                         claude=str(stub))
    assert not ok and "process is running" in msg


def test_a_branch_that_now_merges_cleanly_is_merged_without_claude(conflict, stub, tmp_path):
    p = plan(conflict, stub)
    commit(conflict, "c.txt", "base\n")  # main drops its side: feat merges cleanly
    ok, msg = tidy.apply(claude_action(p), tmp_path / "log", busy=(), now=OLD, claude=str(stub))
    assert ok, msg
    assert not (tmp_path / "calls").exists() or '"-p"' not in (tmp_path / "calls").read_text()


def test_a_changed_test_command_is_skipped(conflict, stub, tmp_path):
    p = plan(conflict, stub)
    ctx = conflict / "docs" / "foundry" / "app-context.md"
    ctx.write_text(APP_CONTEXT.replace("python3 check.py", "python3 -c pass"))
    sh(conflict, "commit", "-qam", "new test command")
    ok, msg = tidy.apply(claude_action(p), tmp_path / "log", busy=(), now=OLD, claude=str(stub))
    assert not ok and "test command changed" in msg


def test_stop_kills_claude_and_keeps_nothing(conflict, stub, tmp_path):
    stub.set_mode("sleep")
    main0, feat0 = tidy.tip(conflict, "main"), tidy.tip(conflict, "feat")
    stopper = cr.Stopper()
    threading.Timer(1.5, stopper.stop).start()
    started = time.monotonic()
    results = run_all(plan(conflict, stub), stub, tmp_path / "log", stop=stopper)
    assert time.monotonic() - started < 30
    _a, ok, msg = next(r for r in results if r[0].kind == "claude_merge")
    assert not ok and "stopped" in msg
    assert all(not ok for _a, ok, _m in results)
    unchanged(conflict, main0, feat0, tmp_path / "resolve")


def test_cleanup_never_removes_a_folder_outside_its_root(lab, tmp_path):
    outside = tmp_path / "keep"
    outside.mkdir()
    (outside / "f").write_text("x")
    cr._cleanup(lab, outside, tmp_path / "resolve", [])
    assert (outside / "f").exists()


# ---------------------------------------------------------------- test command
def _ctx(repo: Path, line: str) -> None:
    (repo / "docs" / "foundry").mkdir(parents=True, exist_ok=True)
    (repo / "docs" / "foundry" / "app-context.md").write_text(
        f"# x\n\n## Commands\n{line}\n\n## Other\n- Run tests: `evil`\n")


def test_command_from_app_context_takes_every_usable_span(tmp_path):
    _ctx(tmp_path, "- Run tests, every mode: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m "
                   "pytest -q` and `python3 -m unittest discover -s tests` (3.11)")
    cmd = cr.test_command(tmp_path)
    assert cmd.source == "app-context"
    assert cmd.argv == (("QT_QPA_PLATFORM=offscreen", ".venv/bin/python", "-m", "pytest", "-q"),
                        ("python3", "-m", "unittest", "discover", "-s", "tests"))


@pytest.mark.parametrize("span", ["pytest | tee x", "cd engine && pytest", "rm -rf $HOME",
                                  "bash run.sh", "python3 x.py > out", "A=1", "/bin/sh -c x",
                                  "/usr/bin/env python3 x", "../other/run", "PATH=/tmp pytest",
                                  "DYLD_INSERT_LIBRARIES=x pytest", "PYTHONPATH=x pytest",
                                  "node_modules/.bin/bash run.sh"])
def test_shell_syntax_is_never_run(tmp_path, span):
    _ctx(tmp_path, f"- Run tests: `{span}`")
    cmd = cr.test_command(tmp_path)
    assert cmd is None or cmd.source == "default"


def test_a_placeholder_falls_back_to_defaults(tmp_path):
    _ctx(tmp_path, "- Run tests (list every mode that must pass): `<cmd>`")
    assert cr.test_command(tmp_path) is None
    (tmp_path / "tests").mkdir()
    assert cr.test_command(tmp_path).argv == (("python3", "-m", "unittest", "discover", "-s", "tests"),)
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    assert cr.test_command(tmp_path).argv == (("python3", "-m", "pytest", "-q"),)
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    (tmp_path / ".venv" / "bin" / "python").write_text("")
    cmd = cr.test_command(tmp_path)
    assert cmd.argv == ((".venv/bin/python", "-m", "pytest", "-q"),) and cmd.source == "default"


def test_npm_default_needs_a_test_script_and_node_modules(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "node --test"}}))
    assert cr.test_command(tmp_path) is None
    (tmp_path / "node_modules").mkdir()
    assert cr.test_command(tmp_path).argv == (("npm", "test"),)


def test_the_claude_child_gets_no_claude_session_variables(monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "x")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://evil")
    monkeypatch.setenv("GIT_DIR", "/elsewhere")
    env = cr.claude_env()
    assert not any(k.startswith("CLAUDE") for k in env)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a-proxy-key")
    env = cr.claude_env()
    assert not any(k.startswith("ANTHROPIC_") for k in env)
    assert "GIT_DIR" not in env


def test_a_signed_out_claude_is_reported_once_in_the_preview(conflict, stub, monkeypatch):
    monkeypatch.setattr(cr, "find_claude", lambda: str(stub))
    assert cr.availability() == (str(stub), "")
    stub.set_mode("signed_out")
    assert cr.availability() == (None, cr.NOT_SIGNED_IN)
    p = tidy.plan([("repo", conflict)])
    assert not any(a.kind == "claude_merge" for a in p.actions)
    assert any("not signed in" in s.reason for s in p.skipped)


# ---------------------------------------------------------------- review fixes
def _land_result(conflict, stub, tmp_path):
    results = run_all(plan(conflict, stub), stub, tmp_path / "log")
    return next(r for r in results if r[0].kind == "claude_merge")


@pytest.mark.parametrize("mode, why", [
    ("dotgit", ".git file"),
    ("venv", "outside the conflict: .venv"),
    ("ignored", "outside the conflict: local.cfg"),
    ("bad_then_cheat", "changed tests or test configuration: check.py"),
    ("bad_then_newfile", "fix added files: helper.txt"),
])
def test_tampering_changes_nothing(conflict, stub, tmp_path, mode, why):
    (conflict / ".gitignore").write_text(".venv/\nlocal.cfg\n")
    sh(conflict, "add", ".gitignore")
    sh(conflict, "commit", "-qm", "ignore")
    sh(conflict, "push", "-q")
    stub.set_mode(mode)
    main0, feat0 = tidy.tip(conflict, "main"), tidy.tip(conflict, "feat")
    _a, ok, msg = _land_result(conflict, stub, tmp_path)
    assert not ok and why in msg, msg
    unchanged(conflict, main0, feat0, tmp_path / "resolve")


def test_markers_in_a_non_ascii_file_name_are_caught(lab, stub, tmp_path):
    (lab / "docs" / "foundry").mkdir(parents=True)
    (lab / "docs" / "foundry" / "app-context.md").write_text(APP_CONTEXT)
    (lab / "check.py").write_text("pass\n")
    sh(lab, "add", "docs", "check.py")
    sh(lab, "commit", "-qm", "tests")
    commit(lab, "café.txt", "base\n")
    sh(lab, "checkout", "-q", "-b", "feat")
    commit(lab, "café.txt", "base\ntheirs\n")
    sh(lab, "checkout", "-q", "main")
    commit(lab, "café.txt", "base\nours\n")
    sh(lab, "push", "-q")
    stub.set_mode("leave")
    main0, feat0 = tidy.tip(lab, "main"), tidy.tip(lab, "feat")
    _a, ok, msg = _land_result(lab, stub, tmp_path)
    assert not ok and "conflict markers are left in café.txt" in msg, msg
    unchanged(lab, main0, feat0, tmp_path / "resolve")


def test_a_symlink_out_of_the_repo_is_refused_before_claude(conflict, stub, tmp_path):
    sh(conflict, "checkout", "-q", "feat")
    (conflict / "out").symlink_to("/etc")
    sh(conflict, "add", "out")
    sh(conflict, "commit", "-qm", "link")
    sh(conflict, "checkout", "-q", "main")
    _a, ok, msg = _land_result(conflict, stub, tmp_path)
    assert not ok and "symlinks that point outside" in msg
    assert not (tmp_path / "calls").exists()  # Claude never ran


def test_a_branch_moved_while_testing_is_not_landed(conflict, stub, tmp_path, monkeypatch):
    p = plan(conflict, stub)
    real = cr.run_tests

    def tests_then_move(*args, **kw):
        result = real(*args, **kw)
        sh(conflict, "branch", "-f", "feat", "main")
        return result

    monkeypatch.setattr(cr, "run_tests", tests_then_move)
    main0 = tidy.tip(conflict, "main")
    ok, msg = tidy.apply(claude_action(p), tmp_path / "log", busy=(), now=OLD, claude=str(stub))
    assert not ok and "the branch moved while Claude worked" in msg
    assert tidy.tip(conflict, "main") == main0


def test_tests_that_touch_git_config_are_not_landed(conflict, stub, tmp_path, monkeypatch):
    p = plan(conflict, stub)
    real = cr.run_tests

    def tests_that_write_config(*args, **kw):
        result = real(*args, **kw)
        with open(conflict / ".git" / "config", "a") as fh:
            fh.write("[alias]\n\tx = status\n")
        return result

    monkeypatch.setattr(cr, "run_tests", tests_that_write_config)
    main0 = tidy.tip(conflict, "main")
    ok, msg = tidy.apply(claude_action(p), tmp_path / "log", busy=(), now=OLD, claude=str(stub))
    assert not ok and "git config, hooks or info" in msg
    assert tidy.tip(conflict, "main") == main0


def test_a_missing_test_program_is_not_sent_to_claude(conflict, stub, tmp_path):
    ctx = conflict / "docs" / "foundry" / "app-context.md"
    ctx.write_text(APP_CONTEXT.replace("python3 check.py", ".venv/bin/python -m pytest"))
    sh(conflict, "commit", "-qam", "venv tests")
    sh(conflict, "push", "-q")
    _a, ok, msg = _land_result(conflict, stub, tmp_path)
    assert not ok and "could not run" in msg and "does not exist" in msg
    assert (tmp_path / "calls").read_text().count('"-p"') == 1  # no fix round


def test_the_resolve_itself_refuses_a_moved_branch(conflict, stub, tmp_path):
    cmd = cr.test_command(conflict)
    out = cr.resolve(conflict, "main", "feat", "0" * 40, cmd, str(stub), tmp_path / "log",
                     cr.Stopper(), lambda _m: None, root=tmp_path / "resolve")
    assert not out.landed and "moved" in out.message


def test_a_stopped_run_skips_every_later_action(lab, tmp_path):
    from .test_repo_tidy import squash_land

    squash_land(lab, "old", "o.txt")
    action = next(a for a in plan(lab, None).actions if a.kind == "delete_branch")
    stopper = cr.Stopper()
    stopper.stop()
    assert tidy.apply(action, tmp_path / "log", busy=(), now=OLD, stop=stopper) == (
        False, "skipped — stopped")
    assert "old" in tidy.local_branches(lab)


def test_a_claude_that_hangs_is_killed_at_the_time_limit(conflict, stub, tmp_path, monkeypatch):
    stub.set_mode("sleep")
    monkeypatch.setattr(cr, "CLAUDE_TIMEOUT", 1)
    main0, feat0 = tidy.tip(conflict, "main"), tidy.tip(conflict, "feat")
    started = time.monotonic()
    _a, ok, msg = _land_result(conflict, stub, tmp_path)
    assert time.monotonic() - started < 30
    assert not ok and "longer than" in msg
    unchanged(conflict, main0, feat0, tmp_path / "resolve")


def test_malformed_stream_json_does_not_crash(tmp_path):
    script = tmp_path / "c"
    script.write_text("#!/bin/sh\necho '{\"type\":\"assistant\",\"message\":\"x\"}'\n"
                      "echo '{\"type\":\"result\",\"total_cost_usd\":\"lots\",\"num_turns\":null}'\n")
    script.chmod(0o755)
    r = cr.run_claude(str(script), "p", tmp_path, 1.0, cr.Stopper(), lambda _m: None)
    assert r.ok and r.cost == 0.0 and r.turns == 0


def test_a_result_that_is_not_a_merge_of_both_tips_is_not_landed(conflict, stub, tmp_path,
                                                                 monkeypatch):
    real = cr._Tmp.git

    def lying_git(self, *args, **kw):
        if args == ("rev-parse", "HEAD^2"):
            return 0, "0" * 40, ""
        return real(self, *args, **kw)

    monkeypatch.setattr(cr._Tmp, "git", lying_git)
    main0 = tidy.tip(conflict, "main")
    _a, ok, msg = _land_result(conflict, stub, tmp_path)
    assert not ok and "not a merge of the two tips" in msg
    assert tidy.tip(conflict, "main") == main0
