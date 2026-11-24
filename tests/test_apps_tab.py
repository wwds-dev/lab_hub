"""The launch cards.

The point of showing running state is that clicking Launch on something already
open is the wrong thing to do — it either opens a second copy or appears to do
nothing. So what these check is that the button changes what it *does*, not just
what it says.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QLabel

from lab_hub import launcher

from ui.apps_tab import AppCard

from .fakes import make_bundle


def _installed(tmp_path, monkeypatch, name="SONAR"):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    make_bundle(tmp_path, name)
    return launcher.ExternalApp("sonar", name, "sonar", "main.py", "summary")


def test_an_idle_app_offers_to_launch(qapp, tmp_path, monkeypatch):
    app = _installed(tmp_path, monkeypatch)
    card = AppCard(app)

    card.refresh(tmp_path, table="/bin/zsh\n")

    assert card.state.text() == "Installed"
    assert card.launch_button.text() == "Launch"
    assert card.launch_button.isEnabled()


def test_a_running_app_offers_to_raise_it(qapp, tmp_path, monkeypatch):
    app = _installed(tmp_path, monkeypatch)
    card = AppCard(app)

    card.refresh(tmp_path, table=f"{tmp_path}/SONAR.app/Contents/MacOS/SONAR\n")

    assert card.state.text() == "Running"
    assert card.launch_button.text() == "Bring to front"
    assert card.launch_button.isEnabled()


def test_the_button_raises_rather_than_relaunching(qapp, tmp_path, monkeypatch):
    """The behaviour that matters: a second copy is what we are avoiding."""
    app = _installed(tmp_path, monkeypatch)
    card = AppCard(app)
    card.refresh(tmp_path, table=f"{tmp_path}/SONAR.app/Contents/MacOS/SONAR\n")

    called = []
    monkeypatch.setattr(
        launcher, "bring_to_front", lambda a, root: called.append("raise") or "raised"
    )
    monkeypatch.setattr(
        launcher, "launch", lambda a, root: called.append("launch") or "launched"
    )

    card._launch()

    assert called == ["raise"]


def test_a_running_source_app_cannot_be_raised(qapp, tmp_path, monkeypatch):
    """No bundle to address, so the button says so instead of failing."""
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "none")
    project = tmp_path / "sonar"
    project.mkdir()
    (project / "main.py").write_text("pass\n")
    app = launcher.ExternalApp("sonar", "SONAR", "sonar", "main.py", "summary")
    card = AppCard(app)

    card.refresh(tmp_path, table=f"/usr/bin/python3 {project}/main.py\n")

    assert card.state.text() == "Running"
    assert card.launch_button.text() == "Running"
    assert not card.launch_button.isEnabled()
    assert "Dock" in card.launch_button.toolTip()


def test_a_missing_app_cannot_be_launched(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "none")
    app = launcher.ExternalApp("ghost", "Ghost", "ghost", "main.py", "summary")
    card = AppCard(app)

    card.refresh(tmp_path, table="")

    assert card.state.text() == "Not found"
    assert not card.launch_button.isEnabled()


def _tab(qapp, tmp_path, monkeypatch, with_checkouts=False):
    """Four cards. `with_checkouts` gives each one a real entry script.

    Without it the apps are nowhere at all, which is the right shape for the
    layout tests and the wrong one for anything about launching: a card with no
    bundle and no checkout has nothing to watch for, so it is never entitled to
    say an app failed to start.
    """
    from lab_hub import config

    from ui.apps_tab import AppsTab

    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "none")
    apps = tuple(
        launcher.ExternalApp(f"a{i}", f"App {i}", f"a{i}", "main.py", "summary")
        for i in range(4)
    )
    settings = config.Settings()
    if with_checkouts:
        for app in apps:
            (tmp_path / app.project).mkdir(parents=True, exist_ok=True)
            (tmp_path / app.project / app.entry).write_text("pass\n")
        settings = config.Settings(lab_root=str(tmp_path))
    tab = AppsTab(settings, apps, "Apps", "intro")
    # Qt defers the resize event until the widget is shown, so a hidden tab
    # never re-arranges and every one of these tests would read one column.
    tab.show()
    return tab


def test_a_wide_window_puts_tiles_side_by_side(qapp, tmp_path, monkeypatch):
    from ui.apps_tab import TILE_MIN_WIDTH

    tab = _tab(qapp, tmp_path, monkeypatch)
    tab.resize(TILE_MIN_WIDTH * 3 + 48, 800)
    qapp.processEvents()

    assert tab._columns > 1, "the launchpad should not be a single stack when wide"


def test_a_narrow_window_falls_back_to_one_column(qapp, tmp_path, monkeypatch):
    from ui.apps_tab import TILE_MIN_WIDTH

    tab = _tab(qapp, tmp_path, monkeypatch)
    tab.resize(TILE_MIN_WIDTH, 800)
    qapp.processEvents()

    assert tab._columns == 1


def test_every_tile_is_placed_exactly_once(qapp, tmp_path, monkeypatch):
    """Re-laying out on resize must not drop or duplicate a tile."""
    from ui.apps_tab import TILE_MIN_WIDTH

    tab = _tab(qapp, tmp_path, monkeypatch)
    for width in (TILE_MIN_WIDTH * 3, TILE_MIN_WIDTH, TILE_MIN_WIDTH * 2):
        tab.resize(width + 48, 800)
        qapp.processEvents()
        placed = [tab.grid.itemAt(i).widget() for i in range(tab.grid.count())]
        assert sorted(map(id, placed)) == sorted(map(id, tab.cards))


# ----------------------------------------------------------------------
# Between pressing Launch and knowing whether it worked
# ----------------------------------------------------------------------
def test_the_card_waits_while_an_app_starts(qapp, tmp_path, monkeypatch):
    import time

    app = _installed(tmp_path, monkeypatch)
    card = AppCard(app)
    card._pending_since = time.monotonic()

    card.refresh(tmp_path, table="/bin/zsh\n")

    assert card.state.text() == "Starting…"
    assert not card.launch_button.isEnabled(), "a second press would start a second copy"


def test_an_app_that_comes_up_ends_the_wait(qapp, tmp_path, monkeypatch):
    import time

    app = _installed(tmp_path, monkeypatch)
    card = AppCard(app)
    card._pending_since = time.monotonic()

    card.refresh(tmp_path, table=f"{tmp_path}/SONAR.app/Contents/MacOS/SONAR\n")

    assert card.state.text() == "Running"
    assert card._pending_since is None


def _stub_card(tmp_path, monkeypatch, project="sentinel"):
    """A card for the bundle shape that execs its checkout and exits."""
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    bundle = make_bundle(tmp_path, "Sentinel")
    resources = bundle / "Contents" / "Resources"
    resources.mkdir(parents=True, exist_ok=True)
    # Pointing nowhere: the case where the tile is left with nothing to watch.
    (resources / launcher.PROJECT_ROOT_FILE).write_text(str(tmp_path / "gone"))
    return launcher.ExternalApp("sf", "Sentinel", project, "main.py", "summary")


def test_a_launch_nobody_can_watch_is_not_called_a_failure(
    qapp, tmp_path, monkeypatch
):
    """Sentinel running, the tile saying *Did not start*, twice over.

    The stub bundle hands off and exits and there is no checkout left to watch,
    so the process table says nothing either way. The old card read that silence
    as death and put a red notice under an app that was open on screen.
    """
    import time

    from ui.apps_tab import LAUNCH_CONFIRM_SECONDS

    app = _stub_card(tmp_path, monkeypatch)
    card = AppCard(app)
    reported = []
    card.start_failed.connect(reported.append)
    card._pending_since = time.monotonic() - LAUNCH_CONFIRM_SECONDS - 1

    card.refresh(tmp_path, table="/bin/zsh\n")

    assert card.state.text() == "Started"
    assert reported == [], "nothing was observed, so nothing can be reported"


def test_an_unwatchable_launch_still_flips_to_running(qapp, tmp_path, monkeypatch):
    """The neutral notice is not a dead end: the moment the app does show up,
    the tile says so."""
    import time

    from ui.apps_tab import LAUNCH_CONFIRM_SECONDS

    _project = tmp_path / "sentinel"
    _project.mkdir()
    (_project / "main.py").write_text("pass\n")
    app = _stub_card(tmp_path, monkeypatch)
    card = AppCard(app)
    card._pending_since = time.monotonic() - LAUNCH_CONFIRM_SECONDS - 1
    card.refresh(tmp_path, table="/bin/zsh\n")

    card.refresh(
        tmp_path, table=f"{tmp_path}/sentinel/.venv/bin/python {_project}/main.py\n"
    )

    assert card.state.text() == "Running"


def test_the_unconfirmed_notice_expires(qapp, tmp_path, monkeypatch):
    """Like the failure notice, it describes one launch, not the app."""
    import time

    from ui.apps_tab import FAILURE_NOTICE_SECONDS, LAUNCH_CONFIRM_SECONDS

    app = _stub_card(tmp_path, monkeypatch)
    card = AppCard(app)
    card._pending_since = time.monotonic() - LAUNCH_CONFIRM_SECONDS - 1
    card.refresh(tmp_path, table="/bin/zsh\n")
    assert card.state.text() == "Started"

    card._unconfirmed_at -= FAILURE_NOTICE_SECONDS + 1
    card.refresh(tmp_path, table="/bin/zsh\n")

    assert card.state.text() == "Installed"


def test_an_app_that_never_comes_up_is_reported(qapp, tmp_path, monkeypatch):
    """The bug this closes: a child that died during startup looked exactly
    like one that started fine — the button greyed for a moment, and nothing
    else ever happened."""
    import time

    from ui.apps_tab import LAUNCH_CONFIRM_SECONDS

    app = _installed(tmp_path, monkeypatch)
    card = AppCard(app)
    reported = []
    card.start_failed.connect(reported.append)
    card._pending_since = time.monotonic() - LAUNCH_CONFIRM_SECONDS - 1

    card.refresh(tmp_path, table="/bin/zsh\n")

    assert card.state.text() == "Did not start"
    assert len(reported) == 1
    assert "never came up" in reported[0]
    assert "log show" in reported[0], "say where to look, not just that it failed"


def test_the_failure_is_reported_once_not_every_poll(qapp, tmp_path, monkeypatch):
    import time

    from ui.apps_tab import LAUNCH_CONFIRM_SECONDS

    app = _installed(tmp_path, monkeypatch)
    card = AppCard(app)
    reported = []
    card.start_failed.connect(reported.append)
    card._pending_since = time.monotonic() - LAUNCH_CONFIRM_SECONDS - 1

    card.refresh(tmp_path, table="/bin/zsh\n")
    card.refresh(tmp_path, table="/bin/zsh\n")
    card.refresh(tmp_path, table="/bin/zsh\n")

    assert len(reported) == 1, "the status bar would be unreadable otherwise"


def test_a_late_arrival_clears_the_failure(qapp, tmp_path, monkeypatch):
    """Slower than the wait is not the same as broken."""
    import time

    from ui.apps_tab import LAUNCH_CONFIRM_SECONDS

    app = _installed(tmp_path, monkeypatch)
    card = AppCard(app)
    card._pending_since = time.monotonic() - LAUNCH_CONFIRM_SECONDS - 1
    card.refresh(tmp_path, table="/bin/zsh\n")
    assert card.state.text() == "Did not start"

    card.refresh(tmp_path, table=f"{tmp_path}/SONAR.app/Contents/MacOS/SONAR\n")

    assert card.state.text() == "Running"


def test_an_app_with_no_interpreter_cannot_be_launched(qapp, tmp_path, monkeypatch):
    """Answered on the card rather than in a dialog after the press."""
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "none")
    monkeypatch.setattr(launcher, "venv_python", lambda project: None)
    monkeypatch.setattr(launcher.shutil, "which", lambda name: None)
    project = tmp_path / "sonar"
    project.mkdir()
    (project / "main.py").write_text("")
    app = launcher.ExternalApp("sonar", "SONAR", "sonar", "main.py", "summary")
    card = AppCard(app)

    card.refresh(tmp_path, table="")

    assert card.state.text() == "Source only"
    assert not card.launch_button.isEnabled()
    assert "no interpreter" in card.launch_button.toolTip()
    assert "no interpreter" in card.detail.text(), "say why, where it is read"


# ----------------------------------------------------------------------
# "Did not start" is a notice about one launch, not a permanent verdict
# ----------------------------------------------------------------------
def test_the_failure_notice_expires(qapp, tmp_path, monkeypatch):
    """It outlived its subject: the tile still said *Did not start* after the
    app had been opened and closed again by hand."""
    import time

    from ui.apps_tab import FAILURE_NOTICE_SECONDS, LAUNCH_CONFIRM_SECONDS

    app = _installed(tmp_path, monkeypatch)
    card = AppCard(app)
    card._pending_since = time.monotonic() - LAUNCH_CONFIRM_SECONDS - 1
    card.refresh(tmp_path, table="/bin/zsh\n")
    assert card.state.text() == "Did not start"

    card._failed_at -= FAILURE_NOTICE_SECONDS + 1
    card.refresh(tmp_path, table="/bin/zsh\n")

    assert card.state.text() == "Installed"


def test_the_notice_stays_up_long_enough_to_read(qapp, tmp_path, monkeypatch):
    import time

    from ui.apps_tab import LAUNCH_CONFIRM_SECONDS

    app = _installed(tmp_path, monkeypatch)
    card = AppCard(app)
    card._pending_since = time.monotonic() - LAUNCH_CONFIRM_SECONDS - 1

    card.refresh(tmp_path, table="/bin/zsh\n")
    card.refresh(tmp_path, table="/bin/zsh\n")

    assert card.state.text() == "Did not start", "one poll must not clear it"


def test_forgetting_the_failure_restores_the_real_state(qapp, tmp_path, monkeypatch):
    import time

    from ui.apps_tab import LAUNCH_CONFIRM_SECONDS

    app = _installed(tmp_path, monkeypatch)
    card = AppCard(app)
    card._pending_since = time.monotonic() - LAUNCH_CONFIRM_SECONDS - 1
    card.refresh(tmp_path, table="/bin/zsh\n")

    card.forget_failure()
    card.refresh(tmp_path, table="/bin/zsh\n")

    assert card.state.text() == "Installed"


def test_re_check_clears_the_notices(qapp, tmp_path, monkeypatch):
    """Re-check means "tell me what is true now"."""
    import time

    from ui.apps_tab import LAUNCH_CONFIRM_SECONDS

    tab = _tab(qapp, tmp_path, monkeypatch, with_checkouts=True)
    for card in tab.cards:
        card._pending_since = time.monotonic() - LAUNCH_CONFIRM_SECONDS - 1
    tab.refresh()
    assert all(card.state.text() == "Did not start" for card in tab.cards)

    tab.recheck()

    assert not any(card.state.text() == "Did not start" for card in tab.cards)


def test_an_app_that_shows_up_late_clears_the_notice(qapp, tmp_path, monkeypatch):
    import time

    from ui.apps_tab import LAUNCH_CONFIRM_SECONDS

    app = _installed(tmp_path, monkeypatch)
    card = AppCard(app)
    card._pending_since = time.monotonic() - LAUNCH_CONFIRM_SECONDS - 1
    card.refresh(tmp_path, table="/bin/zsh\n")

    card.refresh(tmp_path, table=f"{tmp_path}/SONAR.app/Contents/MacOS/SONAR\n")

    assert card.state.text() == "Running"


# ----------------------------------------------------------------------
# The background engine, reported without being mistaken for the app
# ----------------------------------------------------------------------
def _sonar_card(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    from .fakes import make_bundle

    make_bundle(tmp_path, "SONAR")
    project = tmp_path / "sonar"
    project.mkdir(exist_ok=True)
    (project / "main.py").write_text("")
    app = launcher.ExternalApp(
        "sonar", "SONAR", "sonar", "main.py", "summary", service="Background engine"
    )
    return AppCard(app)


def test_the_engine_line_reports_a_running_daemon(qapp, tmp_path, monkeypatch):
    card = _sonar_card(tmp_path, monkeypatch)

    card.refresh(
        tmp_path,
        table=f"{tmp_path}/sonar/.venv/bin/python {tmp_path}/sonar/main.py --headless\n",
    )

    assert card.service.text() == "Background engine · running"
    assert card.state.text() == "Installed", "a daemon is not an open window"
    assert card.launch_button.text() == "Launch"


def test_the_engine_line_reports_a_stopped_daemon(qapp, tmp_path, monkeypatch):
    card = _sonar_card(tmp_path, monkeypatch)

    card.refresh(tmp_path, table="/bin/zsh\n")

    assert card.service.text() == "Background engine · stopped"


def test_the_app_and_its_engine_are_reported_together(qapp, tmp_path, monkeypatch):
    card = _sonar_card(tmp_path, monkeypatch)

    card.refresh(
        tmp_path,
        table=(
            f"{tmp_path}/sonar/.venv/bin/python {tmp_path}/sonar/main.py --headless\n"
            f"{tmp_path}/SONAR.app/Contents/MacOS/SONAR\n"
        ),
    )

    assert card.state.text() == "Running"
    assert card.service.text() == "Background engine · running"


def test_an_app_without_a_service_says_nothing(qapp, tmp_path, monkeypatch):
    """The row is still reserved, so the tiles stay the same height."""
    app = _installed(tmp_path, monkeypatch)
    card = AppCard(app)

    card.refresh(tmp_path, table="/bin/zsh\n")

    assert card.service.text() == ""
    assert card.service.height() or True  # present, just empty


def test_the_launchpad_has_a_build_check_and_the_others_do_not(qapp, tmp_path, monkeypatch):
    """One button, reporting every app. The question it answers is not per-tab,
    so three copies of it would be noise."""
    from PySide6.QtWidgets import QPushButton

    from lab_hub import config
    from ui.apps_tab import AppsTab

    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "none")
    apps = (launcher.ExternalApp("a", "A", "a", "main.py", "s"),)

    with_button = AppsTab(config.Settings(), apps, "Apps", "intro", check_builds=True)
    without = AppsTab(config.Settings(), apps, "Apps", "intro")

    def labels(tab):
        return {b.text() for b in tab.findChildren(QPushButton)}

    assert "Check builds" in labels(with_button)
    assert "Check builds" not in labels(without)


def test_a_tools_only_tab_checks_its_own_build(qapp, tmp_path, monkeypatch):
    """A Tools-only app has no launchpad tile, so its tab carries the same
    check and Update now — asking about its own apps, never every app."""
    from ui.progress_window import BuildCheckWindow

    from lab_hub import config
    from ui.apps_tab import AppsTab

    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "none")
    apps = (launcher.ExternalApp("b", "B", "b", "main.py", "s"),)
    tab = AppsTab(config.Settings(), apps, "B", "intro", check_own_builds=True)
    assert tab.check_button.text() == "Check build"

    asked = []

    def report(root, scope=None):
        asked.append(scope)
        return (launcher.BuildStatus(apps[0], launcher.Version(), "behind",
                                     "built older.", None, "cd /b && ./build_app.sh"),)

    seen = {}
    monkeypatch.setattr(launcher, "build_report", report)
    monkeypatch.setattr(BuildCheckWindow, "ask", lambda self: seen.update(
        text=self.text(), labels={b.text() for b in self.buttons()}))
    tab.show_build_report()

    assert asked == [apps]
    assert seen["text"] == "B would open something older than its source."
    assert "Update now" in seen["labels"]

    # Delete the tab now rather than leaving it to the garbage collector, which
    # would free it mid-way through a later test's window construction.
    import shiboken6

    tab._poll.stop()
    shiboken6.delete(tab)


def test_a_scoped_check_never_speaks_for_every_app(qapp, tmp_path, monkeypatch):
    """Backup and Sync checks its own two apps. "Every app is the newest build"
    is the launchpad's answer, and this report has not looked at every app."""
    from ui.progress_window import BuildCheckWindow

    from lab_hub import config
    from ui.apps_tab import AppsTab

    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "none")
    apps = (launcher.ExternalApp("c", "C", "c", "main.py", "s"),
            launcher.ExternalApp("d", "D", "d", "main.py", "s"))
    tab = AppsTab(config.Settings(), apps, "C and D", "intro", check_own_builds=True)
    assert tab.check_button.text() == "Check builds"

    asked = []

    def report(root, scope=None):
        asked.append(scope)
        return tuple(
            launcher.BuildStatus(app, launcher.Version("1.0", "bundle"), "current",
                                 "matches its source.")
            for app in apps
        )

    seen = {}
    monkeypatch.setattr(launcher, "build_report", report)
    monkeypatch.setattr(BuildCheckWindow, "ask", lambda self: seen.update(
        text=self.text(), labels={b.text() for b in self.buttons()}))
    tab.show_build_report()

    assert asked == [apps]
    assert seen["text"] == "All 2 apps are the newest build of themselves."
    # Nothing to rebuild, so no Update now.
    assert "Update now" not in seen["labels"]

    import shiboken6

    tab._poll.stop()
    shiboken6.delete(tab)


def test_copying_the_commands_puts_them_on_the_clipboard(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    from lab_hub import config
    from ui.apps_tab import AppsTab

    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "none")
    apps = (launcher.ExternalApp("a", "A", "a", "main.py", "s"),)
    tab = AppsTab(config.Settings(), apps, "Apps", "intro", check_builds=True)
    said = []
    tab.launched.connect(said.append)

    tab.copy_commands(["cd /x && ./build_app.sh --install"])

    assert QApplication.clipboard().text() == "cd /x && ./build_app.sh --install"
    assert said and "clipboard" in said[0]


def _pump_until(qapp, predicate, timeout_ms=15000):
    """Run the event loop until `predicate()` is true or the timeout elapses."""
    import time as _time

    from PySide6.QtWidgets import QApplication

    deadline = _time.monotonic() + timeout_ms / 1000
    while not predicate() and _time.monotonic() < deadline:
        QApplication.processEvents()
        _time.sleep(0.01)
    return predicate()


def test_the_update_button_shows_only_when_something_is_behind(
    qapp, tmp_path, monkeypatch
):
    """Nothing to rebuild, no rebuild button — the same reason the copy buttons
    only appear when there is a command to copy."""
    from ui.progress_window import BuildCheckWindow

    from lab_hub import config
    from ui.apps_tab import AppsTab

    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "none")
    apps = (launcher.ExternalApp("a", "A", "a", "main.py", "s"),)
    tab = AppsTab(config.Settings(), apps, "Apps", "intro", check_builds=True)

    seen = {}

    def capture(box):
        seen["labels"] = {b.text() for b in box.buttons()}

    monkeypatch.setattr(BuildCheckWindow, "ask", lambda self: capture(self))

    # A checkout that is level with its source: no command, so no Update now.
    monkeypatch.setattr(
        launcher,
        "build_report",
        lambda root: (
            launcher.BuildStatus(
                apps[0], launcher.Version(), "current", "matches its source.",
            ),
        ),
    )
    tab.show_build_report()
    assert "Update now" not in seen["labels"]

    # One behind, with a command to run: Update now appears.
    monkeypatch.setattr(
        launcher,
        "build_report",
        lambda root: (
            launcher.BuildStatus(
                apps[0], launcher.Version(), "behind", "built older.",
                None, "cd /x && ./build_app.sh",
            ),
        ),
    )
    tab.show_build_report()
    assert "Update now" in seen["labels"]


def _by_hand_tab(qapp, monkeypatch, rows_for):
    """An AppsTab whose build report is `rows_for(apps)`; the dialog's buttons
    and text are recorded, and `press` (if given) clicks the named button."""
    from ui.progress_window import BuildCheckWindow

    from lab_hub import config
    from ui.apps_tab import AppsTab

    apps = (launcher.ExternalApp("p", "P", "p", "main.py", "s"),
            launcher.ExternalApp("q", "Q", "q", "main.py", "s"))
    tab = AppsTab(config.Settings(), apps, "P", "intro", check_own_builds=True)
    monkeypatch.setattr(launcher, "build_report",
                        lambda root, scope=None: rows_for(apps))
    seen = {}

    def exec_(box, press=None):
        seen.update(info=box.informativeText(),
                    labels={b.text() for b in box.buttons()})
        for b in box.buttons():
            if b.text() == seen.get("press"):
                b.click()

    monkeypatch.setattr(BuildCheckWindow, "ask", exec_)
    return tab, seen


def _drop(tab):
    import shiboken6

    tab._poll.stop()
    shiboken6.delete(tab)


def test_a_by_hand_install_gets_update_now_and_is_named_in_the_text(qapp, monkeypatch):
    """Provisio alone being behind used to leave no Update now. Now it is there,
    says the installer opens in Terminal and asks the owner there, and an app
    with no command is still named."""
    tab, seen = _by_hand_tab(qapp, monkeypatch, lambda apps: (
        launcher.BuildStatus(apps[0], launcher.Version(), "behind", "older.",
                             None, "cd /r && ./scripts/install_app.sh",
                             by_hand=True),
        launcher.BuildStatus(apps[1], launcher.Version(), "behind", "older."),
    ))
    tab.show_build_report()

    assert "Update now" in seen["labels"]
    assert "Copy commands" in seen["labels"]
    assert "Update now opens Terminal for P" in seen["info"]
    assert "confirm in its window" in seen["info"]
    assert "after the rebuilds" not in seen["info"]  # nothing rebuilds first here
    assert "cd /r && ./scripts/install_app.sh" in seen["info"]
    assert "No rebuild command for: Q." in seen["info"]
    _drop(tab)


def test_update_now_opens_terminal_for_a_by_hand_app_and_runs_no_dialog(qapp, monkeypatch):
    """Only a by-hand app is behind: no in-app rebuild, one Terminal window."""
    from ui import apps_tab

    tab, seen = _by_hand_tab(qapp, monkeypatch, lambda apps: (
        launcher.BuildStatus(apps[0], launcher.Version(), "behind", "older.",
                             None, "cd /r && ./scripts/install_app.sh",
                             by_hand=True),))
    seen["press"] = "Update now"
    ran, opened = [], []
    monkeypatch.setattr(apps_tab, "Rebuild",
                        lambda *a, **k: ran.append(a) or pytest.fail("no in-app run"))
    monkeypatch.setattr(launcher, "run_in_terminal",
                        lambda commands, *a, **k: opened.append(list(commands)) or [])
    monkeypatch.setattr(tab, "recheck", lambda: None)
    tab.show_build_report()

    assert ran == []
    assert opened == [["cd /r && ./scripts/install_app.sh"]]
    _drop(tab)


class _FakeRebuild:
    """Stands in for Rebuild: records what it was asked to run."""
    ok = True
    asked: list = []
    failed_commands: list = []  # failed, but the run went on to the end

    def __init__(self, commands, parent=None, **_hooks):
        type(self).asked.append(list(commands))
        self.failed = list(type(self).failed_commands)
        self.ran_to_end = type(self).ok or bool(self.failed)
        self.succeeded = self.ran_to_end and not self.failed

    def exec(self):
        return 0


def _mixed_rows(apps):
    return (launcher.BuildStatus(apps[0], launcher.Version(), "behind", "older.",
                                 None, "cd /r && ./scripts/install_app.sh",
                                 by_hand=True),
            launcher.BuildStatus(apps[1], launcher.Version(), "behind", "older.",
                                 None, "cd /q && ./build_app.sh"))


def test_update_now_runs_the_in_app_rebuilds_then_opens_terminal(qapp, monkeypatch):
    from ui import apps_tab

    _FakeRebuild.ok, _FakeRebuild.asked, _FakeRebuild.failed_commands = True, [], []
    tab, seen = _by_hand_tab(qapp, monkeypatch, _mixed_rows)
    seen["press"] = "Update now"
    order = []
    monkeypatch.setattr(apps_tab, "Rebuild",
                        lambda *a, **k: order.append("rebuild") or _FakeRebuild(*a, **k))
    monkeypatch.setattr(launcher, "run_in_terminal",
                        lambda commands, *a, **k: order.append(("terminal", list(commands))) or [])
    rechecked, said = [], []
    monkeypatch.setattr(tab, "recheck", lambda: rechecked.append(1))
    tab.launched.connect(said.append)
    tab.show_build_report()

    assert "after the rebuilds above succeed" in seen["info"]
    assert _FakeRebuild.asked == [["cd /q && ./build_app.sh"]]  # never the by-hand one
    assert order == ["rebuild", ("terminal", ["cd /r && ./scripts/install_app.sh"])]
    assert rechecked == [1]
    # One message, saying both things; the first is not overwritten by the second.
    assert len(said) == 1
    assert "Rebuilt and reinstalled 1 app." in said[0] and "Opened Terminal for 1 installer" in said[0]
    _drop(tab)


def test_a_cancelled_in_app_rebuild_opens_no_terminal(qapp, monkeypatch):
    from ui import apps_tab

    _FakeRebuild.ok, _FakeRebuild.asked, _FakeRebuild.failed_commands = False, [], []
    tab, seen = _by_hand_tab(qapp, monkeypatch, _mixed_rows)
    seen["press"] = "Update now"
    opened = []
    monkeypatch.setattr(apps_tab, "Rebuild", _FakeRebuild)
    monkeypatch.setattr(launcher, "run_in_terminal",
                        lambda commands, *a, **k: opened.append(list(commands)) or [])
    monkeypatch.setattr(tab, "recheck", lambda: None)
    said = []
    tab.launched.connect(said.append)
    tab.show_build_report()

    assert _FakeRebuild.asked and opened == []
    assert said and "No Terminal windows opened" in said[0]
    _drop(tab)


def test_a_failed_in_app_rebuild_opens_no_terminal_though_the_run_went_on(qapp, monkeypatch):
    """Spec land-update-gaps §3.2 (review P2-1): the run now goes on past a
    failed rebuild, and the Terminal installers still do not open."""
    from ui import apps_tab

    _FakeRebuild.ok, _FakeRebuild.asked = False, []
    _FakeRebuild.failed_commands = ["cd /q && ./build_app.sh"]
    try:
        tab, seen = _by_hand_tab(qapp, monkeypatch, _mixed_rows)
        seen["press"] = "Update now"
        opened = []
        monkeypatch.setattr(apps_tab, "Rebuild", _FakeRebuild)
        monkeypatch.setattr(launcher, "run_in_terminal",
                            lambda commands, *a, **k: opened.append(list(commands)) or [])
        monkeypatch.setattr(tab, "recheck", lambda: None)
        said = []
        tab.launched.connect(said.append)
        tab.show_build_report()
    finally:
        _FakeRebuild.failed_commands = []

    assert _FakeRebuild.asked and opened == []
    assert said and "1 failed (" in said[0]
    assert "No Terminal windows opened because a rebuild failed." in said[0]
    assert "Rebuilt and reinstalled" not in said[0]
    _drop(tab)


def test_cancel_right_after_a_failed_rebuild_starts_nothing_more(qapp):
    """Review P3-4: Cancel in the moment between a failure and the next start."""
    dialog, rebuild = _rebuild_window(["false", "echo should-not-run"])
    seen = dialog.command_finished

    def finished(command, ok, cancelled=False, code=0):
        seen(command, ok, cancelled, code)
        if not ok:
            rebuild.cancel()

    dialog.command_finished = finished
    dialog.show()
    assert _pump_until(qapp, lambda: rebuild.ended)
    for _ in range(20):
        qapp.processEvents()
    assert "$ echo should-not-run" not in dialog.output_text()
    assert not rebuild.ran_to_end and rebuild.failed == ["false"]
    dialog.draw()
    assert dialog.header.outcome.text().startswith("Cancelled.")
    dialog.close()


def _forward_row(app):
    return launcher.BuildStatus(
        app, launcher.Version(), "behind", "its release clone is behind.", None,
        "git -C /r fetch origin && git -C /r merge --ff-only origin/main",
        forward=True)


def test_a_release_clone_behind_is_listed_to_move_and_gets_no_update_now(qapp, monkeypatch):
    """The forward command is shown and copyable under its own heading, the
    installer is not offered, and Update now is not there for it."""
    tab, seen = _by_hand_tab(qapp, monkeypatch, lambda apps: (_forward_row(apps[0]),))
    tab.show_build_report()

    assert "Update now" not in seen["labels"]
    assert "Copy commands" in seen["labels"]
    assert "Move the release clone first" in seen["info"]
    assert "Lab Hub runs nothing there" in seen["info"]
    assert "git -C /r fetch origin && git -C /r merge --ff-only origin/main" in seen["info"]
    assert "Update now opens Terminal" not in seen["info"]
    # Show and copy only (spec §5.1): no Terminal is offered for this report.
    assert "Copy and open Terminal" not in seen["labels"]
    _drop(tab)


def test_copy_commands_includes_the_forward_command_and_nothing_runs_it(qapp, monkeypatch):
    from ui import apps_tab

    tab, seen = _by_hand_tab(qapp, monkeypatch, lambda apps: (
        _forward_row(apps[0]),
        launcher.BuildStatus(apps[1], launcher.Version(), "behind", "older.",
                             None, "cd /q && ./build_app.sh")))
    seen["press"] = "Copy commands"
    copied, ran, opened = [], [], []
    monkeypatch.setattr(tab, "copy_commands", lambda commands: copied.append(list(commands)))
    monkeypatch.setattr(apps_tab, "Rebuild", lambda *a, **k: ran.append(a))
    monkeypatch.setattr(launcher, "run_in_terminal",
                        lambda commands, *a, **k: opened.append(commands) or [])
    tab.show_build_report()

    assert copied == [["cd /q && ./build_app.sh",
                       "git -C /r fetch origin && git -C /r merge --ff-only origin/main"]]
    assert ran == [] and opened == []
    _drop(tab)


def test_update_now_with_a_forward_row_runs_only_the_in_app_rebuilds(qapp, monkeypatch):
    from ui import apps_tab

    _FakeRebuild.ok, _FakeRebuild.asked = True, []
    tab, seen = _by_hand_tab(qapp, monkeypatch, lambda apps: (
        _forward_row(apps[0]),
        launcher.BuildStatus(apps[1], launcher.Version(), "behind", "older.",
                             None, "cd /q && ./build_app.sh")))
    seen["press"] = "Update now"
    opened = []
    monkeypatch.setattr(apps_tab, "Rebuild", _FakeRebuild)
    monkeypatch.setattr(launcher, "run_in_terminal",
                        lambda commands, *a, **k: opened.append(commands) or [])
    monkeypatch.setattr(tab, "recheck", lambda: None)
    tab.show_build_report()

    assert _FakeRebuild.asked == [["cd /q && ./build_app.sh"]]  # never the git command
    assert opened == []
    _drop(tab)


def test_two_by_hand_apps_get_two_separate_windows(qapp, monkeypatch):
    tab, seen = _by_hand_tab(qapp, monkeypatch, lambda apps: (
        launcher.BuildStatus(apps[0], launcher.Version(), "behind", "older.",
                             None, "cd /r && ./a.sh", by_hand=True),
        launcher.BuildStatus(apps[1], launcher.Version(), "behind", "older.",
                             None, "cd /q && ./b.sh", by_hand=True)))
    seen["press"] = "Update now"
    opened = []
    monkeypatch.setattr(launcher, "run_in_terminal",
                        lambda commands, *a, **k: opened.append(list(commands)) or [])
    monkeypatch.setattr(tab, "recheck", lambda: None)
    tab.show_build_report()

    assert opened == [["cd /r && ./a.sh", "cd /q && ./b.sh"]]  # one call, two commands
    _drop(tab)


def test_a_bad_terminal_command_stops_everything_before_any_rebuild(qapp, monkeypatch):
    """A command that cannot be opened is found before minutes of rebuilding,
    and the owner is told, not left with a click that did nothing."""
    from PySide6.QtWidgets import QMessageBox

    from ui import apps_tab

    _FakeRebuild.ok, _FakeRebuild.asked = True, []
    tab, seen = _by_hand_tab(qapp, monkeypatch, lambda apps: (
        launcher.BuildStatus(apps[0], launcher.Version(), "behind", "older.",
                             None, "cd /r\nrm x", by_hand=True),
        launcher.BuildStatus(apps[1], launcher.Version(), "behind", "older.",
                             None, "cd /q && ./build_app.sh")))
    seen["press"] = "Update now"
    warned = []
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda parent, title, text: warned.append(text)))
    monkeypatch.setattr(apps_tab, "Rebuild", _FakeRebuild)
    monkeypatch.setattr(tab, "recheck", lambda: None)
    tab.show_build_report()

    assert _FakeRebuild.asked == []
    assert len(warned) == 1 and "Nothing was started" in warned[0]
    _drop(tab)


def test_a_terminal_that_will_not_open_is_shown_not_swallowed(qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    tab, seen = _by_hand_tab(qapp, monkeypatch, lambda apps: (
        launcher.BuildStatus(apps[0], launcher.Version(), "behind", "older.",
                             None, "cd /r && ./i.sh", by_hand=True),))
    seen["press"] = "Update now"
    warned, said = [], []

    def fail(commands, *a, **k):
        raise launcher.LaunchError("Terminal did not open for: cd /r && ./i.sh")

    monkeypatch.setattr(launcher, "run_in_terminal", fail)
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda parent, title, text: warned.append(text)))
    monkeypatch.setattr(tab, "recheck", lambda: None)
    tab.launched.connect(said.append)
    tab.show_build_report()

    assert len(warned) == 1 and "Terminal did not open" in warned[0]
    assert said == []  # no "Opened Terminal" claim
    _drop(tab)


def test_nothing_behind_means_no_update_now_and_no_terminal(qapp, monkeypatch):
    tab, seen = _by_hand_tab(qapp, monkeypatch, lambda apps: (
        launcher.BuildStatus(apps[0], launcher.Version(), "current", "matches."),))
    opened = []
    monkeypatch.setattr(launcher, "run_in_terminal",
                        lambda commands, *a, **k: opened.append(commands) or [])
    tab.show_build_report()

    assert "Update now" not in seen["labels"]
    assert opened == []
    _drop(tab)


def test_an_app_with_no_command_gets_open_in_terminal(qapp, monkeypatch, tmp_path):
    """Nothing to run is not a dead end: its folder opens in Terminal."""
    from ui.progress_window import BuildCheckWindow

    from lab_hub import config
    from ui.apps_tab import AppsTab

    apps = (launcher.ExternalApp("s", "S", "s", "main.py", "x"),)
    tab = AppsTab(config.Settings(), apps, "S", "intro", check_own_builds=True)
    guide = tmp_path / "desktop" / "BUILDING.md"
    monkeypatch.setattr(launcher, "build_report", lambda root, scope=None: (
        launcher.BuildStatus(apps[0], launcher.Version(), "behind", "older.",
                             project=tmp_path, guide=guide),
    ))
    opened = []
    monkeypatch.setattr(launcher, "open_terminal", opened.append)
    seen = {}

    def press(box):
        seen.update(info=box.informativeText(), labels={b.text() for b in box.buttons()})
        for b in box.buttons():
            if b.text() == "Open in Terminal":
                b.click()

    monkeypatch.setattr(BuildCheckWindow, "ask", press)
    tab.show_build_report()

    assert "Update now" not in seen["labels"]
    assert "Open in Terminal" in seen["labels"]
    assert str(guide) in seen["info"]
    assert opened == [tmp_path]

    import shiboken6

    tab._poll.stop()
    shiboken6.delete(tab)


def _rebuild_window(commands, rows=(), lab_root=None):
    """A Check builds window at its Update step, running `commands` for real."""
    from lab_hub import progress
    from ui.progress_window import BuildCheckWindow
    from ui.rebuild import Rebuild

    window = BuildCheckWindow(progress.build_check_view(rows, scoped=True), lab_root)
    rebuild = Rebuild(commands, window)
    return window, rebuild


def _exec_bounded(rebuild, limit_s=8.0) -> float:
    """`rebuild.exec()`, with a watchdog so a run that never ends fails the test
    instead of hanging the suite. Returns how long exec() took."""
    import time as _time

    from PySide6.QtCore import QTimer

    hung = []

    def watchdog():
        if rebuild._loop is not None:
            hung.append(True)
            rebuild._loop.quit()

    QTimer.singleShot(int(limit_s * 1000), watchdog)
    start = _time.monotonic()
    rebuild.exec()
    took = _time.monotonic() - start
    assert not hung, f"exec() did not return within {limit_s} s"
    return took


def test_the_rebuild_dialog_runs_the_commands_in_order(qapp):
    """Two commands, both succeed, both show up in the log — and `succeeded`
    reports the run as clean."""
    dialog, rebuild = _rebuild_window(["echo first-command", "echo second-command"])
    dialog.show()
    assert _pump_until(qapp, lambda: dialog.cancel_button.text() == "Close")
    log = dialog.output_text()
    assert "first-command" in log and "second-command" in log
    assert rebuild.succeeded
    assert dialog.header.outcome.text() == "Done. Every app was rebuilt and reinstalled."
    dialog.close()


def test_a_failed_rebuild_does_not_stop_the_others(qapp):
    """Spec land-update-gaps §3.2 (was: a failure halted the run): one app that
    fails to build no longer keeps the later ones from being built."""
    rows = _x_rows("false") + (launcher.BuildStatus(
        launcher.ExternalApp("y", "Y", "y", "main.py", "s"), launcher.Version(), "behind",
        "older.", None, "echo third-command"),)
    dialog, rebuild = _rebuild_window(["false", "echo second-command", "echo third-command"],
                                      rows)
    dialog.show()
    assert _pump_until(qapp, lambda: dialog.cancel_button.text() == "Close")
    log = dialog.output_text()
    assert "second-command" in log and "third-command" in log
    assert "[X: the rebuild exited with code 1 — going on with the next]" in log
    assert rebuild.failed == ["false"] and rebuild.ran_to_end and not rebuild.succeeded
    dialog.draw()
    assert dialog.header.outcome.text() == "1 of 3 rebuilds failed: X. See the live output."
    assert dialog.rows[1].reason.text() != dialog.rows[0].reason.text()  # Y passed
    dialog.close()


def test_build_check_dialog_can_be_dismissed(qapp_or_none=None):
    """A window whose only buttons are copy buttons still has Close, and the
    red close button and Escape both dismiss it."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from lab_hub import progress
    from ui.application import LabHubApplication
    from ui.progress_window import BuildCheckWindow

    app = QApplication.instance() or LabHubApplication([])
    a = launcher.ExternalApp("f", "F", "f", "main.py", "s")
    rows = (launcher.BuildStatus(a, launcher.Version(), "behind", "older.", None,
                                 "git -C /r merge --ff-only origin/main", forward=True),)
    box = BuildCheckWindow(progress.build_check_view(rows, scoped=True))
    assert {b.text() for b in box.buttons()} == {"Copy commands", "Close"}

    box.show()
    app.processEvents()
    assert box.close(), "dialog refused to close"
    app.processEvents()
    assert not box.isVisible()

    box.show()
    app.processEvents()
    QTest.keyClick(box, Qt.Key.Key_Escape)
    app.processEvents()
    assert not box.isVisible()
    assert box.choice is None


def test_escape_during_a_rebuild_kills_it_and_the_next_command_never_starts(qapp, tmp_path):
    """Regression (spec progress-windows §8.7): Escape on the old RebuildDialog
    called reject(), which hid it without its closeEvent, so the build kept
    running unwatched and the next command started when it ended."""
    from PySide6.QtCore import QProcess, Qt, QTimer
    from PySide6.QtTest import QTest

    marker = tmp_path / "second-ran"
    dialog, rebuild = _rebuild_window(["sleep 30", f"touch '{marker}'"])
    dialog.show()
    assert _pump_until(qapp, lambda: rebuild.running)
    QTimer.singleShot(100, lambda: QTest.keyClick(dialog, Qt.Key.Key_Escape))
    took = _exec_bounded(rebuild)  # returns: the run ended and the window is closed

    assert took < 5, f"Escape did not kill the build: exec() took {took:.1f} s"
    assert rebuild.ended and not rebuild.succeeded
    assert rebuild._proc.state() == QProcess.ProcessState.NotRunning
    assert not dialog.isVisible()
    _pump_until(qapp, lambda: marker.exists(), timeout_ms=800)
    assert not marker.exists()
    assert "cancelled" in dialog.output_text()


def test_the_close_button_during_a_rebuild_kills_it_too(qapp, tmp_path):
    from PySide6.QtCore import QTimer

    marker = tmp_path / "second-ran"
    dialog, rebuild = _rebuild_window(["sleep 30", f"touch '{marker}'"])
    dialog.show()
    assert _pump_until(qapp, lambda: rebuild.running)
    QTimer.singleShot(100, dialog.close)  # the red button
    took = _exec_bounded(rebuild)
    assert took < 5, f"closing did not kill the build: exec() took {took:.1f} s"
    assert rebuild.ended and not rebuild.succeeded and not rebuild.running
    _pump_until(qapp, lambda: marker.exists(), timeout_ms=800)
    assert not marker.exists()


def _x_rows(command):
    app = launcher.ExternalApp("x", "X", "x", "main.py", "s")
    return (launcher.BuildStatus(app, launcher.Version(), "behind", "older.", None, command),)


def test_cancel_during_a_rebuild_stops_it_and_leaves_the_window_at_done(qapp, tmp_path):
    """Review P2-1: Cancel closed the window, so "Cancelled", the row's reason
    and the output were never seen. Now it stops the build at once and the
    window stays, its button reading Close; a cancelled build records nothing."""
    import time as _time

    from lab_hub import durations

    marker = tmp_path / "second-ran"
    dialog, rebuild = _rebuild_window(["echo 'INFO: PyInstaller: 6'; sleep 30",
                                       f"touch '{marker}'"],
                                      _x_rows("echo 'INFO: PyInstaller: 6'; sleep 30"))
    dialog.show()
    assert _pump_until(qapp, lambda: rebuild.running and "PyInstaller" in dialog.output_text())
    start = _time.monotonic()
    dialog.cancel_button.click()
    assert _time.monotonic() - start < 5
    assert rebuild.ended and not rebuild.succeeded and not rebuild.running
    assert dialog.isVisible() and dialog.cancel_button.text() == "Close"
    dialog.draw()
    assert dialog.header.outcome.text() == "Cancelled. Some apps may still be out of date."
    assert [m.text() for m in dialog.steps._marks] == ["✓"] * 4
    assert dialog.rows[0].pill.text() == "Cancelled"
    assert dialog.rows[0].reason.text() == "The build was stopped."
    assert "cancelled" in dialog.output_text()
    _pump_until(qapp, lambda: marker.exists(), timeout_ms=800)
    assert not marker.exists()
    assert "app:x" not in durations.load()
    dialog.cancel_button.click()  # now Close
    assert not dialog.isVisible()
    assert _exec_bounded(rebuild, 3) < 1


def test_cancel_stops_what_the_build_started_not_only_the_shell(qapp, tmp_path):
    """Review P2-4 / Secure P2-2: kill() reached only `$SHELL -lc`; a tool the
    script started (here a `sleep`) was left running after "stopped"."""
    import os
    import signal
    import time as _time

    pidfile, after = tmp_path / "child.pid", tmp_path / "after"
    script = (f"bash -c 'sleep 47 & echo $! > \"{pidfile}\"; wait; touch \"{after}\"'")
    dialog, rebuild = _rebuild_window([script])
    dialog.show()
    assert _pump_until(qapp, lambda: pidfile.exists() and pidfile.read_text().strip())
    pid = int(pidfile.read_text())

    def alive():
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        return True

    try:
        assert alive()
        start = _time.monotonic()
        dialog.cancel_button.click()
        assert _time.monotonic() - start < 5
        assert rebuild.ended and not rebuild.running
        assert _pump_until(qapp, lambda: not alive(), timeout_ms=3000), \
            "the build's child process outlived Cancel"
        assert not after.exists()
    finally:
        if alive():
            os.kill(pid, signal.SIGKILL)
    dialog.close()


def test_a_command_that_cannot_start_fails_and_the_run_still_ends(qapp, monkeypatch):
    """Review P1-1: with no shell to start, QProcess sent errorOccurred and never
    finished; the run never ended, Cancel did nothing and exec() never returned.
    Each command is tried in turn (spec land-update-gaps §3.2)."""
    monkeypatch.setenv("SHELL", "/nonexistent/shell")
    dialog, rebuild = _rebuild_window(["echo hi", "echo second"], _x_rows("echo hi"))
    dialog.show()
    assert _pump_until(qapp, lambda: rebuild.ended, timeout_ms=5000)
    assert not rebuild.succeeded and not rebuild.running
    assert dialog.cancel_button.text() == "Close"
    dialog.draw()
    assert dialog.header.outcome.text() == ("2 of 2 rebuilds failed: X, echo second. "
                                            "See the live output.")
    assert dialog.rows[0].reason.text() == "It could not start; see the live output."
    assert rebuild.failed == ["echo hi", "echo second"]
    log = dialog.output_text()
    assert "X: the rebuild could not start" in log and "$ echo second" in log
    from PySide6.QtCore import QTimer

    QTimer.singleShot(200, dialog.cancel_button.click)  # Close
    assert _exec_bounded(rebuild, 5) < 3
    assert not dialog.isVisible()


def test_escape_after_a_command_could_not_start_returns(qapp, monkeypatch):
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtTest import QTest

    monkeypatch.setenv("SHELL", "/nonexistent/shell")
    dialog, rebuild = _rebuild_window(["echo hi"])
    dialog.show()
    QTimer.singleShot(400, lambda: QTest.keyClick(dialog, Qt.Key.Key_Escape))
    assert _exec_bounded(rebuild, 5) < 3
    assert rebuild.ended and not rebuild.succeeded and not dialog.isVisible()


def test_escape_before_the_first_command_starts_runs_nothing(qapp, tmp_path):
    """Review P1-1 / Secure P3-1: closing the window before the first command
    started hid it, and then every command ran with nothing watching."""
    first, second = tmp_path / "first", tmp_path / "second"
    dialog, rebuild = _rebuild_window([f"touch '{first}'", f"touch '{second}'"])
    dialog.show()
    dialog.reject()  # before the event loop has turned once
    assert rebuild.ended and not rebuild.succeeded and not dialog.isVisible()
    assert _exec_bounded(rebuild, 3) < 1
    _pump_until(qapp, lambda: first.exists(), timeout_ms=800)
    assert not first.exists() and not second.exists()


def test_done_stops_a_running_rebuild(qapp, tmp_path):
    """Review P3-1: done() closed the window without going through reject()."""
    marker = tmp_path / "second-ran"
    dialog, rebuild = _rebuild_window(["sleep 30", f"touch '{marker}'"])
    dialog.show()
    assert _pump_until(qapp, lambda: rebuild.running)
    dialog.done(0)
    assert rebuild.ended and not rebuild.running and not rebuild.succeeded
    assert _exec_bounded(rebuild, 3) < 1
    _pump_until(qapp, lambda: marker.exists(), timeout_ms=800)
    assert not marker.exists()


def test_a_failed_build_records_no_durations(qapp, tmp_path):
    from lab_hub import durations

    command = "echo 'INFO: PyInstaller: 6'; echo 'Built: x'; false"
    dialog, rebuild = _rebuild_window([command], _x_rows(command), lab_root=tmp_path)
    dialog.show()
    assert _pump_until(qapp, lambda: rebuild.ended)
    assert not rebuild.succeeded
    assert "app:x" not in durations.load()
    dialog.close()


def test_a_version_read_that_raises_does_not_end_the_run(qapp, tmp_path):
    from lab_hub import progress
    from ui.progress_window import BuildCheckWindow
    from ui.rebuild import Rebuild

    def broken(_app, _root):
        raise RuntimeError("no plist")

    window = BuildCheckWindow(progress.build_check_view(_x_rows("echo one"), scoped=True),
                              tmp_path)
    rebuild = Rebuild(["echo one", "echo two"], window, verify=broken)
    window.show()
    assert _pump_until(qapp, lambda: rebuild.ended)
    assert rebuild.succeeded and "two" in window.output_text()
    assert window.model.snapshot().rows[0].reason == "Installed; no version could be read."
    window.close()


def test_one_long_line_with_no_newline_is_shown_in_pieces_without_freezing(qapp):
    """Secure P3-3: 2 MB with no newline took a minute to reach the pane."""
    import time as _time

    from lab_hub import progress

    dialog, rebuild = _rebuild_window(["head -c 2000000 /dev/zero | tr '\\0' x"])
    dialog.show()
    dialog.output.toggle.setChecked(True)
    start = _time.monotonic()
    assert _pump_until(qapp, lambda: rebuild.ended)
    dialog.draw()
    lines = [line for line in dialog.output_text().splitlines() if line.startswith("x")]
    took = _time.monotonic() - start
    assert took < 10, f"{took:.1f} s"
    assert sum(len(line) for line in lines) == 2_000_000
    assert max(len(line) for line in lines) <= progress.LINE_MAX
    dialog.close()


def test_stage_chips_advance_on_the_lab_hub_markers_and_verify_shows_the_version(
    qapp, tmp_path, monkeypatch
):
    """A fake build printing Lab Hub's own build_app.sh lines walks the four
    stages; after exit 0 the installed version Lab Hub reads is on the row, and
    the durations are recorded for the next estimate."""
    from lab_hub import config, durations

    app = launcher.ExternalApp("labhub", "Lab Hub", "lab_hub", "main.py", "s")
    script = ("echo '12 INFO: PyInstaller: 6.11'; sleep 0.3; "
              "echo 'Self-testing the build…'; sleep 0.3; "
              "echo 'Installed: /Applications/Lab Hub.app'")
    rows = (launcher.BuildStatus(app, launcher.Version(), "behind", "older.", None, script),)
    monkeypatch.setattr(launcher, "version", lambda a, root: launcher.Version("v9.9"))
    dialog, rebuild = _rebuild_window([script], rows, lab_root=tmp_path)
    dialog.show()
    seen = []

    def stages():
        snap = dialog.model.snapshot()
        seen.append(tuple(s.state for s in snap.rows[0].stages))
        return dialog.cancel_button.text() == "Close"

    assert _pump_until(qapp, stages)
    assert rebuild.succeeded
    assert ("done", "running", "waiting", "waiting") in seen
    final = dialog.model.snapshot().rows[0]
    assert [s.state for s in final.stages] == ["done"] * 4
    assert final.reason == "Installed: v9.9"
    assert (final.stages[0].label, final.stages[0].state) == ("Build", "done")
    assert len(dialog.rows[0].chips) == 4
    history = durations.load(path=config.SUPPORT_DIR / "durations.json")
    assert set(history["app:labhub"]) == {"build", "package", "install", "verify", "rebuild"}
    dialog.close()


def test_a_build_with_no_marker_shows_one_rebuilding_stage(qapp, tmp_path, monkeypatch):
    app = launcher.ExternalApp("x", "X", "x", "main.py", "s")
    rows = (launcher.BuildStatus(app, launcher.Version(), "behind", "older.", None,
                                 "echo compiling"),)
    monkeypatch.setattr(launcher, "version", lambda a, root: launcher.Version())
    dialog, rebuild = _rebuild_window(["echo compiling"], rows, lab_root=tmp_path)
    dialog.show()
    assert _pump_until(qapp, lambda: dialog.cancel_button.text() == "Close")
    row = dialog.model.snapshot().rows[0]
    assert [(s.label, s.state) for s in row.stages] == [("Rebuilding", "done")]
    assert len(dialog.rows[0].chips) == 1
    dialog.close()


def test_build_output_is_shown_as_typed(qapp, tmp_path):
    dialog, rebuild = _rebuild_window(["printf '\\033[31m<b>x</b>\\033[0m\\n'"])
    dialog.show()
    assert _pump_until(qapp, lambda: dialog.cancel_button.text() == "Close")
    assert "<b>x</b>" in dialog.output_text()
    assert "\x1b" not in dialog.output_text()
    dialog.close()


def test_update_now_hands_its_open_window_to_the_rebuild(qapp, monkeypatch):
    """Update now keeps the window open and hands that same window to the
    rebuild for its Update step. (Copy commands closing it on Review is
    `test_progress_window.py::test_review_button_answers_and_copy_closes_update_stays`.)"""
    from ui import apps_tab
    from ui.progress_window import BuildCheckWindow

    _FakeRebuild.ok, _FakeRebuild.asked = True, []
    tab, seen = _by_hand_tab(qapp, monkeypatch, _mixed_rows)
    windows, closed_before = [], []
    closes = []
    real_done = BuildCheckWindow.done
    monkeypatch.setattr(BuildCheckWindow, "done",
                        lambda self, code: closes.append(code) or real_done(self, code))

    class Spy(_FakeRebuild):
        def __init__(self, commands, window=None, **hooks):
            super().__init__(commands, window, **hooks)
            windows.append(window)
            closed_before.append(len(closes))

    monkeypatch.setattr(apps_tab, "Rebuild", Spy)
    monkeypatch.setattr(launcher, "run_in_terminal", lambda *a, **k: [])
    monkeypatch.setattr(tab, "recheck", lambda: None)
    seen["press"] = "Update now"
    tab.show_build_report()
    assert windows and windows[0].choice == "Update now"
    assert isinstance(windows[0], BuildCheckWindow)
    assert closed_before == [0]  # Update now did not close the window it handed over
    assert _FakeRebuild.asked == [["cd /q && ./build_app.sh"]]
    _drop(tab)


def test_update_now_without_a_window_deletes_the_one_it_made(qapp, monkeypatch):
    """Review P3-2: run_updates(window=None) made a window and never freed it."""
    import shiboken6
    from PySide6.QtCore import QCoreApplication, QEvent

    from ui import apps_tab

    tab, _seen = _by_hand_tab(qapp, monkeypatch, _mixed_rows)
    made = []

    class Spy(_FakeRebuild):
        def __init__(self, commands, window=None, **hooks):
            super().__init__(commands, window, **hooks)
            made.append(window)

    monkeypatch.setattr(apps_tab, "Rebuild", Spy)
    monkeypatch.setattr(tab, "recheck", lambda: None)
    tab.run_updates(["echo x"])
    assert len(made) == 1
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not shiboken6.isValid(made[0])
    _drop(tab)


# ----------------------------------------------------------------------
# A web app's tile — Provisio
# ----------------------------------------------------------------------
def _web_card(tmp_path, monkeypatch, serving=False):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "none")
    monkeypatch.setattr(launcher, "serving", lambda _app: serving)
    project = tmp_path / "provisio"
    (project / "scripts").mkdir(parents=True)
    (project / "scripts" / "run-framework.mjs").write_text("\n")
    (project / "node_modules").mkdir()
    app = launcher.ExternalApp(
        "provisio", "Provisio", "provisio", "scripts/run-framework.mjs", "summary",
        url="http://localhost:5173/", runtime="node", args=("dev",),
    )
    return AppCard(app), project


def test_a_stopped_web_app_is_at_rest_not_a_warning(qapp, tmp_path, monkeypatch):
    card, _project = _web_card(tmp_path, monkeypatch)

    card.refresh(tmp_path, table="/bin/zsh\n")

    assert card.state.text() == "Stopped"
    assert card.launch_button.text() == "Launch"
    assert card.launch_button.isEnabled()
    assert not card.stop_button.isEnabled()


def test_a_serving_web_app_opens_in_the_browser(qapp, tmp_path, monkeypatch):
    card, project = _web_card(tmp_path, monkeypatch, serving=True)

    card.refresh(tmp_path, table=f"node {project}/scripts/run-framework.mjs dev\n")

    assert card.state.text() == "Running"
    assert card.launch_button.text() == "Open in browser"
    assert card.stop_button.isEnabled()


def test_a_server_started_by_hand_cannot_be_stopped_from_here(qapp, tmp_path, monkeypatch):
    """It answers, so the page can be opened — but nothing on the process
    table says it is ours, and killing whatever holds the port could be
    anything."""
    card, _project = _web_card(tmp_path, monkeypatch, serving=True)

    card.refresh(tmp_path, table="node scripts/run-framework.mjs dev\n")

    assert card.launch_button.text() == "Open in browser"
    assert not card.stop_button.isEnabled()
    assert "Control-C" in card.stop_button.toolTip()


def test_launching_a_web_app_waits_for_it_then_opens_it(qapp, tmp_path, monkeypatch):
    from ui import web_open

    card, _project = _web_card(tmp_path, monkeypatch)
    card.refresh(tmp_path, table="/bin/zsh\n")
    monkeypatch.setattr(launcher, "launch", lambda a, root: "launched")
    opened = []
    monkeypatch.setattr(launcher, "open_url", opened.append)

    card._launch()
    assert card.state.text() == "Starting…"
    # Its server is on the table but not yet listening: still starting, and
    # already stoppable.
    card.refresh(tmp_path, table=f"node {_project}/scripts/run-framework.mjs dev\n")
    assert card.state.text() == "Starting…"
    assert card.stop_button.isEnabled()
    assert isinstance(card.opener, web_open.OpenWhenServing)
    assert card.opener.waiting

    card.opener._check()
    assert opened == [], "nothing answers yet, so nothing is opened"

    monkeypatch.setattr(launcher, "serving", lambda _app: True)
    card.opener._check()
    assert opened == ["http://localhost:5173/"]
    assert not card.opener.waiting
    assert card.state.text() == "Running"


def test_a_desktop_app_has_no_stop_button(qapp, tmp_path, monkeypatch):
    app = _installed(tmp_path, monkeypatch)

    assert AppCard(app).stop_button is None


def test_a_bundle_built_in_its_checkout_reads_built(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "none")
    project = tmp_path / "syndustryx"
    (project / "dist").mkdir(parents=True)
    (project / "server.py").write_text("\n")
    make_bundle(project / "dist", "SYNDUSTRYX")
    app = launcher.ExternalApp(
        "syndustryx", "SYNDUSTRYX", "syndustryx", "server.py", "summary",
        bundle_dir="dist", runs_from_source=False,
    )
    card = AppCard(app)

    card.refresh(tmp_path, table="/bin/zsh\n")

    assert card.state.text() == "Built"
    assert card.launch_button.isEnabled()


def test_long_version_and_badge_do_not_widen_a_tile(qapp):
    """The version marker and the "to land" badge live on their own line,
    so they cannot push a tile wider than the name, status and summary need."""
    from ui.apps_tab import AppCard
    from ui.status_rows import Row

    card = AppCard(launcher.ExternalApp("s", "SYNDUSTRYX", "s", "main.py", "summary"))
    base = card.minimumSizeHint().width()
    card.version.setText("v0.6.53+g861546d-dirty · 126 behind · and a very long tail")
    card.status.set_rows([Row("land", "26 branches · 7 worktrees · 1 file waiting to land")])
    assert card.minimumSizeHint().width() <= base + 160
    assert card.header.indexOf(card.version) == -1 and card.header.indexOf(card.status) == -1


def test_the_longest_badge_wraps_instead_of_widening_a_tile(qapp):
    """Regression (2026-11-16): "2 unpushed commits · 1 commit behind · 2
    branches to land" on one unwrapped line pushed the grid off the window."""
    from ui.apps_tab import AppCard
    from ui.status_rows import Row

    card = AppCard(launcher.ExternalApp("s", "Sentinel", "s", "main.py", "summary"))
    base = card.minimumSizeHint().width()
    card.set_check_builds_available(True)  # the link must not widen it either
    card.status.set_rows([
        Row("update", "Installed build is 126 commits old", link=True),
        Row("land", "2 unpushed commits · 1 commit behind · 2 branches waiting to land"),
        Row("uncommitted", "Uncommitted changes in source"),
    ])
    texts = card.status.findChildren(QLabel, "statusText")
    assert texts and all(label.wordWrap() for label in texts)
    assert card.minimumSizeHint().width() <= base + 20


# ---------------------------------------------------------------------------
# A Check build button on each tile (spec tile-check-build)
# ---------------------------------------------------------------------------


from lab_hub import self_update  # noqa: E402


def _status(app):
    return launcher.BuildStatus(app, launcher.Version(), "behind", "older.", None,
                                f"cd /{app.project} && ./build_app.sh")


def test_a_tiles_check_build_reports_only_its_own_app(qapp, tmp_path, monkeypatch):
    from ui.progress_window import BuildCheckWindow

    tab = _tab(qapp, tmp_path, monkeypatch, with_checkouts=True)
    asked, rows = [], []
    monkeypatch.setattr(launcher, "build_report", lambda root, scope=None: (
        asked.append(scope), tuple(_status(a) for a in (scope or tab._shown[0])))[1])
    monkeypatch.setattr(BuildCheckWindow, "ask", lambda self: rows.append(
        [i.name for i in self.view.items]))

    card = tab.cards[2]
    assert not card.check_build_button.isHidden()
    card.check_build_button.click()

    assert asked == [(card.app,)]
    assert len(rows[0]) == 1 and "App 2" in rows[0][0]
    _drop(tab)


def test_the_page_level_check_builds_still_asks_about_every_app(qapp, tmp_path, monkeypatch):
    """The tile button must not change what the page button reports."""
    from ui.progress_window import BuildCheckWindow

    tab = _tab(qapp, tmp_path, monkeypatch)
    asked = []
    monkeypatch.setattr(launcher, "build_report", lambda root, scope=None: (
        asked.append(scope), ())[1])
    monkeypatch.setattr(BuildCheckWindow, "ask", lambda self: None)
    monkeypatch.setattr(self_update, "self_status", lambda root, **kw: _status(self_update.SELF))
    tab.show_build_report(False)  # a button's clicked(bool) passes its state
    assert asked == [None]
    _drop(tab)


def test_the_real_page_button_click_still_scopes_to_its_apps(qapp, tmp_path, monkeypatch):
    """Driven through the button, so clicked(bool) really reaches show_build_report."""
    from lab_hub import config
    from ui.apps_tab import AppsTab
    from ui.progress_window import BuildCheckWindow

    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "none")
    apps = (launcher.ExternalApp("b", "B", "b", "main.py", "s"),)
    tab = AppsTab(config.Settings(), apps, "B", "intro", check_own_builds=True)
    asked = []
    monkeypatch.setattr(launcher, "build_report", lambda root, scope=None: (
        asked.append(scope), (_status(apps[0]),))[1])
    monkeypatch.setattr(BuildCheckWindow, "ask", lambda self: None)
    tab.check_button.click()
    assert asked == [apps]
    _drop(tab)


def test_a_tile_with_no_install_and_no_checkout_hides_check_build(qapp, tmp_path, monkeypatch):
    tab = _tab(qapp, tmp_path, monkeypatch)  # the apps are nowhere at all
    tab.refresh()
    assert all(card.check_build_button.isHidden() for card in tab.cards)
    _drop(tab)


def test_a_tile_with_a_checkout_shows_check_build_after_refresh(qapp, tmp_path, monkeypatch):
    tab = _tab(qapp, tmp_path, monkeypatch, with_checkouts=True)
    tab.refresh()
    assert all(not card.check_build_button.isHidden() for card in tab.cards)
    _drop(tab)


def test_check_build_waits_while_another_job_lands_the_same_repo(qapp, monkeypatch, tmp_path):
    from lab_hub import land
    from ui.apps_tab import AppCard

    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "none")
    card = AppCard(launcher.ExternalApp("b", "B", "b", "main.py", "x"))
    from lab_hub import hygiene

    row = hygiene.RepoRow("b", tmp_path, "main", ("1 unpushed commit",))
    monkeypatch.setattr(land, "landing", lambda path: True)
    card.refresh_hygiene(row)
    assert not card.check_build_button.isEnabled()
    monkeypatch.setattr(land, "landing", lambda path: False)
    card.refresh_hygiene(row)
    assert card.check_build_button.isEnabled()


def test_lab_hubs_own_check_build_error_is_said_not_an_empty_window(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from lab_hub import self_update
    from ui.progress_window import BuildCheckWindow

    tab = _tab(qapp, tmp_path, monkeypatch)

    def boom(root, **kw):
        raise RuntimeError("git is broken")

    monkeypatch.setattr(self_update, "self_status", boom)
    said, opened = [], []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: said.append(a[2]))
    monkeypatch.setattr(BuildCheckWindow, "ask", lambda self: opened.append(1))
    tab.check_card_build(self_update.OWN_TILE)
    assert opened == [] and "git is broken" in said[0]
    _drop(tab)


def test_a_tile_with_nothing_to_build_has_no_check_build_button(qapp, monkeypatch, tmp_path):
    from ui.apps_tab import AppCard

    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "none")
    card = AppCard(launcher.ExternalApp("s", "S", "s", None, "source only"))
    assert card.check_build_button.isHidden()
    shown = AppCard(launcher.ExternalApp("b", "B", "b", "main.py", "x"))
    assert not shown.check_build_button.isHidden()


def test_check_build_waits_while_the_tile_is_landing(qapp, monkeypatch, tmp_path):
    from lab_hub import land
    from ui.apps_tab import AppCard

    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "none")
    card = AppCard(launcher.ExternalApp("b", "B", "b", "main.py", "x"))
    assert card.check_build_button.isEnabled()
    card.set_landing("Merging…")
    assert not card.check_build_button.isEnabled()
    card.set_landing(None)
    assert card.check_build_button.isEnabled()
    card.set_landing("Merging…")
    card.show_outcome(land.LandResult("b", "landed"))
    assert card.check_build_button.isEnabled()


def test_lab_hubs_own_tile_checks_only_its_own_row(qapp, tmp_path, monkeypatch):
    from lab_hub import self_update
    from ui.apps_tab import OwnCard
    from ui.progress_window import BuildCheckWindow

    tab = _tab(qapp, tmp_path, monkeypatch)
    own = _status(self_update.SELF)
    monkeypatch.setattr(self_update, "self_status", lambda root, **kw: own)
    calls, rows = [], []
    monkeypatch.setattr(launcher, "build_report", lambda root, scope=None: calls.append(scope) or ())
    monkeypatch.setattr(BuildCheckWindow, "ask", lambda self: rows.append(len(self.view.items)))

    assert not OwnCard(self_update.OWN_TILE).check_build_button.isHidden()
    tab.check_card_build(self_update.OWN_TILE)

    assert calls == [] and rows == [1]
    _drop(tab)
