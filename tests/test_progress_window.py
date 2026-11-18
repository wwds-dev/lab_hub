"""The progress windows' widgets (spec progress-windows §8.6, §8.8, §8.12).

The model is tested in `test_progress.py`; here: that the widgets show it, as
plain text, no more than ten times a second, and only while someone can see it.
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

from lab_hub import durations, launcher, progress, repo_tidy
from lab_hub.land import LandPlan, LandResult, StepEvent
from ui.progress_window import BuildCheckWindow, LandWindow


class Clock:
    def __init__(self, t: float = 500.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


WALL = datetime(2026, 11, 17, 14, 0, 0)


def pump(seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.005)


def _plans():
    def plan(name, *kinds):
        return LandPlan(name, Path("/x"), tuple(
            repo_tidy.Action(name, Path("/x"), k, f"b{i}", "why", branch="main")
            for i, k in enumerate(kinds)))
    return [plan("SONAR", "commit", "merge", "push"), plan("Backstage", "merge")]


def _land_window(qapp, clock=None):
    window = LandWindow(clock=clock or Clock(), wall=lambda: WALL)
    window.start(_plans())
    return window


def test_renders_are_throttled_to_ten_a_second(qapp):
    clock = Clock()
    window = _land_window(qapp, clock)
    window.renders = 0
    end = time.monotonic() + 1.0
    sent = 0
    while time.monotonic() < end:
        window.on_progress("SONAR", f"line {sent}")
        sent += 1
        QApplication.processEvents()
        time.sleep(0.002)  # a line every ~2 ms: far closer together than 100 ms
    during = window.renders
    pump(0.15)
    assert sent > 100
    assert 1 <= window.renders <= 11  # 10 in the second, plus one pending at its edge
    # A throttle, not a debounce: steady output still renders about ten times a
    # second (a timer restarted on every line would render only once it stops).
    assert during >= 3  # about 10 expected; a debounce gives 0
    assert window.output.text().splitlines()[-1] == f"SONAR: line {sent - 1}"
    window.close()


def test_a_hidden_window_updates_its_model_and_draws_nothing(qapp):
    clock = Clock()
    window = _land_window(qapp, clock)
    window.hide()
    window.renders = 0
    window.on_step(StepEvent("SONAR", 0, 3, "commit", "start", clock()))
    window.on_progress("SONAR", "working")
    pump(0.3)
    assert window.renders == 0 and not window._tick.isActive()
    assert window.model.rows[0].units[0].state == progress.RUNNING
    window.show()
    assert window.renders == 1  # shown again: drawn at once, with what it missed
    assert window.rows[0].steps.isVisibleTo(window.rows[0])
    assert "SONAR: working" in window.output.text()
    window.close()


def test_the_activity_line_turns_amber_after_a_minute(qapp):
    clock = Clock()
    window = _land_window(qapp, clock)
    clock.t += 59
    window.draw()
    assert window.header.activity.text() == "Last activity 59s ago"
    assert window.header.activity.objectName() == "hint"
    clock.t += 1
    window.draw()
    assert window.header.activity.text() == "No output for 1:00. Still running."
    assert window.header.activity.objectName() == "stateWarn"
    window.on_progress("SONAR", "pytest: 212 passed so far")
    window.draw()
    assert window.header.activity.text() == "Last activity 0s ago"
    window.close()


def test_no_history_says_estimating_and_history_gives_time_left(qapp):
    window = _land_window(qapp)
    assert progress.ESTIMATING in window.header.times.text()
    assert "done around" not in window.header.times.text()
    window.close()
    for kind, value in (("commit", 2), ("merge", 30), ("push", 3)):
        durations.record("repo:SONAR", kind, value)
    durations.record("repo:Backstage", "merge", 20)
    window = _land_window(qapp)
    assert window.header.times.text() == "0:00 elapsed · ~55 s left · done around 14:00"
    assert window.rows[0].pill.text() == "Next · ~35 s"
    window.close()


def test_the_running_row_opens_into_its_steps_with_its_own_timer(qapp):
    clock = Clock()
    durations.record("repo:SONAR", "merge", 150)
    window = _land_window(qapp, clock)
    window.on_step(StepEvent("SONAR", 0, 3, "commit", "start", clock()))
    clock.t += 4
    window.on_step(StepEvent("SONAR", 0, 3, "commit", "end", clock(), clock() - 4, "done"))
    window.on_step(StepEvent("SONAR", 1, 3, "merge", "start", clock()))
    clock.t += 92
    window.draw()
    row = window.rows[0]
    assert row.steps.isVisibleTo(row)
    times = [line[3].text() for line in row.steps._lines]
    assert times == ["4s", "1:32 / ~2:30"]
    assert row.steps.then.text() == "Then: Push b2 — why"
    assert [c.property("state") in ("running", "pulse") for c in row.chips] == [
        False, True, False, False]
    assert window.header.percent.text() == "25%"  # 1 of 4 planned steps
    assert not window.rows[1].steps.isVisibleTo(window.rows[1])
    window.close()


def test_names_reasons_and_output_are_plain_text(qapp):
    clock = Clock()
    window = LandWindow(clock=clock)
    plan = LandPlan("<i>evil</i>", Path("/x"), (repo_tidy.Action(
        "<i>evil</i>", Path("/x"), "merge", "b", "why", branch="main"),))
    window.start([plan])
    window.on_progress("<i>evil</i>", "\x1b[1m<b>bold?</b>\x1b[0m\x07")
    window.on_repo_done("<i>evil</i>", LandResult("<i>evil</i>", "not_landed", "<a href=x>no</a>"))
    window.finish([LandResult("<i>evil</i>", "not_landed", "<a href=x>no</a>")])
    window.draw()
    assert window.rows[0].name.text() == "<i>evil</i>"
    assert window.rows[0].reason.text() == "<a href=x>no</a>"
    assert window.output.text().endswith("<i>evil</i>: <b>bold?</b>")
    labels = window.findChildren(QLabel)
    assert labels and all(lbl.textFormat() == Qt.TextFormat.PlainText for lbl in labels)
    window.close()


def test_closing_the_land_window_hides_it_and_stop_is_a_signal(qapp):
    window = _land_window(qapp)
    stopped = []
    window.stop_requested.connect(lambda: stopped.append(1))
    window.close()
    assert not window.isVisible() and window.model.live
    window.show()
    window.stop_button.click()
    assert stopped == [1] and window.stop_button.text() == "Stopping…"
    window.close()


# ---------------------------------------------------------------- Check builds
def _app(key):
    return launcher.ExternalApp(key, key.upper(), key, "main.py", "s")


def _view(*rows):
    return progress.build_check_view(rows, scoped=True)


def test_review_shows_the_box_buttons_and_escape_answers_none(qapp):
    rows = (launcher.BuildStatus(_app("x"), launcher.Version(), "behind", "older.", None,
                                 "cd /x && ./build_app.sh"),
            launcher.BuildStatus(_app("ok"), launcher.Version("2.3"), "current", "matches."))
    window = BuildCheckWindow(_view(*rows))
    assert [b.text() for b in window.buttons()] == [
        "Update now", "Copy commands", "Copy and open Terminal", "Close"]
    assert window.update_button.isDefault()
    assert window.text() == "1 of 2 apps would open something older than their source."
    assert window.rows[0].pill.text() == "Out of date"
    assert window.current_line.text().startswith("✓  OK 2.3")
    assert window.header.bar.isHidden()  # nothing runs at Review
    QTimer.singleShot(50, lambda: QTest.keyClick(window, Qt.Key.Key_Escape))
    assert window.ask() is None
    assert not window.isVisible()


def test_review_button_answers_and_copy_closes_update_stays(qapp):
    rows = (launcher.BuildStatus(_app("x"), launcher.Version(), "behind", "older.", None,
                                 "cd /x && ./build_app.sh"),)
    window = BuildCheckWindow(_view(*rows))
    QTimer.singleShot(50, lambda: window.buttons()[1].click())  # Copy commands
    assert window.ask() == "Copy commands"
    assert not window.isVisible()

    window = BuildCheckWindow(_view(*rows))
    QTimer.singleShot(50, lambda: window.buttons()[0].click())  # Update now
    assert window.ask() == "Update now"
    assert window.isVisible()
    window.begin_update()
    assert all(b.isHidden() for b in window.buttons())
    copied = []
    window.copy_requested.connect(copied.append)
    window.update_copy.click()
    assert copied == [["cd /x && ./build_app.sh"]] and window.isVisible()
    assert window.cancel_button.text() == "Cancel"
    window.update_ended("done")
    assert window.cancel_button.text() == "Close"
    window.cancel_button.click()
    assert not window.isVisible()


def test_a_terminal_only_and_a_no_command_app_say_what_happens(qapp):
    rows = (launcher.BuildStatus(_app("p"), launcher.Version(), "behind", "4 commits behind",
                                 None, "cd /r && ./i.sh", by_hand=True),
            launcher.BuildStatus(_app("n"), launcher.Version(), "behind", "older.",
                                 project=Path("/n")))
    window = BuildCheckWindow(_view(*rows))
    assert "Open in Terminal" in [b.text() for b in window.buttons()]
    assert window.rows[0].pill.text() == "Needs Terminal"
    assert window.rows[0].detail.text() == "4 commits behind"
    assert window.rows[1].pill.text() == "Needs you"
    counts = [lbl.text() for lbl in window.header._count_labels]
    assert counts == ["1 needs Terminal", "1 needs you"]
    window.close()


def test_the_tick_moves_the_dots_and_the_clocks_with_no_events(qapp):
    """QA P2: nothing let the 500 ms tick fire. With no event at all, the dots
    turn, elapsed and last activity count up, and a minute without output turns
    the line amber."""
    clock = Clock()
    window = _land_window(qapp, clock)
    window.renders = 0
    phase = window.header.dots.phase
    assert window._tick.isActive()
    clock.t += 3
    pump(1.2)
    assert window.renders >= 2
    assert window.header.dots.phase != phase or window.phase >= 2
    assert window.header.times.text().startswith("0:03 elapsed")
    assert window.header.activity.text() == "Last activity 3s ago"
    clock.t += 60
    pump(0.7)
    assert window.header.activity.text() == "No output for 1:03. Still running."
    assert window.header.activity.objectName() == "stateWarn"
    window.finish([LandResult("SONAR", "landed"), LandResult("Backstage", "landed")])
    assert not window._tick.isActive()  # ended: nothing moves any more
    window.close()


def test_only_a_finished_land_step_is_recorded(qapp):
    """QA REC1: a failed or skipped step is not a duration to estimate from."""
    clock = Clock()
    window = _land_window(qapp, clock)
    for index, kind, outcome in ((0, "commit", "failed"), (1, "merge", "skipped"),
                                 (2, "push", "done")):
        window.on_step(StepEvent("SONAR", index, 3, kind, "start", clock()))
        clock.t += 7
        window.on_step(StepEvent("SONAR", index, 3, kind, "end", clock(), clock() - 7,
                                 outcome))
    assert durations.load() == {"repo:SONAR": {"push": [7.0]}}
    window.close()


def test_nothing_ticks_at_review(qapp):
    """Review P3-3: the 500 ms tick ran (and rendered) while nothing was running."""
    rows = (launcher.BuildStatus(_app("x"), launcher.Version(), "behind", "older.", None,
                                 "cd /x && ./build_app.sh"),)
    window = BuildCheckWindow(_view(*rows))
    window.show()
    window.renders = 0
    pump(0.7)
    assert not window._tick.isActive() and window.renders == 0
    window.begin_update()
    assert window._tick.isActive()
    window.update_ended("cancelled")
    assert not window._tick.isActive()
    window.close()


def test_the_check_builds_step_header_and_end_lines(qapp):
    """QA P2: Check, Review, Update, Done and the three end lines, in words."""
    rows = (launcher.BuildStatus(_app("x"), launcher.Version(), "behind", "older.", None,
                                 "cd /x && ./build_app.sh"),)

    def marks(window):
        return [m.text() for m in window.steps._marks]

    for how, line in (("done", "Done. Every app was rebuilt and reinstalled."),
                      ("failed", "A rebuild failed — see the live output."),
                      ("cancelled", "Cancelled. Some apps may still be out of date.")):
        window = BuildCheckWindow(_view(*rows))
        assert marks(window) == ["✓", "2", "3", "4"]
        assert window.steps._marks[1].property("tone") == "run"
        window.show()
        window.begin_update()
        assert marks(window) == ["✓", "✓", "3", "4"]
        window.update_ended(how)
        assert marks(window) == ["✓", "✓", "✓", "✓"]
        assert window.header.outcome.text() == line
        assert window.output.toggle.isChecked() is (how == "failed")
        window.close()


def test_the_open_in_terminal_tooltip_is_plain_text(qapp):
    """Secure P3-5: an app name with tags was rendered as markup."""
    app = launcher.ExternalApp("n", "<b>N</b>", "n", "main.py", "s")
    rows = (launcher.BuildStatus(app, launcher.Version(), "behind", "older.",
                                 project=Path("/n")),)
    window = BuildCheckWindow(_view(*rows))
    button = next(b for b in window.buttons() if b.text() == "Open in Terminal")
    tip = button.toolTip()
    assert "<b>" not in tip and "&lt;b&gt;N&lt;/b&gt;" in tip
    window.close()


# ------------------------------------------- land-pick-and-time: the end of a Land
def _finished_window(qapp):
    clock = Clock()
    window = _land_window(qapp, clock)
    window.on_step(StepEvent("SONAR", 0, 3, "commit", "start", clock()))
    clock.t += 4
    window.on_step(StepEvent("SONAR", 0, 3, "commit", "end", clock(), clock() - 4, "done"))
    window.on_repo_done("SONAR", LandResult("SONAR", "not_landed", "tests fail"))
    window.on_repo_done("Backstage", LandResult("Backstage", "nothing"))
    clock.t += 858
    window.finish([LandResult("SONAR", "not_landed", "tests fail"),
                   LandResult("Backstage", "nothing")], "Landed 0 of 2 repos.")
    window.draw()
    return window


def test_the_finished_header_keeps_the_time_and_the_run_is_logged(qapp):
    window = _finished_window(qapp)
    assert window.header.times.isVisibleTo(window.header)
    assert window.header.times.text() == "Took 14:22 · 14:00 to 14:00"
    assert window.header.title.text() == "Land finished · 2 repos"
    assert window.rows[0].pill.text() == "Needs you · 0:04"
    runs = durations.load_runs()
    assert [(r.repos, r.landed, r.seconds) for r in runs] == [(1, 0, 862.0)]
    window.finish([], "again")  # a second finish adds no second entry
    assert len(durations.load_runs()) == 1
    window.close()


def test_a_finished_row_opens_and_folds_with_its_button(qapp):
    window = _finished_window(qapp)
    row = window.rows[0]
    assert row.opener.isVisibleTo(row) and not row.steps.isVisibleTo(row)
    assert row.opener.accessibleName() == "Show steps of SONAR"
    assert not window.rows[1].opener.isVisibleTo(window.rows[1])  # nothing ran there
    row.opener.click()
    assert row.steps.isVisibleTo(row)
    lines = [(line[1].text(), line[3].text()) for line in row.steps._lines]
    assert [t for _l, t in lines] == ["4s", "", ""]  # skipped steps have no time
    assert lines[0][0].startswith("Commit") and lines[1][0].startswith("Merge")
    window.draw()  # a later render keeps it open
    assert row.steps.isVisibleTo(row)
    row.opener.click()
    assert not row.steps.isVisibleTo(row)
    window.close()


def test_the_earlier_line_shows_past_runs_and_not_this_one(qapp):
    window = _land_window(qapp)
    window.draw()
    assert not window.header.earlier.isVisibleTo(window.header)  # no history yet
    window.close()
    durations.record_run(datetime(2026, 11, 17, 16, 20), 6, 5, 5525)
    window = _land_window(qapp)
    window.draw()
    assert window.header.earlier.text() == "Earlier: 17 Nov 16:20, 6 repos, 1:32:05"
    assert window.header.earlier.isVisibleTo(window.header)
    window.close()


# --- review findings (docs/audit/land-pick-and-time-review.md) ---------------
def test_a_land_where_nothing_ran_is_not_logged(qapp):
    window = _land_window(qapp)
    window.on_repo_done("SONAR", LandResult("SONAR", "nothing"))
    window.on_repo_done("Backstage", LandResult("Backstage", "nothing"))
    window.finish([LandResult("SONAR", "nothing"), LandResult("Backstage", "nothing")], "x")
    assert durations.load_runs() == []  # review P3-4: "0 repos" never pushes a real run out
    window.close()


def test_two_rows_with_the_same_name_open_one_at_a_time(qapp):
    clock = Clock()
    window = LandWindow(clock=clock, wall=lambda: WALL)
    plans = [LandPlan("app", Path("/x"), (repo_tidy.Action("app", Path("/x"), "push", "b0",
                                                           "why", branch="main"),))
             for _ in range(2)]
    window.start(plans)
    for _ in range(2):
        window.on_step(StepEvent("app", 0, 1, "push", "start", clock()))
        clock.t += 2
        window.on_step(StepEvent("app", 0, 1, "push", "end", clock(), clock() - 2, "done"))
        window.on_repo_done("app", LandResult("app", "landed"))
    window.finish([LandResult("app", "landed")] * 2, "x")
    window.draw()
    window.rows[1].opener.click()
    assert window.rows[1].steps.isVisibleTo(window.rows[1])
    assert not window.rows[0].steps.isVisibleTo(window.rows[0])  # review P3-7
    window.close()
