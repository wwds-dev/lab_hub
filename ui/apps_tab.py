"""The Apps tab: one card per standalone app, each with a Launch button."""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from lab_hub import config, launcher

from . import theme
from .widgets import scroll_column

STATE_LABELS = {
    "installed": ("Installed", "stateOk"),
    "source": ("Source only", "stateWarn"),
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

# How long to wait for a launched app to appear in the process table before
# saying it never came up. Generous on purpose: a cold PyInstaller bundle
# unpacks itself before it execs, and a false "Did not start" would be worse
# than a slow "Starting…". A source launch is already death-watched inside
# `launcher.launch`, which reports the exit code outright.
LAUNCH_CONFIRM_SECONDS = 20.0

# Slow enough to be invisible in Activity Monitor, quick enough that the card
# is right by the time you have finished reading it.
POLL_MS = 3000

# A tile narrower than this squeezes the summary into a ragged column of
# single words, so the grid drops a column instead of going narrower.
TILE_MIN_WIDTH = 380
SUMMARY_HEIGHT = 52
GRID_MAX_WIDTH = 1500


class AppCard(QWidget):
    """Name, what it does, where it will be started from, and a Launch button."""

    launched = Signal(str)
    start_failed = Signal(str)

    def __init__(self, app: launcher.ExternalApp, parent=None) -> None:
        super().__init__(parent)
        self.app = app
        self.lab_root = config.DEFAULT_LAB_ROOT
        self.running = False
        # Set while a launch is in flight, cleared the moment the app shows up
        # in the process table — or turned into `_did_not_start` if it never does.
        self._pending_since: float | None = None
        self._did_not_start = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        frame, layout = theme.card()
        outer.addWidget(frame)

        header = QHBoxLayout()
        header.setSpacing(12)

        name = QLabel(app.name)
        name.setObjectName("appName")

        self.state = QLabel()
        self.state.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.launch_button = QPushButton("Launch")
        self.launch_button.setObjectName("primary")
        self.launch_button.clicked.connect(self._launch)

        # Name and state on one line, the button along the bottom. Side by side
        # the tiles are too narrow to keep all three on one row without the
        # summary being squeezed into a column of single words.
        header.addWidget(name)
        header.addStretch(1)
        header.addWidget(self.state)

        summary = theme.hint(app.summary)
        # The tiles sit in a grid, so they must agree on a height; the summaries
        # differ in length and would otherwise give every row a ragged edge.
        summary.setMinimumHeight(SUMMARY_HEIGHT)
        summary.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.detail = QLabel()
        self.detail.setObjectName("hint")
        self.detail.setWordWrap(True)
        self.detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        layout.addLayout(header)
        layout.addWidget(summary)
        layout.addWidget(self.detail)
        layout.addWidget(self.launch_button)

        # Spare room at the bottom keeps every tile's Launch button on the same
        # line, whatever the summary length.
        layout.addStretch(1)

    # ------------------------------------------------------------------
    def refresh(self, lab_root: Path, table: str | None = None) -> None:
        self.lab_root = lab_root
        ready = launcher.readiness(self.app, lab_root)
        self.running = ready.state != "missing" and launcher.is_running(
            self.app, lab_root, table
        )
        self._settle_pending_launch()

        label, style = self._state_label(ready)
        self.state.setText(label)
        self.state.setObjectName(style)
        # A changed objectName only takes effect after the style is re-applied.
        self.state.style().unpolish(self.state)
        self.state.style().polish(self.state)

        # A reason it cannot run beats a path it would have run from.
        self.detail.setText(ready.problem or ready.detail)
        self._update_button(ready)

    def _state_label(self, ready: launcher.Readiness) -> tuple[str, str]:
        if self.running:
            return RUNNING_LABEL
        if self._pending_since is not None:
            return STARTING_LABEL
        if self._did_not_start:
            return FAILED_LABEL
        return STATE_LABELS[ready.state]

    def _settle_pending_launch(self) -> None:
        """Decide whether a launch we started has come up, or never will."""
        if self.running:
            self._pending_since = None
            self._did_not_start = False
            return
        if self._pending_since is None:
            return
        if time.monotonic() - self._pending_since <= LAUNCH_CONFIRM_SECONDS:
            return
        self._pending_since = None
        self._did_not_start = True
        self.start_failed.emit(
            f"{self.app.name} was started but never came up. "
            f"Look in {launcher.startup_log_hint(self.app)}"
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
            # could only ever produce a dialog.
            self.launch_button.setToolTip(ready.problem or "")
            self.launch_button.setEnabled(ready.ok)
            return

        if launcher.can_bring_to_front(self.app):
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
            self._did_not_start = False
            self.refresh(self.lab_root)
        self.launched.emit(message)


LAUNCHPAD_INTRO = (
    "These run in their own window, as their own process — quitting Lab Hub "
    "leaves them running. Each starts from its installed app if there is one, "
    "and from its source checkout otherwise."
)


class AppsTab(QWidget):
    """A page of launch cards. Used for the launchpad and for one-off apps."""

    launched = Signal(str)
    start_failed = Signal(str)

    def __init__(
        self,
        settings: config.Settings,
        apps: tuple[launcher.ExternalApp, ...] = launcher.LAUNCHPAD,
        title: str = "Standalone apps",
        intro: str = LAUNCHPAD_INTRO,
        sections: tuple[tuple[str, str, tuple[launcher.ExternalApp, ...]], ...] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings

        area, column = scroll_column(max_width=GRID_MAX_WIDTH)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(area)

        # One page, several headed sections. Suites, the sync companions and the
        # small utilities are different kinds of thing and reading them as one
        # undifferentiated wall of tiles was the problem with the flat grid.
        groups = sections if sections is not None else ((title, intro, apps),)

        self.cards = []
        self.grids = []
        for group_title, group_intro, group_apps in groups:
            column.addWidget(theme.section_title(group_title))
            if group_intro:
                column.addWidget(theme.hint(group_intro))

            grid = QGridLayout()
            grid.setSpacing(16)
            column.addLayout(grid)
            self.grids.append((grid, []))

            for app in group_apps:
                card = AppCard(app)
                card.launched.connect(self.launched)
                card.start_failed.connect(self.start_failed)
                self.cards.append(card)
                self.grids[-1][1].append(card)

        # Tests and the resize logic reach for the first grid by name.
        self.grid = self.grids[0][0]
        self._columns = 0
        self._arrange(1)

        refresh = QPushButton("Re-check")
        refresh.setToolTip("Look again for installed apps and source checkouts")
        refresh.clicked.connect(self.refresh)
        row = QHBoxLayout()
        row.addWidget(refresh)
        row.addStretch(1)
        column.addLayout(row)
        column.addStretch(1)

        # An app can start or quit without Lab Hub being told, so the state has
        # to be re-read rather than remembered. Only while the tab is on screen:
        # polling a page nobody is looking at is pure waste.
        self._poll = QTimer(self)
        self._poll.setInterval(POLL_MS)
        self._poll.timeout.connect(self.refresh)

        self.refresh()

    def _arrange(self, columns: int) -> None:
        """Lay the tiles out in `columns` columns, if that is a change."""
        if columns == self._columns:
            return
        self._columns = columns

        for grid, cards in self.grids:
            for card in cards:
                grid.removeWidget(card)
            for index, card in enumerate(cards):
                grid.addWidget(card, index // columns, index % columns)
            # Equal shares, and no leftover stretch from a wider previous layout
            # holding open an empty column.
            for index in range(grid.columnCount()):
                grid.setColumnStretch(index, 1 if index < columns else 0)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        usable = self.width() - 48  # the column's own margins
        fits = max(1, usable // TILE_MIN_WIDTH)
        self._arrange(min(len(self.cards) or 1, fits))

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        self.refresh()
        self._poll.start()

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().hideEvent(event)
        self._poll.stop()

    def apply_settings(self, settings: config.Settings) -> None:
        self.settings = settings
        self.refresh()

    def refresh(self) -> None:
        lab_root = self.settings.resolved_lab_root()
        table = launcher.process_table()  # one snapshot, shared by every card
        for card in self.cards:
            card.refresh(lab_root, table)
