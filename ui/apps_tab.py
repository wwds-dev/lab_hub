"""The Apps tab: one card per standalone app, each with a Launch button."""

from __future__ import annotations

import html
import os
import subprocess
import time
from dataclasses import replace
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QProcess, QProcessEnvironment, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
)

from lab_hub import (claude_resolve, config, discovery, handoff, hygiene, land, land_resolve,
                     launcher, progress, self_update, version)

from . import theme
from .progress_window import BuildCheckWindow, LandWindow
from .rebuild import Rebuild, Skipped
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
from .discovery_banner import SuggestionBanner
from .busy_monitor import BusyMonitor
from .lander import Lander
from .own_verdict import OwnResult, OwnVerdict
from .status_rows import Row, StatusRows, update_text
from .web_open import OpenWhenServing
from .widgets import plain_tip  # noqa: F401 - plain_tip is re-exported: tests and the Land code import it from here

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

# A project with no launch command (spec apps-discovery §7, §12.2). The hint
# goes in the `service` line, which every tile reserves, so these tiles stay
# level with the launchable ones; `detail` keeps showing where the project is.
NO_LAUNCH_HINT = "No launch button: it has no app to open yet."
NO_LAUNCH_TIP = (
    "Lab Hub shows its version and repo state. Add a launch entry to the "
    "registry when it has an app to open."
)
OWN_HINT = "You are using it: it has no Launch button."
ORDER_NOTE = "Run Land all first, then Check builds."
ORDER_TIP = ("Run Land all first, then Check builds: the build check then compares "
             "against the landed code, so nothing it rebuilds is stale a minute later.")
CLOSE_NOT_RECOMMENDED = (
    "Not recommended: this ends running processes. A test run, build or Claude Code "
    "session in this folder loses its work. Waiting until they finish is safer.")
BEHIND_TIP = "A newer build is ready to install: use Check builds."


class AppCard(Tile):
    """Name, what it does, where it will be started from, and a Launch button."""

    launched = Signal(str)
    start_failed = Signal(str)
    land_requested = Signal(object)  # this card
    review_requested = Signal(object)  # this card
    check_builds_requested = Signal()
    check_build_requested = Signal(object)  # this card's app

    def __init__(self, app: launcher.ExternalApp, parent=None) -> None:
        # A name from a README is cut to one line instead of widening the tile.
        super().__init__(app.name, app.summary, parent, elide_name=not app.launchable)
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
        # A VERSION file is the project's own text: shown as typed, never as markup.
        self.version.setTextFormat(Qt.TextFormat.PlainText)

        # One row per fact under the version (spec tile-status-rows): a stale
        # build, work to land (read from git_autosync's report, so a file read
        # and never a git call on this thread), uncommitted changes, or "up to
        # date" when there is evidence for it. Each row wraps, so a long count
        # never widens a tile column and pushes the grid off-window.
        # True only when a comparison with the source actually ran, so "up to
        # date" is never said from a number alone (spec tile-status-rows §2.4).
        self._compared = False
        self._stale_behind = 0
        self._dirty_text = ""
        self._dirty_in_checkout = False
        self.status = StatusRows()
        self.status.link_clicked.connect(self.check_builds_requested)

        # Version and status get lines of their own under the name. On the
        # name's line they set a minimum width wider than a tile column, and
        # the grid pushed the third column off the window.
        self.meta = QVBoxLayout()
        self.meta.setSpacing(2)
        self.meta.addWidget(self.version)
        self.meta.addWidget(self.status)
        self.heading.addLayout(self.meta)

        self.launch_button = QPushButton("Launch")
        self.launch_button.setObjectName("primary")
        self.launch_button.clicked.connect(self._launch)
        self.buttons.addWidget(self.launch_button, 1)
        if not app.launchable:
            # Nothing to start: no button at all, not a disabled one.
            self.launch_button.setVisible(False)

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
        # Check build: this app's row of Check builds, on its own (spec
        # tile-check-build). No button when there is nothing to build, not a
        # disabled one.
        self.check_build_button = QPushButton("Check build")
        self.check_build_button.setToolTip(
            "Compare this app's installed build with its source and rebuild it "
            "if it is behind. Only this app is checked."
        )
        self.check_build_button.clicked.connect(
            lambda: self.check_build_requested.emit(self.app))
        self.check_build_button.setVisible(self._can_check_build())
        self.buttons.addWidget(self.check_build_button)
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
        # The live "busy now" line (spec land-blocker-actions §9.2): who runs in
        # this repo's worktrees, so Land is not started under them. Advice only.
        self.busy_line = QLabel()
        self.busy_line.setObjectName("stateWarn")
        self.busy_line.setWordWrap(True)
        self.busy_line.setTextFormat(Qt.TextFormat.PlainText)  # process names from lsof
        self.busy_line.hide()
        self.extra.addWidget(self.busy_line)
        self._busy_text = ""

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

        if not app.launchable:
            self._init_no_launch()

        self.refresh_version(self.lab_root)

    # ------------------------------------------------------------------
    # A tile with no launch command (spec apps-discovery §4.6, §12.2).
    # ------------------------------------------------------------------
    # What the tile says about itself; Lab Hub's own tile says its own.
    no_launch_hint = NO_LAUNCH_HINT
    name_tip = NO_LAUNCH_TIP

    def _init_no_launch(self) -> None:
        # The left edge, since Launch's stretch is gone: Land and Open in
        # Terminal stay at their own size, and Land lines up with the
        # neighbouring tiles' buttons (the stretch above them pins the row).
        self.buttons.addStretch(1)
        # The state pill would say "Ready" about an app that cannot be run,
        # or draw an orphan marker with nothing in it.
        self.state.hide()
        # The tooltip holds the full name (while it is cut) and the §7 words.
        if self.name_tip:
            self.name.setNote(self.name_tip)
            # A tooltip alone is mouse-only.
            self.name.setAccessibleDescription(self.name_tip)
        # Beside Land rather than under the path, as design 12.2.5 has it, and
        # always visible: without it a tile with nothing to land would have no
        # control at all.
        self.extra.removeWidget(self.terminal_button)
        self.buttons.insertWidget(self.buttons.count() - 1, self.terminal_button)
        self.terminal_button.setVisible(True)

    def _refresh_no_launch(self, lab_root: Path) -> None:
        """What the 3-second poll does for a tile with no launch command: the
        version line and where the project is. No readiness, presence or `ps`:
        there is nothing to start or to find running."""
        self.lab_root = lab_root
        self.running = False
        self.refresh_version(lab_root)
        project = launcher.source_dir(self.app, lab_root)
        self.detail.setText(
            str(project) if project is not None
            else f"no folder at {lab_root / self.app.project}"
        )
        if self._repo_path is None and project is not None:
            self._repo_path = project  # Open in Terminal, before any report names it
        self.service.setText(self.no_launch_hint)
        self.restyle(self.service, "hint")
        if not self._landing:  # a Land in flight hides it until it ends
            self.terminal_button.setVisible(True)

    # ------------------------------------------------------------------
    def refresh(self, lab_root: Path, table: str | None = None) -> None:
        if not self.app.launchable:
            return self._refresh_no_launch(lab_root)
        self.lab_root = lab_root
        ready = launcher.readiness(self.app, lab_root)
        # Nothing installed and no checkout: nothing to check (spec tile-check-build §2.5).
        self.check_build_button.setVisible(self._can_check_build() and ready.state != "missing")
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
        self._compared = found.known and bool(found.commit) and not found.behind_unknown
        self._dirty_in_checkout = found.origin == "checkout"
        self._stale_behind = found.behind if found.known and found.stale else 0
        self._dirty_text = (
            ("Uncommitted changes in source" if found.origin == "checkout"
             else "Built from uncommitted changes")
            if found.known and found.commit and found.dirty else ""
        )
        self.restyle(self.version, "hint")
        if not found.known:
            self.version.setText("")
            self.version.setToolTip(plain_tip(
                f"Lab Hub cannot tell which build of {self.app.name} is installed."
                + (f" {found.detail}." if found.detail else "")
            ))
            self._sync_status()
            return

        # The line is only the ID. An installed build older than its source is
        # still the answer to the question the number exists for, so it gets a
        # status row of its own (spec tile-status-rows) rather than a suffix.
        self.version.setText(found.marker.removesuffix("-dirty"))
        commit = (
            f" Commit {found.commit}{' with uncommitted changes' if found.dirty else ''}."
            if found.commit
            else f" Commit unknown: {found.commit_note or 'no evidence'}."
        )
        self.version.setToolTip(plain_tip(
            f"{self.app.name} {found.text} — {found.detail}.{commit}"
            + (
                " Whether the working checkout has moved past it cannot be told: its "
                "commit is not in that checkout's history."
                if found.behind_unknown
                else ""
            )
            + (
                f" The working checkout is {launcher.state.commits_further(found.behind)}, so Launch "
                "opens the older build until it is rebuilt and reinstalled."
                if found.stale
                else ""
            )
        ))
        self._update_tip = (
            f"The working checkout is {launcher.state.commits_further(found.behind)}, so Launch "
            "opens the older build until it is rebuilt and reinstalled."
        )
        self._sync_status()

    _update_tip = ""

    def _can_check_build(self) -> bool:
        """Whether Check builds has a row for this app (it lists launchable apps)."""
        return self.app.launchable

    def _sync_check_build(self) -> None:
        """One job per repo: no build check from the tile while it is landing."""
        row = self.hygiene_row
        claimed = row is not None and land.landing(row.path)  # another card or page is landing it
        self.check_build_button.setEnabled(not (self._landing or claimed))

    def set_check_builds_available(self, available: bool) -> None:
        """The update row links to Check builds only on a page that has it."""
        self.status.set_link_available(available)

    def _status_rows(self) -> list[Row]:
        """What the status block says, from evidence already on the tile."""
        rows: list[Row] = []
        if self._stale_behind:
            rows.append(Row("update", update_text(self._stale_behind),
                            self._update_tip, link=True))
        row = self.hygiene_row
        if row is not None and row.needs_attention:
            tip = (f"{self.app.name} ({row.branch or 'unknown branch'}): {row.detail}. "
                   "Press Land to commit, merge and push it.")
            if row.error:
                rows.append(Row("unreadable", "Repo not readable", tip))
            elif row.badge:
                rows.append(Row("land", row.badge.removesuffix(" to land") + " waiting to land", tip))
        # A checkout's uncommitted files are already in the "waiting to land" row.
        said = self._dirty_in_checkout and any(r.kind == "land" for r in rows)
        if self._dirty_text and not said:
            rows.append(Row("uncommitted", self._dirty_text,
                            "The build was made from a checkout with changes not yet committed."))
        if (not rows and self._compared and row is not None
                and not row.needs_attention):
            rows.append(Row("clean", "Up to date, nothing to land"))
        return rows

    def _sync_status(self) -> None:
        self.status.set_rows(self._status_rows())

    def refresh_hygiene(self, row: hygiene.RepoRow | None) -> None:
        """Say how much of this app's work has not landed yet, or nothing."""
        self.hygiene_row = row
        if row is not None:
            self._repo_path = row.path
        self._sync_land()
        self._sync_check_build()
        self._sync_status()

    def _sync_land(self) -> None:
        """Land shows while there is work to land, and not while one is running."""
        row = self.hygiene_row
        show = row is not None and row.needs_attention
        self.land_button.setVisible(show)
        self.busy_line.setVisible(show and bool(self._busy_text) and not self._landing)
        if not self._landing:
            count = row.land_count if show else 0
            self.land_button.setText(f"Land ({count})" if count else "Land")
            self.land_button.setEnabled(
                self._land_allowed and not (show and land.landing(row.path))
            )

    def set_busy(self, text: str) -> None:
        """The live line under Land: "" hides it (spec land-blocker-actions §9.2)."""
        self._busy_text = text
        self.busy_line.setText(text)
        self.busy_line.setToolTip(plain_tip(text) if text else "")
        self._sync_land()

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
            self._sync_check_build()
            return
        if not self._landing:
            self._before = (self.outcome.text(), self.outcome.objectName(),
                            self.outcome.toolTip(), not self.outcome.isHidden(),
                            not self.review_button.isHidden())
            self._before_failed = not self.terminal_button.isHidden()
        self._landing = True
        self._busy_text = ""  # stale after the Land; the next check says (review P3-3)
        self.busy_line.hide()  # Land's own steps would show as busy
        self._sync_check_build()
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
        self._sync_check_build()
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
        if not self.app.launchable:  # not reached from refresh; the one place Launch is worded
            self.launch_button.hide()
            return
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
        if not self.app.launchable:
            return
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


class OwnCard(AppCard):
    """Lab Hub's own tile (spec apps-discovery §5, §12.3): the window the owner
    is already in, so it has no Launch, Bring to front, Stop or Update now.

    It is a no-launch card (`self_update.OWN_TILE` has no entry) whose version
    line is the running build, as the window title shows it, and whose verdict
    line is Lab Hub's row in Check builds. The verdict costs git, so it is not
    computed here: `OwnVerdict` does it off the UI thread and the page hands the
    result to `set_verdict`. Until it arrives the line is blank.
    """

    no_launch_hint = OWN_HINT
    name_tip = ""  # the registry advice in NO_LAUNCH_TIP does not apply to Lab Hub
    verdict: QLabel | None = None  # set in __init__; the base __init__ reads the version first
    _result: OwnResult | None = None

    def __init__(self, app: launcher.ExternalApp, parent=None) -> None:
        super().__init__(app, parent)
        self.verdict = QLabel()
        self.verdict.setObjectName("hint")
        self.verdict.setWordWrap(True)
        self.verdict.setTextFormat(Qt.TextFormat.PlainText)
        self.meta.insertWidget(1, self.verdict)
        self.refresh_version(self.lab_root)

    def _can_check_build(self) -> bool:
        return True  # Lab Hub's own row is in Check builds, though it has no Launch

    def set_verdict(self, result: OwnResult | None) -> None:
        self._result = result
        self.refresh_version(self.lab_root)

    def refresh_version(self, lab_root: Path) -> None:
        # `version.info()` is cached for the life of the process (it shells out
        # to git once, for the window title), so this is safe on the poll.
        text = version.version_string()
        tooltip = version.tooltip()
        row = self._result.row if self._result is not None else None
        behind = row is not None and row.verdict == "behind"
        if behind:
            tooltip += f"\n{BEHIND_TIP}"
        # "Behind" is a status row (spec tile-status-rows), not a suffix; a
        # count Lab Hub could not make still says the build is older.
        self._compared = row is not None and self_update.verdict_line(row) == "up to date"
        self._stale_behind = (max(row.version.behind, 0) or -1) if behind else 0
        self._update_tip = BEHIND_TIP
        self._dirty_text = ""
        self.version.setText(text)
        self.version.setToolTip(plain_tip(tooltip))
        self.version.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.restyle(self.version, "hint")
        self._sync_status()
        if self.verdict is None:
            return
        if row is not None:
            # Behind is said once, by the status row above.
            self.verdict.setText("" if behind else self_update.verdict_line(row))
            self.verdict.setToolTip(plain_tip(row.note) if row.note else "")
        else:
            error = self._result.error if self._result is not None else None
            self.verdict.setText("")
            self.verdict.setToolTip(
                plain_tip(f"Could not check Lab Hub's own build: {error}") if error else ""
            )


LAUNCHPAD_INTRO = (
    "These run in their own window, as their own process — quitting Lab Hub "
    "leaves them running. Each starts from its installed app if there is one, "
    "and from its source checkout otherwise."
)


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
    # Lab Hub's own build passed and was staged (a `self_update.Staged`): quit
    # and let the helper install it (spec self-update).
    restart_requested = Signal(object)
    # An Add changed the app list (spec apps-discovery): the window rereads it
    # and every page, the menu bar included, looks again.
    apps_changed = Signal()

    def __init__(
        self,
        settings: config.Settings,
        apps: AppSource | None = None,
        title: str = "Standalone apps",
        intro: str = LAUNCHPAD_INTRO,
        sections: tuple[tuple[str, str, AppSource], ...] | None = None,
        check_builds: bool = False,
        check_own_builds: bool = False,
        discover: bool = False,
        parent=None,
    ) -> None:
        super().__init__(POLL_MS, parent)
        self.settings = settings
        # Land runs off the UI thread, one job at a time per page. A repo is
        # also claimed in `lab_hub.land`, so two pages cannot land the same one.
        self.lander = Lander(self)
        self.lander.planned.connect(self._land_planned)
        self.lander.progress.connect(self._land_progress)
        self.lander.step.connect(self._land_step)
        self.lander.repo_done.connect(self._land_repo_done)
        self.lander.finished.connect(self._land_finished)
        self.lander.held.connect(self._land_held)
        self.busy_monitor = BusyMonitor(self._busy_repos, self)
        self.busy_monitor.updated.connect(self._busy_updated)
        self.busy_monitor.start()
        # Cards Land was asked on, by repo name, held from the click: a hygiene
        # refresh or a rebuilt tile mid-Land must not lose the outcome.
        self._landing_cards: dict[str, AppCard] = {}
        self._clearing: dict[str, str] = {}  # repo -> the row button now running for it
        self._rerun_name = ""  # the repo a row's button cleared, until its Land starts
        # What is running in this process that a restart would end. The main
        # window replaces this with one that looks at every page and tool.
        self.busy_reasons: Callable[[], list[str]] = self._own_busy_reasons
        # Land jobs on every page, for Ask Claude (spec claude-handoff §4.3);
        # the main window replaces it too. Tools running do not count.
        self.land_jobs: Callable[[], list[str]] = self._own_busy_reasons
        # Called when a Land starts or ends here; the main window makes it
        # refresh Ask Claude on every page (review P2-2).
        self.land_state_changed: Callable[[], None] = self.refresh_handoff_buttons
        self._build_window: BuildCheckWindow | None = None  # while Check builds is open
        # The Land window (spec progress-windows): opened after the
        # confirmation, fed from the same signals as the tiles. Closing it
        # only hides it; Show progress brings it back while Land runs.
        self.land_window: LandWindow | None = None
        # True while the running Land is the one `land_window` shows. A later
        # Land that opens no window (one repo, nothing to do) must not feed
        # the finished window of an earlier run.
        self._land_window_owns_run = False
        self._recheck_after = False
        # Lab Hub's own verdict, computed off the UI thread (spec apps-discovery
        # §13.4); the last result is kept so a rebuilt tile can show it at once.
        self._own_verdict = OwnVerdict(self)
        self._own_verdict.ready.connect(self._own_verdict_ready)
        self._own_result: OwnResult | None = None
        app = QApplication.instance()
        if app is not None:
            # Quitting mid-Land ends a running Claude or test step and waits a
            # moment, so a repo is not left in a half-merged state.
            app.aboutToQuit.connect(self.lander.shutdown)
            app.aboutToQuit.connect(self._own_verdict.shutdown)

        # One page, several headed sections. Suites, the sync companions and the
        # small utilities are different kinds of thing and reading them as one
        # undifferentiated wall of tiles was the problem with the flat grid.
        if apps is None:
            apps = lambda: launcher.LAUNCHPAD  # noqa: E731
        groups = sections if sections is not None else ((title, intro, apps),)
        self._sources: list[AppSource] = [source for _t, _i, source in groups]
        # New projects in the lab folder (spec apps-discovery): the first things
        # in the column, above the first title. Only the Apps page asks.
        self.banner: SuggestionBanner | None = None
        self.local_note: QLabel | None = None
        if discover:
            self.local_note = QLabel()
            self.local_note.setObjectName("hint")
            self.local_note.setWordWrap(True)
            self.local_note.setTextFormat(Qt.TextFormat.PlainText)  # a TOML error, a path
            # Selectable, so the path in the tooltip can be copied.
            self.local_note.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.local_note.hide()
            self.column.addWidget(self.local_note)
            self.banner = SuggestionBanner()
            self.banner.add_requested.connect(self._add_suggestion)
            self.banner.not_now_requested.connect(
                lambda s: self._dismiss_suggestion(s, "not_now"))
            self.banner.never_requested.connect(
                lambda s: self._dismiss_suggestion(s, "never"))
            self.column.addWidget(self.banner)
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
        # At startup and on Refresh only (never on the poll): file existence
        # checks, under a millisecond (spec §13.3).
        self._scan()
        self._request_own_verdict()

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
                "Compare every installed app against its source checkout. "
                + ORDER_TIP
            )
            check.clicked.connect(self.show_build_report)
            self.buttons.addWidget(check)
            self.check_button = check
            land_all = QPushButton("Land all")
            land_all.setToolTip(
                "Land every repo that has work not yet committed, pushed or "
                "merged. You confirm once; a repo that fails is reported and "
                "the rest carry on. " + ORDER_TIP
            )
            land_all.setEnabled(False)
            land_all.clicked.connect(self.land_all)
            self.buttons.addWidget(land_all)
            self.land_all_button = land_all
            # Which first (spec land-blocker-actions §9.3).
            self.order_note = QLabel(ORDER_NOTE)
            self.order_note.setObjectName("hint")
            self.order_note.setToolTip(ORDER_TIP)
            self.buttons.addWidget(self.order_note)
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
        # The first tiles were made before the page knew whether it has Check builds.
        for card in self.cards:
            card.set_check_builds_available(self.check_button is not None)
        self.show_land_button = QPushButton("Show progress")
        self.show_land_button.setToolTip("Show the Land window again")
        self.show_land_button.clicked.connect(self.show_land_window)
        self.show_land_button.hide()
        self.buttons.addWidget(self.show_land_button)
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
                card = OwnCard(app) if app == self_update.OWN_TILE else AppCard(app)
                if isinstance(card, OwnCard):
                    card.set_verdict(self._own_result)
                card.launched.connect(self.launched)
                card.start_failed.connect(self.start_failed)
                card.land_requested.connect(self.land_card)
                card.review_requested.connect(self.review_card)
                card.set_land_enabled(not self.lander.busy)
                card.set_check_builds_available(getattr(self, "check_button", None) is not None)
                card.check_builds_requested.connect(self.show_build_report)
                card.check_build_requested.connect(self.check_card_build)
                cards.append(card)
            self.set_tiles(index, cards)
        self._shown = wanted
        return True

    # -- Lab Hub's own verdict (spec apps-discovery §13.4) -------------
    def _request_own_verdict(self) -> None:
        """Ask for Lab Hub's build verdict if this page shows its tile. Not
        from `refresh`: the poll must never cost git."""
        if any(isinstance(card, OwnCard) for card in self.cards):
            self._own_verdict.request(self.settings.resolved_lab_root())

    def _own_verdict_ready(self, result: OwnResult) -> None:
        self._own_result = result
        for card in self.cards:
            if isinstance(card, OwnCard):
                card.set_verdict(result)

    # -- New projects in the lab folder (spec apps-discovery) ----------
    def _scan(self) -> None:
        """Look for projects the page does not list, and say if the local app
        list could not be read. Startup and Refresh only: file existence checks,
        no git, no network."""
        if self.banner is None or self.local_note is None:
            return
        try:
            found = discovery.suggestions(self.settings.resolved_lab_root(), discovery.today())
        except Exception:  # noqa: BLE001
            # The page must never fail on a name or folder it cannot read: ask
            # about nothing this time.
            found = ()
        self.banner.set_suggestions(found)
        note = launcher.registry.local_note
        self.local_note.setText(note or "")
        self.local_note.setToolTip(
            plain_tip(f"{launcher.registry.local_path()}\n{note}") if note else ""
        )
        self.local_note.setVisible(bool(note))

    def rescan(self) -> None:
        """Ask again now, e.g. after Settings gave a hidden project back."""
        self._scan()

    @staticmethod
    def _reason(error: Exception) -> str:
        return str(error).rstrip(". ")

    def _add_suggestion(self, suggestion: discovery.Suggestion) -> None:
        """Add to Apps: write the entry, reread the list, show the tile."""
        assert self.banner is not None
        index = self._row_index(suggestion)
        try:
            discovery.add(suggestion, self.settings.resolved_lab_root())
        except discovery.DiscoveryError as error:
            self.banner.show_error(
                suggestion.folder, f"Could not add {suggestion.name}: {self._reason(error)}."
            )
            return
        # The list now has the project: read it back here (this page may stand
        # alone), then let the window refresh every other page and the menu bar.
        launcher.reload(self.settings.resolved_lab_root())
        self._sync_cards()
        self._scan()
        self._answered(index)
        self.apps_changed.emit()
        # After `apps_changed`: the window's refresh writes its own status line.
        self.launched.emit(f"Added {suggestion.name} to Apps.")
        card = next((c for c in self.cards if c.app.key == suggestion.folder), None)
        area = self.findChild(QScrollArea)
        if card is not None and area is not None:
            # Once the new tile has a place in the layout.
            QTimer.singleShot(0, lambda: area.ensureWidgetVisible(card))

    def _dismiss_suggestion(self, suggestion: discovery.Suggestion, answer: str) -> None:
        """Not now (asked again in 14 days) or Never for this folder."""
        assert self.banner is not None
        index = self._row_index(suggestion)
        try:
            discovery.dismiss(suggestion.folder, answer, discovery.today())
        except discovery.DiscoveryError as error:
            self.banner.show_error(
                suggestion.folder,
                f"Could not save your answer for {suggestion.name}: "
                f"{self._reason(error)}. It will be asked again.",
            )
            return
        self._scan()
        self._answered(index)
        self.launched.emit(
            f"{suggestion.name}: not asked for {discovery.NOT_NOW_DAYS} days."
            if answer == "not_now"
            else f"{suggestion.name} hidden. You can undo this in Settings."
        )

    def _row_index(self, suggestion: discovery.Suggestion) -> int:
        assert self.banner is not None
        return next(
            (i for i, row in enumerate(self.banner.rows) if row.suggestion == suggestion), 0
        )

    def _answered(self, index: int) -> None:
        """Focus follows the answer: the next row's Add to Apps, else the page,
        so the next Tab reaches the first tile button (never dropped to the
        window)."""
        assert self.banner is not None
        if not self.banner.focus_row(index):
            area = self.findChild(QScrollArea)
            if area is not None:
                area.setFocus()

    def apply_settings(self, settings: config.Settings) -> None:
        self.settings = settings
        lab_root = settings.resolved_lab_root()
        for card in self.cards:
            card.refresh_version(lab_root)
        self.refresh()
        # A new lab folder is a Refresh moment: the banner and Lab Hub's verdict
        # were for the old one (Add would otherwise write an entry for a folder
        # that is not there).
        self._scan()
        self._request_own_verdict()

    def check_card_build(self, app: launcher.ExternalApp) -> None:
        """A tile's Check build: the same window, for that one app."""
        self.show_build_report(only=app)

    def show_build_report(self, *_checked, only: launcher.ExternalApp | None = None) -> None:
        """Say, for every registered app, whether it is the newest available.
        With `only`, for that app alone (spec tile-check-build); the extra
        positional is the `clicked(bool)` a button passes.

        A frozen bundle is only as new as its last build, and two different
        things can leave it behind: commits since the build, and edits never
        committed. The commit count sees the first and cannot see the second,
        so both are checked here.
        """
        root = self.settings.resolved_lab_root()
        scope = (only,) if only is not None else self._build_apps
        own_only = only is not None and only == self_update.OWN_TILE
        if own_only:
            report = ()
        elif scope is None:
            report = launcher.build_report(root)
        else:
            report = launcher.build_report(root, scope)
        if own_only or (only is None and self._build_apps is None):
            # The launchpad's report speaks for every app, Lab Hub included,
            # always last (spec self-update §2.1); Lab Hub's own tile asks for
            # that row alone.
            try:
                own = self_update.self_status(root)
                busy = self.busy_reasons()
                if own.runs_in_app and busy:
                    # Said at the review step too (spec §5.2).
                    own = replace(own, note=f"{own.note} Will update after this "
                                            f"finishes: {'; '.join(busy)}.")
                report = (*report, own)
            except Exception as error:  # noqa: BLE001 - its own row must not hide the others
                if own_only:  # nothing else to show: never an empty "all newest" window
                    QMessageBox.warning(self, "Check build",
                                        f"Could not check Lab Hub's own build: {error}")
                    return
                self.launched.emit(f"Could not check Lab Hub's own build: {error}")
        # The words and commands are computed as the message box had them
        # (spec progress-windows §8.7); the window shows them as rows and
        # offers exactly the box's buttons, under the same conditions.
        view = progress.build_check_view(report, scoped=scope is not None)
        commands, by_hand, forward = (list(view.commands), list(view.by_hand),
                                      list(view.forward))
        folders = list(view.folders)
        window = BuildCheckWindow(view, root, self)
        window.copy_requested.connect(self.copy_commands)
        # Ask Claude: each row's folder and command, in the window's names.
        # Keyed as the rows are: `plain` names (review P3-5).
        for row, item in zip(report, view.items):
            name = progress.plain(item.name)
            window.handoff_paths[name] = row.project or launcher.source_dir(row.app, root)
            if item.command:
                window.handoff_commands[name] = item.command
        window.handoff_requested.connect(self._ask_claude_clicked)
        window.set_handoff_busy("; ".join(self.land_jobs()))  # no rebuild yet at Review
        self._build_window = window
        try:
            window.ask()
            clicked = window.choice
            if clicked in ("Copy commands", "Copy and open Terminal"):
                self.copy_commands(commands + by_hand + forward)
            if clicked == "Copy and open Terminal":
                # The commands each begin with their own `cd`, so where the window
                # opens does not change what they do — it only has to be somewhere
                # sensible to land.
                launcher.open_terminal(self.settings.resolved_lab_root())
            if clicked == "Open in Terminal":
                for folder in folders:
                    launcher.open_terminal(folder)
            if clicked == "Update now":
                self.run_updates(commands, by_hand, window=window)
        finally:
            self._build_window = None
            if window.isVisible():
                window.done(0)
            window.deleteLater()

    def run_updates(self, commands: list[str], by_hand: list[str] | None = None,
                    window: BuildCheckWindow | None = None) -> None:
        """Rebuild and reinstall the out-of-date apps without leaving Lab Hub,
        then hand the installers that need a terminal to Terminal.

        Whatever the outcome, re-check versions afterwards so the tiles stop
        saying "behind" the moment a rebuild lands — a cancelled or partial run
        simply leaves the ones it did not reach still saying so, which is true.
        A run in which any rebuild failed, or that was cancelled, opens no
        Terminal window; a failed rebuild no longer ends the run itself (spec
        land-update-gaps §3.2). The windows are not
        watched; Refresh shows the result once the owner has answered there.
        The Terminal commands are checked before the first rebuild starts, and a
        Terminal step that fails is shown to the owner rather than lost.
        The rebuilds run in the Check builds window's Update step.
        """
        by_hand = list(by_hand or [])
        try:
            launcher.check_terminal_commands(by_hand)
        except ValueError as error:
            QMessageBox.warning(self, "Update now",
                                f"Nothing was started: {error}")
            return
        said = []
        built_self = False
        if commands:
            created = window is None
            if created:
                window = BuildCheckWindow(
                    progress.build_check_view((), scoped=True),
                    self.settings.resolved_lab_root(), self)
                window.show()
            restarts = getattr(window.view, "restarts", None)
            try:
                dialog = Rebuild(commands, window, hold=self._hold_for(restarts))
                dialog.exec()
                failed = list(dialog.failed)
                names = ", ".join(window.name_for(c) for c in failed)
            finally:
                if created:  # show_build_report deletes the window it passed in
                    window.deleteLater()
            self.recheck()
            # A failed rebuild no longer ends the run (spec land-update-gaps
            # §3.2): only a cancel or a broken hold check stops it early.
            if not dialog.ran_to_end:
                if by_hand:
                    self.launched.emit(
                        "No Terminal windows opened because the rebuild did "
                        "not finish."
                    )
                return
            built_self = (bool(restarts) and restarts not in getattr(dialog, "skipped", ())
                          and restarts not in failed)
            others = [c for c in commands if c != restarts]
            rebuilt = len([c for c in others if c not in failed])
            if rebuilt:
                said.append(f"Rebuilt and reinstalled {rebuilt} app"
                            f"{'' if rebuilt == 1 else 's'}.")
            if failed:
                said.append(f"{len(failed)} failed ({names}): see Check builds.")
            if restarts and not built_self:
                said.append("Lab Hub itself was not rebuilt.")
            if failed and by_hand:
                said.append("No Terminal windows opened because a rebuild failed.")
                by_hand = []
        elif window is not None and window.isVisible():
            window.done(0)  # nothing to watch here: the installers run in Terminal
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
        if commands and built_self:
            self._restart_on(restarts)

    def _restart_on(self, restarts: str) -> None:
        """Lab Hub's own build passed: copy it out of its snapshot now, checked
        against the commit the command recorded (spec §11), then ask for the
        restart. The shared checkout's state since then does not matter."""
        project = launcher.source_dir(self_update.SELF, self.settings.resolved_lab_root())
        try:
            if project is None:
                raise ValueError("its checkout is gone")
            staged = self_update.stage_build(self_update.planned_commit(restarts, project))
        except (ValueError, OSError, subprocess.SubprocessError) as error:
            QMessageBox.warning(self, "Lab Hub was not restarted",
                                f"The new build was not installed: {error}. "
                                "This copy keeps running.")
            return
        self.restart_requested.emit(staged)

    # -- Ask Claude (spec claude-handoff) ---------------------------------
    def _handoff_jobs(self, window) -> str:
        """The job that keeps Ask Claude off, or "" (spec §4.3)."""
        if isinstance(window, BuildCheckWindow) and window._rebuild_live():
            return "Update now is rebuilding"
        return "; ".join(self.land_jobs())

    def _handoff_forbidden(self) -> list[Path]:
        """Folders a row's command may never add to a session (security P2-1):
        the lab root and every registered app's checkout."""
        root = self.settings.resolved_lab_root()
        apps = (*launcher.SUITES, *launcher.BACKUP_SYNC_APPS, *launcher.UTILITIES,
                *launcher.TOOLS_ONLY_APPS)
        found = [root]
        for app in apps:
            try:
                folder = launcher.source_dir(app, root)
            except Exception:  # noqa: BLE001 - one odd entry must not stop the rest
                folder = None
            if folder is not None:
                found.append(folder)
        return found

    def refresh_handoff_buttons(self) -> None:
        """Ask Claude's enabled state on this page's open windows (spec §4.3)."""
        for window in (self._build_window, self.land_window):
            if window is not None:
                window.set_handoff_busy(self._handoff_jobs(window))

    def _ask_claude_clicked(self) -> None:
        # A bound slot, not a closure over the window: the window is a child
        # that is deleted while the page lives on.
        window = self.sender()
        if window is not None:
            self.ask_claude(window)

    def ask_claude(self, window) -> None:
        """Ask Claude…: group the window's open rows by repo, confirm, and open
        one Claude Code session per ticked repo in Terminal."""
        busy = self._handoff_jobs(window)
        if busy:
            window.set_handoff_busy(busy)
            QMessageBox.information(window, "Ask Claude",
                                    f"Not now: {busy}. Try again when it has finished.")
            return
        where = "Check builds" if isinstance(window, BuildCheckWindow) else "Land"
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            claude = claude_resolve.find_claude()  # runs `claude --version` (review P3-2)
            if claude is None:
                found, unplaced, items = [], [], []
            else:
                found, unplaced = handoff.collect(window.handoff_rows(), window.handoff_paths,
                                                  window.handoff_commands,
                                                  forbidden=self._handoff_forbidden(),
                                                  goals=getattr(window, "handoff_goals", {}))
                listing = land_resolve.cwd_listing() if found else None
                items = []
                for h in found:
                    ctx = handoff.context(h, listing)
                    items.append((h, ctx, handoff.prompt(h, ctx, where)))
        finally:
            QApplication.restoreOverrideCursor()
        if claude is None:
            QMessageBox.warning(window, "Ask Claude",
                                "Claude Code was not found on this Mac. Install it and sign "
                                "in, then try again.")
            return
        if not items:
            # Names on their own line: Qt judges rich text by the first line,
            # so a name that looks like HTML stays plain (security P3-6).
            QMessageBox.information(window, "Ask Claude",
                                    "None of these rows has a folder a session could work in:\n"
                                    + ", ".join(unplaced) + ".")
            return
        chosen = self.confirm_handoff(items, unplaced, window)
        if not chosen:
            return
        busy = self._handoff_jobs(window)  # checked again in the same call as the open
        if busy:
            QMessageBox.information(window, "Ask Claude", f"Nothing opened: {busy}.")
            return
        texts = {h.path: text for h, _ctx, text in items}
        opener = handoff.Launcher(launcher.run_in_terminal, config.SUPPORT_DIR)
        failed, opened = [], []
        for h in chosen:
            try:
                opener.launch(claude, h, texts[h.path])
            except Exception as error:  # noqa: BLE001 - say it; the other repos still open
                failed.append(f"{h.repo}: {error}")
                continue
            opened.append(h.repo)
        if opened:
            window.show_handoff_note(f"Opened Claude Code in Terminal for {', '.join(opened)}. "
                                     "Press Refresh when the session is done.")
            self.refresh()  # spec §3
        if failed:
            QMessageBox.warning(window, "Ask Claude",
                                "Could not open a session for:\n" + "\n".join(failed))

    def confirm_handoff(self, items, unplaced, parent) -> list:
        """The Ask Claude confirmation (tests replace this)."""
        from .handoff_dialog import HandoffDialog

        dialog = HandoffDialog(items, unplaced, parent)
        try:
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
            if dialog.copied is not None:
                parent.show_handoff_note(
                    f"Copied the prompt for {dialog.copied.repo}: paste it into the Claude "
                    "Code session already open there.")
            return dialog.chosen() if accepted else []
        finally:
            dialog.deleteLater()

    def _own_busy_reasons(self) -> list[str]:
        if self.lander.running:
            return ["Land is running"]
        if self.lander.busy:
            return ["Land is reading the repos"]
        return []

    def _hold_for(self, restarts: str | None):
        """Lab Hub's own build waits for anything a restart would end (spec
        §5.2). It builds the commit its row recorded in a snapshot of its own,
        so what a Land did to the shared checkout meanwhile does not matter
        (spec §11); only a checkout that is gone skips it."""
        if not restarts:
            return None

        def hold(command: str) -> str | None:
            if command != restarts:
                return None
            reasons = self.busy_reasons()
            if reasons:
                return "; ".join(reasons) + ". Lab Hub builds when that finishes"
            project = launcher.source_dir(self_update.SELF,
                                          self.settings.resolved_lab_root())
            if project is None:
                raise Skipped("Lab Hub was not rebuilt: its checkout is gone")
            return None

        return hold

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
        self._scan()
        self._request_own_verdict()
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
        self.land_state_changed()
        self.show_land_button.setVisible(self.lander.running and self._run_window() is not None)
        for card in self.cards:
            card.set_land_enabled(not busy)

    def _busy_repos(self) -> list[tuple[str, Path]] | None:
        """What the busy line looks at now: repos with a Land button, while this
        page is visible and no Land or look at git is under way."""
        window = self.window()
        if (not self.isVisible() or self.lander.busy or window.isMinimized()
                or QGuiApplication.applicationState() != Qt.ApplicationState.ApplicationActive):
            return None  # nobody looking: no lsof (review P2-3)
        if self._hygiene_proc is not None:
            return None  # its own git would count as busy (review P3-1)
        # land.landing: a Land from another page counts too (review P3-2).
        return [(c.hygiene_row.name, c.hygiene_row.path) for c in self.cards
                if c.hygiene_row is not None and c.hygiene_row.needs_attention
                and not land.landing(c.hygiene_row.path)]

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        self.busy_monitor.poll()  # not the line from hours ago (review P3-3)

    def _busy_updated(self, lines: dict) -> None:
        if self.lander.busy:
            return  # a Land started while lsof ran: its own steps are not "busy"
        for card in self.cards:
            row = card.hygiene_row
            if row is not None and row.name in lines:
                card.set_busy(lines[row.name])

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

    def confirm_land(self, plans: list[land.LandPlan]) -> list[land.LandPlan]:
        """The one confirmation: what will happen, per repo, with a tick box per
        repo. Returns the plans to land, [] for Cancel (tests replace this;
        True still means all of them)."""
        from .land_confirm import LandConfirmDialog

        dialog = LandConfirmDialog(plans, self, confirm_close=self.confirm_close)
        chosen = dialog.chosen() if dialog.exec() == QDialog.DialogCode.Accepted else []
        dialog.deleteLater()  # review P3-7
        return chosen

    def _land_planned(self, plans) -> None:
        if self.land_window is not None:
            self.land_window.set_clearing("")  # a row's button led here, or nothing did
        rerun, self._rerun_name = self._rerun_name, ""
        cleared = self._clearing.get(rerun, "")
        self._clearing.clear()
        window = self.land_window
        if rerun and window is not None and [p.name for p in plans] == [rerun]:
            self._rerun_planned(window, plans[0], cleared)
            return
        try:
            answer = True if all(p.nothing for p in plans) else self.confirm_land(plans)
        except Exception:  # noqa: BLE001 - never leave the tiles on "Looking…"
            answer = False
        if answer is True:
            picked = list(plans)
        elif isinstance(answer, (list, tuple)):
            ids = {id(p) for p in answer}
            # Repos with nothing to land are not cards; they keep their row (§8.1).
            picked = [p for p in plans if id(p) in ids or (p.nothing and ids)]
        else:
            picked = []
        for plan in plans:  # left out or cancelled: the tile goes back at once
            if not any(plan is p for p in picked):
                card = self._card_for(plan.name)
                if card is not None:
                    card.set_landing(None)
                self._landing_cards.pop(plan.name, None)
        if not picked:
            self._landing_cards.clear()
            self._update_land_controls()
            return
        from_land_all = len(plans) > 1
        plans = picked
        # The window opens after the confirmation. A single repo with nothing
        # to do (no confirmation either) says so on its tile alone, as before;
        # Land all always gets the window, whose end state is its summary.
        self._land_window_owns_run = False
        if self.lander.run(plans) and (from_land_all or any(p.actions for p in plans)):
            self._open_land_window(plans)
        self._update_land_controls()

    def _open_land_window(self, plans) -> None:
        old, self.land_window = self.land_window, LandWindow(self)
        self.land_window.stop_requested.connect(self.lander.stop)
        if old is not None:
            old.hide()
            old.deleteLater()
        self._land_window_owns_run = True
        self.land_window.start(plans)
        self.land_window.handoff_requested.connect(self._ask_claude_clicked)
        self.land_window.clear_requested.connect(self.clear_land_row)

    # -- a Land row's own button (spec land-blocker-actions §3) ----------------
    def clear_land_row(self, name: str, action: str) -> None:
        """Try again or Close it… on the Land window's row for repo `name`.
        Clears the stop on the worker; then the repo is planned and confirmed
        as Land always is, or the row says why the stop is still there."""
        window = self.land_window
        if window is None:
            return
        key = progress.plain(name)
        result, path = window.results.get(key), window.handoff_paths.get(key)
        if result is None or path is None:
            return
        if self.lander.busy:
            QMessageBox.information(window, "Land", "Not now: Land is still running. Try "
                                    "again when it has finished.")
            return
        stops: tuple = ()
        if action == land_resolve.CLOSE:
            stops = result.busy
            if not stops or not self.confirm_close(name, Path(path), stops, window):
                return
        if not self.lander.clear(name, Path(path), action, stops):
            return
        self._clearing[name] = action
        self._rerun_name = name  # its Land re-runs in this window (owner, P2-4)
        what = ("Closing the processes, then looking at the repo…" if stops
                else "Checking that origin answers…")
        window.set_clearing(f"{name}: {what}")
        card = self._card_for(name)
        if card is not None:
            self._landing_cards[name] = card
            card.set_landing(what)
        self._update_land_controls()

    def _rerun_planned(self, window, plan, cleared: str = "") -> None:
        """A row's button cleared its stop: confirm as Land always does, then
        land that repo in the same window, resetting only its row (owner, P2-4)."""
        try:
            answer = True if plan.nothing else self.confirm_land([plan])
        except Exception:  # noqa: BLE001 - never leave the tile on "Looking…"
            answer = False
        go = answer is True or (isinstance(answer, (list, tuple))
                                and any(p is plan for p in answer))
        if not go:  # cancelled: the row says the stop is gone and offers Try again
            card = self._card_for(plan.name)
            if card is not None:
                card.set_landing(None)
            self._landing_cards.clear()
            window.restate(plan.name, land.LandResult(
                plan.name, "not_landed",
                f"cleared, but the Land was cancelled: {land_resolve.TRY_AGAIN}"), cleared)
            self._update_land_controls()
            return
        if self.lander.run([plan]):
            self._land_window_owns_run = True
            window.rerun(plan)
        self._update_land_controls()

    def confirm_close(self, name: str, repo: Path, stops, parent) -> bool:
        """The one confirm for Close it…: every process and its own folder, as
        lsof sees it now (tests replace this)."""
        listing = land_resolve.cwd_listing() or []
        where = {f"{cmd} (pid {pid})": cwd for cmd, pid, cwd in listing}
        mine = f" (pid {os.getpid()})"
        lines = [f"{p}  in  {where.get(p, s.target)}  ({land.stop_view(s, repo).place})"
                 for s in stops for p in s.processes if not p.endswith(mine)]
        if not lines:
            return False
        box = QMessageBox(parent)
        box.setWindowTitle("Close processes")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setTextFormat(Qt.TextFormat.PlainText)
        n = len(lines)
        box.setText(f"Close {n} process{'es' if n != 1 else ''} running in {name}?")
        box.setInformativeText(
            CLOSE_NOT_RECOMMENDED + "\n\n" + "\n".join(lines) + "\n\nLab Hub asks each one to quit (SIGTERM, never a forced "
            "kill) and waits up to 5 seconds. Unsaved work in a terminal or editor there can "
            "be lost. A process that ignores the request stays open and stays on the row, "
            "named: an interactive shell such as zsh does. Close its Terminal window, then "
            "press Close it… again. When nothing is left, Land looks at the repo again and "
            "asks you before it runs.")
        close = box.addButton("Close anyway", QMessageBox.ButtonRole.DestructiveRole)
        cancel = box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(cancel)
        box.exec()
        return box.clickedButton() is close

    def _land_held(self, name: str, result) -> None:
        """A row's button ran and the stop is still there."""
        self._rerun_name = ""
        card = self._card_for(name)
        if card is not None:
            card.show_outcome(result)
        self._landing_cards.pop(name, None)
        if self.land_window is not None:
            self.land_window.restate(name, result, self._clearing.pop(name, ""))
        self._update_land_controls()

    def _run_window(self) -> LandWindow | None:
        """The Land window, if it shows the Land now running; else None."""
        return self.land_window if self._land_window_owns_run else None

    def show_land_window(self) -> None:
        """Show progress: bring the hidden Land window back."""
        if self.land_window is not None:
            self.land_window.show()
            self.land_window.raise_()
            self.land_window.activateWindow()

    def _land_progress(self, name: str, line: str) -> None:
        card = self._card_for(name)
        if card is not None:
            card.set_landing(line.strip())
        if (window := self._run_window()) is not None:
            window.on_progress(name, line)

    def _land_step(self, event) -> None:
        if (window := self._run_window()) is not None:
            window.on_step(event)

    def _land_repo_done(self, name: str, result) -> None:
        card = self._card_for(name)
        if card is not None:
            card.show_outcome(result)
        if (window := self._run_window()) is not None:
            window.on_repo_done(name, result)

    def _land_finished(self, results) -> None:
        self._landing_cards.clear()
        self._update_land_controls()
        self.refresh_repos(force=True)
        try:
            if len(results) > 1:
                self.show_land_summary(results)
            elif (window := self._run_window()) is not None:
                window.finish(results)
        finally:
            self._land_window_owns_run = False  # the next run's lines are not this window's

    def show_land_summary(self, results) -> None:
        """After Land all: how many landed, and why each other one did not.
        The Land window's end state, shown again if it was hidden: it replaces
        the box that used to say this."""
        landed = [r for r in results if r.state == "landed"]
        lines = tuple(f"{r.name}: {r.line}" for r in results if r.state != "landed")
        window = self._run_window()
        if window is None:
            return
        window.finish(results, f"Landed {len(landed)} of {len(results)} repos.", lines)
        self.show_land_window()

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
