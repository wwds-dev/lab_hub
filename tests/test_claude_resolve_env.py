"""The test run's time limit and program lookup (spec land-from-tiles §10)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from lab_hub import claude_resolve as cr


def context(repo: Path, *lines: str) -> None:
    folder = repo / "docs" / "foundry"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "app-context.md").write_text("# App\n\n## Commands\n" + "".join(f"{l}\n" for l in lines)
                                           + "\n## Other\n- Test timeout: 99 min\n")


@pytest.mark.parametrize("line, seconds", [
    ("- Test timeout: 60 min", 3600),
    ("- Test timeout: 45 minutes (the full suite takes 35)", 2700),
    ("- Test timeout: 180 min", 180 * 60),
    ("- Test timeout: 1 min", 60),
    ("- Test timeout: 181 min", 0),   # over the cap: the default, not a day-long Land
    ("- Test timeout: 0 min", 0),
    ("- Test timeout: 99999 min", 0),
    ("- Test timeout: soon", 0),
    ("- Test timeout: -5 min", 0),
    ("- Test timeout: 60", 0),            # no unit
    ("- Test timeout: 90 seconds", 0),
    ("- Test timeout: 5 minimum", 0),
    ("- Test timeouts: 60 min", 0),
    ("- Test timeout notes: 60 min", 0),
    ("  - Test timeout: 60 min", 3600),   # indented
    ("- Test timeout: 60 min\r", 3600),   # CRLF file
    ("- Run tests: `pytest -q`", 0),
])
def test_timeout_line(tmp_path, line, seconds):
    context(tmp_path, line)
    assert cr.test_timeout(tmp_path) == seconds


def test_only_the_commands_section_counts_and_no_file_means_default(tmp_path):
    assert cr.test_timeout(tmp_path) == 0
    context(tmp_path, "- Run tests: `python3 -m pytest -q`")
    assert cr.test_timeout(tmp_path) == 0  # the 99 under "## Other" is not read


def test_the_command_carries_the_repos_limit(tmp_path):
    context(tmp_path, "- Run tests: `python3 -m pytest -q`", "- Test timeout: 60 min")
    cmd = cr.test_command(tmp_path)
    assert cmd.timeout == 3600 and cmd.limit == 3600
    assert cmd.display == "python3 -m pytest -q"  # the preview's command is unchanged
    assert cr.TestCommand((("x", "y"),), "default").limit == cr.TEST_TIMEOUT


def test_the_default_command_gets_the_limit_too(tmp_path):
    (tmp_path / "tests").mkdir()
    context(tmp_path, "- Test timeout: 45 min")
    cmd = cr.test_command(tmp_path)
    assert cmd.source == "default" and cmd.limit == 2700


def test_a_run_past_the_repos_limit_times_out_and_says_how_to_raise_it(tmp_path, monkeypatch):
    seen = {}

    def fake_stream(argv, cwd, env, timeout, stop, on_line):
        seen["timeout"] = timeout
        return type("R", (), {"stopped": False, "timed_out": True, "returncode": 1, "lines": []})()

    monkeypatch.setattr(cr, "_stream", fake_stream)
    cmd = cr.TestCommand((("python3", "-c", "pass"),), "default", "", 120)
    run = cr.run_tests(cmd, tmp_path, tmp_path, cr.Stopper(), lambda _m: None)
    assert seen["timeout"] == 120
    assert run.status == "timeout" and "2 minutes" in run.output and "Test timeout" in run.output


def test_programs_are_looked_up_in_homebrew_before_the_system_folders():
    path = cr.test_env()["PATH"].split(":")
    assert path.index("/opt/homebrew/bin") < path.index("/usr/bin")
    assert path.index("/usr/local/bin") < path.index("/usr/bin")
    assert "/bin" in path and path[-1].endswith(".local/bin")
    assert all(p.startswith("/") for p in path)  # nothing relative, nothing from the repo


def test_the_environment_is_still_an_allowlist(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret")
    monkeypatch.setenv("SSH_AUTH_SOCK", "/tmp/agent")
    monkeypatch.setenv("PATH", "/evil:/usr/bin")
    env = cr.test_env()
    assert "ANTHROPIC_API_KEY" not in env and "SSH_AUTH_SOCK" not in env
    assert "/evil" not in env["PATH"]


@pytest.mark.skipif(not Path("/opt/homebrew/bin/python3").exists(), reason="no Homebrew python")
def test_a_bare_python3_is_not_the_old_system_one():
    assert shutil.which("python3", path=cr.test_env()["PATH"]) == "/opt/homebrew/bin/python3"


def test_every_command_on_the_line_gets_the_limit(tmp_path, monkeypatch):
    seen = []

    def fake_stream(argv, cwd, env, timeout, stop, on_line):
        seen.append(timeout)
        return type("R", (), {"stopped": False, "timed_out": False, "returncode": 0, "lines": []})()

    monkeypatch.setattr(cr, "_stream", fake_stream)
    cmd = cr.TestCommand((("python3", "-c", "pass"), ("python3", "-c", "pass")), "default", "", 120)
    assert cr.run_tests(cmd, tmp_path, tmp_path, cr.Stopper(), lambda _m: None).status == "pass"
    assert seen == [120, 120]


def test_a_longer_label_is_not_mistaken_for_the_run_tests_line(tmp_path):
    context(tmp_path, "- Run tests timeout: 60 min", "- Run tests: `python3 -m pytest -q`",
            "- Test timeout: 45 min")
    cmd = cr.test_command(tmp_path)
    assert cmd.display == "python3 -m pytest -q" and cmd.limit == 2700


def test_run_tests_with_a_bracketed_note_before_the_colon_still_parses(tmp_path):
    context(tmp_path, "- Run tests (every mode): `python3 -m pytest -q`")
    assert cr.test_command(tmp_path).display == "python3 -m pytest -q"


def test_the_preview_says_the_limit_or_that_the_line_was_not_understood(tmp_path):
    context(tmp_path, "- Run tests: `pytest -q`")
    assert cr.timeout_note(tmp_path) == ""
    context(tmp_path, "- Test timeout: 60 min")
    assert cr.timeout_note(tmp_path) == "limit 60 min per command"
    context(tmp_path, "- Test timeout: 2 h")
    assert "not understood" in cr.timeout_note(tmp_path) and "30 min" in cr.timeout_note(tmp_path)


def test_the_log_names_the_program_a_bare_name_resolved_to(tmp_path, monkeypatch):
    monkeypatch.setattr(cr, "_stream", lambda *a, **k: type(
        "R", (), {"stopped": False, "timed_out": False, "returncode": 0, "lines": []})())
    said = []
    cr.run_tests(cr.TestCommand((("python3", "-c", "pass"),), "default"), tmp_path, tmp_path,
                 cr.Stopper(), said.append)
    assert said and said[0].startswith("  Tests: python3 -c pass (/") and "python3" in said[0]


def test_the_system_folders_stay_on_the_path():
    path = cr.test_env()["PATH"].split(":")
    assert {"/usr/bin", "/bin", "/usr/sbin", "/sbin"} <= set(path)
