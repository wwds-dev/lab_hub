"""Repo hygiene in Lab Hub: the report is read, never computed on the UI thread,
and it shows as a badge per app plus a Check repos report."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from lab_hub import config, hygiene, launcher


def _write(root, rows, generated=None, fetched=True):
    folder = root / "git_autosync"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = generated or datetime.now().astimezone().isoformat(timespec="seconds")
    (folder / hygiene.REPORT_NAME).write_text(json.dumps(
        {"generated": stamp, "fetched": fetched, "repos": rows}))


def _row(root, name, problems=(), error=""):
    out = {"name": name, "path": str((root / name).resolve()), "branch": "main",
           "problems": list(problems), "notes": []}
    if error:
        out["error"] = error
    return out


def test_no_report_is_none(tmp_path):
    assert hygiene.load(tmp_path) is None


def test_a_garbled_report_is_none_not_a_crash(tmp_path):
    (tmp_path / "git_autosync").mkdir()
    (tmp_path / "git_autosync" / hygiene.REPORT_NAME).write_text("{not json")
    assert hygiene.load(tmp_path) is None


def test_rows_are_matched_by_resolved_checkout(tmp_path):
    (tmp_path / "a").mkdir()
    _write(tmp_path, [_row(tmp_path, "a", ["2 uncommitted files"])])
    report = hygiene.load(tmp_path)
    row = report.for_project(tmp_path, "a")
    assert row.needs_attention and row.badge == "2 files to land"
    assert row.detail == "2 uncommitted files"
    assert report.for_project(tmp_path, "other") is None


def test_a_clean_repo_has_no_badge_and_an_unreadable_one_says_so(tmp_path):
    _write(tmp_path, [_row(tmp_path, "ok"), _row(tmp_path, "bad", error="not a git repository")])
    report = hygiene.load(tmp_path)
    assert report.for_project(tmp_path, "ok").badge == ""
    assert report.for_project(tmp_path, "bad").badge == "repo not readable"
    assert [r.name for r in report.attention] == ["bad"]


def test_an_old_report_is_stale(tmp_path):
    old = (datetime.now().astimezone() - timedelta(hours=hygiene.STALE_AFTER_HOURS + 1))
    _write(tmp_path, [], generated=old.isoformat(timespec="seconds"))
    assert hygiene.load(tmp_path).stale
    _write(tmp_path, [])
    assert not hygiene.load(tmp_path).stale


def test_command_needs_the_script(tmp_path):
    assert hygiene.command(tmp_path) is None
    script = hygiene.script_path(tmp_path)
    script.parent.mkdir(parents=True)
    script.write_text("")
    argv = hygiene.command(tmp_path)
    assert argv[1] == str(script) and "--fetch" not in argv
    assert argv[argv.index("--out") + 1] == str(hygiene.report_path(tmp_path))
    assert argv[argv.index("--lab-root") + 1] == str(tmp_path.parent)


# --- the tab -----------------------------------------------------------------

def _tab(qapp, tmp_path, monkeypatch, **kwargs):
    from ui.apps_tab import AppsTab

    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "none")
    apps = tuple(launcher.ExternalApp(k, k.upper(), k, "main.py", "s") for k in ("a", "b"))
    tab = AppsTab(config.Settings(lab_root=str(tmp_path)), apps, "Apps", "intro", **kwargs)
    return tab, apps


def _drop(tab):
    import shiboken6

    tab._poll.stop()
    shiboken6.delete(tab)


def test_the_badge_shows_on_the_app_with_unfinished_work(qapp, tmp_path, monkeypatch):
    _write(tmp_path, [_row(tmp_path, "a", ["3 uncommitted files", "1 unpushed commit"]),
                      _row(tmp_path, "b")])
    tab, _ = _tab(qapp, tmp_path, monkeypatch)
    tab.refresh()
    a, b = tab.cards
    assert a.hygiene.text() == "3 files · 1 unpushed commit to land"
    assert "3 uncommitted files; 1 unpushed commit" in a.hygiene.toolTip()
    assert b.hygiene.text() == ""
    _drop(tab)


def test_the_badge_clears_when_the_work_lands(qapp, tmp_path, monkeypatch):
    _write(tmp_path, [_row(tmp_path, "a", ["1 unpushed commit"])])
    tab, _ = _tab(qapp, tmp_path, monkeypatch)
    tab.refresh()
    assert tab.cards[0].hygiene.text() == "1 unpushed commit to land"
    _write(tmp_path, [_row(tmp_path, "a")] + [_row(tmp_path, "pad", ["x"])])  # new size and mtime
    tab.refresh()
    assert tab.cards[0].hygiene.text() == ""
    _drop(tab)


def test_check_repos_button_is_the_launchpads_only(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QPushButton

    def labels(tab):
        return {b.text() for b in tab.findChildren(QPushButton)}

    with_button, _ = _tab(qapp, tmp_path, monkeypatch, check_builds=True)
    without, _ = _tab(qapp, tmp_path, monkeypatch)
    assert "Check repos" in labels(with_button) and "Check repos" not in labels(without)
    _drop(with_button)
    _drop(without)


def test_the_report_dialog_lists_what_has_not_landed(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    _write(tmp_path, [_row(tmp_path, "a", ["1 branch not merged into main"]),
                      _row(tmp_path, "b")], fetched=False)
    tab, _ = _tab(qapp, tmp_path, monkeypatch, check_builds=True)
    seen = {}
    monkeypatch.setattr(QMessageBox, "exec", lambda self: seen.update(
        text=self.text(), body=self.informativeText()))
    tab.show_repo_report()
    assert seen["text"] == "1 of 2 repos have work that has not landed."
    assert "[!!] a (main) — 1 branch not merged into main" in seen["body"]
    assert "[ok] b" in seen["body"]
    assert "last fetch" in seen["body"]
    _drop(tab)


def test_everything_landed_says_so(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    _write(tmp_path, [_row(tmp_path, "a")])
    tab, _ = _tab(qapp, tmp_path, monkeypatch, check_builds=True)
    seen = {}
    monkeypatch.setattr(QMessageBox, "exec", lambda self: seen.update(text=self.text()))
    tab.show_repo_report()
    assert seen["text"] == "Everything is committed, pushed and merged."
    _drop(tab)


def test_without_the_script_check_repos_says_why_and_starts_nothing(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    tab, _ = _tab(qapp, tmp_path, monkeypatch, check_builds=True)
    seen = {}
    monkeypatch.setattr(QMessageBox, "exec", lambda self: seen.update(
        text=self.text(), body=self.informativeText()))
    tab.check_repos()
    assert tab._hygiene_proc is None
    assert seen["text"] == "No repo report yet." and "not found" in seen["body"]
    _drop(tab)


@pytest.mark.parametrize("problems, badge", [
    (["6 branches not merged into master", "2 worktrees with uncommitted work"],
     "6 branches · 2 worktrees to land"),
    (["1 branch not merged into main"], "1 branch to land"),
    (["diverged: 2 unpushed, 1 behind"], "2 unpushed commits · 1 commit behind to land"),
    (["new words", "other new words"], "2 items to land"),
    (["3 behind origin/main"], "3 commits behind to land"),
    (["1 uncommitted file", "1 worktree with uncommitted work"], "1 file · 1 worktree to land"),
    (["something git_autosync says in new words"], "1 item to land"),
    ([], ""),
])
def test_the_badge_counts_things_not_problem_kinds(tmp_path, problems, badge):
    row = hygiene.RepoRow("a", tmp_path, problems=tuple(problems))
    assert row.badge == badge
