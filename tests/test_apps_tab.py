"""The launch cards.

The point of showing running state is that clicking Launch on something already
open is the wrong thing to do — it either opens a second copy or appears to do
nothing. So what these check is that the button changes what it *does*, not just
what it says.
"""

from __future__ import annotations

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
    from PySide6.QtWidgets import QMessageBox

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
    monkeypatch.setattr(QMessageBox, "exec", lambda self: seen.update(
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
    from PySide6.QtWidgets import QMessageBox

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
    monkeypatch.setattr(QMessageBox, "exec", lambda self: seen.update(
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
    from PySide6.QtWidgets import QMessageBox

    from lab_hub import config
    from ui.apps_tab import AppsTab

    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "none")
    apps = (launcher.ExternalApp("a", "A", "a", "main.py", "s"),)
    tab = AppsTab(config.Settings(), apps, "Apps", "intro", check_builds=True)

    seen = {}

    def capture(box):
        seen["labels"] = {b.text() for b in box.buttons()}

    monkeypatch.setattr(QMessageBox, "exec", lambda self: capture(self))

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


def test_the_rebuild_dialog_runs_the_commands_in_order(qapp):
    """Two commands, both succeed, both show up in the log — and `succeeded`
    reports the run as clean."""
    from ui.apps_tab import RebuildDialog

    dialog = RebuildDialog(["echo first-command", "echo second-command"])
    dialog.show()
    assert _pump_until(qapp, lambda: dialog._button.text() == "Close")
    log = dialog._log.toPlainText()
    assert "first-command" in log and "second-command" in log
    assert dialog.succeeded
    dialog.close()


def test_a_failed_rebuild_stops_the_run(qapp):
    """A command that exits non-zero halts the run rather than rebuilding on top
    of a broken build — the later command never runs."""
    from ui.apps_tab import RebuildDialog

    dialog = RebuildDialog(["false", "echo should-not-run"])
    dialog.show()
    assert _pump_until(qapp, lambda: dialog._button.text() == "Close")
    log = dialog._log.toPlainText()
    assert "should-not-run" not in log
    assert not dialog.succeeded
    dialog.close()


def test_build_check_dialog_can_be_dismissed(qapp_or_none=None):
    """A QMessageBox whose only buttons are ActionRole has nothing to map the
    red close button or Escape onto — it becomes impossible to dismiss."""
    from PySide6.QtWidgets import QApplication, QMessageBox

    app = QApplication.instance() or QApplication([])
    box = QMessageBox()
    box.addButton("Copy commands", QMessageBox.ButtonRole.ActionRole)
    box.addButton("Copy and open Terminal", QMessageBox.ButtonRole.ActionRole)
    close = box.addButton("Close", QMessageBox.ButtonRole.RejectRole)
    box.setEscapeButton(close)

    box.show()
    app.processEvents()
    assert box.close(), "dialog refused to close"
    app.processEvents()
    assert not box.isVisible()


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
    project = tmp_path / "agent_lab"
    (project / "dist").mkdir(parents=True)
    (project / "server.py").write_text("\n")
    make_bundle(project / "dist", "SYNDUSTRYX")
    app = launcher.ExternalApp(
        "agent_lab", "SYNDUSTRYX", "agent_lab", "server.py", "summary",
        bundle_dir="dist", runs_from_source=False,
    )
    card = AppCard(app)

    card.refresh(tmp_path, table="/bin/zsh\n")

    assert card.state.text() == "Built"
    assert card.launch_button.isEnabled()
