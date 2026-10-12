"""The Apps tab: one card per standalone app, each with a Launch button."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QProcess, QProcessEnvironment, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from lab_hub import config, launcher

from . import theme
from .tiles import (  # noqa: F401 - the layout constants are re-exported
    GRID_MAX_WIDTH,
    POLL_MS,
    SUMMARY_HEIGHT,
    TILE_MIN_WIDTH,
    Tile,
    TilePage,
    arrange_tiles,
    columns_for,
)
from .web_open import OpenWhenServing

STATE_LABELS = {
    "installed": ("Installed", "stateOk"),
    # Built inside its own checkout and never installed — SYNDUSTRYX's builder
    # stops at `dist/`. Nothing wrong with it, so not a warning.
    "built": ("Built", "stateOk"),
    "source": ("Source only", "stateWarn"),
    # A web app's checkout is how it always runs, so a stopped server is the
    # resting state rather than something to warn about.
    "server": ("Stopped", "hint"),
    "missing": ("Not found", "stateBad"),
}

# While an app is running, that is the more useful thing to say — where it
# would have been started from is answered by the path underneath either way.
RUNNING_LABEL = ("Running", "stateOk")

# The two states between pressing Launch and knowing whether it worked. A
# child that dies during startup used to look exactly like one that started
# fine — the button greyed for a moment and nothing else ever happened.
STARTING_LABEL = ("Starting…", "stateWarn")
FAILED_LABEL = ("Did not start", "stateBad")

# Started, and there is no way from here to tell whether it came up. Not the
# same claim as *Did not start*, and the difference is the whole point: a stub
# bundle with no checkout to watch leaves nothing durable in the process table,
# so a launch that worked looks exactly like one that died. Guessing "failed"
# there is what put a red notice under a running Sentinel.
UNCONFIRMED_LABEL = ("Started", "stateWarn")
UNCONFIRMED_TOOLTIP = (
    "Lab Hub started it and cannot see whether it came up — this app leaves "
    "nothing behind to watch for. Check your Dock or ⌘-Tab."
)

# How long to wait for a launched app to appear in the process table before
# saying it never came up. Generous on purpose: a cold PyInstaller bundle
# unpacks itself before it execs, and a false "Did not start" would be worse
# than a slow "Starting…". A source launch is already death-watched inside
# `launcher.launch`, which reports the exit code outright.
LAUNCH_CONFIRM_SECONDS = 20.0
# A dev server compiles before it listens, and the first start after its
# dependencies change pre-bundles them too. Provisio's answered in ~5s, back
# when it was a web app.
SERVER_CONFIRM_SECONDS = 60.0

# How long *Did not start* stays on the tile. It is a notice about one launch,
# not a property of the app, so it has to expire: leaving it up meant a tile
# still reading "Did not start" long after the app had been opened and closed
# again by hand. Refresh (Cmd+R) clears it outright.
FAILURE_NOTICE_SECONDS = 60.0

# Reserved on every tile, even where there is nothing to say. A line that
# appeared on one card only would push its Launch button out of line with the
# rest of the row, and the tiles sit side by side in a grid.
SERVICE_HEIGHT = 18


class AppCard(Tile):
    """Name, what it does, where it will be started from, and a Launch button."""

    launched = Signal(str)
    start_failed = Signal(str)

    def __init__(self, app: launcher.ExternalApp, parent=None) -> None:
        super().__init__(app.name, app.summary, parent)
        self.app = app
        self.lab_root = config.DEFAULT_LAB_ROOT
        self.running = False
        # Set while a launch is in flight, cleared the moment the app shows up
        # in the process table — or turned into a failure notice if it never does.
        self._pending_since: float | None = None
        self._failed_at: float | None = None
        # Set instead of `_failed_at` when the launch could not be watched.
        self._unconfirmed_at: float | None = None

        # Which build the button would actually open. Resolved once here and on
        # Refresh, never on the poll: it shells out to `git rev-list`, and a
        # subprocess every three seconds to restate a number that changes on
        # rebuild would be pure waste.
        self.version = QLabel()
        self.version.setObjectName("hint")
        self.header.insertWidget(1, self.version)

        self.launch_button = QPushButton("Launch")
        self.launch_button.setObjectName("primary")
        self.launch_button.clicked.connect(self._launch)
        self.buttons.addWidget(self.launch_button, 1)

        # Only a web app has one. A server has no window to close, so without
        # this one started from here would run until the Mac restarts.
        self.stop_button: QPushButton | None = None
        self.opener: OpenWhenServing | None = None
        if app.served:
            self.stop_button = QPushButton("Stop")
            self.stop_button.clicked.connect(self._stop)
            self.buttons.addWidget(self.stop_button)
            # Its window is a browser tab, opened the moment the server answers
            # rather than on the next three-second poll.
            self.opener = OpenWhenServing(app, self)
            self.opener.opened.connect(lambda _message: self.refresh(self.lab_root))
            self.opener.opened.connect(self.launched)

        # An app's windowless background copy, reported separately from the app
        # itself. SONAR's engine runs under launchd around the clock and is the
        # data the app exists to collect, but it is not an open window and the
        # button above must not act as though it were.
        self.service = QLabel()
        self.service.setObjectName("hint")
        self.service.setFixedHeight(SERVICE_HEIGHT)
        if app.service is not None:
            self.service.setToolTip(
                f"{app.name} keeps working with no window open: a background "
                "process that goes on collecting and settling its data around "
                "the clock. It runs whether or not you open the app, and Launch "
                "neither starts nor stops it — that is its launchd agent's job."
            )
        self.extra.addWidget(self.service)

        self.refresh_version(self.lab_root)

    # ------------------------------------------------------------------
    def refresh(self, lab_root: Path, table: str | None = None) -> None:
        self.lab_root = lab_root
        ready = launcher.readiness(self.app, lab_root)
        here = (
            launcher.presence(self.app, lab_root, table)
            if ready.state != "missing"
            else launcher.Presence(window=False, service=False)
        )
        self.running = here.window
        self.refresh_version(lab_root)
        self._update_service(here.service)
        self._settle_pending_launch()
        self._update_stop(table)

        label, style = self._state_label(ready)
        self.set_state(
            label, style, UNCONFIRMED_TOOLTIP if self._showing_unconfirmed() else ""
        )

        # A reason it cannot run beats a path it would have run from.
        self.detail.setText(ready.problem or ready.detail)
        self._update_button(ready)

    def _state_label(self, ready: launcher.Readiness) -> tuple[str, str]:
        if self.running:
            return RUNNING_LABEL
        if self._pending_since is not None:
            return STARTING_LABEL
        if self._showing_failure():
            return FAILED_LABEL
        if self._showing_unconfirmed():
            return UNCONFIRMED_LABEL
        return STATE_LABELS[ready.state]

    def refresh_version(self, lab_root: Path) -> None:
        """Re-read which build this tile would launch.

        Says nothing at all when there is no evidence — a frozen bundle with no
        stamp in it cannot be described by the checkout's number, because that
        is not the code that would open.
        """
        found = launcher.version(self.app, lab_root)
        if not found.known:
            self.version.setText("")
            self.version.setToolTip(
                f"Lab Hub cannot tell which build of {self.app.name} is installed."
            )
            self.restyle(self.version, "hint")
            return

        # An installed build older than its source is the answer to the question
        # the number exists for. Saying only the number would be true and
        # useless: the button would still open the old one without a word.
        suffix = f" · {found.behind} behind" if found.stale else ""
        self.version.setText(found.text + suffix)
        self.version.setToolTip(
            f"{self.app.name} {found.text} — {found.detail}."
            + (
                f" Its checkout is {found.behind} commits further on, so Launch "
                "opens the older build until it is rebuilt and reinstalled."
                if found.stale
                else ""
            )
        )
        self.restyle(self.version, "stateWarn" if found.stale else "hint")

    def _update_service(self, running: bool) -> None:
        """Report the background copy, for the apps that have one."""
        if self.app.service is None:
            self.service.setText("")
            return
        self.service.setText(
            f"{self.app.service} · {'running' if running else 'stopped'}"
        )
        self.restyle(self.service, "stateOk" if running else "hint")

    def _showing_failure(self) -> bool:
        """Whether the last launch's failure notice is still worth showing."""
        if self._failed_at is None:
            return False
        if time.monotonic() - self._failed_at > FAILURE_NOTICE_SECONDS:
            self._failed_at = None
            return False
        return True

    def _showing_unconfirmed(self) -> bool:
        """Whether the last launch is still unaccounted for. Expires alike."""
        if self._unconfirmed_at is None:
            return False
        if time.monotonic() - self._unconfirmed_at > FAILURE_NOTICE_SECONDS:
            self._unconfirmed_at = None
            return False
        return True

    def forget_failure(self) -> None:
        """Drop the launch notices. Refresh asks for the state as it is now."""
        self._failed_at = None
        self._unconfirmed_at = None

    def _settle_pending_launch(self) -> None:
        """Decide whether a launch we started has come up, or never will."""
        if self.running:
            self._pending_since = None
            self._failed_at = None
            self._unconfirmed_at = None
            return
        if self._pending_since is None:
            return
        window = SERVER_CONFIRM_SECONDS if self.app.served else LAUNCH_CONFIRM_SECONDS
        if time.monotonic() - self._pending_since <= window:
            return
        self._pending_since = None

        # Silence is only evidence when there was something to listen for.
        # Where there was not, say so plainly instead of accusing the app of
        # dying: it is usually up, and a red "Did not start" under a running
        # window is worse than admitting the tile cannot tell.
        if not launcher.launch_is_observable(self.app, self.lab_root):
            self._unconfirmed_at = time.monotonic()
            return

        self._failed_at = time.monotonic()
        self.start_failed.emit(
            f"{self.app.name} was started but never came up. "
            f"Look in {launcher.startup_log_hint(self.app, self.lab_root)}"
        )

    def _update_button(self, ready: launcher.Readiness) -> None:
        if self._pending_since is not None and not self.running:
            # Pressing again here would start a second copy of something that
            # is already on its way up.
            self.launch_button.setText("Starting…")
            self.launch_button.setToolTip("Waiting for it to come up")
            self.launch_button.setEnabled(False)
            return

        if not self.running:
            self.launch_button.setText("Launch")
            # Checked before the press, not discovered during it: a checkout
            # with no interpreter used to offer a working-looking button that
            # could only ever produce a dialog. Left enabled after an
            # unconfirmed launch on purpose — these apps hand off to the copy
            # already running rather than opening a second window.
            self.launch_button.setToolTip(
                ready.problem
                or (UNCONFIRMED_TOOLTIP if self._showing_unconfirmed() else "")
                or (
                    f"Start its local server and open {self.app.url} once it answers"
                    if self.app.served else ""
                )
            )
            self.launch_button.setEnabled(ready.ok)
            return

        if self.app.served:
            # The browser is its window, and that can always be opened.
            self.launch_button.setText("Open in browser")
            self.launch_button.setToolTip(f"Already serving — open {self.app.url}")
            self.launch_button.setEnabled(True)
            return

        if launcher.can_bring_to_front(self.app, self.lab_root):
            self.launch_button.setText("Bring to front")
            self.launch_button.setToolTip("Already open — raise its window")
            self.launch_button.setEnabled(True)
        else:
            # Nothing to address it by, so offering a button that cannot work
            # would be worse than saying plainly that it is already open.
            self.launch_button.setText("Running")
            self.launch_button.setToolTip(
                "Already open. Lab Hub can only raise apps installed in "
                "/Applications — switch to it from the Dock or with ⌘-Tab."
            )
            self.launch_button.setEnabled(False)

    def _update_stop(self, table: str | None) -> None:
        """Offer Stop only for a server this card can actually recognise."""
        if self.stop_button is None:
            return
        marker = launcher.checkout_marker(self.app, self.lab_root)
        snapshot = launcher.process_table() if table is None else table
        ours = marker is not None and any(
            marker in line for line in snapshot.splitlines()
        )
        self.stop_button.setEnabled(ours)
        self.stop_button.setToolTip(
            "Stop its local server"
            if ours else
            "Something is serving it that Lab Hub did not start — stop it "
            "where it was started (Control-C in its Terminal window)."
            if self.running else
            "Not running"
        )

    def _stop(self) -> None:
        try:
            message = launcher.stop(self.app, self.lab_root)
        except launcher.LaunchError as error:
            QMessageBox.warning(self, f"Could not stop {self.app.name}", str(error))
            return
        self._pending_since = None
        if self.opener is not None:
            self.opener.stop()
        self.refresh(self.lab_root)
        self.launched.emit(message)

    def _launch(self) -> None:
        raising = self.running
        action = launcher.bring_to_front if raising else launcher.launch
        try:
            message = action(self.app, self.lab_root)
        except launcher.LaunchError as error:
            self._pending_since = None
            QMessageBox.warning(self, f"Could not launch {self.app.name}", str(error))
            return
        if not raising:
            # `launch` returning only means the app was started, not that it
            # stayed up. The card watches for it to appear from here.
            self._pending_since = time.monotonic()
            self._failed_at = None
            self._unconfirmed_at = None
            if self.opener is not None:
                self.opener.start(SERVER_CONFIRM_SECONDS)
            self.refresh(self.lab_root)
        self.launched.emit(message)


LAUNCHPAD_INTRO = (
    "These run in their own window, as their own process — quitting Lab Hub "
    "leaves them running. Each starts from its installed app if there is one, "
    "and from its source checkout otherwise."
)


class RebuildDialog(QDialog):
    """Run the rebuild commands in-app, one after another, showing their output.

    The build report used to only *hand over* the commands, on the reasoning
    that a rebuild takes minutes and you want somewhere to watch it and stop it.
    This keeps both of those — a live log and a Cancel button that kills the
    running build — without leaving Lab Hub, which is the whole point of a
    button that says "Update now". The Terminal handoff stays for anyone who
    would rather drive it themselves.

    Each command is its own `cd … && ./build_app.sh`, so they are independent;
    one that fails stops the run rather than rebuilding on top of a broken
    build. They run through a login shell (`$SHELL -lc`) because that is the
    environment the Terminal handoff always assumed — the build scripts reach
    for `pyinstaller`, `uv` and friends that a bundle's bare PATH would miss —
    and with `child_env()` so a rebuild is not poisoned by our own Qt runtime,
    exactly as a real launch is.
    """

    def __init__(self, commands: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Update apps")
        self._commands = list(commands)
        self._index = 0
        self._cancelled = False
        self._failed = False

        layout = QVBoxLayout(self)
        self._status = QLabel()
        layout.addWidget(self._status)
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMinimumSize(560, 320)
        self._log.setObjectName("hint")
        layout.addWidget(self._log)
        self._button = QPushButton("Cancel")
        self._button.clicked.connect(self._on_button)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self._button)
        layout.addLayout(row)

        self._proc = QProcess(self)
        env = QProcessEnvironment()
        for name, value in launcher.child_env().items():
            env.insert(name, value)
        self._proc.setProcessEnvironment(env)
        self._proc.setProcessChannelMode(
            QProcess.ProcessChannelMode.MergedChannels
        )
        self._proc.readyReadStandardOutput.connect(self._read)
        self._proc.finished.connect(self._finished)

        # Start once the dialog is actually on screen, so the first line of
        # output has somewhere to land.
        QTimer.singleShot(0, self._start_next)

    @property
    def succeeded(self) -> bool:
        return not self._cancelled and not self._failed and self._index >= len(
            self._commands
        )

    def _shell(self) -> str:
        return os.environ.get("SHELL", "/bin/zsh")

    def _start_next(self) -> None:
        if self._cancelled or self._index >= len(self._commands):
            self._all_done()
            return
        command = self._commands[self._index]
        self._append(f"$ {command}\n")
        self._status.setText(
            f"Rebuilding {self._index + 1} of {len(self._commands)}… "
            "this takes a few minutes."
        )
        self._proc.start(self._shell(), ["-lc", command])

    def _read(self) -> None:
        chunk = bytes(self._proc.readAllStandardOutput()).decode(errors="replace")
        self._append(chunk)

    def _append(self, text: str) -> None:
        self._log.moveCursor(self._log.textCursor().MoveOperation.End)
        self._log.insertPlainText(text)
        bar = self._log.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _finished(self, code: int, _status: object) -> None:
        if self._cancelled:
            self._all_done()
            return
        if code != 0:
            self._failed = True
            self._append(f"\n[stopped — a rebuild exited with code {code}]\n")
            self._all_done()
            return
        self._index += 1
        self._start_next()

    def _on_button(self) -> None:
        # One button, two jobs: it cancels a running build and closes a
        # finished one. There is never a moment where both apply.
        if self._proc.state() != QProcess.ProcessState.NotRunning:
            self._cancelled = True
            self._append("\n[cancelled — the running build was stopped]\n")
            self._proc.kill()
        else:
            self.accept()

    def _all_done(self) -> None:
        if self._cancelled:
            self._status.setText("Cancelled. Some apps may still be out of date.")
        elif self._failed:
            self._status.setText("A rebuild failed — see the log above.")
        else:
            self._status.setText("Done. Every app was rebuilt and reinstalled.")
        self._button.setText("Close")

    def closeEvent(self, event: object) -> None:  # noqa: N802 (Qt override)
        # Closing the window mid-build must not leave a detached rebuild
        # running with nothing watching it.
        if self._proc.state() != QProcess.ProcessState.NotRunning:
            self._cancelled = True
            self._proc.kill()
            self._proc.waitForFinished(3000)
        super().closeEvent(event)


# Which apps a page shows: a fixed tuple, or a callable read again on every
# Refresh — `lambda: launcher.SUITES` — so an app added to apps.toml gets its
# tile without a restart.
AppSource = tuple[launcher.ExternalApp, ...] | Callable[[], tuple[launcher.ExternalApp, ...]]


def resolve_apps(source: AppSource) -> tuple[launcher.ExternalApp, ...]:
    return tuple(source() if callable(source) else source)


class AppsTab(TilePage):
    """A page of launch cards. Used for the launchpad and for one-off apps."""

    launched = Signal(str)
    start_failed = Signal(str)

    def __init__(
        self,
        settings: config.Settings,
        apps: AppSource | None = None,
        title: str = "Standalone apps",
        intro: str = LAUNCHPAD_INTRO,
        sections: tuple[tuple[str, str, AppSource], ...] | None = None,
        check_builds: bool = False,
        check_own_builds: bool = False,
        parent=None,
    ) -> None:
        super().__init__(POLL_MS, parent)
        self.settings = settings

        # One page, several headed sections. Suites, the sync companions and the
        # small utilities are different kinds of thing and reading them as one
        # undifferentiated wall of tiles was the problem with the flat grid.
        if apps is None:
            apps = lambda: launcher.LAUNCHPAD  # noqa: E731
        groups = sections if sections is not None else ((title, intro, apps),)
        self._sources: list[AppSource] = [source for _t, _i, source in groups]
        for group_title, group_intro, _source in groups:
            self.column.addWidget(theme.section_title(group_title))
            if group_intro:
                self.column.addWidget(theme.hint(group_intro))
            self.add_grid()
        # Tests and the resize logic reach for the first grid by name.
        self.grid = self.grids[0][0]
        self._shown: list[tuple[launcher.ExternalApp, ...]] = []
        self._sync_cards()
        self._arrange(1)

        # Which apps the build check reports: None is every registered app (the
        # launchpad's question), otherwise only this tab's own.
        self._own_builds = check_own_builds and not check_builds
        self.check_button: QPushButton | None = None
        # One button reports every registered app, and it is the launchpad's:
        # the question it answers — "am I opening the newest of everything?" —
        # is not per-tab, and a copy of it on every tab would be noise.
        if check_builds:
            check = QPushButton("Check builds")
            check.setToolTip(
                "Compare every installed app against its source checkout"
            )
            check.clicked.connect(self.show_build_report)
            self.buttons.addWidget(check)
            self.check_button = check
        elif check_own_builds:
            # Backstage and the two sync companions have no launchpad tile, so
            # their own tab carries the same check and Update now — scoped to
            # the apps on that tab, so the launchpad's all-apps report is still
            # the only one of those.
            count = len(self._build_apps)
            check = QPushButton("Check build" if count == 1 else "Check builds")
            check.setToolTip(
                "Compare the installed app against its source checkout, and "
                "rebuild it if it is behind"
                if count == 1 else
                "Compare these installed apps against their source checkouts, "
                "and rebuild any that are behind"
            )
            check.clicked.connect(self.show_build_report)
            self.buttons.addWidget(check)
            self.check_button = check
        self.finish()

        self.refresh()

    @property
    def cards(self) -> list[AppCard]:
        return self.tiles()

    @property
    def _build_apps(self) -> tuple[launcher.ExternalApp, ...] | None:
        if not self._own_builds:
            return None
        return tuple(app for group in self._shown for app in group)

    def _sync_cards(self) -> bool:
        """Rebuild a section's tiles when its app list has changed."""
        wanted = [resolve_apps(source) for source in self._sources]
        if wanted == self._shown:
            return False
        for index, apps in enumerate(wanted):
            if index < len(self._shown) and apps == self._shown[index]:
                continue
            cards = []
            for app in apps:
                card = AppCard(app)
                card.launched.connect(self.launched)
                card.start_failed.connect(self.start_failed)
                cards.append(card)
            self.set_tiles(index, cards)
        self._shown = wanted
        return True

    def apply_settings(self, settings: config.Settings) -> None:
        self.settings = settings
        lab_root = settings.resolved_lab_root()
        for card in self.cards:
            card.refresh_version(lab_root)
        self.refresh()

    def show_build_report(self) -> None:
        """Say, for every registered app, whether it is the newest available.

        A frozen bundle is only as new as its last build, and two different
        things can leave it behind: commits since the build, and edits never
        committed. The commit count sees the first and cannot see the second,
        so both are checked here.
        """
        root = self.settings.resolved_lab_root()
        report = (launcher.build_report(root) if self._build_apps is None
                  else launcher.build_report(root, self._build_apps))
        behind = [row for row in report if row.needs_rebuild]
        unknown = [row for row in report if row.verdict == "unknown"]

        if behind and len(report) == 1:
            headline = (
                f"{report[0].app.name} would open something older than its source."
            )
        elif behind:
            headline = (
                f"{len(behind)} of {len(report)} apps would open something older "
                "than their source."
            )
        elif unknown:
            headline = (
                f"Nothing is out of date, but {len(unknown)} could not be checked."
            )
        elif self._build_apps is None:
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

        commands = [row.command for row in behind if row.command]
        if commands:
            lines.append("")
            lines.append("Run this to bring it up to date:")
            lines.extend(f"  {command}" for command in commands)

        box = QMessageBox(self)
        box.setWindowTitle("Build check")
        box.setText(headline)
        box.setInformativeText("\n".join(lines))
        box.setIcon(
            QMessageBox.Icon.Warning if behind else QMessageBox.Icon.Information
        )
        # Update now runs the rebuilds here; the two copy buttons still hand the
        # commands off for anyone who would rather drive them in a terminal. A
        # rebuild replaces an installed app and takes minutes — the difference
        # the buttons make is between "there is a command" and "it is running".
        update = copy = terminal = None
        if commands:
            update = box.addButton(
                "Update now", QMessageBox.ButtonRole.AcceptRole
            )
            copy = box.addButton("Copy commands", QMessageBox.ButtonRole.ActionRole)
            terminal = box.addButton(
                "Copy and open Terminal", QMessageBox.ButtonRole.ActionRole
            )
        # A QMessageBox whose only buttons are ActionRole has nothing to map the
        # red close button or Escape onto, so both become dead and the dialog
        # cannot be dismissed at all. Give it an explicit way out.
        close = box.addButton("Close", QMessageBox.ButtonRole.RejectRole)
        box.setEscapeButton(close)
        box.setDefaultButton(update or close)
        box.exec()
        clicked = box.clickedButton()
        if clicked is not None and clicked in (copy, terminal):
            self.copy_commands(commands)
        if terminal is not None and clicked is terminal:
            # The commands each begin with their own `cd`, so where the window
            # opens does not change what they do — it only has to be somewhere
            # sensible to land.
            launcher.open_terminal(self.settings.resolved_lab_root())
        if update is not None and clicked is update:
            self.run_updates(commands)

    def run_updates(self, commands: list[str]) -> None:
        """Rebuild and reinstall the out-of-date apps without leaving Lab Hub.

        Whatever the outcome, re-check versions afterwards so the tiles stop
        saying "behind" the moment a rebuild lands — a cancelled or partial run
        simply leaves the ones it did not reach still saying so, which is true.
        """
        dialog = RebuildDialog(commands, self)
        dialog.exec()
        self.recheck()
        if dialog.succeeded:
            self.launched.emit(
                f"Rebuilt and reinstalled {len(commands)} app"
                f"{'' if len(commands) == 1 else 's'}."
            )

    def copy_commands(self, commands: list[str]) -> None:
        """Put the rebuild commands on the clipboard, one per line."""
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText("\n".join(commands))
        self.launched.emit(
            f"Copied {len(commands)} rebuild command"
            f"{'' if len(commands) == 1 else 's'} to the clipboard."
        )

    def recheck(self) -> None:
        """What Refresh asks of this tab: pick up added or removed apps,
        forget stale notices, then look."""
        self._sync_cards()
        lab_root = self.settings.resolved_lab_root()
        for card in self.cards:
            card.forget_failure()
            card.refresh_version(lab_root)
        self.refresh()

    def refresh(self) -> None:
        lab_root = self.settings.resolved_lab_root()
        table = launcher.process_table()  # one snapshot, shared by every card
        for card in self.cards:
            card.refresh(lab_root, table)
