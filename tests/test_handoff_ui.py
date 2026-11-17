"""Ask Claude in the Check builds and Land windows (spec claude-handoff §2, §9).

The confirmation is replaced where it would block; Terminal, lsof and Claude
Code are replaced at their module functions. Repos are real temporary ones.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox

from lab_hub import claude_resolve, handoff, land_resolve, launcher, progress, repo_tidy
from lab_hub.land import LandPlan, LandResult
from ui.handoff_dialog import HandoffDialog
from ui.progress_window import BuildCheckWindow, LandWindow

from .test_hygiene import _drop
from .test_land_ui import tab_for
from .test_repo_tidy import lab, sh  # noqa: F401 (fixture)

WALL = datetime(2026, 11, 17, 15, 0)


def _app(key):
    return launcher.ExternalApp(key, key.upper(), key, "main.py", "s")


def _forward(project):
    return launcher.BuildStatus(_app("p"), launcher.Version(), "behind",
                                "release clone is 4 commits behind; follow RUNBOOK-release.md",
                                None, "cd ~/rel && git pull --ff-only", forward=True,
                                project=project)


def _rebuild():
    return launcher.BuildStatus(_app("x"), launcher.Version(), "behind", "older.", None,
                                "cd /x && ./build_app.sh")


def _plan(name, path):
    return LandPlan(name, path, (repo_tidy.Action(name, path, "merge", "b0", "why",
                                                  branch="main"),))


@pytest.fixture
def fakes(monkeypatch):
    """Terminal, lsof and Claude Code, replaced; what would have run is kept."""
    opened, shown = [], []
    monkeypatch.setattr(claude_resolve, "find_claude", lambda: "/bin/claude")
    monkeypatch.setattr(land_resolve, "cwd_listing", lambda: [])
    monkeypatch.setattr(launcher, "run_in_terminal",
                        lambda commands, directory=None: opened.append((commands, directory)))
    for kind in ("information", "warning"):
        monkeypatch.setattr(QMessageBox, kind,
                            lambda *a, kind=kind, **k: shown.append((kind, a[2])))
    return opened, shown


# ---------------------------------------------------------- the button's state
def test_check_builds_offers_it_for_a_needs_you_row_and_not_for_a_plain_rebuild(qapp, lab):
    window = BuildCheckWindow(progress.build_check_view((_rebuild(),), scoped=True))
    assert window.ask_claude_button.isHidden()  # Update now does this one
    assert window.ask_claude_button not in window.buttons()
    window.close()

    window = BuildCheckWindow(progress.build_check_view((_forward(lab), _rebuild()),
                                                        scoped=True))
    assert not window.ask_claude_button.isHidden()
    assert window.ask_claude_button.isEnabled()
    assert [r.name for r in window.handoff_rows()] == ["P"]
    assert not window.ask_claude_button.isDefault() and not window.ask_claude_button.autoDefault()
    window.close()


def test_hidden_while_update_now_runs_and_back_at_done_for_a_failed_rebuild(qapp, lab):
    window = BuildCheckWindow(progress.build_check_view((_rebuild(),), scoped=True))
    window.show()
    window.begin_update()
    assert window.ask_claude_button.isHidden()
    window.command_started("cd /x && ./build_app.sh")
    window.command_finished("cd /x && ./build_app.sh", False, code=1)
    assert window.ask_claude_button.isHidden()  # still at Update
    window.update_ended("failed", ("cd /x && ./build_app.sh",), 1)
    assert not window.ask_claude_button.isHidden()
    assert [r.name for r in window.handoff_rows()] == ["X"]
    window.done(0)


def test_busy_disables_it_and_says_which_job(qapp, lab):
    window = BuildCheckWindow(progress.build_check_view((_forward(lab),), scoped=True))
    window.set_handoff_busy("Land is running")
    assert not window.ask_claude_button.isHidden()
    assert not window.ask_claude_button.isEnabled()
    assert "Land is running" in window.ask_claude_button.toolTip()
    window.set_handoff_busy("")
    assert window.ask_claude_button.isEnabled()
    window.close()


def test_land_offers_it_only_after_the_run_for_a_stop_or_archived_branches(qapp, lab, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    window = LandWindow(wall=lambda: WALL)
    window.start([_plan("repo", lab), _plan("other", other), _plan("clean", other)])
    assert window.ask_claude_button.isHidden()  # running
    window.on_repo_done("repo", LandResult("repo", "not_landed",
                                           "a merge is in progress: finish or abort it in "
                                           "Terminal"))
    window.on_repo_done("other", LandResult("other", "landed", done=1, archived=2))
    window.on_repo_done("clean", LandResult("clean", "landed", done=1))
    assert window.ask_claude_button.isHidden()  # not finished yet
    window.finish([])
    assert not window.ask_claude_button.isHidden()
    rows = {r.name: r for r in window.handoff_rows()}
    assert set(rows) == {"repo", "other"}
    assert rows["repo"].status == "Needs you"
    assert rows["repo"].reason.startswith("a merge is in progress")
    assert rows["other"].status == "Landed · 2 branches archived"
    window.close()


# ------------------------------------------------------------------ the dialog
def _items(*paths, running=()):
    out = []
    for path in paths:
        h = handoff.Handoff(path.name, path, (handoff.Item("A", "Needs you", "why"),))
        ctx = handoff.Context(claude=running if path == paths[0] else ())
        out.append((h, ctx, f"prompt for {path.name}"))
    return out


def test_the_dialog_counts_ticks_states_the_cost_and_lists_rows_with_no_folder(qapp, tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    dialog = HandoffDialog(_items(a, b), ["Lost"])
    assert dialog.open_button.text() == "Open 2 sessions"
    dialog.blocks[1].tick.setChecked(False)
    assert dialog.open_button.text() == "Open 1 session"
    dialog.blocks[0].tick.setChecked(False)
    assert not dialog.open_button.isEnabled()
    texts = [w.text() for w in dialog.findChildren(QLabel)]
    assert any("Lab Hub sets no cap" in t for t in texts)
    assert any(t == "Lost: no folder, not sent." for t in texts)
    assert any(t == "A: Needs you. why" for t in texts)
    _delete(dialog)


def test_a_repo_with_claude_running_starts_unticked_and_copy_opens_nothing(qapp, tmp_path):
    a = tmp_path / "a"
    dialog = HandoffDialog(_items(a, running=("claude (pid 7) in .",)), [])
    assert not dialog.blocks[0].tick.isChecked()
    assert dialog.blocks[0].copy_button is not None
    dialog.blocks[0].copy_button.click()
    assert QApplication.clipboard().text() == "prompt for a"
    assert dialog.copied.repo == "a" and dialog.chosen() == []
    _delete(dialog)


def _delete(widget):
    """Free a parentless dialog now: one left for interpreter exit crashes Qt."""
    widget.close()
    widget.deleteLater()
    QApplication.sendPostedEvents(None, 0)  # 0: DeferredDelete included


# ----------------------------------------------------------- AppsTab end to end
def _tab(qapp, tmp_path, monkeypatch):
    return tab_for(qapp, tmp_path, [], monkeypatch)


def test_ask_claude_opens_one_session_per_repo_with_the_row_text(qapp, tmp_path, lab,
                                                                  monkeypatch, fakes):
    opened, shown = fakes
    other = tmp_path / "other"
    other.mkdir()
    sh(other, "init", "-q")
    tab = _tab(qapp, tmp_path, monkeypatch)
    seen = []
    tab.confirm_handoff = lambda items, unplaced, parent: (
        seen.append(items) or [h for h, _c, _t in items])
    window = LandWindow(wall=lambda: WALL)
    window.start([_plan("repo", lab), _plan("other", other)])
    window.on_repo_done("repo", LandResult("repo", "not_landed", "push rejected by origin"))
    window.on_repo_done("other", LandResult("other", "not_landed", "gitleaks is missing"))
    window.finish([])
    tab.ask_claude(window)
    assert shown == []
    [items] = seen
    assert [h.path for h, _c, _t in items] == [lab.resolve(), other.resolve()]
    assert "- repo: Needs you. push rejected by origin" in items[0][2]
    assert "Lab Hub's Land window" in items[0][2]
    assert len(opened) == 2
    assert opened[0][0][0].startswith(f"cd -- {lab.resolve()} && /bin/claude ")
    assert (opened[0][1] / "prompt.md").read_text() == items[0][2]
    assert "Opened Claude Code for repo in Terminal." in window.model.take_output()
    window.close()
    _drop(tab)


def test_nothing_opens_while_land_runs_or_on_cancel(qapp, tmp_path, lab, monkeypatch, fakes):
    opened, shown = fakes
    tab = _tab(qapp, tmp_path, monkeypatch)
    window = BuildCheckWindow(progress.build_check_view((_forward(lab),), scoped=True))
    window.handoff_paths["P"] = lab
    asked = []
    tab.confirm_handoff = lambda items, unplaced, parent: asked.append(1) or []
    tab.land_jobs = lambda: ["Land is running"]
    tab.ask_claude(window)
    assert asked == [] and opened == []
    assert shown == [("information",
                      "Not now: Land is running. Try again when it has finished.")]
    assert not window.ask_claude_button.isEnabled()

    tab.land_jobs = lambda: []
    window.set_handoff_busy("")
    tab.ask_claude(window)  # confirmation cancelled
    assert asked == [1] and opened == []

    # A Land that starts while the confirmation is open: checked again, nothing opens.
    def confirm_then_land(items, unplaced, parent):
        tab.land_jobs = lambda: ["Land is reading the repos"]
        return [h for h, _c, _t in items]
    tab.confirm_handoff = confirm_then_land
    shown.clear()
    tab.ask_claude(window)
    assert opened == [] and shown == [("information", "Nothing opened: Land is reading the repos.")]
    window.close()
    _drop(tab)


def test_no_claude_code_says_so_and_opens_nothing(qapp, tmp_path, lab, monkeypatch, fakes):
    opened, shown = fakes
    monkeypatch.setattr(claude_resolve, "find_claude", lambda: None)
    tab = _tab(qapp, tmp_path, monkeypatch)
    window = BuildCheckWindow(progress.build_check_view((_forward(lab),), scoped=True))
    window.handoff_paths["P"] = lab
    tab.ask_claude(window)
    assert opened == [] and shown[0][0] == "warning" and "not found" in shown[0][1]
    window.close()
    _drop(tab)


def test_check_builds_passes_each_rows_folder_and_command(qapp, tmp_path, lab, monkeypatch,
                                                          fakes):
    """show_build_report fills the window's folders and commands from the report."""
    opened, _shown = fakes
    tab = tab_for(qapp, tmp_path, ["p"], monkeypatch, check_own_builds=True)  # scoped report
    monkeypatch.setattr(launcher, "build_report", lambda root, *a: (_forward(lab),))
    seen = []
    tab.confirm_handoff = lambda items, unplaced, parent: seen.append(items) or []

    def press(window):
        window.ask_claude_button.click()
        window.done(0)
    original = BuildCheckWindow.ask
    monkeypatch.setattr(BuildCheckWindow, "ask", lambda self: (press(self), None)[1])
    tab.show_build_report()
    monkeypatch.setattr(BuildCheckWindow, "ask", original)
    [items] = seen
    text = items[0][2]
    assert f"Folder: {lab.resolve()}" in text
    assert "  Command Lab Hub shows for it: cd ~/rel && git pull --ff-only" in text
    assert "release clone is 4 commits behind" in text
    _drop(tab)


def test_the_page_disables_an_open_land_windows_button_while_land_runs(qapp, tmp_path, lab,
                                                                      monkeypatch):
    tab = _tab(qapp, tmp_path, monkeypatch)
    tab._open_land_window([_plan("repo", lab)])
    window = tab.land_window
    window.on_repo_done("repo", LandResult("repo", "not_landed", "push rejected by origin"))
    window.finish([])
    tab.land_jobs = lambda: ["Land is running"]
    tab._update_land_controls()
    assert not window.ask_claude_button.isEnabled()
    tab.land_jobs = lambda: []
    tab._update_land_controls()
    assert window.ask_claude_button.isEnabled()
    window.close()
    _drop(tab)


def test_main_window_counts_land_on_any_page_but_not_tools(qapp):
    from ui.main_window import MainWindow

    def page(*reasons):
        return SimpleNamespace(_own_busy_reasons=lambda: list(reasons))
    pages = (page(), page("Land is running"), page("Land is running"), page())
    fake = SimpleNamespace(_app_pages=lambda: pages,
                           _running_panels=lambda: ["Convert"])  # a tool: not counted
    assert MainWindow.land_jobs(fake) == ["Land is running"]
