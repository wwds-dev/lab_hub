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

from .fakes import make_bundle


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


# ----------------------------------------------------------------------
# Knowing what is already running
# ----------------------------------------------------------------------
def test_an_installed_app_is_seen_by_its_bundle_executable(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    make_bundle(tmp_path, "SONAR")
    app = launcher.ExternalApp("sonar", "SONAR", "sonar", "main.py", "")
    table = f"/bin/zsh\n{tmp_path}/SONAR.app/Contents/MacOS/SONAR\n"

    assert launcher.is_running(app, tmp_path, table) is True
    assert launcher.is_running(app, tmp_path, "/bin/zsh\n") is False


def test_a_source_run_is_told_apart_by_its_absolute_entry(tmp_path, monkeypatch):
    """Every project's entry is `main.py`, so a relative command line would
    make one running project look like all of them."""
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "none")
    _project(tmp_path, "sonar")
    _project(tmp_path, "vidforge")
    sonar = launcher.ExternalApp("sonar", "SONAR", "sonar", "main.py", "")
    other = launcher.ExternalApp("vidforge", "vidforge", "vidforge", "main.py", "")
    table = f"/usr/bin/python3 {tmp_path}/sonar/main.py\n"

    assert launcher.is_running(sonar, tmp_path, table) is True
    assert launcher.is_running(other, tmp_path, table) is False


def test_an_app_that_is_nowhere_is_never_running(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "none")
    app = launcher.ExternalApp("ghost", "Ghost", "ghost", "main.py", "")

    assert launcher.is_running(app, tmp_path, "anything") is False


def test_only_an_installed_app_can_be_raised(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    make_bundle(tmp_path, "SONAR")
    installed = launcher.ExternalApp("sonar", "SONAR", "sonar", "main.py", "")
    from_source = launcher.ExternalApp("v", "vidforge", "vidforge", "main.py", "")

    assert launcher.can_bring_to_front(installed) is True
    assert launcher.can_bring_to_front(from_source) is False


def test_raising_a_source_run_says_why_it_cannot(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "none")
    _project(tmp_path, "sonar")
    app = launcher.ExternalApp("sonar", "SONAR", "sonar", "main.py", "")

    with pytest.raises(launcher.LaunchError) as raised:
        launcher.bring_to_front(app, tmp_path)

    assert "Dock" in str(raised.value), "tell the user what to do instead"


def test_the_process_table_is_readable():
    assert "\n" in launcher.process_table()


def test_background_bundle_launch_passes_the_hidden_flag(tmp_path, monkeypatch):
    app = launcher.ExternalApp("backup", "Backup", "backup", "main.py", "summary")
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    make_bundle(tmp_path, "Backup")
    calls = []
    monkeypatch.setattr(
        launcher.subprocess,
        "run",
        lambda command, **kwargs: calls.append(command)
        or launcher.subprocess.CompletedProcess(command, 0, "", ""),
    )

    launcher.launch(app, tmp_path, background=True)

    assert calls[0][-2:] == ["--args", "--background"]


# ----------------------------------------------------------------------
# Readiness: answered before the button is pressed, not during
# ----------------------------------------------------------------------
def test_an_installed_app_is_ready(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    make_bundle(tmp_path, "SONAR")
    app = launcher.ExternalApp("sonar", "SONAR", "sonar", "main.py", "")

    ready = launcher.readiness(app, tmp_path)

    assert ready.ok
    assert ready.state == "installed"


def test_a_gutted_bundle_is_not_ready(tmp_path, monkeypatch):
    """A bundle with nothing inside it still looks installed to `is_dir`."""
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    (tmp_path / "SONAR.app").mkdir()
    app = launcher.ExternalApp("sonar", "SONAR", "sonar", "main.py", "")

    ready = launcher.readiness(app, tmp_path)

    assert ready.state == "installed"
    assert not ready.ok
    assert "rebuild" in ready.problem.lower()


def test_a_gutted_bundle_refuses_to_launch(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    (tmp_path / "SONAR.app").mkdir()
    app = launcher.ExternalApp("sonar", "SONAR", "sonar", "main.py", "")

    with pytest.raises(launcher.LaunchError) as raised:
        launcher.launch(app, tmp_path)

    assert "no executable" in str(raised.value)


def test_the_executable_comes_from_the_plist(tmp_path, monkeypatch):
    """Sentinel is wrapped by an applet: its binary is called `applet`.

    Assuming the executable shares the app's name would call that bundle
    broken and refuse to start a perfectly good app.
    """
    import plistlib

    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    macos = tmp_path / "Sentinel.app" / "Contents" / "MacOS"
    macos.mkdir(parents=True)
    (macos / "applet").write_text("#!/bin/sh\n")
    with (tmp_path / "Sentinel.app" / "Contents" / "Info.plist").open("wb") as f:
        plistlib.dump({"CFBundleExecutable": "applet"}, f)
    app = launcher.ExternalApp("sf", "Sentinel", "sentinel_fork", "main.py", "")

    assert launcher.bundle_executable(app).name == "applet"
    assert launcher.readiness(app, tmp_path).ok


def test_a_checkout_with_no_interpreter_is_not_ready(tmp_path, monkeypatch):
    """The case that used to offer a working-looking button and a dialog."""
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "none")
    monkeypatch.setattr(launcher, "venv_python", lambda project: None)
    monkeypatch.setattr(launcher.shutil, "which", lambda name: None)
    _project(tmp_path, "sonar")
    app = launcher.ExternalApp("sonar", "SONAR", "sonar", "main.py", "")

    ready = launcher.readiness(app, tmp_path)

    assert ready.state == "source"
    assert not ready.ok
    assert "no interpreter" in ready.problem


def test_a_checkout_with_a_venv_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "none")
    monkeypatch.setattr(
        launcher, "venv_python", lambda project: project / ".venv" / "bin" / "python"
    )
    _project(tmp_path, "sonar")
    app = launcher.ExternalApp("sonar", "SONAR", "sonar", "main.py", "")

    ready = launcher.readiness(app, tmp_path)

    assert ready.ok
    assert ".venv" in ready.detail


def test_something_nowhere_is_not_ready(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "none")
    app = launcher.ExternalApp("ghost", "Ghost", "ghost", "main.py", "")

    ready = launcher.readiness(app, tmp_path)

    assert ready.state == "missing"
    assert not ready.ok


def test_the_log_hint_for_a_bundle_names_the_process(tmp_path, monkeypatch):
    """A bundle started through `open` is not our child, so its output is not
    ours to capture — the unified log is where it went."""
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    make_bundle(tmp_path, "SONAR")
    app = launcher.ExternalApp("sonar", "SONAR", "sonar", "main.py", "")

    hint = launcher.startup_log_hint(app)

    assert "log show" in hint
    assert '"SONAR"' in hint


def test_the_log_hint_for_a_source_run_is_the_captured_file(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "none")
    app = launcher.ExternalApp("sonar", "SONAR", "sonar", "main.py", "")

    assert launcher.startup_log_hint(app) == str(launcher.launch_log(app))


# ----------------------------------------------------------------------
# Spotting a running copy when the bundle is not the process
# ----------------------------------------------------------------------
def test_an_installed_app_running_from_its_checkout_counts_as_running(
    tmp_path, monkeypatch
):
    """The *Did not start* bug, in one assertion.

    Sentinel's bundle is a one-shot launcher: it execs the project's python and
    exits, so seconds after a good launch the only thing in the process table
    is `<project>/main.py`. Matching the bundle alone called a running app
    dead, and kept saying so until the window was closed.
    """
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    make_bundle(tmp_path, "Sentinel")
    _project(tmp_path, "sentinel_fork")
    app = launcher.ExternalApp("sf", "Sentinel", "sentinel_fork", "main.py", "")
    table = (
        "/bin/zsh\n"
        f"{tmp_path}/sentinel_fork/.venv/bin/python {tmp_path}/sentinel_fork/main.py\n"
    )

    assert launcher.is_running(app, tmp_path, table)


def test_the_bundle_still_counts_on_its_own(tmp_path, monkeypatch):
    """A self-contained bundle keeps its own process; that must still match."""
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    make_bundle(tmp_path, "SONAR")
    app = launcher.ExternalApp("sonar", "SONAR", "sonar", "main.py", "")

    assert launcher.is_running(
        app, tmp_path, f"{tmp_path}/SONAR.app/Contents/MacOS/SONAR\n"
    )


def test_both_markers_are_offered_when_both_exist(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    make_bundle(tmp_path, "Sentinel")
    _project(tmp_path, "sentinel_fork")
    app = launcher.ExternalApp("sf", "Sentinel", "sentinel_fork", "main.py", "")

    markers = launcher.running_markers(app, tmp_path)

    assert str(tmp_path / "Sentinel.app" / "Contents" / "MacOS") in markers
    assert str(tmp_path / "sentinel_fork" / "main.py") in markers


def test_an_unrelated_process_is_not_mistaken_for_it(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    make_bundle(tmp_path, "Sentinel")
    _project(tmp_path, "sentinel_fork")
    app = launcher.ExternalApp("sf", "Sentinel", "sentinel_fork", "main.py", "")

    assert not launcher.is_running(app, tmp_path, "/bin/zsh\n/usr/bin/python main.py\n")


def test_nothing_to_match_means_not_running(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "none")
    app = launcher.ExternalApp("ghost", "Ghost", "ghost", "main.py", "")

    assert launcher.running_markers(app, tmp_path) == ()
    assert not launcher.is_running(app, tmp_path, "anything at all\n")


# ----------------------------------------------------------------------
# A headless daemon is not an open app
# ----------------------------------------------------------------------
def _sonar(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    make_bundle(tmp_path, "SONAR")
    _project(tmp_path, "sonar")
    return launcher.ExternalApp("sonar", "SONAR", "sonar", "main.py", "")


def test_a_headless_daemon_does_not_count_as_running(tmp_path, monkeypatch):
    """SONAR's launchd agent runs `main.py --headless` around the clock.

    It matches the entry script, so once the checkout became a marker it made
    the tile read *Running* permanently — offering to raise a window that does
    not exist, even with the app properly quit.
    """
    app = _sonar(tmp_path, monkeypatch)
    table = f"{tmp_path}/sonar/.venv/bin/python {tmp_path}/sonar/main.py --headless --port 8787\n"

    assert not launcher.is_running(app, tmp_path, table)


def test_the_real_app_still_counts_beside_the_daemon(tmp_path, monkeypatch):
    app = _sonar(tmp_path, monkeypatch)
    table = (
        f"{tmp_path}/sonar/.venv/bin/python {tmp_path}/sonar/main.py --headless\n"
        f"{tmp_path}/SONAR.app/Contents/MacOS/SONAR\n"
    )

    assert launcher.is_running(app, tmp_path, table)


def test_a_background_start_is_running(tmp_path, monkeypatch):
    """`--background` is the whole app with its window hidden, not a daemon.

    It is how Lab Hub starts Backup Control Center and git_autosync itself, and
    they live in the menu bar and can be raised. Calling them stopped would
    offer a Launch button that starts a second copy.
    """
    app = _sonar(tmp_path, monkeypatch)
    table = f"{tmp_path}/SONAR.app/Contents/MacOS/SONAR --background\n"

    assert launcher.is_running(app, tmp_path, table)


def test_a_flag_on_one_line_does_not_discount_another(tmp_path, monkeypatch):
    """Matching is per command line; a table-wide search would see the flag
    anywhere in the snapshot and discount every app at once."""
    app = _sonar(tmp_path, monkeypatch)
    table = (
        "/usr/bin/something --headless\n"
        f"{tmp_path}/SONAR.app/Contents/MacOS/SONAR\n"
    )

    assert launcher.is_running(app, tmp_path, table)


# ----------------------------------------------------------------------
# Window and background service are separate answers
# ----------------------------------------------------------------------
def test_presence_separates_the_window_from_the_daemon(tmp_path, monkeypatch):
    app = _sonar(tmp_path, monkeypatch)
    table = f"{tmp_path}/sonar/.venv/bin/python {tmp_path}/sonar/main.py --headless\n"

    here = launcher.presence(app, tmp_path, table)

    assert here.service, "the engine is up"
    assert not here.window, "but there is no window to raise"


def test_presence_sees_both_at_once(tmp_path, monkeypatch):
    app = _sonar(tmp_path, monkeypatch)
    table = (
        f"{tmp_path}/sonar/.venv/bin/python {tmp_path}/sonar/main.py --headless\n"
        f"{tmp_path}/SONAR.app/Contents/MacOS/SONAR\n"
    )

    here = launcher.presence(app, tmp_path, table)

    assert here.window and here.service


def test_presence_of_something_nowhere_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "none")
    app = launcher.ExternalApp("ghost", "Ghost", "ghost", "main.py", "")

    here = launcher.presence(app, tmp_path, "anything\n")

    assert not here.window and not here.service


def test_only_sonar_declares_a_background_service():
    """Naming one is a claim that the app has a windowless copy worth
    reporting; the others do not."""
    named = {app.key: app.service for app in launcher.APPS if app.service}

    assert named == {"sonar": "Engine"}


# ----------------------------------------------------------------------
# Which build would actually open
# ----------------------------------------------------------------------
def _stamp(bundle, major="2", build=103):
    import json

    target = bundle / "Contents" / "Resources"
    target.mkdir(parents=True, exist_ok=True)
    (target / launcher.BUILD_INFO_NAME).write_text(
        json.dumps({"major": major, "build": build})
    )


def _checkout(tmp_path, name, major="2", monkeypatch=None, build=55):
    """A project with an arc. The commit count is stubbed: these tests are
    about *which* source is consulted, not about git — one further down runs
    the real thing against this repository."""
    project = _project(tmp_path, name)
    (project / "VERSION").write_text(f"{major}\n")
    if monkeypatch is not None:
        monkeypatch.setattr(launcher, "_commit_count", lambda _project: build)
    return project


def test_a_frozen_bundle_answers_with_its_own_stamp(tmp_path, monkeypatch):
    """The bundle is what opens, so the bundle's build is the answer — even
    with a checkout sitting right beside it."""
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    bundle = make_bundle(tmp_path, "SONAR")
    _stamp(bundle, build=103)
    _checkout(tmp_path, "sonar")
    app = launcher.ExternalApp("sonar", "SONAR", "sonar", "main.py", "")

    found = launcher.version(app, tmp_path)

    assert found.text == "v2.103"
    assert found.origin == "bundle"


def test_an_unstamped_frozen_bundle_says_nothing(tmp_path, monkeypatch):
    """The checkout's number would describe code that is not what opens.

    AGENTS.md's rule: say unknown rather than claim current with no evidence —
    a lie told in exactly the moment someone is asking.
    """
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    make_bundle(tmp_path, "SONAR")
    _checkout(tmp_path, "sonar")
    app = launcher.ExternalApp("sonar", "SONAR", "sonar", "main.py", "")

    found = launcher.version(app, tmp_path)

    assert not found.known
    assert found.text == ""


def test_a_launcher_bundle_answers_with_the_checkout(tmp_path, monkeypatch):
    """Sentinel's stub runs the project's source, so the source is the answer.

    Its own Info.plist says 2.0, hand-typed once and never touched since.
    """
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    bundle = make_bundle(tmp_path, "Sentinel")
    (bundle / "Contents" / "Resources").mkdir(parents=True, exist_ok=True)
    (bundle / "Contents" / "Resources" / "project_root.txt").write_text("/somewhere")
    _stamp(bundle, build=999)  # even a stamp must not win here
    _checkout(tmp_path, "sentinel_fork", monkeypatch=monkeypatch)
    app = launcher.ExternalApp("sf", "Sentinel", "sentinel_fork", "main.py", "")

    found = launcher.version(app, tmp_path)

    assert found.origin == "checkout"
    assert found.text.startswith("v2.")
    assert found.text != "v2.999"


def test_an_applet_bundle_also_answers_with_the_checkout(tmp_path, monkeypatch):
    import plistlib

    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    macos = tmp_path / "Imprint.app" / "Contents" / "MacOS"
    macos.mkdir(parents=True)
    (macos / "applet").write_text("#!/bin/sh\n")
    with (tmp_path / "Imprint.app" / "Contents" / "Info.plist").open("wb") as f:
        plistlib.dump({"CFBundleExecutable": "applet"}, f)
    _checkout(tmp_path, "imprint", monkeypatch=monkeypatch)
    app = launcher.ExternalApp("imprint", "Imprint", "imprint", "main.py", "")

    assert launcher.version(app, tmp_path).origin == "checkout"


def test_a_source_only_app_answers_with_the_checkout(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "none")
    _checkout(tmp_path, "sonar", monkeypatch=monkeypatch)
    app = launcher.ExternalApp("sonar", "SONAR", "sonar", "main.py", "")

    assert launcher.version(app, tmp_path).origin == "checkout"


def test_a_version_file_holding_a_whole_version_yields_the_arc(tmp_path, monkeypatch):
    """`sentinel_fork/VERSION` holds `2.001` against a convention that says the
    build half is derived. Take the arc; derive the rest."""
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "none")
    project = _project(tmp_path, "sentinel_fork")
    (project / "VERSION").write_text("2.001\n")
    monkeypatch.setattr(launcher, "_commit_count", lambda _project: 55)
    app = launcher.ExternalApp("sf", "Sentinel", "sentinel_fork", "main.py", "")

    text = launcher.version(app, tmp_path).text

    assert text.startswith("v2."), text
    assert not text.startswith("v2.001."), "the hand-written build must not stack up"


def test_nothing_anywhere_is_an_empty_version(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "none")
    app = launcher.ExternalApp("ghost", "Ghost", "ghost", "main.py", "")

    assert not launcher.version(app, tmp_path).known


def test_the_commit_count_is_read_from_a_real_repository():
    """The stubs above would keep passing if git were never called at all."""
    from pathlib import Path as _Path

    here = _Path(__file__).resolve().parents[1]

    count = launcher._commit_count(here)

    assert isinstance(count, int) and count > 0


def test_this_project_reports_its_own_version():
    """End to end against the real checkout, arc and git history."""
    from pathlib import Path as _Path

    found = launcher.checkout_version(_Path(__file__).resolve().parents[1])

    assert found.known
    assert found.text.startswith("v2."), found.text


# ----------------------------------------------------------------------
# An installed build older than its source
# ----------------------------------------------------------------------
def test_a_bundle_behind_its_checkout_says_how_far(tmp_path, monkeypatch):
    """The question the number exists for. Committing to a project does not
    rebuild it, so the installed app is routinely older than the source."""
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    bundle = make_bundle(tmp_path, "SONAR")
    _stamp(bundle, build=104)
    _checkout(tmp_path, "sonar", monkeypatch=monkeypatch, build=109)
    app = launcher.ExternalApp("sonar", "SONAR", "sonar", "main.py", "")

    found = launcher.version(app, tmp_path)

    assert found.text == "v2.104", "the number still describes what opens"
    assert found.stale and found.behind == 5


def test_a_bundle_level_with_its_checkout_is_not_stale(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    bundle = make_bundle(tmp_path, "SONAR")
    _stamp(bundle, build=109)
    _checkout(tmp_path, "sonar", monkeypatch=monkeypatch, build=109)
    app = launcher.ExternalApp("sonar", "SONAR", "sonar", "main.py", "")

    assert not launcher.version(app, tmp_path).stale


def test_a_bundle_ahead_of_its_checkout_is_not_reported_as_behind(tmp_path, monkeypatch):
    """Possible after a branch switch. Negative staleness is not a thing."""
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    bundle = make_bundle(tmp_path, "SONAR")
    _stamp(bundle, build=120)
    _checkout(tmp_path, "sonar", monkeypatch=monkeypatch, build=109)
    app = launcher.ExternalApp("sonar", "SONAR", "sonar", "main.py", "")

    assert not launcher.version(app, tmp_path).stale


def test_a_launcher_bundle_is_never_behind(tmp_path, monkeypatch):
    """It runs the checkout, so it cannot lag it."""
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    bundle = make_bundle(tmp_path, "Sentinel")
    (bundle / "Contents" / "Resources").mkdir(parents=True, exist_ok=True)
    (bundle / "Contents" / "Resources" / "project_root.txt").write_text("/somewhere")
    _stamp(bundle, build=1)
    _checkout(tmp_path, "sentinel_fork", monkeypatch=monkeypatch, build=55)
    app = launcher.ExternalApp("sf", "Sentinel", "sentinel_fork", "main.py", "")

    found = launcher.version(app, tmp_path)

    assert found.origin == "checkout"
    assert not found.stale


def test_the_commit_count_is_cached_against_head(tmp_path, monkeypatch):
    """The tile re-reads the version on every poll, so this cannot shell out
    to git each time."""
    project = _project(tmp_path, "sonar")
    (project / ".git").mkdir()
    (project / ".git" / "HEAD").write_text("nothing that looks like a ref\n")
    calls = []
    real = launcher.subprocess.run

    def counting(*args, **kwargs):
        calls.append(args)
        return real(*args, **kwargs)

    monkeypatch.setattr(launcher.subprocess, "run", counting)
    launcher._COUNT_CACHE.clear()

    launcher._commit_count(project)
    launcher._commit_count(project)
    launcher._commit_count(project)

    assert len(calls) == 1, "git ran more than once for an unchanged HEAD"


def test_a_new_commit_invalidates_the_cached_count(tmp_path, monkeypatch):
    project = _project(tmp_path, "sonar")
    (project / ".git").mkdir()
    head = project / ".git" / "HEAD"
    head.write_text("first\n")
    launcher._COUNT_CACHE.clear()
    monkeypatch.setattr(launcher, "subprocess", launcher.subprocess)

    seen = []
    monkeypatch.setattr(
        launcher.subprocess,
        "run",
        lambda *a, **k: seen.append(1) or type("R", (), {"returncode": 1, "stdout": ""})(),
    )
    launcher._commit_count(project)
    import os, time

    time.sleep(0.01)
    os.utime(head, None)
    head.write_text("second\n")
    launcher._commit_count(project)

    assert len(seen) == 2, "a moved HEAD must be re-read"
