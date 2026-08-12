"""Finding and starting the standalone apps.

`child_env` is the important one. A frozen Lab Hub exports its own Qt paths
into the process; a launched app that inherited them loaded *our* cocoa plugin
against *its* QtGui and was killed by qFatal inside QApplication() before any
window appeared. From source there is nothing to inherit, which is exactly why
that shipped — so these tests set the variables by hand.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from lab_hub import launcher


# ----------------------------------------------------------------------
# Environment sanitising
# ----------------------------------------------------------------------
def test_our_qt_paths_are_kept_from_the_child(monkeypatch):
    monkeypatch.setenv("QT_PLUGIN_PATH", "/Applications/Lab Hub.app/…/plugins")
    monkeypatch.setenv("QML2_IMPORT_PATH", "/Applications/Lab Hub.app/…/qml")

    env = launcher.child_env()

    assert "QT_PLUGIN_PATH" not in env
    assert "QML2_IMPORT_PATH" not in env


def test_the_value_pyinstaller_saved_is_put_back(monkeypatch):
    """PyInstaller stashes what it replaced as <VAR>_ORIG. Dropping ours and
    ignoring theirs would still leave the child worse off than an ordinary
    shell would."""
    monkeypatch.setenv("DYLD_LIBRARY_PATH", "/inside/the/bundle")
    monkeypatch.setenv("DYLD_LIBRARY_PATH_ORIG", "/what/the/user/had")

    env = launcher.child_env()

    assert env["DYLD_LIBRARY_PATH"] == "/what/the/user/had"
    assert "DYLD_LIBRARY_PATH_ORIG" not in env, "the bookkeeping should not leak"


def test_unrelated_variables_survive(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("HOME", "/Users/someone")

    env = launcher.child_env()

    assert env["PATH"] == "/usr/bin:/bin"
    assert env["HOME"] == "/Users/someone"


def test_nothing_is_stripped_when_running_from_source(monkeypatch):
    """The reason this bug was invisible in development."""
    for name in launcher.INHERITED_VARS:
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(f"{name}_ORIG", raising=False)

    assert set(os.environ) - set(launcher.child_env()) == set()


# ----------------------------------------------------------------------
# Locating an app
# ----------------------------------------------------------------------
def _project(root: Path, name: str, entry: str = "main.py", body: str = "") -> Path:
    project = root / name
    project.mkdir(parents=True, exist_ok=True)
    script = project / entry
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(body or "pass\n")
    return project


def test_a_checkout_is_reported_as_source(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "no-such-Applications")
    _project(tmp_path, "sonar")
    app = launcher.ExternalApp("sonar", "SONAR", "sonar", "main.py", "")

    state, detail = launcher.status(app, tmp_path)

    assert state == "source"
    assert "sonar" in detail


def test_an_app_that_is_nowhere_is_reported_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "no-such-Applications")
    app = launcher.ExternalApp("ghost", "Ghost", "ghost", "main.py", "")

    state, detail = launcher.status(app, tmp_path)

    assert state == "missing"
    assert "not in /Applications" in detail


def test_launching_something_that_is_nowhere_explains_itself(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "no-such-Applications")
    app = launcher.ExternalApp("ghost", "Ghost", "ghost", "main.py", "")

    with pytest.raises(launcher.LaunchError) as raised:
        launcher.launch(app, tmp_path)

    assert "Settings tab" in str(raised.value), "tell the user how to fix it"


# ----------------------------------------------------------------------
# Reporting a child that dies
# ----------------------------------------------------------------------
def test_a_child_that_dies_reports_why(tmp_path, monkeypatch):
    """This used to go to DEVNULL, which turned a diagnosable crash into
    'nothing happened' — the single worst part of the original bug."""
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "no-such-Applications")
    monkeypatch.setattr(launcher, "venv_python", lambda project: Path(sys.executable))
    _project(
        tmp_path,
        "doomed",
        body="import sys\nprint('the reason', file=sys.stderr)\nsys.exit(3)\n",
    )
    app = launcher.ExternalApp("doomed", "Doomed", "doomed", "main.py", "")

    with pytest.raises(launcher.LaunchError) as raised:
        launcher.launch(app, tmp_path)

    message = str(raised.value)
    assert "status 3" in message
    assert "the reason" in message, "the child's own output is the diagnosis"


def test_a_healthy_child_is_left_running(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "no-such-Applications")
    monkeypatch.setattr(launcher, "venv_python", lambda project: Path(sys.executable))
    monkeypatch.setattr(launcher, "STARTUP_GRACE_SECONDS", 0.4)
    # Long enough to outlive the grace window, short enough that the suite does
    # not leave a process lying around.
    _project(tmp_path, "alive", body="import time\ntime.sleep(3)\n")
    app = launcher.ExternalApp("alive", "Alive", "alive", "main.py", "")

    message = launcher.launch(app, tmp_path)

    assert "Launched Alive" in message
