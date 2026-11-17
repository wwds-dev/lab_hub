"""Ask Claude: which rows go, how they group, what the prompt says, how it opens.

Spec `docs/specs/claude-handoff.md`, ADR 0004. Real temporary git repos; no
Claude Code runs: the launch line runs for real under zsh against a stand-in
`claude` that records its arguments.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

from lab_hub import handoff
from lab_hub.progress import RowView

from .test_repo_tidy import add_worktree, lab, sh  # noqa: F401

WHEN = datetime(2026, 11, 17, 15, 30)


def row(name, status, icon="needs", reason="", detail=""):
    return RowView(name, icon, status=status, reason=reason, detail=detail)


# ------------------------------------------------------------------ qualifies
@pytest.mark.parametrize("view, expected", [
    (row("P", "Needs you"), True),  # forward / no_command / Land stop
    (row("L", "Not now"), True),  # Lab Hub's own build held
    (row("U", "Cannot check", icon="unknown"), True),
    (row("R", "Not rebuilt", icon="failed"), True),  # refused before it ran
    (row("C", "Not rebuilt", icon="nothing"), True),  # cancelled before it ran
    (row("F", "Failed · exit 1", icon="failed"), True),  # a failed rebuild
    (row("A", "Landed · 2 branches archived", icon="done"), True),
    (row("OK", "Landed · 0:42", icon="done"), False),
    (row("N", "Nothing to land", icon="nothing"), False),
    (row("S", "Not reached", icon="nothing"), False),  # the owner stopped Land
    (row("T", "Needs Terminal", icon="terminal"), False),  # Update now opens it
    (row("M", "Not installed", icon="unknown"), False),
    (row("O", "Out of date", icon="needs"), False),  # Update now rebuilds it
])
def test_only_rows_lab_hub_could_not_clear_qualify(view, expected):
    assert handoff.qualifies(view) is expected


# ------------------------------------------------------------------- collect
def test_rows_group_by_repo_and_a_row_with_no_folder_is_not_sent(lab, tmp_path):
    sub = lab / "app2"
    sub.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    sh(other, "init", "-q")
    rows = [row("App1", "Needs you", reason="Move its release clone first."),
            row("App2", "Not rebuilt", icon="failed", reason="dirty checkout"),
            row("Other", "Needs you"),
            row("Fine", "Up to date", icon="done"),
            row("Lost", "Needs you")]
    paths = {"App1": lab, "App2": sub, "Other": other, "Fine": lab, "Lost": None}
    got, unplaced = handoff.collect(rows, paths, {"App1": "cd /r && git pull"})
    assert [(h.repo, [i.name for i in h.items]) for h in got] == [
        ("repo", ["App1", "App2"]), ("other", ["Other"])]
    assert got[0].path == lab.resolve()
    assert got[0].items[0].command == "cd /r && git pull"
    assert unplaced == ["Lost"]


def test_a_folder_that_is_gone_is_not_sent(tmp_path):
    got, unplaced = handoff.collect([row("Gone", "Needs you")], {"Gone": tmp_path / "nope"})
    assert got == [] and unplaced == ["Gone"]


# ------------------------------------------------------------------- context
def test_context_finds_claude_and_others_in_the_checkout_and_its_worktrees(lab, tmp_path):
    sh(lab, "branch", "feat")
    wt = add_worktree(lab, "feat", lab / ".claude" / "worktrees" / "w1")
    h = handoff.Handoff("repo", lab.resolve(), ())
    listing = [("claude", "11", wt / "sub"), ("zsh", "12", lab), ("vim", "13", tmp_path),
               ("python3", "99", lab)]
    ctx = handoff.context(h, listing, me=99)
    assert ctx.claude == ("claude (pid 11) in .claude/worktrees/w1",)
    assert ctx.others == ("zsh (pid 12) in .",)
    assert handoff.context(h, None).known is False


# -------------------------------------------------------------------- prompt
def _handoff(path=Path("/lab/provisio")):
    return handoff.Handoff("provisio", path, (
        handoff.Item("Provisio", "Needs you", "Move its release clone first; Lab Hub runs "
                     "nothing there.", "release clone is 4 commits behind; follow "
                     "RUNBOOK-release.md", "cd ~/rel/provisio && git pull --ff-only"),))


def test_the_prompt_carries_the_rows_word_for_word_and_the_limits():
    text = handoff.prompt(_handoff(), handoff.Context(claude=("claude (pid 7) in .",)),
                          "Check builds", WHEN)
    assert text == "\n".join([
        "Lab Hub's Check builds window could not clear these rows. Resolve them in this repo.",
        "",
        "Repo: provisio",
        "Folder: /lab/provisio",
        "Shown by Lab Hub on 2026-11-17 15:30:",
        "- Provisio: Needs you. Move its release clone first; Lab Hub runs nothing there. "
        "release clone is 4 commits behind; follow RUNBOOK-release.md",
        "  Command Lab Hub shows for it: cd ~/rel/provisio && git pull --ff-only",
        "",
        "Also running in this repo's checkout and worktrees right now:",
        "- claude (pid 7) in .",
        "Do not build, switch branches or commit in a folder another process is using "
        "without asking the owner first.",
        "",
        'Done looks like: the owner presses Refresh in Lab Hub and every row above reads '
        '"Up to date", "Landed" or "Nothing to land".',
        "",
        handoff.LIMITS,
        "",
        "End with two short lists: what you did, and what only the owner can do.",
    ])


def test_the_limits_name_every_hard_rule():
    for words in ("legal_gate.py sign", "signoff.jsonl", "record_approval.py",
                  "on the owner's behalf", "Never push, merge into the default branch",
                  "unless the owner says yes in this session", "Never another repo's",
                  "Update now or Land", "build_app.sh", "list for the owner"):
        assert words in handoff.LIMITS


def test_the_prompt_says_when_lsof_could_not_tell_and_when_nothing_runs():
    assert "could not tell what else is running" in handoff.prompt(
        _handoff(), handoff.Context(known=False), "Land", WHEN)
    assert "Nothing else was running" in handoff.prompt(
        _handoff(), handoff.Context(), "Land", WHEN)


# -------------------------------------------------------------------- launch
def test_settings_ask_before_push_and_deny_sign_off():
    rules = handoff.SETTINGS["permissions"]
    assert "Bash(git push:*)" in rules["ask"] and "Bash(git merge:*)" in rules["ask"]
    assert "Bash(*legal_gate.py sign*)" in rules["deny"]
    assert "Bash(*record_approval.py*)" in rules["deny"]
    assert "Edit(**/docs/legal/signoff.jsonl)" in rules["deny"]


def _launcher(tmp_path, calls, clock=lambda: 1_763_390_000.0):
    def runner(commands, directory=None):
        calls.append((commands, directory))
        return []
    return handoff.Launcher(runner, tmp_path / "support", clock)


def test_launch_writes_private_files_and_hands_one_line_to_terminal(tmp_path):
    calls = []
    repo = tmp_path / "repo"
    repo.mkdir()
    folder = _launcher(tmp_path, calls).launch("/bin/claude", _handoff(repo), "the task")
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    for name in ("prompt.md", "limits.md", "settings.json"):
        assert stat.S_IMODE((folder / name).stat().st_mode) == 0o600
    assert (folder / "prompt.md").read_text() == "the task"
    assert json.loads((folder / "settings.json").read_text()) == handoff.SETTINGS
    [(commands, directory)] = calls
    assert directory == folder and len(commands) == 1 and "\n" not in commands[0]
    assert "--permission-mode manual" in commands[0]
    assert "the task" not in commands[0]  # the prompt never enters the line


def test_two_repos_open_two_sessions_each_in_its_own_folder(tmp_path):
    calls = []
    launcher = _launcher(tmp_path, calls)
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    launcher.launch("/bin/claude", handoff.Handoff("a", a, ()), "x")
    launcher.launch("/bin/claude", handoff.Handoff("b", b, ()), "y")
    assert len(calls) == 2 and calls[0][1] != calls[1][1]
    assert calls[0][0][0].startswith(f"cd -- {a} && ")
    assert calls[1][0][0].startswith(f"cd -- {b} && ")


def test_a_linked_launch_folder_is_refused(tmp_path):
    (tmp_path / "support").mkdir()
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "support" / handoff.FOLDER).symlink_to(tmp_path / "elsewhere")
    with pytest.raises(OSError, match="is a link"):
        _launcher(tmp_path, []).launch("/bin/claude", _handoff(tmp_path), "x")


def test_old_launch_folders_go_and_nothing_else_does(tmp_path):
    base = tmp_path / "support" / handoff.FOLDER
    base.mkdir(parents=True)
    old, keep, new = base / "20260101T000000Z-1", base / "notes", base / "20261117T000000Z-1"
    for folder in (old, keep, new):
        folder.mkdir()
    now = 1_763_390_000.0
    os.utime(old, (now - 2 * 86400, now - 2 * 86400))
    os.utime(keep, (now - 2 * 86400, now - 2 * 86400))
    os.utime(new, (now - 3600, now - 3600))
    _launcher(tmp_path, [], clock=lambda: now).launch("/bin/claude", _handoff(tmp_path), "x")
    assert not old.exists() and keep.exists() and new.exists()


@pytest.mark.skipif(sys.platform != "darwin" and not Path("/bin/zsh").exists(),
                    reason="the .command line runs under zsh")
def test_a_hostile_repo_name_reaches_claude_as_data_not_shell(tmp_path):
    """The line runs for real under zsh: a repo name and a prompt full of shell
    syntax arrive as plain arguments, and nothing in them runs."""
    repo = tmp_path / "a'b $(touch PWNED) `touch PWNED2`; touch PWNED3"
    repo.mkdir()
    out = tmp_path / "argv.json"
    fake = tmp_path / "claude"
    fake.write_text(f"#!{sys.executable}\nimport json, os, sys\n"
                    f"json.dump({{'argv': sys.argv[1:], 'cwd': os.getcwd()}}, "
                    f"open({str(out)!r}, 'w'))\n")
    fake.chmod(0o755)
    calls = []
    task = "fix $(touch PWNED4) and `touch PWNED5` \"quoted\" 'single'"
    h = handoff.Handoff(repo.name, repo, ())
    folder = _launcher(tmp_path, calls).launch(str(fake), h, task)
    subprocess.run(["/bin/zsh", "-c", calls[0][0][0]], check=True, cwd=tmp_path)
    got = json.loads(out.read_text())
    assert got["cwd"] == str(repo.resolve()) or got["cwd"] == str(repo)
    assert got["argv"] == ["--permission-mode", "manual",
                           "--settings", str(folder / "settings.json"),
                           "--append-system-prompt", handoff.LIMITS,
                           "-n", f"Lab Hub: {repo.name}", task]
    assert not list(tmp_path.rglob("PWNED*"))
