"""What the Land and Check builds progress windows show, without Qt.

Spec: `docs/specs/progress-windows.md` §8.5-8.6. The engine says what happens
(`land.StepEvent`, build output lines); this module turns that into numbers and
words a window can show: percent, counts, elapsed, time left, "done around",
the alive signal, and one row per repo or app with its stage track. Widgets in
`ui/progress_window.py` render a `Snapshot` of it and decide nothing.

Time comes from an injected monotonic `clock` and wall clock `wall`, so tests
drive it with a counter. The estimate is the median of past durations
(`lab_hub.durations`); with none, the window says "Estimating…" instead of
guessing, and a step that runs past its median says "Taking longer than usual"
rather than a negative number.
"""

from __future__ import annotations

import math
import re
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from . import durations

STALE_AFTER = 60.0  # seconds without output before the activity line turns amber
OUTPUT_KEEP = 5000  # lines of live output kept while nothing renders them
LINE_MAX = 4000  # characters of one output line shown; one 2 MB line froze the pane

WAITING, RUNNING, DONE, FAILED, SKIPPED = "waiting", "running", "done", "failed", "skipped"
FINISHED = (DONE, FAILED, SKIPPED)
NEEDS, NOTHING, PARTIAL, NONE = "needs", "nothing", "partial", "none"

ESTIMATING = "Estimating…"
OVERRUN = "Taking longer than usual"

# ----------------------------------------------------------------------
# Text that came from git, Claude Code or a build script
# ----------------------------------------------------------------------
# OSC (a terminal title, a hyperlink) and the other string commands, up to
# their terminator; the class stops at ESC, so an unterminated one costs linear time.
_STRING = re.compile(r"\x1b[\]PX^_][^\x07\x1b]*(?:\x07|\x1b\\)")
_CSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_ESC = re.compile(r"\x1b[ -/]*[0-~]")  # the remaining two- and three-byte escapes
# Every C0 control but tab, DEL, C1, and the bidi controls that can turn the
# rest of a line around (a status that reads backwards).
_CONTROL = re.compile("[\x00-\x08\x0a-\x1f\x7f-\x9f\u061c\u200e\u200f"
                      "\u202a-\u202e\u2066-\u2069]")


def plain(text: str) -> str:
    """Tool output with terminal escapes (OSC, CSI and the rest), control
    characters but tab, and bidi controls removed. Shown as plain text on top
    of this; this only keeps a terminal program's codes out of a line."""
    text = _ESC.sub("", _CSI.sub("", _STRING.sub("", str(text))))
    return _CONTROL.sub("", text)


def cap(line: str) -> str:
    """One output line, cut to LINE_MAX characters."""
    return line if len(line) <= LINE_MAX else line[:LINE_MAX] + "…"


# ----------------------------------------------------------------------
# Formatting
# ----------------------------------------------------------------------
def fmt_clock(seconds: float) -> str:
    """m:ss, never negative."""
    s = max(0, int(seconds))
    return f"{s // 60}:{s % 60:02d}"


def fmt_left(seconds: float) -> str:
    """~N min (rounded up) above 60 s, ~N s at or below."""
    s = max(0.0, float(seconds))
    if s > 60:
        return f"~{math.ceil(s / 60)} min"
    return f"~{math.ceil(s)} s"


def fmt_took(seconds: float) -> str:
    """How long a finished step took: 4s, or m:ss from a minute on."""
    s = max(0.0, float(seconds))
    return f"{int(round(s))}s" if s < 59.5 else fmt_clock(s)


def _n(count: int, one: str, many: str | None = None) -> str:
    return f"{count} {one if count == 1 else (many or one + 's')}"


# ----------------------------------------------------------------------
# Stages
# ----------------------------------------------------------------------
LAND_STAGES = (("commit", "Commit"), ("merge", "Merge and test"), ("push", "Push"),
               ("tidy", "Tidy"))
_LAND_STAGE = {"commit": "commit", "merge": "merge", "claude_merge": "merge",
               "push": "push", "pull": "push", "delete_branch": "tidy",
               "remove_worktree": "tidy"}


def land_stage(kind: str) -> str | None:
    """Which column of the Land track a step kind belongs to."""
    return _LAND_STAGE.get(kind)


BUILD_STAGES = (("build", "Build"), ("package", "Package"), ("install", "Install"),
                ("verify", "Verify"))
_BUILD_INDEX = {key: i for i, (key, _label) in enumerate(BUILD_STAGES)}
# Markers from the real build scripts in the lab (spec §8.5), case-sensitive,
# not depending on the ▸/✓ glyphs. A self-test runs before install in every
# script that has one, so its lines count as package.
_BUILD_MARKERS = (
    ("build", re.compile(r"INFO: PyInstaller:|with PyInstaller")),
    ("package", re.compile(r"INFO: Building BUNDLE|INFO: Build complete!|^\W*Built: "
                           r"|^Sealed \(ad hoc\):|Self-testing the build|Running self-test")),
    ("install", re.compile(r"^\W*Installing to |^\W*Installed: |hecking the new build first")),
)


def build_stage(line: str) -> str | None:
    """build, package, install or None for one line of build output."""
    for stage, pattern in _BUILD_MARKERS:
        if pattern.search(line):
            return stage
    return None


# ----------------------------------------------------------------------
# What a window renders
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class StageView:
    label: str
    state: str  # none | waiting | running | partial | done | failed | skipped
    note: str = ""


@dataclass(frozen=True)
class StepView:
    label: str
    state: str
    time: str = ""
    fraction: float | None = None  # the running step's share of its median


@dataclass(frozen=True)
class RowView:
    name: str
    icon: str  # waiting | running | done | needs | failed | terminal | unknown | nothing
    stages: tuple[StageView, ...] = ()
    detail: str = ""  # shown across the track when there is no track
    status: str = ""
    tone: str = ""  # ok | run | warn | bad | muted | wait
    reason: str = ""
    reason_tone: str = "warn"
    expanded: bool = False
    steps: tuple[StepView, ...] = ()
    then: str = ""
    stage_notes: bool = False  # show each stage's time under its chip


@dataclass(frozen=True)
class Snapshot:
    title: str
    live: bool
    started: bool  # False while Check builds is still at Review
    percent: int
    subtitle: str
    elapsed: str
    left: str  # "~4 min left", "Estimating…", "Taking longer than usual" or ""
    done_around: str  # HH:MM, or "" with no estimate
    overrun: bool
    counts: tuple[tuple[str, str], ...]  # (text, tone)
    activity: str
    stale: bool
    outcome: str
    outcome_tone: str
    details: tuple[str, ...]
    rows: tuple[RowView, ...]
    current_line: str = ""  # Check builds: the apps already up to date, on one line


# ----------------------------------------------------------------------
# The model
# ----------------------------------------------------------------------
@dataclass
class Unit:
    kind: str
    label: str
    estimate: float | None
    state: str = WAITING
    started: float | None = None
    ended: float | None = None


@dataclass
class Row:
    key: str
    name: str
    subject: str
    units: list[Unit] = field(default_factory=list)
    state: str = WAITING
    status: str = ""
    tone: str = ""
    reason: str = ""
    reason_tone: str = "warn"
    started: float | None = None
    ended: float | None = None
    # Check builds only
    category: str = ""
    note: str = ""
    stage: int = 0
    stages: list[str] = field(default_factory=list)
    entered: float = 0.0
    took: dict[int, float] = field(default_factory=dict)
    matched: bool = False


class RunModel:
    """Times, the alive signal, the estimate and the output buffer; the rows
    are a subclass's. Every event marks it dirty; a window renders `snapshot()`."""

    def __init__(self, history: durations.History | None = None, *,
                 clock=time.monotonic, wall=datetime.now) -> None:
        self.history = history or {}
        self.clock = clock
        self.wall = wall
        self.rows: list[Row] = []
        self.started = clock()
        self.last_activity = self.started
        self.ended: float | None = None
        self.outcome = ""
        self.outcome_tone = ""
        self.details: tuple[str, ...] = ()
        self._output: deque[str] = deque(maxlen=OUTPUT_KEEP)
        self.dirty = True

    # -- events ---------------------------------------------------------------
    def touch(self) -> None:
        self.last_activity = self.clock()
        self.dirty = True

    def on_output(self, line: str) -> None:
        self._output.append(cap(plain(line)))
        self.touch()

    def take_output(self) -> list[str]:
        """Lines not yet shown, oldest first; the pane appends them once a render."""
        lines = list(self._output)
        self._output.clear()
        return lines

    def finish(self, line: str, tone: str = "", details: tuple[str, ...] = ()) -> None:
        self.ended = self.clock()
        self.outcome, self.outcome_tone = plain(line), tone
        self.details = tuple(plain(d) for d in details)
        self.dirty = True

    # -- reading --------------------------------------------------------------
    @property
    def live(self) -> bool:
        return self.ended is None

    def _now(self) -> float:
        return self.ended if self.ended is not None else self.clock()

    def elapsed(self) -> float:
        return max(0.0, self._now() - self.started)

    def stale_seconds(self) -> float:
        return max(0.0, self.clock() - self.last_activity)

    def activity(self) -> tuple[str, bool]:
        s = self.stale_seconds()
        if s >= STALE_AFTER:
            return f"No output for {fmt_clock(s)}. Still running.", True
        return f"Last activity {int(s)}s ago", False

    def units(self) -> list[Unit]:
        return [u for row in self.rows for u in row.units]

    def left(self, units: list[Unit] | None = None) -> tuple[float | None, bool]:
        """Seconds left over these units, or None if any still to run has no
        history; and whether the running one is past its median."""
        now = self.clock()
        total, known, overrun = 0.0, True, False
        for unit in self.units() if units is None else units:
            if unit.state == WAITING:
                if unit.estimate is None:
                    known = False
                else:
                    total += unit.estimate
            elif unit.state == RUNNING:
                if unit.estimate is None:
                    known = False
                    continue
                ran = now - (unit.started if unit.started is not None else now)
                overrun = overrun or ran > unit.estimate
                total += max(0.0, unit.estimate - ran)
        return (total if known else None), overrun

    def _times(self) -> tuple[str, str, bool]:
        if not self.live:
            return "", "", False
        left, overrun = self.left()
        around = ""
        if left is not None:
            around = (self.wall() + timedelta(seconds=left)).strftime("%H:%M")
        if overrun:
            return OVERRUN, around, True
        if left is None:
            return ESTIMATING, "", False
        return f"{fmt_left(left)} left", around, False

    def _row_status_left(self, row: Row) -> tuple[str, str]:
        """For a running row: its own time left, the estimate's absence, or overrun."""
        left, overrun = self.left(row.units)
        if overrun:
            return OVERRUN, "warn"
        if left is None:
            return ESTIMATING, "run"
        return f"{fmt_left(left)} left", "run"

    def _waiting_status(self, row: Row, first: bool) -> tuple[str, str]:
        left, _over = self.left(row.units)
        text = "Next" if first else "Waiting"
        return (f"{text} · {fmt_left(left)}" if left is not None else text), "wait"

    def _snapshot(self, *, title: str, started: bool, percent: int, subtitle: str,
                  counts, rows, current_line: str = "") -> Snapshot:
        self.dirty = False
        left, around, overrun = self._times() if started else ("", "", False)
        activity, stale = self.activity() if (self.live and started) else ("", False)
        return Snapshot(
            title=title, live=self.live, started=started, percent=percent,
            subtitle=subtitle, elapsed=fmt_clock(self.elapsed()) if started else "",
            left=left, done_around=around, overrun=overrun, counts=tuple(counts),
            activity=activity, stale=stale, outcome=self.outcome,
            outcome_tone=self.outcome_tone, details=self.details, rows=tuple(rows),
            current_line=current_line)

    def _percent(self, done: float, total: int) -> int:
        if not self.live:
            return 100
        if total <= 0:
            return 0
        return min(99, int(math.floor(100 * done / total)))


def _short(label: str, name: str) -> str:
    """A step label without the repo name it starts with: the row already says it."""
    text = plain(label).strip()
    return text[len(name) + 2:] if text.startswith(f"{name}: ") else text


def _steps_then(units: list[Unit], now: float, name: str = "") -> tuple[tuple[StepView, ...], str]:
    """The running row's step list: the last few finished, the running one with
    its own timer, then one "Then: …" line for what is still waiting."""
    finished = [u for u in units if u.state in FINISHED]
    shown: list[StepView] = []
    if len(finished) > 5:
        shown.append(StepView(f"{len(finished) - 5} earlier steps finished", DONE))
        finished = finished[-5:]
    for unit in units:
        if unit in finished:
            took = (unit.ended or now) - (unit.started or now)
            shown.append(StepView(_short(unit.label, name), unit.state, fmt_took(took)))
        elif unit.state == RUNNING:
            ran = now - (unit.started or now)
            if unit.estimate:
                shown.append(StepView(_short(unit.label, name), RUNNING,
                                      f"{fmt_clock(ran)} / ~{fmt_clock(unit.estimate)}",
                                      min(1.0, ran / unit.estimate)))
            else:
                shown.append(StepView(_short(unit.label, name), RUNNING, fmt_clock(ran)))
    waiting = [_short(u.label, name) for u in units if u.state == WAITING]
    then = ""
    if waiting:
        then = "Then: " + ", ".join(waiting[:3])
        if len(waiting) > 3:
            then += f" and {len(waiting) - 3} more"
    return tuple(shown), then


# ----------------------------------------------------------------------
# Land
# ----------------------------------------------------------------------
class LandModel(RunModel):
    """One row per repo, one unit per planned step. The denominator is fixed
    from the plans before the first step runs."""

    def __init__(self, plans, history=None, *, clock=time.monotonic, wall=datetime.now):
        super().__init__(history, clock=clock, wall=wall)
        for plan in plans:
            subject = durations.subject("repo", plan.name)
            units = [Unit(a.kind, a.label,
                          durations.estimate(self.history, subject, a.kind))
                     for a in plan.actions]
            row = Row(plan.name, plain(plan.name), subject, units)
            if not units:  # nothing planned: say so now, not "Waiting · ~0 s"
                row.state, row.status, row.tone = NOTHING, "Nothing to land", "muted"
            self.rows.append(row)

    def _row(self, name: str) -> Row | None:
        # A repo name could repeat; the first one not yet finished is the one landing.
        rows = [r for r in self.rows if r.key == name]
        for row in rows:
            if row.ended is None:
                return row
        return rows[-1] if rows else None

    def on_step(self, event) -> None:
        row = self._row(event.repo)
        if row is None or not 0 <= event.index < len(row.units):
            self.touch()
            return
        unit = row.units[event.index]
        if event.phase == "start":
            unit.state, unit.started = RUNNING, event.at
            if row.started is None:
                row.started = event.at
            row.state = RUNNING
        else:
            unit.state = event.outcome if event.outcome in FINISHED else FAILED
            unit.started = event.started
            unit.ended = event.at
        self.touch()

    def on_repo_done(self, name: str, result) -> None:
        row = self._row(name)
        if row is None:
            self.touch()
            return
        for unit in row.units:
            if unit.state in (WAITING, RUNNING):
                unit.state = SKIPPED  # stopped or never reached: the bar must not stall
        row.ended = self.clock()
        if row.started is None:
            row.started = row.ended
        row.reason = ""
        if result.state == "landed" and not result.remaining:
            row.state, row.tone = DONE, "ok"
            row.status = f"Landed · {fmt_clock(row.ended - row.started)}"
        elif result.state == "nothing":
            row.state, row.status, row.tone = NOTHING, "Nothing to land", "muted"
        else:
            row.state, row.status, row.tone = NEEDS, "Needs you", "warn"
            row.reason = plain(result.line if result.state == "landed" else result.reason)
        self.touch()

    def _stages(self, row: Row) -> tuple[StageView, ...]:
        views = []
        for key, label in LAND_STAGES:
            states = [u.state for u in row.units if land_stage(u.kind) == key]
            if not states:
                state = NONE
            elif RUNNING in states:
                state = RUNNING
            elif FAILED in states:
                state = FAILED
            elif all(s == WAITING for s in states):
                state = WAITING
            elif WAITING in states:
                state = PARTIAL
            elif all(s == DONE for s in states):
                state = DONE
            else:
                state = SKIPPED if all(s == SKIPPED for s in states) else DONE
            views.append(StageView(label, state))
        return tuple(views)

    def snapshot(self) -> Snapshot:
        now = self.clock()
        units = self.units()
        finished = sum(1 for u in units if u.state in FINISHED)
        running = next((r for r in self.rows if r.state == RUNNING), None)
        rows, first_waiting = [], True
        for row in self.rows:
            steps, then = (), ""
            if row.state == RUNNING:
                status, tone = self._row_status_left(row)
                steps, then = _steps_then(row.units, now, row.name)
                icon = "running"
            elif row.state == WAITING:
                status, tone = self._waiting_status(row, first_waiting and self.live)
                first_waiting = False
                icon = "waiting" if self.live else "nothing"
                if not self.live:
                    status, tone = "Not reached", "muted"
            else:
                status, tone = row.status, row.tone
                icon = {DONE: "done", NOTHING: "nothing"}.get(row.state, "needs")
            rows.append(RowView(
                name=row.name, icon=icon, stages=self._stages(row), status=status,
                tone=tone, reason=row.reason, expanded=row.state == RUNNING,
                steps=steps, then=then))
        counts = (
            (f"{sum(r.state == DONE for r in self.rows)} landed", "ok"),
            (f"{sum(r.state == RUNNING for r in self.rows)} running", "run"),
            (f"{sum(r.state == WAITING for r in self.rows)} waiting", "muted"),
            (f"{sum(r.state == NEEDS for r in self.rows)} needs you", "warn"),
        )
        total = len(units)
        if running is not None and self.live:
            subtitle = f"Working on {running.name} · {finished} of {total} steps"
        elif self.live:
            subtitle = f"{finished} of {total} steps"
        else:
            subtitle = f"{finished} of {total} steps finished"
        title = (f"Landing {self.rows[0].name}" if len(self.rows) == 1
                 else f"Landing {_n(len(self.rows), 'repo')}")
        return self._snapshot(title=title, started=True,
                              percent=self._percent(finished, total),
                              subtitle=subtitle, counts=counts, rows=rows)


# ----------------------------------------------------------------------
# Check builds
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class BuildItem:
    key: str
    name: str
    category: str  # current | rebuild | terminal | forward | no_command | unknown | missing
    note: str
    version: str
    command: str | None = None


@dataclass(frozen=True)
class BuildCheckView:
    """What `show_build_report` computed, kept as it was (spec §8.7): the same
    headline, informative text and command lists, plus one item per app."""

    headline: str
    info: str
    behind: bool
    commands: tuple[str, ...]
    by_hand: tuple[str, ...]
    forward: tuple[str, ...]
    folders: tuple[Path, ...]
    folder_names: str
    items: tuple[BuildItem, ...]
    apps: tuple[tuple[str, object], ...] = ()  # (command, ExternalApp) for in-app rebuilds

    @property
    def show_update(self) -> bool:
        return bool(self.commands or self.by_hand)

    @property
    def show_copy(self) -> bool:
        return bool(self.commands or self.by_hand or self.forward)

    @property
    def show_terminal(self) -> bool:
        # A report with only a release-clone move opens no Terminal (release-root-behind §5.1).
        return bool(self.commands or self.by_hand)

    def app_for(self, command: str):
        return next((app for cmd, app in self.apps if cmd == command), None)


def build_check_view(report, scoped: bool) -> BuildCheckView:
    """The build report's words and commands, exactly as the message box had them."""
    behind = [row for row in report if row.needs_rebuild]
    unknown = [row for row in report if row.verdict == "unknown"]

    if behind and len(report) == 1:
        headline = f"{report[0].app.name} would open something older than its source."
    elif behind:
        headline = (f"{len(behind)} of {len(report)} apps would open something older "
                    "than their source.")
    elif unknown:
        headline = f"Nothing is out of date, but {len(unknown)} could not be checked."
    elif not scoped:
        headline = "Every app is the newest build of itself."
    elif len(report) == 1:
        headline = f"{report[0].app.name} is the newest build of itself."
    else:
        # A scoped report cannot speak for apps it never looked at.
        headline = f"All {len(report)} apps are the newest build of themselves."

    lines = []
    for row in report:
        mark = {"current": "ok", "behind": "OLD", "uncommitted": "OLD",
                "unknown": "??", "missing": "--"}[row.verdict]
        version = row.version.text or "no version"
        lines.append(f"[{mark}] {row.app.name} — {version}\n      {row.note}")

    # Update now runs only what can run without a terminal. An installer that
    # refuses one (Provisio's) is listed for the owner to run, and an app with
    # no known build script is named rather than dropped.
    commands = [row.command for row in behind if row.runs_in_app]
    by_hand = [row.command for row in behind if row.by_hand and row.command]
    forward = [row.command for row in behind if row.forward and row.command]
    no_command = [row for row in behind if not row.command]
    if commands:
        lines.append("")
        lines.append("Update now runs:")
        lines.extend(f"  {command}" for command in commands)
    if by_hand:
        names = ", ".join(row.app.name for row in behind if row.by_hand and row.command)
        after = " after the rebuilds above succeed" if commands else ""
        lines.append("")
        lines.append(
            f"Update now opens Terminal for {names}{after} and starts the "
            "installer there. Each one asks you to confirm in its window "
            "(Provisio's asks you to type install); Lab Hub types nothing:"
        )
        lines.extend(f"  {command}" for command in by_hand)
    if forward:
        names = ", ".join(row.app.name for row in behind if row.forward)
        lines.append("")
        lines.append(
            f"Move the release clone first for {names} (its installer "
            "would only rebuild the old clone). Lab Hub runs nothing there; "
            "run it yourself after the runbook's CI and legal checks, then "
            "do its dependency and selftest steps:"
        )
        lines.extend(f"  {command}" for command in forward)
    if no_command:
        lines.append("")
        lines.append(
            f"No rebuild command for: {', '.join(r.app.name for r in no_command)}. "
            "Open in Terminal opens its folder; build it there by its own steps."
        )
        lines.extend(f"  {r.app.name}: {r.guide}" for r in no_command if r.guide)

    items = []
    for row in report:
        if row.verdict == "current":
            category = "current"
        elif row.verdict == "unknown":
            category = "unknown"
        elif row.verdict == "missing":
            category = "missing"
        elif row.runs_in_app:
            category = "rebuild"
        elif row.by_hand and row.command:
            category = "terminal"
        elif row.forward:
            category = "forward"
        else:
            category = "no_command"
        items.append(BuildItem(row.app.key, row.app.name, category, row.note,
                               row.version.text, row.command))

    return BuildCheckView(
        headline=headline, info="\n".join(lines), behind=bool(behind),
        commands=tuple(commands), by_hand=tuple(by_hand), forward=tuple(forward),
        folders=tuple(r.project for r in no_command if r.project is not None),
        folder_names=", ".join(r.app.name for r in no_command),
        items=tuple(items),
        apps=tuple((row.command, row.app) for row in behind if row.runs_in_app))


_STATIC = {
    # category: (icon, status, tone, reason)
    "unknown": ("unknown", "Cannot check", "muted", ""),
    "missing": ("unknown", "Not installed", "muted", ""),
    "forward": ("needs", "Needs you", "warn",
                "Move its release clone first; Lab Hub runs nothing there."),
    "no_command": ("needs", "Needs you", "warn",
                   "No rebuild command: Open in Terminal opens its folder."),
}


class BuildModel(RunModel):
    """Check builds: Review, then Update (one unit per in-app rebuild, each
    with its four stages or one "Rebuilding"), then Done."""

    def __init__(self, view: BuildCheckView, history=None, *, clock=time.monotonic,
                 wall=datetime.now):
        super().__init__(history, clock=clock, wall=wall)
        self.view = view
        self.step = "review"  # review | update | done
        self.current = [i for i in view.items if i.category == "current"]
        for item in view.items:
            if item.category == "current":
                continue
            subject = durations.subject("app", item.key)
            units = []
            if item.category == "rebuild":
                units = [Unit("rebuild", item.command or "",
                              durations.estimate(self.history, subject, "rebuild"))]
            self.rows.append(Row(item.key, plain(item.name), subject, units,
                                 category=item.category, note=plain(item.note)))

    def _row(self, key: str) -> Row | None:
        return next((r for r in self.rows if r.key == key), None)

    def _stage_history(self, row: Row) -> bool:
        return any(durations.estimate(self.history, row.subject, kind) is not None
                   for kind, _label in BUILD_STAGES[:3])

    # -- events ---------------------------------------------------------------
    def start_update(self) -> None:
        self.step = "update"
        self.started = self.last_activity = self.clock()
        self.dirty = True

    def start_command(self, key: str) -> None:
        row = self._row(key)
        now = self.clock()
        if row is not None and row.units:
            unit = row.units[0]
            unit.state, unit.started = RUNNING, now
            row.state, row.started = RUNNING, now
            # The build stage runs from the start: a script's set-up belongs to it.
            row.stage, row.entered, row.took, row.matched = 0, now, {}, False
            row.stages = [RUNNING, WAITING, WAITING, WAITING]
        self.touch()

    def on_build_output(self, key: str | None, line: str) -> None:
        self.on_output(line)
        row = self._row(key) if key else None
        if row is None or row.state != RUNNING:
            return
        stage = build_stage(plain(line))
        if stage is None:
            return
        index = _BUILD_INDEX[stage]
        row.matched = True
        if index <= row.stage:
            return  # a late marker for a stage already passed: ignored
        now = self.clock()
        row.took[row.stage] = now - row.entered
        row.stages[row.stage] = DONE
        for skipped in range(row.stage + 1, index):
            row.stages[skipped] = SKIPPED  # not seen; its time is the stage before's
        row.stage, row.entered = index, now
        row.stages[index] = RUNNING

    def end_command(self, key: str, ok: bool, cancelled: bool = False,
                    code: int | None = 0) -> None:
        """The command exited (`code` None: it never started). On success
        Verify starts (the version read)."""
        row = self._row(key)
        now = self.clock()
        if row is None or not row.units:
            self.touch()
            return
        unit = row.units[0]
        if ok:
            row.took[row.stage] = now - row.entered
            row.stages[row.stage] = DONE
            for later in range(row.stage + 1, 3):
                row.stages[later] = SKIPPED
            row.stage, row.entered = 3, now
            row.stages[3] = RUNNING
            unit.ended = now
        else:
            row.stages[row.stage] = SKIPPED if cancelled else FAILED
            unit.state, unit.ended = (SKIPPED if cancelled else FAILED), now
            row.state, row.ended = FAILED, now
            row.status, row.tone = ("Cancelled", "warn") if cancelled else ("Failed", "bad")
            row.reason = ("The build was stopped." if cancelled
                          else "It could not start; see the live output." if code is None
                          else f"It exited with code {code}; see the live output.")
            row.reason_tone = "warn" if cancelled else "bad"
        self.touch()

    def verified(self, key: str, version: str) -> dict[str, float]:
        """The installed version was read: the row is done. Returns the samples
        to record (only ever after exit 0): stages seen, verify, the whole run."""
        row = self._row(key)
        now = self.clock()
        if row is None or not row.units:
            return {}
        unit = row.units[0]
        row.took[3] = now - row.entered
        row.stages[3] = DONE
        unit.state = DONE
        row.state, row.ended = DONE, now
        row.status, row.tone = f"Rebuilt · {fmt_clock(now - (unit.started or now))}", "ok"
        row.reason = f"Installed: {version}" if version else "Installed; no version could be read."
        row.reason_tone = "muted"
        samples = {"rebuild": (unit.ended or now) - (unit.started or now), "verify": row.took[3]}
        if row.matched:
            for index, (kind, _label) in enumerate(BUILD_STAGES[:3]):
                if index in row.took and row.stages[index] == DONE:
                    samples[kind] = row.took[index]
        self.touch()
        return samples

    def finish(self, line: str, tone: str = "", details: tuple[str, ...] = ()) -> None:
        self.step = "done"
        super().finish(line, tone, details)

    # -- reading --------------------------------------------------------------
    def _track(self, row: Row, now: float) -> tuple[StageView, ...]:
        if row.state == WAITING and self.step == "update":
            if self._stage_history(row):
                return tuple(StageView(label, WAITING, self._median_note(row, kind))
                             for kind, label in BUILD_STAGES)
            return (StageView("Rebuilding", WAITING),)
        if not row.stages:
            return ()
        if not (row.matched or self._stage_history(row)):
            whole = (row.ended or now) - (row.started or now)
            state = {DONE: DONE, FAILED: FAILED}.get(row.state, RUNNING)
            if row.state == FAILED and row.units and row.units[0].state == SKIPPED:
                state = SKIPPED
            return (StageView("Rebuilding", state, fmt_clock(whole)),)
        views = []
        for index, (kind, label) in enumerate(BUILD_STAGES):
            state = row.stages[index]
            if state == DONE and index in row.took:
                note = fmt_clock(row.took[index])
            elif state == RUNNING:
                note = fmt_clock(now - row.entered)
            elif state == SKIPPED:
                note = "not seen"
            else:
                note = self._median_note(row, kind)
            views.append(StageView(label, state, note))
        return tuple(views)

    def _median_note(self, row: Row, kind: str) -> str:
        median = durations.estimate(self.history, row.subject, kind)
        return f"~{fmt_clock(median)}" if median is not None else ""

    def snapshot(self) -> Snapshot:
        now = self.clock()
        rebuilds = [r for r in self.rows if r.category == "rebuild"]
        has_commands = bool(self.view.commands)
        rows, first_waiting = [], True
        for row in self.rows:
            if row.category == "rebuild":
                if self.step == "review":
                    rows.append(RowView(row.name, "needs", detail=row.note,
                                        status="Out of date", tone="warn"))
                    continue
                if row.state == RUNNING:
                    status, tone = self._row_status_left(row)
                    icon = "running"
                elif row.state == WAITING:
                    if self.live:
                        status, tone = self._waiting_status(row, first_waiting)
                        icon = "waiting"
                    else:
                        status, tone, icon = "Not rebuilt", "muted", "nothing"
                    first_waiting = False
                else:
                    status, tone = row.status, row.tone
                    icon = "done" if row.state == DONE else "failed"
                rows.append(RowView(
                    row.name, icon, stages=self._track(row, now),
                    detail="" if row.state != WAITING or self.step == "update" else row.note,
                    status=status, tone=tone,
                    reason=row.note if row.state == RUNNING else row.reason,
                    reason_tone="muted" if row.state == RUNNING else row.reason_tone,
                    expanded=row.state == RUNNING, stage_notes=True))
            elif row.category == "terminal":
                reason = ("Its installer opens in Terminal after the rebuilds; confirm there."
                          if has_commands else
                          "Update now opens its installer in Terminal; confirm there.")
                rows.append(RowView(row.name, "terminal", detail=row.note,
                                    status="Your turn after" if has_commands
                                    else "Needs Terminal",
                                    tone="warn", reason=reason))
            else:
                icon, status, tone, reason = _STATIC[row.category]
                rows.append(RowView(row.name, icon, detail=row.note, status=status,
                                    tone=tone, reason=reason))

        counts = []
        if self.current:
            counts.append((f"{len(self.current)} up to date", "ok"))
        if self.step == "review":
            if rebuilds:
                counts.append((f"{len(rebuilds)} to rebuild", "run"))
        else:
            going = sum(r.state in (WAITING, RUNNING) for r in rebuilds)
            if going and self.live:
                counts.append((f"{going} rebuilding", "run"))
            if done := sum(r.state == DONE for r in rebuilds):
                counts.append((f"{done} rebuilt", "ok"))
            if failed := sum(r.state == FAILED for r in rebuilds):
                counts.append((f"{failed} not rebuilt", "bad"))
        tally = {c: sum(r.category == c for r in self.rows)
                 for c in ("terminal", "unknown", "forward", "no_command")}
        if tally["terminal"]:
            counts.append((f"{tally['terminal']} needs Terminal", "warn"))
        if tally["unknown"]:
            counts.append((f"{tally['unknown']} cannot check", "muted"))
        if needs := tally["forward"] + tally["no_command"]:
            counts.append((f"{needs} needs you", "warn"))

        started = self.step != "review"
        finished = sum(1.0 for r in rebuilds if r.state in (DONE, FAILED))
        running = next((r for r in rebuilds if r.state == RUNNING), None)
        if running is not None and running.stages:
            if running.matched or self._stage_history(running):
                finished += sum(s in (DONE, SKIPPED) for s in running.stages) / 4
        if self.step == "review":
            subtitle = self.view.headline
        elif running is not None:
            index = rebuilds.index(running) + 1
            subtitle = f"Updating {running.name} · {index} of {len(rebuilds)}"
        elif self.live:
            subtitle = f"Updating {len(rebuilds)} app{'s' if len(rebuilds) != 1 else ''}"
        else:
            subtitle = ""
        current_line = "   ".join(
            f"{i.name} {i.version}".strip() if i.version else i.name for i in self.current)
        return self._snapshot(title="Check builds", started=started,
                              percent=self._percent(finished, len(rebuilds)),
                              subtitle=subtitle, counts=counts, rows=rows,
                              current_line=current_line)
