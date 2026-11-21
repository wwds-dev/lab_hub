"""Security review of spec `apps-discovery`: P2-1, P2-2, P2-3.

Each test is the review's reproduction, so a regression fails here instead of
hanging, running a stranger's interpreter, or stopping Lab Hub from starting.
"""

from __future__ import annotations

import os
import stat
import threading
from pathlib import Path

import pytest

from lab_hub import discovery
from lab_hub.launcher import registry

import main


@pytest.fixture(autouse=True)
def _restore_registry():
    registry.use(None)
    registry.last_error = None
    yield
    registry.use(None)
    registry.last_error = None


# -- P2-1: the self-test never runs an added project's interpreter -------------
def _planted_project(lab: Path, name: str, marker: Path) -> None:
    """A project with a `main.py` and a venv python that leaves `marker`."""
    project = lab / name
    (project / ".venv" / "bin").mkdir(parents=True)
    (project / "main.py").write_text("print('hi')\n")
    python = project / ".venv" / "bin" / "python"
    python.write_text(f"#!/bin/sh\ntouch '{marker}'\n")
    python.chmod(0o755)


def _app(key: str, *, local: bool) -> registry.ExternalApp:
    return registry.ExternalApp(key, key.title(), key, "main.py", "s", local=local)


def test_the_selftest_probe_never_runs_an_added_projects_python(tmp_path):
    lab = tmp_path / "lab"
    local_marker, shipped_marker = tmp_path / "local-ran", tmp_path / "shipped-ran"
    _planted_project(lab, "stranger", local_marker)
    _planted_project(lab, "curated", shipped_marker)
    registry.use(registry.Registry(suites=(
        _app("curated", local=False), _app("stranger", local=True))))

    results = main._probe_child_launches(lab)

    assert not local_marker.exists(), "the self-test ran an apps-local.toml entry's python"
    # apps.toml entries are probed as before (the probe's whole purpose).
    assert shipped_marker.exists()
    by_name = {name: (ok, why) for name, ok, why in results}
    assert by_name["Stranger"][0] is None
    assert "added" in by_name["Stranger"][1]


# -- P2-2: a deeply nested answers file reads as corrupt, not as a crash -------
NESTED = b"[" * 30000 + b"]" * 30000


@pytest.fixture
def deep_json():
    path = discovery.dismissed_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(NESTED)
    assert path.stat().st_size < discovery.DISMISSED_MAX_BYTES
    return path


def test_a_deeply_nested_answers_file_reads_as_corrupt(deep_json):
    assert discovery.load_dismissed() == {}
    assert discovery.dismissed_ok() is False


def test_every_reader_of_a_nested_answers_file_survives(deep_json, tmp_path):
    from datetime import date

    assert discovery.hidden(tmp_path, date(2026, 1, 1)) == []
    discovery.forget("kaila")  # nothing to undo: the corrupt file is left alone
    assert deep_json.read_bytes() == NESTED

    discovery.dismiss("kaila", "never", date(2026, 1, 1))  # sets the bad file aside

    assert set(discovery.load_dismissed()) == {"kaila"}
    assert discovery.dismissed_ok() is True
    assert (deep_json.parent / (deep_json.name + ".bad")).read_bytes() == NESTED


def test_lab_hub_starts_with_a_deeply_nested_answers_file(qapp, deep_json):
    from ui.main_window import MainWindow

    win = MainWindow()
    try:
        tab = win.settings_tab
        assert tab.hidden_unreadable.isVisibleTo(tab)
    finally:
        win._quitting = True
        win.close()
        win.deleteLater()


# -- P2-3: a FIFO or a link as apps-local.toml is a bad file, never a hang -----
def _within(seconds: float, call):
    """`call()`'s result, or fail: a regression hangs on a FIFO's blocking open,
    and a hung test would stop the whole suite."""
    box: dict = {}

    def run():
        try:
            box["value"] = call()
        except BaseException as error:  # noqa: BLE001 - re-raised below
            box["error"] = error

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(seconds)
    if thread.is_alive():
        # Unblock the stuck open so the daemon thread ends, then fail.
        try:
            fd = os.open(registry.local_path(), os.O_WRONLY | os.O_NONBLOCK)
            os.close(fd)
        except OSError:
            pass
        pytest.fail(f"reading the local file hung for more than {seconds} s")
    if "error" in box:
        raise box["error"]
    return box["value"]


def _fifo():
    path = registry.local_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    os.mkfifo(path)
    assert stat.S_ISFIFO(os.lstat(path).st_mode)


def test_a_fifo_as_the_local_file_is_a_bad_file_not_a_hang():
    _fifo()

    entries, why = _within(5, registry._read_local)

    assert entries is None and why and "not a regular file" in why


def test_a_fifo_keeps_the_last_good_local_part_and_says_so():
    good = (_app("mine", local=True),)
    registry._last_local = good
    _fifo()

    merged = _within(5, lambda: registry._with_local(registry.Registry(suites=())))

    assert registry.local_ok is False
    assert registry.local_note and "Your added projects file was ignored" in registry.local_note
    assert [a.key for a in merged.suites] == ["mine"]


def test_a_symlink_as_the_local_file_is_refused(tmp_path):
    target = tmp_path / "elsewhere.toml"
    target.write_text('[[suites]]\nkey = "x"\nname = "X"\nproject = "x"\nsummary = "s"\n')
    path = registry.local_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.symlink_to(target)

    entries, why = _within(5, registry._read_local)

    assert entries is None and why


def test_a_device_as_the_local_file_is_refused():
    path = registry.local_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.symlink_to("/dev/zero")
    except OSError:
        pytest.skip("cannot link")

    entries, why = _within(5, registry._read_local)

    assert entries is None and why


def test_a_regular_local_file_and_a_missing_one_still_read(tmp_path):
    assert registry._read_local() == ((), None)

    path = registry.local_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('[[suites]]\nkey = "x"\nname = "X"\nproject = "x"\nsummary = "s"\n')

    entries, why = registry._read_local()

    assert why is None and [a.key for a in entries] == ["x"]


def test_an_oversized_local_file_is_still_refused():
    path = registry.local_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"#" * (registry.LOCAL_MAX_BYTES + 1))

    entries, why = registry._read_local()

    assert entries is None and "over" in why
