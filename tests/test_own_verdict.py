"""Lab Hub's own build verdict, off the UI thread (spec apps-discovery §13.4).

The one worker thread in the change. What matters: the git-costing call never
runs on the GUI thread or on the poll, a burst of requests costs at most one
extra run, a failure leaves the line blank rather than breaking the tile, and
the thread touches no Qt.
"""

from __future__ import annotations

import inspect
import threading
from pathlib import Path

import pytest

from lab_hub import self_update
from lab_hub.launcher.state import BuildStatus, Version
from ui import own_verdict
from ui.own_verdict import OwnVerdict

# The conftest fixture patches `request` out for every other test; this file is
# the one that needs the real one.
_REAL_REQUEST = OwnVerdict.request


@pytest.fixture(autouse=True)
def real_request(monkeypatch):
    monkeypatch.setattr(OwnVerdict, "request", _REAL_REQUEST)


def _row(note: str = "") -> BuildStatus:
    return BuildStatus(self_update.SELF, Version(), "current", note)


def _wait(verdict: OwnVerdict) -> None:
    """Let the running worker finish, then deliver its result like the timer."""
    thread = verdict._thread
    assert thread is not None
    thread.join(5)
    assert not thread.is_alive()
    verdict._drain()


class _Gate:
    """A `self_status` that holds until released, and records each call."""

    def __init__(self) -> None:
        self.calls: list[Path] = []
        self.threads: list[threading.Thread] = []
        self.started = threading.Event()
        self.release = threading.Event()

    def __call__(self, lab_root, **kwargs):
        self.calls.append(lab_root)
        self.threads.append(threading.current_thread())
        self.started.set()
        assert self.release.wait(5)
        return _row(f"run {len(self.calls)}")


def test_a_request_runs_self_status_off_the_gui_thread_and_signals_the_row(
        qapp, monkeypatch, tmp_path):
    seen = []

    def fake(lab_root, **kwargs):
        seen.append((lab_root, threading.current_thread()))
        return _row("fine")

    monkeypatch.setattr(self_update, "self_status", fake)
    verdict = OwnVerdict()
    got = []
    verdict.ready.connect(lambda result: got.append((result, threading.current_thread())))

    verdict.request(tmp_path)
    _wait(verdict)

    assert seen[0][0] == tmp_path
    assert seen[0][1] is not threading.main_thread()
    result, delivered_on = got[0]
    assert result.row.note == "fine" and result.error is None
    assert delivered_on is threading.main_thread()
    assert not verdict.busy
    verdict.shutdown()


def test_a_burst_of_requests_costs_one_extra_run(qapp, monkeypatch, tmp_path):
    gate = _Gate()
    monkeypatch.setattr(self_update, "self_status", gate)
    verdict = OwnVerdict()
    got = []
    verdict.ready.connect(got.append)

    verdict.request(tmp_path / "one")
    assert gate.started.wait(5)
    for name in ("two", "three", "four", "five"):
        verdict.request(tmp_path / name)  # all while the first is running
    gate.release.set()
    while verdict.busy:  # the first result, then the one follow-up it started
        _wait(verdict)

    assert [c.name for c in gate.calls] == ["one", "five"]  # the latest root wins
    assert [r.row.note for r in got] == ["run 1", "run 2"]
    assert not verdict.busy
    verdict.shutdown()


def test_a_failure_leaves_the_line_blank_with_the_reason(qapp, monkeypatch, tmp_path):
    def broken(lab_root, **kwargs):
        raise RuntimeError("git is not installed")

    monkeypatch.setattr(self_update, "self_status", broken)
    verdict = OwnVerdict()
    got = []
    verdict.ready.connect(got.append)

    verdict.request(tmp_path)
    _wait(verdict)

    assert got[0].row is None
    assert got[0].error == "git is not installed"
    # And it is not stuck: the next request runs.
    monkeypatch.setattr(self_update, "self_status", lambda root, **kw: _row("ok"))
    verdict.request(tmp_path)
    _wait(verdict)
    assert got[1].row.note == "ok"
    verdict.shutdown()


def test_an_exception_with_no_message_still_gives_a_reason(qapp, monkeypatch, tmp_path):
    def broken(lab_root, **kwargs):
        raise KeyError()

    monkeypatch.setattr(self_update, "self_status", broken)
    verdict = OwnVerdict()
    got = []
    verdict.ready.connect(got.append)

    verdict.request(tmp_path)
    _wait(verdict)

    assert got[0].error == "KeyError"
    verdict.shutdown()


def test_the_worker_touches_no_qt():
    """The thread body only calls `self_status` and puts on the queue; the
    module starts no QThread (the worker is a plain daemon thread)."""
    source = inspect.getsource(OwnVerdict._work)
    for forbidden in ("emit", "Signal", "QTimer", "self.ready", "self._timer", "setText"):
        assert forbidden not in source
    assert "QThread" not in inspect.getsource(own_verdict)


def test_after_shutdown_nothing_runs_and_nothing_is_signalled(qapp, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(self_update, "self_status", lambda root, **kw: calls.append(root) or _row())
    verdict = OwnVerdict()
    got = []
    verdict.ready.connect(got.append)
    verdict.request(tmp_path)
    _wait(verdict)
    assert len(got) == 1

    verdict.shutdown()
    verdict.request(tmp_path)  # idle and closed: must not start a thread

    assert verdict._thread is None
    assert calls == [tmp_path]
    assert not verdict._timer.isActive()

    # A run still in flight when the app quits delivers nothing.
    other = OwnVerdict()
    late = []
    other.ready.connect(late.append)
    other.request(tmp_path)
    other.shutdown()
    other._thread.join(5)
    other._drain()
    assert late == []
