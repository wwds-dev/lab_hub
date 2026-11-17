"""The Apps tab: one card per standalone app, each with a Launch button."""

from __future__ import annotations

import html
import os
import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QProcess, QProcessEnvironment, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from lab_hub import config, hygiene, land, launcher

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
from .lander import Lander
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

def plain_tip(text: str) -> str:
    """A tooltip that shows `text` as typed. Qt renders a tooltip as rich text
    when it looks like HTML, and this text is git, pytest and Claude output."""
    return "<qt>" + html.escape(text).replace("\n", "<br>") + "</qt>"


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
    land_requested = Signal(object)  # this card
    review_requested = Signal(object)  # this card

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
        self.version.setWordWrap(True)

        # Work not yet committed, pushed or merged: read from git_autosync's
        # report, so it costs a file read and never a git call on this thread.
        self.hygiene = QLabel()
        self.hygiene.setObjectName("hint")
        # Wrapped, and stacked under the version below: "2 unpushed commits ·
        # 1 commit behind · 2 branches to land" on one unwrappable line sets a
        # minimum width wider than a tile column and pushes the grid off-window.
        self.hygiene.setWordWrap(True)
        self.hygiene.setTextFormat(Qt.TextFormat.PlainText)  # the report is a file

        # Version and badge get a line of their own under the name. On the
        # name's line, "v0.6.53+g861546d · 1 behind" plus "3 to land" plus the
        # status chip set a minimum width wider than a tile column, and the
        # grid pushed the third column off the window.
        self.meta = QVBoxLayout()
        self.meta.setSpacing(2)
        self.meta.addWidget(self.version)
        self.meta.addWidget(self.hygiene)
        self.heading.addLayout(self.meta)

        self.launch_button = QPushButton("Launch")
        self.launch_button.setObjectName("primary")
        self.launch_button.clicked.connect(self._launch)
        self.buttons.addWidget(self.launch_button, 1)

        # Land: the one action for the badge above. Shown only while this app's
        # repo has work that has not landed; the outcome is stated on the tile
        # (spec land-from-tiles), never left in a log.
        self.hygiene_row: hygiene.RepoRow | None = None
        self._landing = False
        self._before: tuple | None = None
        self._before_failed = False
        self._land_allowed = True
        self.land_button = QPushButton("Land")
        self.land_button.setObjectName("land")
        self.land_button.setToolTip(
            "Commit this app's open work, merge its branches into the main "
            "branch and push. You confirm once; nothing is forced."
        )
        self.land_button.clicked.connect(lambda: self.land_requested.emit(self))
        self.land_button.hide()
        self.buttons.addWidget(self.land_button)
        self.outcome = QLabel()
        self.outcome.setObjectName("hint")
        self.outcome.setWordWrap(True)
        self.outcome.setTextFormat(Qt.TextFormat.PlainText)  # git/pytest/Claude output
        self.outcome.hide()
        self.extra.addWidget(self.outcome)
        self._repo_path: Path | None = None
        self.terminal_button = QPushButton("Open in Terminal")
        self.terminal_button.setFlat(True)
        self.terminal_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.terminal_button.setToolTip("Open a Terminal window in this repo to look at it yourself")
        self.terminal_button.clicked.connect(self._open_terminal)
        self.terminal_button.hide()
        self.extra.addWidget(self.terminal_button)
        self.review_button = QPushButton()
        self.review_button.setFlat(True)
        self.review_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.review_button.clicked.connect(lambda: self.review_requested.emit(self))
        self.review_button.hide()
        self.extra.addWidget(self.review_button)

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
                + (f" {found.detail}." if found.detail else "")
            )
            self.restyle(self.version, "hint")
            return

        # An installed build older than its source is the answer to the question
        # the number exists for. Saying only the number would be true and
        # useless: the button would still open the old one without a word.
        suffix = f" · {found.behind} behind" if found.stale else ""
        self.version.setText(found.marker + suffix)
        commit = (
            f" Commit {found.commit}{' with uncommitted changes' if found.dirty else ''}."
            if found.commit
            else f" Commit unknown: {found.commit_note or 'no evidence'}."
        )
        self.version.setToolTip(
            f"{self.app.name} {found.text} — {found.detail}.{commit}"
            + (
                " Whether the working checkout has moved past it cannot be told: its "
                "commit is not in that checkout's history."
                if found.behind_unknown
                else ""
            )
            + (
                f" The working checkout is {found.behind} commits further on, so Launch "
                "opens the older build until it is rebuilt and reinstalled."
                if found.stale
                else ""
            )
        )
        self.restyle(self.version, "stateWarn" if found.stale else "hint")

    def refresh_hygiene(self, row: hygiene.RepoRow | None) -> None:
        """Say how much of this app's work has not landed yet, or nothing."""
        self.hygiene_row = row
        if row is not None:
            self._repo_path = row.path
        self._sync_land()
        if row is None or not row.badge:
            self.hygiene.setText("")
            self.hygiene.setToolTip("")
            self.restyle(self.hygiene, "hint")
            return
        self.hygiene.setText(row.badge)
        self.hygiene.setToolTip(plain_tip(
            f"{self.app.name} ({row.branch or 'unknown branch'}): {row.detail}. "
            "Press Land to commit, merge and push it."
        ))
        self.restyle(self.hygiene, "stateWarn")

    def _sync_land(self) -> None:
        """Land shows while there is work to land, and not while one is running."""
        row = self.hygiene_row
        show = row is not None and row.needs_attention
        self.land_button.setVisible(show)
        if not self._landing:
            self.land_button.setText("Land")
            self.land_button.setEnabled(
                self._land_allowed and not (show and land.landing(row.path))
            )

    def set_land_enabled(self, allowed: bool) -> None:
        """The page disables every Land while any one is running."""
        self._land_allowed = allowed
        self._sync_land()

    def set_landing(self, line: str | None) -> None:
        """Show progress on the tile; None ends it."""
        if line is None:
            # Cancelled before anything ran: put back what the tile said before.
            if self._landing and self._before is not None:
                text, style, tip, shown, review = self._before
                failed = self._before_failed
                self.outcome.setText(text)
                self.outcome.setToolTip(tip)
                self.restyle(self.outcome, style)
                self.outcome.setVisible(shown)
                self.review_button.setVisible(review)
                self.terminal_button.setVisible(failed)
            self._before = None
            self._landing = False
            self._sync_land()
            return
        if not self._landing:
            self._before = (self.outcome.text(), self.outcome.objectName(),
                            self.outcome.toolTip(), not self.outcome.isHidden(),
                            not self.review_button.isHidden())
            self._before_failed = not self.terminal_button.isHidden()
        self._landing = True
        self.land_button.setText("Landing…")
        self.land_button.setEnabled(False)
        self.land_button.show()
        self.review_button.hide()
        self.terminal_button.hide()
        self.outcome.setText(line if len(line) <= 120 else line[:119] + "…")
        self.outcome.setToolTip(plain_tip(line))
        self.restyle(self.outcome, "hint")
        self.outcome.show()

    def show_outcome(self, result: land.LandResult) -> None:
        """Say how Land went, in words, on the tile."""
        self._landing = False
        self._before = None
        self.outcome.setText(result.line)
        self.outcome.setToolTip(plain_tip("\n".join(result.notes)) if result.notes else "")
        self.restyle(
            self.outcome,
            {"landed": "stateOk", "not_landed": "stateBad"}.get(result.state, "hint"),
        )
        self.outcome.show()
        self.terminal_button.setVisible(result.state == "not_landed")
        if result.remaining:
            n = result.remaining
            self.review_button.setText(
                f"{n} branch{'es' if n != 1 else ''} need{'s' if n == 1 else ''} your decision — review"
            )
            self.review_button.show()
        else:
            self.review_button.hide()
        self._sync_land()

    def clear_outcome(self) -> None:
        """Refresh (⌘R) forgets how the last Land went; the badge says what is left."""
        if self._landing:
            return
        self._before = None
        self.outcome.hide()
        self.review_button.hide()
        self.terminal_button.hide()

    def _open_terminal(self) -> None:
        if self._repo_path is not None:
            launcher.open_terminal(self._repo_path)

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
        # Land runs off the UI thread, one job at a time per page. A repo is
        # also claimed in `lab_hub.land`, so two pages cannot land the same one.
        self.lander = Lander(self)
        self.lander.planned.connect(self._land_planned)
        self.lander.progress.connect(self._land_progress)
        self.lander.repo_done.connect(self._land_repo_done)
        self.lander.finished.connect(self._land_finished)
        # Cards Land was asked on, by repo name, held from the click: a hygiene
        # refresh or a rebuilt tile mid-Land must not lose the outcome.
        self._landing_cards: dict[str, AppCard] = {}
        self._recheck_after = False
        app = QApplication.instance()
        if app is not None:
            # Quitting mid-Land ends a running Claude or test step and waits a
            # moment, so a repo is not left in a half-merged state.
            app.aboutToQuit.connect(self.lander.shutdown)

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
        self.land_all_button: QPushButton | None = None
        self._hygiene_proc: QProcess | None = None
        self._hygiene_stamp: tuple[int, int] | None = None
        self._hygiene_report: hygiene.Report | None = None
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
            land_all = QPushButton("Land all")
            land_all.setToolTip(
                "Land every repo that has work not yet committed, pushed or "
                "merged. You confirm once; a repo that fails is reported and "
                "the rest carry on."
            )
            land_all.setEnabled(False)
            land_all.clicked.connect(self.land_all)
            self.buttons.addWidget(land_all)
            self.land_all_button = land_all
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
        self.stop_land_button = QPushButton("Stop landing")
        self.stop_land_button.setToolTip(
            "End the running Claude Code or test run and skip everything after "
            "it. Work already landed stays landed."
        )
        self.stop_land_button.clicked.connect(self.lander.stop)
        self.stop_land_button.hide()
        self.buttons.addWidget(self.stop_land_button)
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
                card.land_requested.connect(self.land_card)
                card.review_requested.connect(self.review_card)
                card.set_land_enabled(not self.lander.busy)
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

        # Update now runs only what can run without a terminal. An installer
        # that refuses one (Provisio's) is listed for the owner to run, and an
        # app with no known build script is named rather than dropped.
        commands = [row.command for row in behind if row.runs_in_app]
        by_hand = [row.command for row in behind if row.by_hand and row.command]
        forward = [row.command for row in behind if row.forward and row.command]
        no_command = [row for row in behind if not row.command]
        if commands:
            lines.append("")
            lines.append("Update now runs:")
            lines.extend(f"  {command}" for command in commands)
        if by_hand:
            names = ", ".join(row.app.name for row in behind
                              if row.by_hand and row.command)
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
        if commands or by_hand:
            update = box.addButton(
                "Update now", QMessageBox.ButtonRole.AcceptRole
            )
        if commands or by_hand or forward:
            copy = box.addButton("Copy commands", QMessageBox.ButtonRole.ActionRole)
        # A report with only a release-clone move to show opens no Terminal:
        # the owner chose show-and-copy for it (spec release-root-behind §5.1).
        if commands or by_hand:
            terminal = box.addButton(
                "Copy and open Terminal", QMessageBox.ButtonRole.ActionRole
            )
        # An app Lab Hub cannot rebuild still gets a way forward: its folder in
        # Terminal, where its own build guide applies.
        folders = [r.project for r in no_command if r.project is not None]
        open_folder = None
        if folders:
            open_folder = box.addButton("Open in Terminal",
                                        QMessageBox.ButtonRole.ActionRole)
            open_folder.setToolTip("Open a Terminal window in the project folder of "
                                   + ", ".join(r.app.name for r in no_command))
        # A QMessageBox whose only buttons are ActionRole has nothing to map the
        # red close button or Escape onto, so both become dead and the dialog
        # cannot be dismissed at all. Give it an explicit way out.
        close = box.addButton("Close", QMessageBox.ButtonRole.RejectRole)
        box.setEscapeButton(close)
        box.setDefaultButton(update or close)
        box.exec()
        clicked = box.clickedButton()
        if clicked is not None and clicked in (copy, terminal):
            self.copy_commands(commands + by_hand + forward)
        if terminal is not None and clicked is terminal:
            # The commands each begin with their own `cd`, so where the window
            # opens does not change what they do — it only has to be somewhere
            # sensible to land.
            launcher.open_terminal(self.settings.resolved_lab_root())
        if open_folder is not None and clicked is open_folder:
            for folder in folders:
                launcher.open_terminal(folder)
        if update is not None and clicked is update:
            self.run_updates(commands, by_hand)

    def run_updates(self, commands: list[str], by_hand: list[str] | None = None) -> None:
        """Rebuild and reinstall the out-of-date apps without leaving Lab Hub,
        then hand the installers that need a terminal to Terminal.

        Whatever the outcome, re-check versions afterwards so the tiles stop
        saying "behind" the moment a rebuild lands — a cancelled or partial run
        simply leaves the ones it did not reach still saying so, which is true.
        A run that failed or was cancelled opens no Terminal window: like the
        rebuilds themselves, it stops rather than going on. The windows are not
        watched; Refresh shows the result once the owner has answered there.
        The Terminal commands are checked before the first rebuild starts, and a
        Terminal step that fails is shown to the owner rather than lost.
        """
        by_hand = list(by_hand or [])
        try:
            launcher.check_terminal_commands(by_hand)
        except ValueError as error:
            QMessageBox.warning(self, "Update now",
                                f"Nothing was started: {error}")
            return
        said = []
        if commands:
            dialog = RebuildDialog(commands, self)
            dialog.exec()
            self.recheck()
            if not dialog.succeeded:
                if by_hand:
                    self.launched.emit(
                        "No Terminal windows opened because the rebuild did "
                        "not finish."
                    )
                return
            said.append(
                f"Rebuilt and reinstalled {len(commands)} app"
                f"{'' if len(commands) == 1 else 's'}."
            )
        if by_hand:
            try:
                launcher.run_in_terminal(by_hand)
            except (launcher.LaunchError, OSError, ValueError) as error:
                QMessageBox.warning(self, "Update now",
                                    "Could not open Terminal. " + str(error))
                return
            said.append(
                f"Opened Terminal for {len(by_hand)} installer"
                f"{'' if len(by_hand) == 1 else 's'}: confirm there, "
                "then press Refresh."
            )
        if said:
            self.launched.emit(" ".join(said))

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
            card.clear_outcome()
            card.refresh_version(lab_root)
        self.refresh()
        self.refresh_repos()

    def hygiene_report(self) -> hygiene.Report | None:
        """The last repo-hygiene report, re-read only when its file changed."""
        path = hygiene.report_path(self.settings.resolved_lab_root())
        try:
            info = path.stat()
            stamp = (info.st_mtime_ns, info.st_size)
        except OSError:
            self._hygiene_stamp, self._hygiene_report = None, None
            return None
        if stamp != self._hygiene_stamp:
            self._hygiene_stamp = stamp
            self._hygiene_report = hygiene.load(path.parent.parent)
        return self._hygiene_report

    def _apply_hygiene(self) -> None:
        lab_root = self.settings.resolved_lab_root()
        report = self.hygiene_report()
        for card in self.cards:
            row = report.for_project(lab_root, card.app.project) if report else None
            card.refresh_hygiene(row)
        self._update_land_controls()

    def refresh_repos(self, force: bool = False) -> None:
        """Recompute the repo report in the background (local git only, no fetch).

        No button and no dialog: the badges and Land all simply update when it
        finishes. A child process, so the window never waits for ten-odd repos
        with their worktrees.
        """
        if self._hygiene_proc is not None:
            # A check that started before Land finished would show the old
            # state; run once more when it ends.
            self._recheck_after = self._recheck_after or force
            return
        argv = hygiene.command(self.settings.resolved_lab_root())
        if argv is None:
            return
        proc = QProcess(self)
        env = QProcessEnvironment()
        for name, value in launcher.child_env().items():
            env.insert(name, value)
        proc.setProcessEnvironment(env)
        # The report goes to its file; an unread pipe would stall the child.
        proc.setStandardOutputFile(QProcess.nullDevice())
        self._hygiene_proc = proc
        proc.finished.connect(self._repos_checked)
        proc.errorOccurred.connect(lambda _e: self._repos_checked(-1, None))
        proc.start(argv[0], argv[1:])

    def _repos_checked(self, code: int, _status) -> None:
        proc, self._hygiene_proc = self._hygiene_proc, None
        if proc is None:
            return  # errorOccurred and finished can both fire
        proc.deleteLater()
        self._apply_hygiene()
        if self._recheck_after:
            self._recheck_after = False
            self.refresh_repos()

    # -- Land (spec land-from-tiles) -----------------------------------
    def _attention_rows(self) -> list[hygiene.RepoRow]:
        report = self.hygiene_report()
        return [r for r in report.rows if r.needs_attention] if report else []

    def _update_land_controls(self) -> None:
        busy = self.lander.busy
        if self.land_all_button is not None:
            n = len([r for r in self._attention_rows() if not land.landing(r.path)])
            self.land_all_button.setText(f"Land all ({n})" if n else "Land all")
            self.land_all_button.setEnabled(bool(n) and not busy)
        self.stop_land_button.setVisible(self.lander.running)
        for card in self.cards:
            card.set_land_enabled(not busy)

    def _card_for(self, name: str) -> AppCard | None:
        held = self._landing_cards.get(name)
        if held is not None and any(held is card for card in self.cards):
            return held
        for card in self.cards:  # rebuilt since the click: find its replacement
            if card.hygiene_row is not None and card.hygiene_row.name == name:
                return card
        return None

    def land_card(self, card: AppCard) -> None:
        """Land this app's repo: look, confirm once, run."""
        row = card.hygiene_row
        if row is None or not row.needs_attention:
            return
        if self.lander.plan([(row.name, row.path)]):
            self._landing_cards[row.name] = card
            card.set_landing("Looking at the repo…")
            self._update_land_controls()

    def land_all(self) -> None:
        rows = [r for r in self._attention_rows() if not land.landing(r.path)]
        if not rows:
            return
        if self.lander.plan([(r.name, r.path) for r in rows]):
            for row in rows:
                card = self._card_for(row.name)
                if card is not None:
                    self._landing_cards[row.name] = card
                    card.set_landing("Looking at the repo…")
            self._update_land_controls()

    def confirm_land(self, plans: list[land.LandPlan]) -> bool:
        """The one confirmation: what will happen, in words (tests replace this)."""
        todo = [p for p in plans if not p.nothing]
        box = QMessageBox(self)
        box.setWindowTitle("Land")
        box.setTextFormat(Qt.TextFormat.PlainText)  # names and reasons come from files and git
        box.setIcon(QMessageBox.Icon.Question)
        box.setText("\n".join(p.sentence for p in todo))
        notices = [p.claude_notice for p in todo if p.claude_notice]
        box.setInformativeText("\n\n".join(notices) or "Each step is checked again just "
                               "before it runs. Nothing is forced.")
        box.setDetailedText("\n\n".join(p.detail for p in todo))
        go = box.addButton("Land", QMessageBox.ButtonRole.AcceptRole)
        cancel = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)
        box.setEscapeButton(cancel)
        box.exec()
        return box.clickedButton() is go

    def _land_planned(self, plans) -> None:
        try:
            go = all(p.nothing for p in plans) or self.confirm_land(plans)
        except Exception:  # noqa: BLE001 - never leave the tiles on "Looking…"
            go = False
        if not go:
            for plan in plans:
                card = self._card_for(plan.name)
                if card is not None:
                    card.set_landing(None)
            self._landing_cards.clear()
            self._update_land_controls()
            return
        self.lander.run(plans)
        self._update_land_controls()

    def _land_progress(self, name: str, line: str) -> None:
        card = self._card_for(name)
        if card is not None:
            card.set_landing(line.strip())

    def _land_repo_done(self, name: str, result) -> None:
        card = self._card_for(name)
        if card is not None:
            card.show_outcome(result)

    def _land_finished(self, results) -> None:
        self._landing_cards.clear()
        self._update_land_controls()
        self.refresh_repos(force=True)
        if len(results) > 1:
            self.show_land_summary(results)

    def show_land_summary(self, results) -> None:
        """After Land all: how many landed, and why each other one did not."""
        landed = [r for r in results if r.state == "landed"]
        lines = [f"{r.name}: {r.line}" for r in results if r.state != "landed"]
        box = QMessageBox(self)
        box.setWindowTitle("Land all")
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setIcon(QMessageBox.Icon.Warning if lines else QMessageBox.Icon.Information)
        box.setText(f"Landed {len(landed)} of {len(results)} repos.")
        box.setInformativeText("\n".join(lines))
        box.exec()

    def review_card(self, card: AppCard) -> None:
        """The branches Land left for you to decide, for this repo only."""
        row = card.hygiene_row
        if row is None:
            return
        from ui.repo_tidy_dialogs import ReviewDialog

        dialog = ReviewDialog([(row.name, row.path)], self)
        dialog.exec()
        if dialog.changed:
            self.refresh_repos()

    def refresh(self) -> None:
        lab_root = self.settings.resolved_lab_root()
        table = launcher.process_table()  # one snapshot, shared by every card
        for card in self.cards:
            card.refresh(lab_root, table)
        self._apply_hygiene()
