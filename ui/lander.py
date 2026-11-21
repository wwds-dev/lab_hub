"""Runs Land off the UI thread and reports back on it.

Two jobs, one thread at a time: `plan()` reads git for some repos (so the
window can say what Land will do before it does it) and `run()` lands the plans
one repo after another, continuing past a repo that fails. Results come back as
Qt signals on the UI thread, drained from a queue by a timer, the same shape as
`repo_tidy_dialogs._Background` and the Resolve progress box it replaces.

Spec: `docs/specs/land-from-tiles.md`.
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from lab_hub import claude_resolve, land, land_resolve

Repos = list[tuple[str, Path]]


class Lander(QObject):
    planned = Signal(object)  # list[land.LandPlan]
    progress = Signal(str, str)  # repo name, one line
    step = Signal(object)  # land.StepEvent, start and end of each step
    repo_done = Signal(str, object)  # repo name, land.LandResult
    finished = Signal(object)  # list[land.LandResult]
    # A row's button ran and its stop is still there: repo name, the new
    # land.LandResult for the row (spec land-blocker-actions §3.1, §3.2).
    held = Signal(str, object)

    def __init__(self, parent: QObject | None = None, *, clock=time.monotonic) -> None:
        super().__init__(parent)
        self._clock = clock
        self._events: queue.SimpleQueue = queue.SimpleQueue()
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._drain)
        self._thread: threading.Thread | None = None
        self._stopper = claude_resolve.Stopper()
        self._running = False

    @property
    def busy(self) -> bool:
        return self._thread is not None

    @property
    def running(self) -> bool:
        """True while a Land (not just a look at git) is under way."""
        return self.busy and self._running

    def plan(self, repos: Repos) -> bool:
        """Look at each repo. False if a job is already running."""
        if self.busy:
            return False
        self._start(lambda: self._plan(repos), running=False)
        return True

    def run(self, plans: list[land.LandPlan]) -> bool:
        if self.busy:
            return False
        self._stopper = claude_resolve.Stopper()
        self._start(lambda: self._run(plans), running=True)
        return True

    def clear(self, name: str, path: Path, action: str,
              stops: tuple[land_resolve.Stop, ...] = ()) -> bool:
        """A Land row's button: "retry" checks origin, "close" closes the
        processes in `stops` the owner confirmed. Then the repo is planned as
        a Land is (`planned`), or the row is told why not (`held`). False if
        a job is already running."""
        if self.busy or action not in (land_resolve.RETRY, land_resolve.CLOSE):
            return False
        self._start(lambda: self._clear(name, path, action, stops), running=False)
        return True

    def stop(self) -> None:
        """End the running Claude Code or test run and skip everything after it.
        A branch already landed stays landed; its push waits for the next Land."""
        self._stopper.stop()

    def shutdown(self, wait_s: float = 8.0) -> None:
        """The app is quitting: end any Claude or test step, give the worker a
        moment to leave the repo in a clean state, and stop watching it."""
        self._stopper.stop()
        thread = self._thread
        if thread is not None:
            thread.join(wait_s)
        self._timer.stop()

    # -- worker side --------------------------------------------------------
    def _start(self, work, running: bool) -> None:
        self._running = running
        self._thread = threading.Thread(target=work, daemon=True, name="lab-hub-land")
        self._timer.start()
        self._thread.start()

    def _plan(self, repos: Repos) -> None:
        plans = []
        for name, path in repos:
            try:
                plans.append(land.make_plan(name, path))
            except Exception as exc:  # noqa: BLE001 - one unreadable repo must not hide the rest
                plans.append(land.LandPlan(name, path, (), ()))
                self._events.put(("progress", name, f"could not read the repo: {exc}"))
        self._events.put(("planned", plans))

    def _clear(self, name: str, path: Path, action: str, stops) -> None:
        try:
            held = self._cleared(name, path, action, stops)
        except Exception as exc:  # noqa: BLE001 - the row must say something
            held = land.LandResult(name, "not_landed", f"{type(exc).__name__}: {exc}")
        if held is not None:
            self._events.put(("held", name, held))
            return
        self._plan([(name, path)])

    @staticmethod
    def _cleared(name: str, path: Path, action: str, stops) -> land.LandResult | None:
        """None when the stop is gone; else the row's new result."""
        if action == land_resolve.RETRY:
            why = land.preflight(land.LandPlan(name, path))
            if not why:
                return None
            return land.LandResult(name, "not_landed", why,
                                   stops=(land_resolve.Stop(name, str(path), why),))
        left = []
        for stop in stops:
            done = land_resolve.close_processes(path, Path(stop.target), stop.processes)
            if not done.clear:
                left.append(land_resolve.Stop(name, stop.target, done.reason, done.left))
        if not left:
            return None
        return land.LandResult(name, "not_landed", land.plain_reason(left[0].reason),
                               stops=tuple(left))

    def _run(self, plans: list[land.LandPlan]) -> None:
        results = []
        for plan in plans:
            name = plan.name
            if self._stopper.stopped:
                result = land.LandResult(name, "not_landed", "it was stopped", stopped=True)
            else:
                result = land.land(plan, progress=lambda line, n=name: self._events.put(
                    ("progress", n, line)), stop=self._stopper,
                    events=lambda e: self._events.put(("step", e)), clock=self._clock)
                if self._stopper.stopped and not result.landed:
                    result = replace(result, stopped=True)  # Stop cut this one short
            results.append(result)
            self._events.put(("repo_done", name, result))
        self._events.put(("finished", results))

    # -- UI side ------------------------------------------------------------
    def _drain(self) -> None:
        done = None
        while True:
            try:
                event = self._events.get_nowait()
            except queue.Empty:
                break
            kind = event[0]
            if kind == "progress":
                self.progress.emit(event[1], event[2])
            elif kind == "step":
                self.step.emit(event[1])
            elif kind == "repo_done":
                self.repo_done.emit(event[1], event[2])
            elif kind in ("planned", "finished", "held"):
                done = event
        if done is not None:
            # Clear the busy state before the callback, so it may start the next job.
            self._thread = None
            self._running = False
            self._timer.stop()
            if done[0] == "held":
                self.held.emit(done[1], done[2])
            else:
                (self.planned if done[0] == "planned" else self.finished).emit(done[1])
