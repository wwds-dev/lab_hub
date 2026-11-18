"""The progress model behind both windows (spec progress-windows §8.5, §8.6, §8.12).

Qt-free: a fake clock and fixture events drive it; what is checked is the
numbers and words a window would show.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from lab_hub import durations, launcher, progress, repo_tidy
from lab_hub.land import LandPlan, LandResult, StepEvent


class Clock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def tick(self, s: float) -> None:
        self.t += s


WALL = datetime(2026, 11, 17, 14, 0, 0)


def _plan(name, *kinds):
    actions = tuple(repo_tidy.Action(name, Path("/x"), k, f"t{i}", "why",
                                     branch="main") for i, k in enumerate(kinds))
    return LandPlan(name, Path("/x"), actions)


def _history(**subjects):
    return {key: {k: list(v) for k, v in kinds.items()} for key, kinds in subjects.items()}


class Feed:
    """Sends start/end events the way `land.land` does, against the fake clock."""

    def __init__(self, model, clock):
        self.model, self.clock, self.open = model, clock, {}

    def start(self, repo, index, kind, count=9):
        self.open[(repo, index)] = self.clock()
        self.model.on_step(StepEvent(repo, index, count, kind, "start", self.clock(),
                                     label=f"{kind} {index}"))

    def end(self, repo, index, kind, outcome="done", count=9):
        self.model.on_step(StepEvent(repo, index, count, kind, "end", self.clock(),
                                     self.open.pop((repo, index)), outcome, f"{kind} {index}"))


# ---------------------------------------------------------------- formatting
@pytest.mark.parametrize("seconds, text", [
    (0, "~0 s"), (1, "~1 s"), (59.2, "~60 s"), (60, "~60 s"), (61, "~2 min"),
    (120, "~2 min"), (121, "~3 min"), (-5, "~0 s"),
])
def test_fmt_left(seconds, text):
    assert progress.fmt_left(seconds) == text


@pytest.mark.parametrize("seconds, text", [(0, "0:00"), (9.9, "0:09"), (61, "1:01"),
                                           (3599, "59:59"), (3600, "1:00:00"),
                                           (5525, "1:32:05"), (36000, "10:00:00"),
                                           (-3, "0:00")])
def test_fmt_clock(seconds, text):
    assert progress.fmt_clock(seconds) == text


def test_plain_strips_ansi_and_controls_but_keeps_tabs_and_markup():
    assert progress.plain("\x1b[1;32mok\x1b[0m\tdone\r\x07") == "ok\tdone"
    assert progress.plain("<b>x</b>") == "<b>x</b>"  # markup is shown, not stripped


# ---------------------------------------------------------------- stages
def test_land_stage():
    assert [progress.land_stage(k) for k in
            ("commit", "merge", "claude_merge", "push", "pull", "delete_branch",
             "remove_worktree", "other")] == [
        "commit", "merge", "merge", "push", "push", "tidy", "tidy", None]


@pytest.mark.parametrize("line, stage", [
    ("123 INFO: PyInstaller: 6.11.1, contrib hooks: 2024.10", "build"),
    ("▸ Building Imprint.app with PyInstaller (this takes ~1 min)…", "build"),
    ("4567 INFO: Building BUNDLE BUNDLE-00.toc", "package"),
    ("8910 INFO: Build complete! The results are available in: dist", "package"),
    ("Built: dist.noindex/Lab Hub.app (212M)", "package"),
    ("✓ Built: /x/dist/Imprint.app", "package"),
    ("Sealed (ad hoc): dist.noindex/SONAR.app", "package"),
    ("Self-testing the build…", "package"),
    ("Running self-test against the built binary…", "package"),
    ("▸ Installing to /Applications/Imprint.app…", "install"),
    ("✓ Installed: /Applications/Imprint.app", "install"),
    ("Installed: /Applications/Lab Hub.app", "install"),
    ("The agent runs /x: checking the new build first…", "install"),
    ("Checking the new build first…", "install"),
    ("123 INFO: Building EXE from EXE-00.toc", None),
    ("Built-in modules loaded", None),
    ("<b>Built: x</b>", None),
    ("# Builds \"SONAR.app\" with pyinstaller", None),
    ("", None),
])
def test_build_stage_on_real_lines(line, stage):
    assert progress.build_stage(line) == stage


# ---------------------------------------------------------------- Land model
def test_percent_counts_and_stages_for_two_repos_with_a_failure_and_a_stop():
    clock = Clock()
    plans = [_plan("a", "commit", "merge", "push", "delete_branch"),
             _plan("b", "merge", "push")]
    model = progress.LandModel(plans, {}, clock=clock, wall=lambda: WALL)
    feed = Feed(model, clock)

    snap = model.snapshot()
    assert snap.percent == 0 and snap.title == "Landing 2 repos"
    assert [c for c, _t in snap.counts] == ["0 landed", "0 running", "2 waiting", "0 needs you"]
    assert [s.state for s in snap.rows[0].stages] == ["waiting"] * 4
    assert [s.state for s in snap.rows[1].stages] == ["none", "waiting", "waiting", "none"]

    feed.start("a", 0, "commit"); clock.tick(4); feed.end("a", 0, "commit")
    feed.start("a", 1, "merge"); clock.tick(2); feed.end("a", 1, "merge", "failed")
    feed.start("a", 2, "push")
    snap = model.snapshot()
    assert snap.percent == 33  # 2 of 6, floored
    assert snap.subtitle == "Working on a · 2 of 6 steps"
    row = snap.rows[0]
    assert row.expanded and row.icon == "running"
    assert [s.state for s in row.stages] == ["done", "failed", "running", "waiting"]
    # The row already names the repo, so its steps do not repeat "a: ".
    labels = [a.label.removeprefix("a: ") for a in plans[0].actions]
    assert all(not label.startswith("a: ") for label in labels)
    assert [s.label for s in row.steps] == labels[:3]
    assert [s.state for s in row.steps] == ["done", "failed", "running"]
    assert [s.time for s in row.steps[:2]] == ["4s", "2s"]
    assert row.then == "Then: " + labels[3]
    assert [c for c, _t in snap.counts] == ["0 landed", "1 running", "1 waiting", "0 needs you"]

    clock.tick(1); feed.end("a", 2, "push")
    feed.start("a", 3, "delete_branch"); clock.tick(1); feed.end("a", 3, "delete_branch")
    model.on_repo_done("a", LandResult("a", "not_landed", "remote said no", 3, 1))
    # b is stopped before it starts: its units are skipped, so the bar reaches the end
    model.on_repo_done("b", LandResult("b", "not_landed", "it was stopped"))
    snap = model.snapshot()
    assert snap.percent == 99  # every unit finished, but capped until finish
    assert [s.state for s in snap.rows[1].stages] == ["none", "skipped", "skipped", "none"]
    assert snap.rows[0].status == "Needs you" and snap.rows[0].reason == "remote said no"
    assert snap.rows[1].reason == "it was stopped"
    assert [c for c, _t in snap.counts] == ["0 landed", "0 running", "0 waiting", "2 needs you"]

    model.finish("Landed 0 of 2 repos.", "warn", ("a: Not landed: remote said no",))
    snap = model.snapshot()
    assert snap.percent == 100 and not snap.live
    assert snap.outcome == "Landed 0 of 2 repos." and snap.details
    assert snap.left == "" and snap.activity == ""


def test_landed_with_branches_left_needs_you_and_a_clean_land_is_landed():
    clock = Clock()
    model = progress.LandModel([_plan("a", "merge"), _plan("b", "merge"), _plan("c")],
                               {}, clock=clock)
    feed = Feed(model, clock)
    feed.start("a", 0, "merge"); clock.tick(42); feed.end("a", 0, "merge")
    model.on_repo_done("a", LandResult("a", "landed"))
    model.on_repo_done("b", LandResult("b", "landed", remaining=1))
    model.on_repo_done("c", LandResult("c", "nothing"))
    rows = model.snapshot().rows
    assert rows[0].status == "Landed" and rows[0].took == "0:42" and rows[0].tone == "ok"
    assert rows[1].took == "" and rows[2].took == ""  # no step of theirs ran
    assert rows[1].status == "Needs you" and "1 branch needs your decision" in rows[1].reason
    assert rows[2].status == "Nothing to land"
    assert [c for c, _t in model.snapshot().counts][::3] == ["1 landed", "1 needs you"]


def test_a_repo_with_nothing_planned_says_so_from_the_start_and_is_not_waiting():
    clock = Clock()
    model = progress.LandModel([_plan("a", "merge"), _plan("b")],
                               _history(**{"repo:a": {"merge": [5.0]}}), clock=clock)
    snap = model.snapshot()
    assert snap.rows[1].status == "Nothing to land" and snap.rows[1].tone == "muted"
    assert snap.rows[0].status.startswith("Next")
    assert "1 waiting" in [c for c, _t in snap.counts]


def test_the_estimate_is_none_until_every_remaining_unit_has_history():
    clock = Clock()
    plans = [_plan("a", "merge", "push")]
    hist = _history(**{"repo:a": {"merge": [10, 20, 30]}})
    model = progress.LandModel(plans, hist, clock=clock, wall=lambda: WALL)
    snap = model.snapshot()
    assert snap.left == progress.ESTIMATING and snap.done_around == ""

    hist["repo:a"]["push"] = [5]
    model = progress.LandModel(plans, hist, clock=clock, wall=lambda: WALL)
    snap = model.snapshot()
    assert snap.left == "~25 s left"
    assert snap.done_around == "14:00"  # 25 s after 14:00:00
    assert snap.rows[0].status == "Next · ~25 s"


def test_left_counts_down_never_goes_negative_and_overrun_is_said():
    clock = Clock()
    hist = _history(**{"repo:a": {"merge": [100], "push": [20]}})
    model = progress.LandModel([_plan("a", "merge", "push")], hist, clock=clock,
                               wall=lambda: WALL)
    feed = Feed(model, clock)
    feed.start("a", 0, "merge")
    clock.tick(40)
    snap = model.snapshot()
    assert snap.left == "~2 min left" and not snap.overrun  # 60 + 20 s, over a minute
    assert snap.rows[0].status == "~2 min left"
    clock.tick(5)
    assert model.left() == (75, False)
    assert snap.rows[0].steps[0].time == "0:40 / ~1:40"
    assert snap.rows[0].steps[0].fraction == pytest.approx(0.4)
    clock.tick(65)  # 110 s into a step whose median is 100 s
    left, overrun = model.left()
    assert left == 20 and overrun  # the merge contributes 0, never -10
    snap = model.snapshot()
    assert snap.left == progress.OVERRUN and snap.overrun
    assert snap.rows[0].status == progress.OVERRUN
    assert snap.done_around == "14:00"


def test_activity_text_at_59_and_60_seconds():
    clock = Clock()
    model = progress.LandModel([_plan("a", "merge")], {}, clock=clock)
    clock.tick(59.9)
    text, stale = model.activity()
    assert text == "Last activity 59s ago" and not stale
    clock.tick(0.1)
    text, stale = model.activity()
    assert text == "No output for 1:00. Still running." and stale
    model.on_output("pytest: 212 passed so far")
    assert model.activity() == ("Last activity 0s ago", False)
    snap = model.snapshot()
    assert snap.activity == "Last activity 0s ago" and not snap.stale


def test_output_is_buffered_cleaned_and_taken_once():
    model = progress.LandModel([], {})
    model.on_output("\x1b[31m<b>x</b>\x1b[0m")
    model.on_output("second")
    assert model.take_output() == ["<b>x</b>", "second"]
    assert model.take_output() == []
    for i in range(progress.OUTPUT_KEEP + 10):
        model.on_output(str(i))
    kept = model.take_output()
    assert len(kept) == progress.OUTPUT_KEEP and kept[-1] == str(progress.OUTPUT_KEEP + 9)


def test_an_event_for_an_unknown_repo_or_index_is_ignored():
    clock = Clock()
    model = progress.LandModel([_plan("a", "merge")], {}, clock=clock)
    model.on_step(StepEvent("zzz", 0, 1, "merge", "start", 1.0))
    model.on_step(StepEvent("a", 7, 1, "merge", "start", 1.0))
    model.on_repo_done("zzz", LandResult("zzz", "landed"))
    assert model.snapshot().rows[0].icon == "waiting"


def test_the_first_waiting_row_is_next_and_a_single_repo_is_named():
    model = progress.LandModel([_plan("a", "merge")], {})
    snap = model.snapshot()
    assert snap.title == "Landing a" and snap.rows[0].status == "Next"
    model = progress.LandModel([_plan("a", "merge"), _plan("b", "merge")], {})
    assert [r.status for r in model.snapshot().rows] == ["Next", "Waiting"]


# ---------------------------------------------------------------- Check builds
def _app(key):
    return launcher.ExternalApp(key, key.upper(), key, "main.py", "s")


def _status(key, verdict="behind", command=None, **kw):
    return launcher.BuildStatus(_app(key), launcher.Version(kw.pop("ver", "")), verdict,
                                kw.pop("note", "older."), None, command, **kw)


def test_build_check_view_keeps_the_headlines_and_text():
    current = (_status("a", "current", note="matches."),)
    assert progress.build_check_view(current, scoped=False).headline == \
        "Every app is the newest build of itself."
    assert progress.build_check_view(current, scoped=True).headline == \
        "A is the newest build of itself."
    two = (_status("c", "current"), _status("d", "current"))
    assert progress.build_check_view(two, scoped=True).headline == \
        "All 2 apps are the newest build of themselves."
    assert progress.build_check_view((_status("u", "unknown"),), scoped=False).headline == \
        "Nothing is out of date, but 1 could not be checked."
    one = (_status("b", command="cd /b && ./build_app.sh"),)
    view = progress.build_check_view(one, scoped=True)
    assert view.headline == "B would open something older than its source."
    assert view.commands == ("cd /b && ./build_app.sh",) and view.show_update
    assert "Update now runs:\n  cd /b && ./build_app.sh" in view.info
    assert view.info.startswith("[OLD] B — no version\n      older.")
    assert view.app_for("cd /b && ./build_app.sh").key == "b"

    mixed = (_status("p", command="cd /r && ./i.sh", by_hand=True),
             _status("q", command="cd /q && ./build_app.sh"),
             _status("f", command="git -C /r merge --ff-only", forward=True),
             _status("n", project=Path("/n"), guide=Path("/n/BUILDING.md")))
    view = progress.build_check_view(mixed, scoped=True)
    assert view.headline == "4 of 4 apps would open something older than their source."
    assert "Update now opens Terminal for P after the rebuilds above succeed" in view.info
    assert "Move the release clone first for F" in view.info
    assert "No rebuild command for: N." in view.info and "N: /n/BUILDING.md" in view.info
    assert view.folders == (Path("/n"),) and view.folder_names == "N"
    assert [i.category for i in view.items] == ["terminal", "rebuild", "forward", "no_command"]
    only_forward = progress.build_check_view((mixed[2],), scoped=True)
    assert only_forward.show_copy and not only_forward.show_update
    assert not only_forward.show_terminal


def _build_model(clock, hist=None, *rows):
    rows = rows or (_status("x", command="cd /x && ./build_app.sh"),
                    _status("y", command="cd /y && ./build_app.sh"),
                    _status("ok", "current", ver="2.3"))
    view = progress.build_check_view(rows, scoped=False)
    return progress.BuildModel(view, hist or {}, clock=clock, wall=lambda: WALL)


def test_review_then_stages_advance_on_markers_and_samples_are_returned():
    clock = Clock()
    model = _build_model(clock)
    snap = model.snapshot()
    assert not snap.started and snap.subtitle.startswith("2 of 3 apps would open")
    assert snap.rows[0].status == "Out of date" and snap.rows[0].detail == "older."
    assert snap.current_line == "OK 2.3"
    assert [c for c, _t in snap.counts] == ["1 up to date", "2 to rebuild"]

    model.start_update()
    model.start_command("x")
    snap = model.snapshot()
    assert snap.started and snap.left == progress.ESTIMATING
    assert [s.label for s in snap.rows[0].stages] == ["Rebuilding"]  # no history, no marker yet
    clock.tick(10)
    model.on_build_output("x", "12 INFO: PyInstaller: 6.11")
    clock.tick(30)
    model.on_build_output("x", "Self-testing the build…")
    snap = model.snapshot()
    assert [s.state for s in snap.rows[0].stages] == ["done", "running", "waiting", "waiting"]
    assert snap.rows[0].stages[0].note == "0:40"  # build ran from the command's start
    assert snap.percent == 12  # (0 + 1/4) of 2 commands
    clock.tick(5)
    model.on_build_output("x", "12 INFO: PyInstaller: late line")  # ignored: already past
    model.on_build_output("x", "Installed: /Applications/X.app")
    clock.tick(2)
    model.end_command("x", ok=True)
    clock.tick(1)
    samples = model.verified("x", "v1.2")
    assert samples == {"build": 40, "package": 5, "install": 2, "verify": 1, "rebuild": 47}
    snap = model.snapshot()
    assert snap.rows[0].status == "Rebuilt · 0:48" and snap.rows[0].reason == "Installed: v1.2"
    assert snap.percent == 50
    assert [c for c, _t in snap.counts] == ["1 up to date", "1 rebuilding", "1 rebuilt"]


def test_a_jump_marks_the_skipped_stage_not_seen():
    clock = Clock()
    model = _build_model(clock)
    model.start_update()
    model.start_command("x")
    clock.tick(10)
    model.on_build_output("x", "▸ Installing to /Applications/X.app…")
    stages = model.snapshot().rows[0].stages
    assert [s.state for s in stages] == ["done", "skipped", "running", "waiting"]
    assert stages[1].note == "not seen"
    clock.tick(3)
    model.end_command("x", ok=True)
    samples = model.verified("x", "")
    assert "package" not in samples and samples["build"] == 10 and samples["install"] == 3


def test_a_run_with_no_marker_is_one_rebuilding_stage_and_records_no_stages():
    clock = Clock()
    model = _build_model(clock)
    model.start_update()
    model.start_command("x")
    model.on_build_output("x", "compiling…")
    clock.tick(30)
    model.end_command("x", ok=True)
    samples = model.verified("x", "1.0")
    assert set(samples) == {"rebuild", "verify"}
    stages = model.snapshot().rows[0].stages
    assert [(s.label, s.state) for s in stages] == [("Rebuilding", "done")]


def test_stage_history_shows_four_stages_from_the_start_and_estimates_by_rebuild():
    clock = Clock()
    hist = _history(**{"app:x": {"build": [40], "rebuild": [100]},
                       "app:y": {"rebuild": [50]}})
    model = _build_model(clock, hist)
    model.start_update()
    snap = model.snapshot()
    assert [s.label for s in snap.rows[0].stages] == ["Build", "Package", "Install", "Verify"]
    assert snap.rows[0].stages[0].note == "~0:40"
    assert snap.left == "~3 min left"  # 100 + 50 s
    model.start_command("x")
    clock.tick(30)
    snap = model.snapshot()
    assert snap.left == "~2 min left" and snap.rows[0].status == "~2 min left"
    clock.tick(15)
    assert model.left(model.rows[0].units) == (55, False)
    assert model.snapshot().rows[0].status == "~55 s left"
    assert snap.subtitle == "Updating X · 1 of 2"


def test_a_failed_or_cancelled_command_is_said_and_returns_nothing_to_record():
    clock = Clock()
    model = _build_model(clock)
    model.start_update()
    model.start_command("x")
    model.end_command("x", ok=False, code=2)
    snap = model.snapshot()
    assert snap.rows[0].status == "Failed" and "code 2" in snap.rows[0].reason
    model.finish("A rebuild failed — see the log above.", "bad")
    snap = model.snapshot()
    assert snap.rows[1].status == "Not rebuilt" and snap.percent == 100

    model = _build_model(clock)
    model.start_update()
    model.start_command("x")
    model.end_command("x", ok=False, cancelled=True)
    assert model.snapshot().rows[0].status == "Cancelled"


def test_static_rows_say_their_verdict_in_words():
    clock = Clock()
    model = _build_model(clock, None,
                         _status("p", command="cd /r && ./i.sh", by_hand=True),
                         _status("u", "unknown", note="no stamp."),
                         _status("n"))
    rows = model.snapshot().rows
    assert (rows[0].icon, rows[0].status) == ("terminal", "Needs Terminal")
    assert (rows[1].status, rows[1].detail) == ("Cannot check", "no stamp.")
    assert rows[2].status == "Needs you"
    assert [c for c, _t in model.snapshot().counts] == [
        "1 needs Terminal", "1 cannot check", "1 needs you"]


def test_durations_subjects_match_the_model(tmp_path):
    """What the window records is what the model looks up next time."""
    file = tmp_path / "d.json"
    durations.record(durations.subject("app", "x"), "rebuild", 60, path=file)
    model = _build_model(Clock(), durations.load(path=file))
    model.start_update()
    assert model.rows[0].units[0].estimate == 60


# ---------------------------------------------------------------- after Review/Verify/Secure
def test_plain_strips_osc_c1_del_and_bidi_controls():
    """Secure P3-4: a hyperlink's OSC text, C1 and DEL stayed, and an RLO could
    turn the rest of a line around."""
    raw = ("\x1b]8;;https://x.example\x1b\\click\x1b]8;;\x1b\\ ‮abc‬ "
           "\x9b31m \x7f\x1b(B\x1b7ok\x1b]0;title\x07⁦x⁩‏")
    assert progress.plain(raw) == "click abc 31m okx"
    # Unterminated: only the escape itself goes; the rest is shown as text.
    assert progress.plain("\x1b]8;;unterminated <b>x</b>") == "8;;unterminated <b>x</b>"
    assert progress.plain("naïve — ✓ 日本\ttab") == "naïve — ✓ 日本\ttab"


def test_a_very_long_output_line_is_cut():
    """Secure P3-3: one 2 MB line froze the pane for a minute."""
    model = progress.LandModel([], {})
    model.on_output("x" * progress.LINE_MAX)
    model.on_output("y" * (progress.LINE_MAX + 1))
    exact, cut = model.take_output()
    assert exact == "x" * progress.LINE_MAX
    assert cut == "y" * progress.LINE_MAX + "…"


def test_names_reasons_labels_and_the_outcome_are_cleaned_for_display():
    clock = Clock()
    name = "rep‮o"
    model = progress.LandModel([_plan(name, "merge")], {}, clock=clock)
    Feed(model, clock).start(name, 0, "merge")
    running = model.snapshot().rows[0]
    assert running.name == "repo"
    assert running.steps[0].label == "Merge t0 into main — why"  # cleaned, then shortened
    model.on_repo_done(name, LandResult(name, "not_landed", "no\x1b[31m way‮"))
    model.finish("done\x9b", "warn", ("a⁦b",))
    snap = model.snapshot()
    assert snap.rows[0].name == "repo" and snap.rows[0].reason == "no way"
    assert snap.outcome == "done" and snap.details == ("ab",)
    assert progress._short(f"{name}: merge \x1b]0;t\x07it", "repo") == "merge it"


def test_a_running_step_with_no_history_says_estimating():
    """QA LF4: a running step without history counted as 0 s left."""
    clock = Clock()
    model = progress.LandModel([_plan("a", "merge")], {}, clock=clock, wall=lambda: WALL)
    Feed(model, clock).start("a", 0, "merge")
    clock.tick(5)
    snap = model.snapshot()
    assert snap.left == progress.ESTIMATING and snap.done_around == ""
    assert snap.rows[0].status == progress.ESTIMATING


def test_done_around_adds_the_time_left_to_the_wall_clock():
    """QA LF5: 90 s from 14:00:00 is 14:01, which `wall()` alone cannot say."""
    model = progress.LandModel([_plan("a", "merge")], _history(**{"repo:a": {"merge": [90]}}),
                               clock=Clock(), wall=lambda: WALL)
    snap = model.snapshot()
    assert snap.left == "~2 min left" and snap.done_around == "14:01"


def test_at_exactly_the_median_it_is_not_yet_taking_longer():
    """QA LF2: overrun is past the median, not at it."""
    clock = Clock()
    model = progress.LandModel([_plan("a", "merge")], _history(**{"repo:a": {"merge": [30]}}),
                               clock=clock, wall=lambda: WALL)
    Feed(model, clock).start("a", 0, "merge")
    clock.tick(30)
    assert model.left() == (0, False)
    assert model.snapshot().left == "~0 s left"
    clock.tick(0.5)
    assert model.left() == (0, True)


def test_overrun_is_said_even_when_a_later_step_has_no_history():
    """QA LF6: past the median wins over "Estimating…"."""
    clock = Clock()
    model = progress.LandModel([_plan("a", "merge", "push")],
                               _history(**{"repo:a": {"merge": [10]}}), clock=clock,
                               wall=lambda: WALL)
    Feed(model, clock).start("a", 0, "merge")
    clock.tick(20)
    snap = model.snapshot()
    assert snap.left == progress.OVERRUN and snap.overrun and snap.done_around == ""


def test_a_stage_with_a_failed_step_and_a_running_one_is_running():
    """QA LS1: a running step outranks an earlier failure in the same column."""
    clock = Clock()
    model = progress.LandModel([_plan("a", "merge", "claude_merge", "push")], {}, clock=clock)
    feed = Feed(model, clock)
    feed.start("a", 0, "merge")
    feed.end("a", 0, "merge", "failed")
    feed.start("a", 1, "claude_merge")
    stages = {s.label: s.state for s in model.snapshot().rows[0].stages}
    assert stages["Merge and test"] == progress.RUNNING
    feed.end("a", 1, "claude_merge", "failed")
    stages = {s.label: s.state for s in model.snapshot().rows[0].stages}
    assert stages["Merge and test"] == progress.FAILED


def test_a_long_step_list_folds_earlier_steps_and_the_rest():
    """QA P3: more than five finished steps, more than three waiting, and a
    column half done."""
    clock = Clock()
    kinds = ("commit",) * 7 + ("push",) * 5
    model = progress.LandModel([_plan("a", *kinds)], {}, clock=clock)
    feed = Feed(model, clock)
    for i in range(6):
        feed.start("a", i, "commit")
        clock.tick(1)
        feed.end("a", i, "commit")
    feed.start("a", 6, "commit")
    row = model.snapshot().rows[0]
    assert row.steps[0].label == "1 earlier steps finished"
    assert len(row.steps) == 1 + 5 + 1
    assert row.then == "Then: Push t7 — why, Push t8 — why, Push t9 — why and 2 more"
    feed.end("a", 6, "commit")
    feed.start("a", 7, "push")
    feed.end("a", 7, "push")
    stages = {s.label: s.state for s in model.snapshot().rows[0].stages}
    assert stages["Push"] == progress.PARTIAL


def test_a_command_that_could_not_start_says_so():
    clock = Clock()
    model = _build_model(clock)
    model.start_update()
    model.start_command("x")
    model.end_command("x", ok=False, code=None)
    row = model.snapshot().rows[0]
    assert row.status == "Failed" and row.reason == "It could not start; see the live output."


# ------------------------------------------- land-pick-and-time: times at the end
class Wall:
    def __init__(self, t: datetime = WALL) -> None:
        self.t = t

    def __call__(self) -> datetime:
        return self.t


def test_the_end_keeps_the_total_time_and_the_clock_span():
    clock, wall = Clock(), Wall(datetime(2026, 11, 18, 13, 55, 10))
    model = progress.LandModel([_plan("a", "merge")], {}, clock=clock, wall=wall)
    feed = Feed(model, clock)
    feed.start("a", 0, "merge"); clock.tick(862); feed.end("a", 0, "merge")
    assert model.snapshot().took == ""  # live: elapsed and time left, as before
    model.on_repo_done("a", LandResult("a", "landed"))
    wall.t = datetime(2026, 11, 18, 14, 9, 32)
    model.finish("Landed 1 of 1 repos.")
    clock.tick(500)  # time after the end does not count
    snap = model.snapshot()
    assert snap.took == "Took 14:22 · 13:55 to 14:09"
    assert snap.title == "Land finished · a"


def test_a_run_over_an_hour_reads_hours():
    clock = Clock()
    model = progress.LandModel([_plan("a", "merge"), _plan("b", "push")], {}, clock=clock,
                               wall=Wall())
    clock.tick(5525)
    model.finish("x")
    snap = model.snapshot()
    assert snap.took.startswith("Took 1:32:05 · ") and snap.title == "Land finished · 2 repos"


def test_every_started_row_has_its_time_and_the_status_word_stays_bare():
    from lab_hub import handoff

    clock = Clock()
    model = progress.LandModel([_plan("a", "merge"), _plan("b", "merge"), _plan("c", "push"),
                                _plan("d"), _plan("e", "push")], {}, clock=clock, wall=Wall())
    feed = Feed(model, clock)
    feed.start("a", 0, "merge"); clock.tick(42); feed.end("a", 0, "merge")
    model.on_repo_done("a", LandResult("a", "landed"))
    feed.start("b", 0, "merge"); clock.tick(41); feed.end("b", 0, "merge", "failed")
    model.on_repo_done("b", LandResult("b", "not_landed", "tests fail"))
    feed.start("c", 0, "push"); clock.tick(63)
    model.on_repo_done("c", LandResult("c", "not_landed", "stopped", stopped=True))
    model.on_repo_done("d", LandResult("d", "nothing"))
    model.finish("Landed 1 of 5 repos.")
    rows = {r.name: r for r in model.snapshot().rows}
    assert (rows["a"].status, rows["a"].took) == ("Landed", "0:42")
    assert (rows["b"].status, rows["b"].took) == ("Needs you", "0:41")
    assert (rows["c"].status, rows["c"].took) == ("Stopped", "1:03")
    assert (rows["d"].status, rows["d"].took) == ("Nothing to land", "")
    assert (rows["e"].status, rows["e"].took) == ("Not reached", "")
    # Ask Claude matches the bare word, never the time
    assert handoff.qualifies(rows["b"]) and not handoff.qualifies(rows["a"])
    assert model.snapshot().title == "Land stopped"


def test_a_finished_row_opens_into_every_step_with_its_time():
    clock = Clock()
    model = progress.LandModel([_plan("a", *(["delete_branch"] * 7)), _plan("b", "push")], {},
                               clock=clock, wall=Wall())
    feed = Feed(model, clock)
    for i in range(7):
        feed.start("a", i, "delete_branch", 7); clock.tick(2)
        feed.end("a", i, "delete_branch", "done", 7)
    model.on_repo_done("a", LandResult("a", "landed"))
    live = {r.name: r for r in model.snapshot().rows}
    assert not live["a"].openable  # while Land runs, only the running row opens
    model.finish("x")
    rows = {r.name: r for r in model.snapshot().rows}
    assert rows["a"].openable and not rows["a"].expanded
    assert [s.time for s in rows["a"].steps] == ["2s"] * 7  # all of them, none folded
    assert not rows["b"].openable  # never reached: nothing to open


def test_earlier_line_is_the_last_three_newest_first():
    runs = [durations.Run(datetime(2026, 11, d, 9, 10), 6, 5, s, d == 17)
            for d, s in ((14, 30), (15, 41), (16, 5525), (17, 862))]
    assert progress.earlier_line(runs) == (
        "Earlier: 17 Nov 09:10, 6 repos, 14:22, stopped · 16 Nov 09:10, 6 repos, 1:32:05 · "
        "15 Nov 09:10, 6 repos, 0:41")
    assert progress.earlier_line(runs[:1]).endswith("14 Nov 09:10, 6 repos, 0:30")
    assert progress.earlier_line([durations.Run(datetime(2026, 1, 2, 3, 4), 1, 1, 9)]) == \
        "Earlier: 2 Jan 03:04, 1 repo, 0:09"
    assert progress.earlier_line([]) == ""
