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


def test_lab_hubs_own_qt_settings_are_not_inherited(monkeypatch):
    """Lab Hub turns on GPU drawing for itself; a launched app chooses its own."""
    monkeypatch.setenv("QT_WIDGETS_RHI", "1")

    env = launcher.child_env()

    assert "QT_WIDGETS_RHI" not in env


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
    app = launcher.ExternalApp("sf", "Sentinel", "sentinel", "main.py", "")

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
    _project(tmp_path, "sentinel")
    app = launcher.ExternalApp("sf", "Sentinel", "sentinel", "main.py", "")
    table = (
        "/bin/zsh\n"
        f"{tmp_path}/sentinel/.venv/bin/python {tmp_path}/sentinel/main.py\n"
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
    _project(tmp_path, "sentinel")
    app = launcher.ExternalApp("sf", "Sentinel", "sentinel", "main.py", "")

    markers = launcher.running_markers(app, tmp_path)

    assert str(tmp_path / "Sentinel.app" / "Contents" / "MacOS") in markers
    assert str(tmp_path / "sentinel" / "main.py") in markers


def test_an_unrelated_process_is_not_mistaken_for_it(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    make_bundle(tmp_path, "Sentinel")
    _project(tmp_path, "sentinel")
    app = launcher.ExternalApp("sf", "Sentinel", "sentinel", "main.py", "")

    assert not launcher.is_running(app, tmp_path, "/bin/zsh\n/usr/bin/python main.py\n")


def test_nothing_to_match_means_not_running(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "none")
    app = launcher.ExternalApp("ghost", "Ghost", "ghost", "main.py", "")

    assert launcher.running_markers(app, tmp_path) == ()
    assert not launcher.is_running(app, tmp_path, "anything at all\n")


# ----------------------------------------------------------------------
# A checkout that has been renamed since this build
# ----------------------------------------------------------------------
def _stub_bundle(tmp_path, name: str, runs: Path):
    """A bundle of the shape that execs the checkout and exits, recording it."""
    bundle = make_bundle(tmp_path, name)
    resources = bundle / "Contents" / "Resources"
    resources.mkdir(parents=True, exist_ok=True)
    (resources / launcher.PROJECT_ROOT_FILE).write_text(f"{runs}\n")
    return bundle


def test_a_renamed_checkout_is_found_through_the_bundle(tmp_path, monkeypatch):
    """The *Did not start* bug's second coming, in one assertion.

    `ExternalApp.project` is a directory name baked in when Lab Hub was built.
    Sentinel's folder was renamed from `sentinel_fork` to `sentinel` while the
    installed Lab Hub still said the old one, so the checkout marker vanished
    and only the bundle was left to match — and that bundle execs and exits.
    A running Sentinel was reported dead. The bundle itself knew where its code
    was the whole time, because its installer rewrites that file on the way.
    """
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    _project(tmp_path, "sentinel")
    _stub_bundle(tmp_path, "Sentinel", tmp_path / "sentinel")
    stale = launcher.ExternalApp("sf", "Sentinel", "sentinel_fork", "main.py", "")

    assert launcher.source_dir(stale, tmp_path) == tmp_path / "sentinel"
    assert str(tmp_path / "sentinel" / "main.py") in launcher.running_markers(
        stale, tmp_path
    )
    assert launcher.is_running(
        stale,
        tmp_path,
        f"{tmp_path}/sentinel/.venv/bin/python {tmp_path}/sentinel/main.py\n",
    )


def test_the_configured_lab_folder_still_wins(tmp_path, monkeypatch):
    """The bundle's record is the fallback, not the authority. Settings decides
    where projects are looked for, and a second copy of a checkout under the
    chosen lab folder is the one that tile is about."""
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    _project(tmp_path, "sentinel")
    _project(tmp_path / "elsewhere", "sentinel")
    _stub_bundle(tmp_path, "Sentinel", tmp_path / "elsewhere" / "sentinel")
    app = launcher.ExternalApp("sf", "Sentinel", "sentinel", "main.py", "")

    assert launcher.source_dir(app, tmp_path) == tmp_path / "sentinel"


def test_a_record_pointing_nowhere_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    _stub_bundle(tmp_path, "Sentinel", tmp_path / "gone")
    app = launcher.ExternalApp("sf", "Sentinel", "sentinel", "main.py", "")

    assert launcher.source_dir(app, tmp_path) is None


# ----------------------------------------------------------------------
# Whether an absence is evidence at all
# ----------------------------------------------------------------------
def test_a_stub_with_no_checkout_cannot_be_watched(tmp_path, monkeypatch):
    """Nothing it leaves behind lasts, so a launch that worked and one that
    died look identical. The tile must not pick one."""
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    _stub_bundle(tmp_path, "Sentinel", tmp_path / "gone")
    app = launcher.ExternalApp("sf", "Sentinel", "sentinel", "main.py", "")

    assert not launcher.launch_is_observable(app, tmp_path)


def test_a_stub_with_a_checkout_can_be_watched(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    _project(tmp_path, "sentinel")
    _stub_bundle(tmp_path, "Sentinel", tmp_path / "sentinel")
    app = launcher.ExternalApp("sf", "Sentinel", "sentinel", "main.py", "")

    assert launcher.launch_is_observable(app, tmp_path)


def test_a_self_contained_bundle_can_be_watched(tmp_path, monkeypatch):
    """It keeps its own process, so its absence really does mean something."""
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    make_bundle(tmp_path, "SONAR")
    app = launcher.ExternalApp("sonar", "SONAR", "sonar", "main.py", "")

    assert launcher.launch_is_observable(app, tmp_path)


def test_an_app_that_is_nowhere_cannot_be_watched(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "none")
    app = launcher.ExternalApp("ghost", "Ghost", "ghost", "main.py", "")

    assert not launcher.launch_is_observable(app, tmp_path)


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

    assert named == {"sonar": "Background engine"}


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
    (bundle / "Contents" / "Resources" / "project_root.txt").write_text(str(tmp_path / "sentinel"))
    _stamp(bundle, build=999)  # even a stamp must not win here
    _checkout(tmp_path, "sentinel", monkeypatch=monkeypatch)
    app = launcher.ExternalApp("sf", "Sentinel", "sentinel", "main.py", "")

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
    """`sentinel/VERSION` holds `2.001` against a convention that says the
    build half is derived. Take the arc; derive the rest."""
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "none")
    project = _project(tmp_path, "sentinel")
    (project / "VERSION").write_text("2.001\n")
    monkeypatch.setattr(launcher, "_commit_count", lambda _project: 55)
    app = launcher.ExternalApp("sf", "Sentinel", "sentinel", "main.py", "")

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
    (bundle / "Contents" / "Resources" / "project_root.txt").write_text(str(tmp_path / "sentinel"))
    _stamp(bundle, build=1)
    _checkout(tmp_path, "sentinel", monkeypatch=monkeypatch, build=55)
    app = launcher.ExternalApp("sf", "Sentinel", "sentinel", "main.py", "")

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


# ----------------------------------------------------------------------
# The build report: is what I would open the newest thing there is?
# ----------------------------------------------------------------------
def test_a_frozen_bundle_behind_its_source_needs_a_rebuild(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    bundle = make_bundle(tmp_path, "SONAR")
    _stamp(bundle, build=104)
    project = _checkout(tmp_path, "sonar", monkeypatch=monkeypatch, build=109)
    (project / "build_app.sh").write_text("#!/bin/sh\n")
    app = launcher.ExternalApp("sonar", "SONAR", "sonar", "main.py", "")

    row = launcher.build_status(app, tmp_path)

    assert row.verdict == "behind"
    assert row.needs_rebuild
    assert row.script.name == "build_app.sh"


def test_an_installer_that_needs_a_terminal_is_left_to_the_owner(
    tmp_path, monkeypatch
):
    """Provisio's install_app.sh refuses without a terminal (`[ ! -t 0 ]`), so
    Update now would only watch it fail: it is marked by hand instead."""
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    bundle = make_bundle(tmp_path, "SONAR")
    _stamp(bundle, build=104)
    project = _checkout(tmp_path, "sonar", monkeypatch=monkeypatch, build=109)
    (project / "scripts").mkdir()
    (project / "scripts" / "install_app.sh").write_text(
        '#!/bin/sh\nif [ ! -t 0 ]; then exit 1; fi\n'
    )
    (project / "docs").mkdir()
    (project / "docs" / "RUNBOOK-release.md").write_text("steps\n")
    app = launcher.ExternalApp("sonar", "SONAR", "sonar", "main.py", "")

    row = launcher.build_status(app, tmp_path)

    assert row.verdict == "behind"
    assert row.by_hand
    assert not row.runs_in_app
    assert row.command.endswith("./scripts/install_app.sh")
    assert "by hand" in row.note
    assert "RUNBOOK-release.md" in row.note


def test_a_behind_app_with_no_build_script_is_named_not_dropped(
    tmp_path, monkeypatch
):
    """SYNDUSTRYX builds with build_desktop.py, which Lab Hub does not run:
    the report says there is no command rather than silently skipping it."""
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    bundle = make_bundle(tmp_path, "SONAR")
    _stamp(bundle, build=104)
    _checkout(tmp_path, "sonar", monkeypatch=monkeypatch, build=109)
    app = launcher.ExternalApp("sonar", "SONAR", "sonar", "main.py", "")

    row = launcher.build_status(app, tmp_path)

    assert row.verdict == "behind"
    assert row.command is None
    assert not row.runs_in_app
    assert "no rebuild command" in row.note


def _root_fixture(tmp_path, monkeypatch, verdict, behind=3, release_name="release"):
    from lab_hub.launcher import state

    project = tmp_path / "sonar"
    (project / "scripts").mkdir(parents=True)
    (project / "scripts" / "install_app.sh").write_text("#!/bin/sh\n")
    release = tmp_path / release_name
    (release / "scripts").mkdir(parents=True)
    # Provisio's installer needs a terminal: it must still not be by-hand here.
    (release / "scripts" / "install_app.sh").write_text(
        "#!/bin/sh\nif [ ! -t 0 ]; then exit 1; fi\n")
    (release / "docs").mkdir()
    (release / "docs" / "RUNBOOK-release.md").write_text("steps\n")
    app = launcher.ExternalApp("sonar", "SONAR", "sonar", "main.py", "")
    found = launcher.Version("2.0.1", "bundle", behind=behind, root=str(release))
    monkeypatch.setattr(state, "_build_status", lambda _a, _r: launcher.BuildStatus(
        app, found, verdict, "behind.", project / "scripts" / "install_app.sh",
        f"cd {project} && ./scripts/install_app.sh",
    ))
    return app, release


def test_a_release_clone_that_is_behind_is_moved_forward_not_reinstalled(
    tmp_path, monkeypatch
):
    """The installer rebuilds from the clone it sits in, so re-running it on a
    clone that is behind changes nothing (2026-11-16, Provisio): the command is
    the fast-forward, and nothing in the row runs an installer."""
    app, release = _root_fixture(tmp_path, monkeypatch, "behind", behind=11)

    row = launcher.build_status(app, tmp_path)

    assert row.command == (f"git -C {release} fetch origin && "
                           f"git -C {release} merge --ff-only origin/main")
    assert row.forward and not row.by_hand and not row.runs_in_app
    assert "install_app" not in row.command and "--force" not in row.command
    assert "11 commits behind the source" in row.note and str(release) in row.note
    assert "would rebuild that same clone" in row.note
    assert "RUNBOOK-release.md" in row.note and "CI" in row.note
    assert "selftest" in row.note  # the steps after the move are named too
    assert "merge and push the source to main" in row.note  # the one trap
    assert "Update now leaves it to you" not in row.note


def test_the_note_is_right_for_one_commit_and_without_a_runbook(tmp_path, monkeypatch):
    app, release = _root_fixture(tmp_path, monkeypatch, "behind", behind=1)
    (release / "docs" / "RUNBOOK-release.md").unlink()

    row = launcher.build_status(app, tmp_path)

    assert "is 1 commit behind" in row.note and "1 commits" not in row.note
    assert "RUNBOOK-release.md" not in row.note
    assert "Use the project's release runbook" in row.note


def test_the_forward_command_quotes_a_clone_path_with_a_space(tmp_path, monkeypatch):
    app, release = _root_fixture(tmp_path, monkeypatch, "behind",
                                 release_name="my release")

    row = launcher.build_status(app, tmp_path)

    assert f"git -C '{release}' fetch origin" in row.command
    assert f"git -C '{release}' merge --ff-only origin/main" in row.command


def test_a_release_clone_that_is_level_keeps_its_installer(tmp_path, monkeypatch):
    """Nothing to move: the row is the shipped one (spec measure 4)."""
    app, release = _root_fixture(tmp_path, monkeypatch, "current", behind=0)

    row = launcher.build_status(app, tmp_path)

    assert row.command == f"cd {release} && ./scripts/install_app.sh"
    assert not row.forward and not row.needs_rebuild


def test_an_app_without_a_recorded_root_is_never_a_forward_row(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    bundle = make_bundle(tmp_path, "SONAR")
    _stamp(bundle, build=104)
    project = _checkout(tmp_path, "sonar", monkeypatch=monkeypatch, build=109)
    (project / "build_app.sh").write_text("#!/bin/sh\n")
    app = launcher.ExternalApp("sonar", "SONAR", "sonar", "main.py", "")

    row = launcher.build_status(app, tmp_path)

    assert not row.forward and row.runs_in_app and "git -C" not in row.command


def test_uncommitted_changes_also_make_a_frozen_build_old(tmp_path, monkeypatch):
    """The gap the commit count cannot see: it only moves on commit, so a
    bundle built from the last commit looks level while the source has since
    been edited."""
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    bundle = make_bundle(tmp_path, "SONAR")
    _stamp(bundle, build=109)
    _checkout(tmp_path, "sonar", monkeypatch=monkeypatch, build=109)
    monkeypatch.setattr(launcher, "dirty_checkout", lambda _project: True)
    app = launcher.ExternalApp("sonar", "SONAR", "sonar", "main.py", "")

    row = launcher.build_status(app, tmp_path)

    assert row.verdict == "uncommitted"
    assert row.needs_rebuild


def test_a_launcher_bundle_is_never_out_of_date(tmp_path, monkeypatch):
    """It runs the source, so uncommitted edits are what opens — being dirty
    does not make it stale, it makes it current."""
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    bundle = make_bundle(tmp_path, "Sentinel")
    (bundle / "Contents" / "Resources").mkdir(parents=True, exist_ok=True)
    (bundle / "Contents" / "Resources" / "project_root.txt").write_text(str(tmp_path / "sentinel"))
    _checkout(tmp_path, "sentinel", monkeypatch=monkeypatch, build=55)
    monkeypatch.setattr(launcher, "dirty_checkout", lambda _project: True)
    app = launcher.ExternalApp("sf", "Sentinel", "sentinel", "main.py", "")

    row = launcher.build_status(app, tmp_path)

    assert row.verdict == "current"
    assert not row.needs_rebuild


def test_a_clean_frozen_build_is_current(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    bundle = make_bundle(tmp_path, "SONAR")
    _stamp(bundle, build=109)
    _checkout(tmp_path, "sonar", monkeypatch=monkeypatch, build=109)
    monkeypatch.setattr(launcher, "dirty_checkout", lambda _project: False)
    app = launcher.ExternalApp("sonar", "SONAR", "sonar", "main.py", "")

    assert launcher.build_status(app, tmp_path).verdict == "current"


def test_an_unstamped_bundle_is_reported_as_uncheckable(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    make_bundle(tmp_path, "Unblock Tracker")
    _checkout(tmp_path, "unblock", monkeypatch=monkeypatch)
    app = launcher.ExternalApp("ub", "Unblock Tracker", "unblock", "main.py", "")

    row = launcher.build_status(app, tmp_path)

    assert row.verdict == "unknown"
    assert not row.needs_rebuild, "unknown is not a claim that it is old"


def test_no_checkout_means_nothing_to_compare(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    bundle = make_bundle(tmp_path, "SONAR")
    _stamp(bundle, build=104)
    app = launcher.ExternalApp("sonar", "SONAR", "sonar", "main.py", "")

    assert launcher.build_status(app, tmp_path).verdict == "missing"


def test_the_report_covers_every_registered_app(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "none")

    report = launcher.build_report(tmp_path)

    assert len(report) == len(launcher.APPS)


# ----------------------------------------------------------------------
# The command handed over has to actually install
# ----------------------------------------------------------------------
def _script(project, relative, body):
    target = project / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body)
    return target


def test_a_script_that_needs_the_flag_gets_it(tmp_path):
    """sonar, unblock_tracker, lab_hub and Sentinel build into dist.noindex/
    and only copy into /Applications when passed --install. Without the flag
    you pay for the whole build and the old app stays exactly where it was."""
    project = tmp_path / "sonar"
    script = _script(
        project, "build_app.sh",
        '#!/bin/bash\nif [[ "${1:-}" == "--install" ]]; then cp -R x /Applications/; fi\n',
    )

    command = launcher.install_command(project, script)

    assert command.endswith("./build_app.sh --install")


def test_a_script_that_installs_by_default_is_left_alone(tmp_path):
    """backup_manager, git_autosync and Imprint install without a flag."""
    project = tmp_path / "backup_manager"
    script = _script(project, "build_app.sh", "#!/bin/bash\ncp -R x /Applications/\n")

    command = launcher.install_command(project, script)

    assert command.endswith("./build_app.sh")
    assert "--install" not in command


def test_a_nested_script_is_named_from_the_project_root(tmp_path):
    """`cd <project> && ./scripts/build_app.sh`, not a cd into scripts/ — the
    script resolves its own paths relative to the project."""
    project = tmp_path / "sentinel"
    script = _script(project, "scripts/build_app.sh", "#!/bin/bash\n")

    command = launcher.install_command(project, script)

    assert command == f"cd {project} && ./scripts/build_app.sh"


def test_the_report_carries_the_command(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    bundle = make_bundle(tmp_path, "SONAR")
    _stamp(bundle, build=104)
    project = _checkout(tmp_path, "sonar", monkeypatch=monkeypatch, build=109)
    _script(project, "build_app.sh", '#!/bin/bash\n"${1:-}" == "--install"\n')
    app = launcher.ExternalApp("sonar", "SONAR", "sonar", "main.py", "")

    row = launcher.build_status(app, tmp_path)

    assert row.needs_rebuild
    assert row.command.startswith(f"cd {project} && ./build_app.sh")


def test_a_release_line_is_kept_whole(tmp_path, monkeypatch):
    """Provisio's VERSION is `2.0`, a release line its own footer stamps as
    `v2.0.<count>`. Only a three-digit tail is a hand-written build."""
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "none")
    project = _project(tmp_path, "provisio", entry="scripts/run-framework.mjs")
    (project / "VERSION").write_text("2.0\n")
    monkeypatch.setattr(launcher, "_commit_count", lambda _project: 64)
    app = launcher.ExternalApp(
        "provisio", "Provisio", "provisio", "scripts/run-framework.mjs", "",
        url="http://localhost:5173/", runtime="node",
    )

    assert launcher.version(app, tmp_path).text == "v2.0.064"


# ----------------------------------------------------------------------
# Web apps — a server in the checkout, the browser as the window
# ----------------------------------------------------------------------
def _web(tmp_path, monkeypatch, *, modules=True):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "none")
    project = _project(tmp_path, "provisio", entry="scripts/run-framework.mjs")
    if modules:
        (project / "node_modules").mkdir()
    app = launcher.ExternalApp(
        "provisio", "Provisio", "provisio", "scripts/run-framework.mjs", "",
        url="http://localhost:5173/", runtime="node", args=("dev",),
    )
    return app, project


def test_a_web_app_is_a_server_not_a_lesser_source_run(tmp_path, monkeypatch):
    app, project = _web(tmp_path, monkeypatch)

    ready = launcher.readiness(app, tmp_path)

    assert ready.state == "server"
    assert ready.ok
    assert "http://localhost:5173/" in ready.detail


def test_a_web_app_without_its_dependencies_is_not_ready(tmp_path, monkeypatch):
    app, _project_dir = _web(tmp_path, monkeypatch, modules=False)

    ready = launcher.readiness(app, tmp_path)

    assert not ready.ok
    assert "install:ci" in ready.problem


def test_a_web_server_is_running_only_once_it_answers(tmp_path, monkeypatch):
    """Its process is on the table seconds before it listens; calling it
    running then would offer a page that cannot load yet."""
    app, project = _web(tmp_path, monkeypatch)
    table = f"node {project}/scripts/run-framework.mjs dev\n"

    monkeypatch.setattr(launcher, "serving", lambda _app: False)
    assert not launcher.presence(app, tmp_path, table).window

    monkeypatch.setattr(launcher, "serving", lambda _app: True)
    assert launcher.presence(app, tmp_path, table).window


def test_a_web_server_started_by_hand_counts_by_its_address(tmp_path, monkeypatch):
    """`start-preview.command` runs it by a relative path no marker can see;
    the address answering is what says it is up."""
    app, _project_dir = _web(tmp_path, monkeypatch)
    monkeypatch.setattr(launcher, "serving", lambda _app: True)

    assert launcher.presence(app, tmp_path, "node scripts/run-framework.mjs dev\n").window


def test_a_quiet_address_and_no_process_is_stopped(tmp_path, monkeypatch):
    app, _project_dir = _web(tmp_path, monkeypatch)
    monkeypatch.setattr(launcher, "serving", lambda _app: False)

    assert not launcher.presence(app, tmp_path, "/bin/zsh\n").window


def test_the_address_probe_reads_a_real_socket():
    """Not stubbed: a listening socket answers and a closed port does not."""
    import socket

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        app = launcher.ExternalApp(
            "w", "W", "w", "x", "", url=f"http://127.0.0.1:{port}/"
        )
        assert launcher.serving(app)
    assert not launcher.serving(app)


def test_a_web_app_launches_node_with_its_absolute_entry(tmp_path, monkeypatch):
    """The absolute path is how its server is recognised and stopped later."""
    app, project = _web(tmp_path, monkeypatch)
    started = {}

    class _Process:
        pid = 4242

        def poll(self):
            return None

    def popen(command, **kwargs):
        started["command"] = command
        started["cwd"] = kwargs["cwd"]
        started["session"] = kwargs["start_new_session"]
        return _Process()

    monkeypatch.setattr(launcher.subprocess, "Popen", popen)
    monkeypatch.setattr(launcher, "STARTUP_GRACE_SECONDS", 0.0)

    launcher.launch(app, tmp_path)

    shell_line = started["command"][-1]
    assert started["command"][1] == "-lc"
    assert shell_line == f"exec node {project}/scripts/run-framework.mjs dev"
    assert started["cwd"] == project
    assert started["session"], "its own process group, so Stop takes its helpers too"


def test_a_web_app_opens_its_address_instead_of_raising(tmp_path, monkeypatch):
    app, _project_dir = _web(tmp_path, monkeypatch)
    opened = []
    monkeypatch.setattr(launcher, "open_url", opened.append)

    message = launcher.bring_to_front(app, tmp_path)

    assert opened == ["http://localhost:5173/"]
    assert "browser" in message
    assert launcher.can_bring_to_front(app, tmp_path)


def test_stop_only_touches_a_server_it_recognises(tmp_path, monkeypatch):
    app, project = _web(tmp_path, monkeypatch)
    table = (
        f"  101 node {project}/scripts/run-framework.mjs dev\n"
        "  202 node scripts/run-framework.mjs dev\n"
        "  303 /bin/zsh\n"
    )
    monkeypatch.setattr(
        launcher.subprocess, "run",
        lambda *a, **k: type("R", (), {"stdout": table, "returncode": 0})(),
    )
    killed = []
    monkeypatch.setattr(launcher.os, "killpg", lambda pid, sig: killed.append(pid))

    launcher.stop(app, tmp_path)

    assert killed == [101], "a server started by hand is not ours to kill"


def test_stop_with_nothing_recognisable_explains_itself(tmp_path, monkeypatch):
    app, _project_dir = _web(tmp_path, monkeypatch)
    monkeypatch.setattr(
        launcher.subprocess, "run",
        lambda *a, **k: type("R", (), {"stdout": "  202 node scripts/x.mjs\n"})(),
    )

    with pytest.raises(launcher.LaunchError, match="Control-C"):
        launcher.stop(app, tmp_path)


# ----------------------------------------------------------------------
# A bundle built inside its own checkout (SYNDUSTRYX)
# ----------------------------------------------------------------------
def _built(tmp_path, monkeypatch, *, with_bundle=True):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "none")
    project = _project(tmp_path, "syndustryx", entry="server.py")
    if with_bundle:
        (project / "dist").mkdir()
        make_bundle(project / "dist", "SYNDUSTRYX")
    app = launcher.ExternalApp(
        "syndustryx", "SYNDUSTRYX", "syndustryx", "server.py", "",
        bundle_dir="dist", runs_from_source=False,
    )
    return app, project


def test_a_bundle_in_the_checkout_is_found_when_none_is_installed(tmp_path, monkeypatch):
    app, project = _built(tmp_path, monkeypatch)

    ready = launcher.readiness(app, tmp_path)

    assert ready.state == "built"
    assert ready.ok
    assert launcher.bundle_path(app, tmp_path) == (project / "dist" / "SYNDUSTRYX.app").resolve()


def test_an_installed_copy_still_wins(tmp_path, monkeypatch):
    app, _project_dir = _built(tmp_path, monkeypatch)
    applications = tmp_path / "Applications"
    applications.mkdir()
    monkeypatch.setattr(launcher, "APPLICATIONS", applications)
    make_bundle(applications, "SYNDUSTRYX")

    assert launcher.readiness(app, tmp_path).state == "installed"


def test_a_built_bundle_is_seen_by_its_real_path(tmp_path, monkeypatch):
    """The checkout is reached through a symlink, and `ps` shows the real
    path — so the marker has to be the resolved one."""
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "none")
    real = _project(tmp_path / "elsewhere", "syndustryx", entry="server.py")
    (real / "dist").mkdir()
    make_bundle(real / "dist", "SYNDUSTRYX")
    lab = tmp_path / "lab"
    lab.mkdir()
    (lab / "syndustryx").symlink_to(real)
    app = launcher.ExternalApp(
        "syndustryx", "SYNDUSTRYX", "syndustryx", "server.py", "",
        bundle_dir="dist", runs_from_source=False,
    )
    table = f"{real.resolve()}/dist/SYNDUSTRYX.app/Contents/MacOS/SYNDUSTRYX\n"

    assert launcher.is_running(app, lab, table)


def test_a_checkout_that_is_not_the_app_is_not_launchable(tmp_path, monkeypatch):
    """SYNDUSTRYX's `server.py` is its engine with no window, on the port the
    Lab Project Monitor already holds — never something to start as the app."""
    app, _project_dir = _built(tmp_path, monkeypatch, with_bundle=False)

    ready = launcher.readiness(app, tmp_path)

    assert not ready.ok
    assert "Build it first" in ready.problem
    with pytest.raises(launcher.LaunchError, match="Build it first"):
        launcher.launch(app, tmp_path)


def test_an_app_outside_the_version_scheme_is_not_told_to_rebuild(tmp_path, monkeypatch):
    """Rebuilding never stamps SYNDUSTRYX, so that advice could not work."""
    app, _project_dir = _built(tmp_path, monkeypatch)

    status = launcher.build_status(app, tmp_path)

    assert status.verdict == "unknown"
    assert "version scheme" in status.note
    assert "rebuild" not in status.note


def test_the_new_apps_are_registered_as_umbrella_apps():
    keys = [app.key for app in launcher.SUITES]

    assert {"provisio", "syndustryx"} <= set(keys)
    provisio = next(app for app in launcher.SUITES if app.key == "provisio")
    syndustryx = next(app for app in launcher.SUITES if app.key == "syndustryx")
    # A native app since 2026-10-07: its own window and server, not a browser tab.
    assert not provisio.served and provisio.runtime == "python"
    assert provisio.entry == "main.py"
    assert not syndustryx.runs_from_source and syndustryx.bundle_dir is None


# ----------------------------------------------------------------------
# An unstamped bundle whose source declares releases (SYNDUSTRYX)
# ----------------------------------------------------------------------
def _release_repo(tmp_path, monkeypatch, installed="0.6.52"):
    """A checkout whose manifest went 0.6.52 -> 0.6.53, then two more commits,
    and an installed bundle at `installed`."""
    import json as _json
    import plistlib as _plistlib
    import subprocess as _sp

    applications = tmp_path / "Applications"
    applications.mkdir()
    monkeypatch.setattr(launcher, "APPLICATIONS", applications)
    bundle = make_bundle(applications, "SYNDUSTRYX")
    with (bundle / "Contents" / "Info.plist").open("wb") as handle:
        _plistlib.dump(
            {"CFBundleExecutable": "SYNDUSTRYX",
             "CFBundleShortVersionString": installed}, handle,
        )
    project = _project(tmp_path, "syndustryx", entry="server.py")

    def git(*args):
        _sp.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                cwd=project, check=True, capture_output=True)

    def release(number):
        (project / "release-manifest.json").write_text(
            _json.dumps({"version": number}, indent=2))
        git("add", "release-manifest.json")
        git("commit", "-m", f"release {number}")

    git("init")
    release("0.6.52")
    release("0.6.53")
    for n in range(2):
        (project / f"work{n}.txt").write_text("x")
        git("add", f"work{n}.txt")
        git("commit", "-m", f"work {n}")
    app = launcher.ExternalApp(
        "syndustryx", "SYNDUSTRYX", "syndustryx", "server.py", "",
        runs_from_source=False,
    )
    return app


def test_an_old_release_is_counted_in_commits_behind(tmp_path, monkeypatch):
    app = _release_repo(tmp_path, monkeypatch, installed="0.6.52")

    found = launcher.version(app, tmp_path)

    assert found.text == "v0.6.52"
    assert found.behind == 3  # the 0.6.53 commit and the two after it
    assert launcher.build_status(app, tmp_path).verdict == "behind"


def test_the_current_release_is_not_behind(tmp_path, monkeypatch):
    app = _release_repo(tmp_path, monkeypatch, installed="0.6.53")

    found = launcher.version(app, tmp_path)

    assert not found.stale


# ----------------------------------------------------------------------
# An app with its own build command (SYNDUSTRYX: build_desktop.py)
# ----------------------------------------------------------------------
def _git_project(path: Path) -> str:
    import subprocess

    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    (path / "a.txt").write_text("x")
    subprocess.run(["git", "add", "a.txt"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "one"], cwd=path, check=True, env=env)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=path, check=True,
                          capture_output=True, text=True).stdout.strip()


_MAKE_BUNDLE = (
    "printf 'built_at now' > a.txt && "  # the build rewrites a tracked file
    "mkdir -p out/X.app/Contents/MacOS && touch out/X.app/new && "
    "printf 'new build' > out/X.app/Contents/MacOS/X && "
    "/usr/libexec/PlistBuddy -c 'Add :CFBundleExecutable string X' "
    "-c 'Add :CFBundleShortVersionString string 0.6.53' out/X.app/Contents/Info.plist"
)


def test_a_registered_build_command_builds_and_installs(tmp_path, monkeypatch):
    """The build runs in the checkout; only after it produced a bundle is the
    installed one moved to the Trash and the new one copied in; the commit it
    was built from is recorded against the new executable."""
    import subprocess

    apps = tmp_path / "Applications"
    (apps / "X.app").mkdir(parents=True)
    (apps / "X.app" / "old").write_text("")
    project = tmp_path / "x"
    head = _git_project(project)
    home = tmp_path / "home"
    (home / ".Trash").mkdir(parents=True)
    monkeypatch.setattr(launcher, "APPLICATIONS", apps)
    monkeypatch.setattr(launcher, "installs_dir", lambda: tmp_path / "installs")
    app = launcher.ExternalApp("x", "X", "x", "server.py", "", build=_MAKE_BUNDLE,
                               build_output="out/X.app")

    command = launcher.registered_build_command(app, project)
    subprocess.run(["/bin/sh", "-c", command], check=True, env={**os.environ, "HOME": str(home)})

    assert (apps / "X.app" / "new").exists() and not (apps / "X.app" / "old").exists()
    (trashed,) = (home / ".Trash").iterdir()
    assert trashed.name.startswith("X before update") and (trashed / "old").exists()
    assert launcher.install_record(app, apps / "X.app") == (head, False)
    # The tracked file the build rewrote is back as committed: nothing for
    # Resolve to commit, so the source does not move past the install.
    assert (project / "a.txt").read_text() == "x"
    # The build's own outputs (out/) are part of the recorded fingerprint, so
    # they do not make the checkout read as changed since the build...
    assert launcher.install_tree(app, apps / "X.app") == launcher.worktree_tree(project)
    # ...but an edit after the build does.
    (project / "a.txt").write_text("edited after the build")
    assert launcher.install_tree(app, apps / "X.app") != launcher.worktree_tree(project)


def test_an_install_record_is_dropped_when_the_bundle_changes(tmp_path, monkeypatch):
    import json

    bundle = tmp_path / "X.app"
    (bundle / "Contents" / "MacOS").mkdir(parents=True)
    (bundle / "Contents" / "MacOS" / "X").write_text("built")
    import plistlib

    (bundle / "Contents" / "Info.plist").write_bytes(plistlib.dumps({"CFBundleExecutable": "X"}))
    monkeypatch.setattr(launcher, "installs_dir", lambda: tmp_path)
    app = launcher.ExternalApp("x", "X", "x", "server.py", "")
    digest = launcher.state._sha256(bundle / "Contents" / "MacOS" / "X")
    (tmp_path / "x.json").write_text(json.dumps(
        {"commit": "a" * 40, "dirty": True, "executable_sha256": digest}))
    assert launcher.install_record(app, bundle) == ("a" * 40, True)

    (bundle / "Contents" / "MacOS" / "X").write_text("something else")
    assert launcher.install_record(app, bundle) is None


def test_a_recorded_install_counts_behind_from_its_commit(tmp_path, monkeypatch):
    """SYNDUSTRYX's plist is pinned at 0.6.53; with Update now's record the
    tile counts from the commit it was built from, not from 0.6.53's cut."""
    import json
    import plistlib
    import subprocess

    apps = tmp_path / "Applications"
    bundle = apps / "X.app"
    (bundle / "Contents" / "MacOS").mkdir(parents=True)
    (bundle / "Contents" / "MacOS" / "X").write_text("built")
    (bundle / "Contents" / "Info.plist").write_bytes(plistlib.dumps(
        {"CFBundleExecutable": "X", "CFBundleShortVersionString": "0.6.53"}))
    project = tmp_path / "x"
    built = _git_project(project)
    (project / "server.py").write_text("")
    monkeypatch.setattr(launcher, "APPLICATIONS", apps)
    monkeypatch.setattr(launcher, "installs_dir", lambda: tmp_path / "installs")
    (tmp_path / "installs").mkdir()
    (tmp_path / "installs" / "x.json").write_text(json.dumps({
        "commit": built, "dirty": False,
        "executable_sha256": launcher.state._sha256(bundle / "Contents" / "MacOS" / "X")}))
    app = launcher.ExternalApp("x", "X", "x", "server.py", "", runs_from_source=False)

    found = launcher.version(app, tmp_path)
    assert (found.text, found.commit, found.behind) == ("v0.6.53", built[:7], 0)

    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "two"], cwd=project,
                   check=True, env=env)
    launcher.state._BEHIND_CACHE.clear()
    assert launcher.version(app, tmp_path).behind == 1


def test_a_failed_registered_build_leaves_the_installed_app(tmp_path, monkeypatch):
    import subprocess

    apps = tmp_path / "Applications"
    (apps / "X.app").mkdir(parents=True)
    project = tmp_path / "x"
    project.mkdir()
    monkeypatch.setattr(launcher, "APPLICATIONS", apps)
    app = launcher.ExternalApp("x", "X", "x", "server.py", "", build="false", build_output="out/X.app")

    result = subprocess.run(["/bin/sh", "-c", launcher.registered_build_command(app, project)])

    assert result.returncode != 0
    assert (apps / "X.app").is_dir()


def test_the_build_report_uses_the_registered_build(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    bundle = make_bundle(tmp_path, "SONAR")
    _stamp(bundle, build=104)
    _checkout(tmp_path, "sonar", monkeypatch=monkeypatch, build=109)
    app = launcher.ExternalApp("sonar", "SONAR", "sonar", "main.py", "",
                               build="python3 build_desktop.py", build_output="dist/SONAR.app")

    row = launcher.build_status(app, tmp_path)

    assert row.runs_in_app
    assert "python3 build_desktop.py" in row.command and "ditto" in row.command


def test_no_command_names_the_projects_build_guide(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    bundle = make_bundle(tmp_path, "SONAR")
    _stamp(bundle, build=104)
    project = _checkout(tmp_path, "sonar", monkeypatch=monkeypatch, build=109)
    (project / "desktop").mkdir()
    (project / "desktop" / "BUILDING.md").write_text("steps\n")
    app = launcher.ExternalApp("sonar", "SONAR", "sonar", "main.py", "")

    row = launcher.build_status(app, tmp_path)

    assert row.command is None
    assert row.guide == project / "desktop" / "BUILDING.md"
    assert row.project == project
    assert "desktop/BUILDING.md" in row.note


def test_a_registered_build_keeps_edits_made_before_it(tmp_path, monkeypatch):
    import subprocess

    apps = tmp_path / "Applications"
    apps.mkdir()
    project = tmp_path / "x"
    _git_project(project)
    (project / "a.txt").write_text("my edit")
    monkeypatch.setattr(launcher, "APPLICATIONS", apps)
    monkeypatch.setattr(launcher, "installs_dir", lambda: tmp_path / "installs")
    app = launcher.ExternalApp("x", "X", "x", "server.py", "", build=_MAKE_BUNDLE,
                               build_output="out/X.app")
    home = tmp_path / "home"
    (home / ".Trash").mkdir(parents=True)

    subprocess.run(["/bin/sh", "-c", launcher.registered_build_command(app, project)],
                   check=True, env={**os.environ, "HOME": str(home)})

    # It was already changed before the build, so it is not restored to HEAD.
    assert (project / "a.txt").read_text() == "built_at now"


# --- run_in_terminal (spec update-now-terminal) -----------------------------


def _record_opens(monkeypatch):
    """Capture the `open` calls run_in_terminal makes instead of running them."""
    calls = []
    monkeypatch.setattr(
        launcher.control.subprocess, "run",
        lambda command, **kwargs: calls.append(command)
        or launcher.control.subprocess.CompletedProcess(command, 0, "", ""),
    )
    return calls


def test_run_in_terminal_writes_one_private_command_file_per_command(tmp_path, monkeypatch):
    """Each by-hand install gets its own file and its own Terminal window; the
    file holds the command and a closing line, mode 0700, nothing else."""
    calls = _record_opens(monkeypatch)
    commands = ["cd '/r/a b' && ./scripts/install_app.sh", "cd /r/c && ./install.sh"]

    files = launcher.run_in_terminal(commands, tmp_path / "runs")

    assert len(files) == 2 and files[0] != files[1]
    assert [c[:3] for c in calls] == [["open", "-a", "Terminal"]] * 2
    assert [c[3] for c in calls] == [str(f) for f in files]
    for command, path in zip(commands, files):
        assert path.suffix == ".command"
        assert (path.stat().st_mode & 0o777) == 0o700
        assert path.read_text() == (
            "#!/bin/zsh -l\n"
            f"{command}\n"
            "status=$?\n"
            "echo\n"
            'echo "Finished (exit $status). Close this window, then press '
            'Refresh in Lab Hub."\n'
            'rm -f -- "$0"\n'
        )
    assert files[0].parent == tmp_path / "runs"
    assert ((tmp_path / "runs").stat().st_mode & 0o777) == 0o700


def test_run_in_terminal_clears_the_previous_run_first(tmp_path, monkeypatch):
    calls = _record_opens(monkeypatch)
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "old.command").write_text("rm -rf /\n")
    (runs / "notes.txt").write_text("keep")

    (new,) = launcher.run_in_terminal(["cd /r && ./i.sh"], runs)

    assert not (runs / "old.command").exists()
    assert (runs / "notes.txt").exists()  # only .command files are ours to clear
    assert new.exists() and len(calls) == 1


def test_run_in_terminal_refuses_a_command_that_is_not_one_line(tmp_path, monkeypatch):
    """The file is executable: a command with a line break or a NUL is more than
    the one line Lab Hub means to run, so nothing is written or opened."""
    calls = _record_opens(monkeypatch)
    runs = tmp_path / "runs"

    for bad in ("cd /r && ./i.sh\nrm -rf ~", "cd /r\r&& x", "cd /r\x00", "   "):
        with pytest.raises(ValueError):
            launcher.run_in_terminal(["cd /ok && ./ok.sh", bad], runs)

    assert calls == []
    assert not list(runs.glob("*.command")) if runs.exists() else True


def test_run_in_terminal_with_nothing_to_run_opens_nothing(tmp_path, monkeypatch):
    calls = _record_opens(monkeypatch)
    assert launcher.run_in_terminal([], tmp_path / "runs") == []
    assert calls == []
    assert not (tmp_path / "runs").exists()  # and no folder or clean-up either


def test_a_refused_command_leaves_the_previous_run_alone(tmp_path, monkeypatch):
    """Validation happens before the clean-up, so a refusal destroys nothing."""
    _record_opens(monkeypatch)
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "install-1.command").write_text("old\n")

    with pytest.raises(ValueError):
        launcher.run_in_terminal(["cd /r\nrm x"], runs)

    assert (runs / "install-1.command").read_text() == "old\n"


def test_run_in_terminal_will_not_write_through_a_linked_folder(tmp_path, monkeypatch):
    calls = _record_opens(monkeypatch)
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "runs").symlink_to(real)

    with pytest.raises(OSError):
        launcher.run_in_terminal(["cd /r && ./i.sh"], tmp_path / "runs")

    assert list(real.iterdir()) == [] and calls == []


def test_run_in_terminal_defaults_to_lab_hubs_own_support_folder(tmp_path, monkeypatch):
    from lab_hub import config

    _record_opens(monkeypatch)
    monkeypatch.setattr(config, "SUPPORT_DIR", tmp_path / "Lab Hub")

    (path,) = launcher.run_in_terminal(["cd /r && ./i.sh"])

    assert path.parent == tmp_path / "Lab Hub" / "terminal-runs"


def test_a_window_that_does_not_open_is_reported_after_trying_every_one(tmp_path, monkeypatch):
    """`open` exiting non-zero is an error the owner is told about, and one
    failure does not stop the other windows from opening."""
    seen = []

    def run(command, **kwargs):
        seen.append(command[3])
        code = 1 if command[3].endswith("install-1.command") else 0
        return launcher.control.subprocess.CompletedProcess(
            command, code, "", "Terminal not found" if code else "")

    monkeypatch.setattr(launcher.control.subprocess, "run", run)

    with pytest.raises(launcher.LaunchError) as raised:
        launcher.run_in_terminal(["cd /a && ./a.sh", "cd /b && ./b.sh"], tmp_path / "runs")

    assert len(seen) == 2
    assert "cd /a && ./a.sh" in str(raised.value) and "Terminal not found" in str(raised.value)
    assert "cd /b" not in str(raised.value)


# ----------------------------------------------------------------------
# A project with no launch command (spec apps-discovery §13.2)
# ----------------------------------------------------------------------
def _no_launch(tmp_path, monkeypatch, *, with_bundle: bool = False):
    """Kaila's shape: a checkout with a VERSION and nothing to start."""
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "Applications")
    if with_bundle:
        make_bundle(tmp_path / "Applications", "Kaila")
    project = tmp_path / "kaila"
    project.mkdir()
    (project / "VERSION").write_text("2\n")
    monkeypatch.setattr(launcher, "_commit_count", lambda _project: 12)
    app = launcher.ExternalApp("kaila", "Kaila", "kaila", None, "A project.")
    return app, project


def test_an_app_without_an_entry_is_not_launchable(tmp_path, monkeypatch):
    app, _ = _no_launch(tmp_path, monkeypatch)

    assert not app.launchable


def test_a_stray_bundle_with_its_name_is_never_this_projects_bundle(tmp_path, monkeypatch):
    app, _ = _no_launch(tmp_path, monkeypatch, with_bundle=True)

    assert launcher.bundle_path(app, tmp_path) is None
    assert launcher.bundle_marker(app, tmp_path) is None
    assert launcher.bundle_executable(app, tmp_path) is None
    assert launcher.can_bring_to_front(app, tmp_path) is False


def test_the_checkout_of_an_entry_less_app_is_its_folder(tmp_path, monkeypatch):
    app, project = _no_launch(tmp_path, monkeypatch)

    assert launcher.source_dir(app, tmp_path) == project
    assert launcher.checkout_marker(app, tmp_path) is None
    assert launcher.running_markers(app, tmp_path) == ()


def test_an_entry_less_app_with_no_folder_has_no_checkout(tmp_path, monkeypatch):
    app, project = _no_launch(tmp_path, monkeypatch, with_bundle=True)
    (project / "VERSION").unlink()
    project.rmdir()

    assert launcher.source_dir(app, tmp_path) is None
    assert launcher.version(app, tmp_path) == launcher.Version()
    assert launcher.status(app, tmp_path)[0] == "missing"


def test_an_entry_less_app_is_never_present_and_never_runs(tmp_path, monkeypatch):
    app, _ = _no_launch(tmp_path, monkeypatch)
    table = f"/usr/bin/python {tmp_path}/kaila/main.py\n{tmp_path}/Applications/Kaila.app/Contents/MacOS/Kaila"

    assert launcher.presence(app, tmp_path, table) == launcher.Presence(False, False)
    assert launcher.is_running(app, tmp_path, table) is False


def test_the_version_of_an_entry_less_app_is_its_checkouts_even_beside_a_bundle(
        tmp_path, monkeypatch):
    app, project = _no_launch(tmp_path, monkeypatch, with_bundle=True)

    found = launcher.version(app, tmp_path)

    assert found == launcher.checkout_version(project)
    assert found.text == "v2.012" and found.origin == "checkout"


def test_an_entry_less_apps_build_status_is_unknown_not_runs_the_checkout(tmp_path, monkeypatch):
    app, project = _no_launch(tmp_path, monkeypatch)

    row = launcher.build_status(app, tmp_path)

    assert row.verdict == "unknown" and not row.needs_rebuild
    assert row.note == "it has no launch command, so there is no build to compare."
    assert "runs the checkout directly" not in row.note
    assert row.version.text == "v2.012"
    assert row.command is None


def test_the_build_report_skips_an_entry_less_app_however_it_is_asked(tmp_path, monkeypatch):
    app, _ = _no_launch(tmp_path, monkeypatch)
    other = launcher.ExternalApp("x", "X", "x", "main.py", "")
    _project(tmp_path, "x")

    assert [r.app.key for r in launcher.build_report(tmp_path, (app, other))] == ["x"]
    assert launcher.build_report(tmp_path, (app,)) == ()
    launcher.registry.use(launcher.registry.Registry(suites=(other, app)))
    try:
        assert [r.app.key for r in launcher.build_report(tmp_path)] == ["x"]
    finally:
        launcher.registry.use(None)


def test_status_and_readiness_of_an_entry_less_app_say_there_is_nothing_to_start(
        tmp_path, monkeypatch):
    app, project = _no_launch(tmp_path, monkeypatch, with_bundle=True)

    assert launcher.status(app, tmp_path) == ("source", str(project))
    ready = launcher.readiness(app, tmp_path)
    assert not ready.ok
    assert ready.problem == "it has no launch command, so there is nothing to start"
    assert ready.state == "source"


def test_launching_or_raising_an_entry_less_app_is_refused_before_anything_runs(
        tmp_path, monkeypatch):
    app, _ = _no_launch(tmp_path, monkeypatch, with_bundle=True)

    def boom(*args, **kwargs):
        raise AssertionError("nothing may be started")

    monkeypatch.setattr(launcher.subprocess, "run", boom)
    monkeypatch.setattr(launcher.subprocess, "Popen", boom)
    for call in (lambda: launcher.launch(app, tmp_path),
                 lambda: launcher.launch(app, tmp_path, background=True),
                 lambda: launcher.bring_to_front(app, tmp_path)):
        with pytest.raises(launcher.LaunchError, match="Kaila has no launch command"):
            call()


def test_the_launcher_caches_are_only_read_and_written_never_cleared_or_walked():
    """Lab Hub's tile verdict (ui/own_verdict.py) fills the git caches from one
    worker thread while the GUI thread fills them too. That is safe only while
    each cache is a plain dict with single gets and sets: a `.clear()`, a `del`
    or a loop over one could meet a second writer mid-way. Checked on the code,
    not on its comment."""
    import ast

    tree = ast.parse(Path(launcher.state.__file__).read_text())

    def target(node):
        return node.target if isinstance(node, ast.AnnAssign) else node.targets[0]

    caches = {
        target(node).id
        for node in ast.walk(tree)
        if isinstance(node, (ast.AnnAssign, ast.Assign))
        and isinstance(target(node), ast.Name) and target(node).id.endswith("_CACHE")
    }
    assert {"_COUNT_CACHE", "_COMMIT_CACHE", "_DIRTY_CACHE", "_BEHIND_CACHE",
            "_ROOT_BEHIND_CACHE", "_SHALLOW_CACHE"} <= caches

    def is_cache(node) -> bool:
        return isinstance(node, ast.Name) and node.id in caches

    walked = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if is_cache(node.func.value) and node.func.attr != "get":
                walked.append((node.lineno, node.func.attr))
        elif isinstance(node, ast.Delete):
            walked += [(node.lineno, "del") for t in node.targets
                       if isinstance(t, ast.Subscript) and is_cache(t.value)]
        elif isinstance(node, (ast.For, ast.comprehension)) and is_cache(node.iter):
            walked.append((getattr(node, "lineno", 0), "iterated"))

    assert walked == []
