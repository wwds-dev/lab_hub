"""The Apps tab: one card per standalone app, each with a Launch button."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
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

# Slow enough to be invisible in Activity Monitor, quick enough that the card
# is right by the time you have finished reading it.
POLL_MS = 3000


class AppCard(QWidget):
    """Name, what it does, where it will be started from, and a Launch button."""

    launched = Signal(str)

    def __init__(self, app: launcher.ExternalApp, parent=None) -> None:
        super().__init__(parent)
        self.app = app
        self.lab_root = config.DEFAULT_LAB_ROOT
        self.running = False

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

        header.addWidget(name)
        header.addWidget(self.state, 1)
        header.addWidget(self.launch_button)

        summary = theme.hint(app.summary)

        self.detail = QLabel()
        self.detail.setObjectName("hint")
        self.detail.setWordWrap(True)
        self.detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        layout.addLayout(header)
        layout.addWidget(summary)
        layout.addWidget(self.detail)

    # ------------------------------------------------------------------
    def refresh(self, lab_root: Path, table: str | None = None) -> None:
        self.lab_root = lab_root
        state, detail = launcher.status(self.app, lab_root)
        self.running = state != "missing" and launcher.is_running(
            self.app, lab_root, table
        )

        label, style = RUNNING_LABEL if self.running else STATE_LABELS[state]
        self.state.setText(label)
        self.state.setObjectName(style)
        # A changed objectName only takes effect after the style is re-applied.
        self.state.style().unpolish(self.state)
        self.state.style().polish(self.state)

        self.detail.setText(detail)
        self._update_button(state)

    def _update_button(self, state: str) -> None:
        if not self.running:
            self.launch_button.setText("Launch")
            self.launch_button.setToolTip("")
            self.launch_button.setEnabled(state != "missing")
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
        action = launcher.bring_to_front if self.running else launcher.launch
        try:
            message = action(self.app, self.lab_root)
        except launcher.LaunchError as error:
            QMessageBox.warning(self, f"Could not launch {self.app.name}", str(error))
            return
        self.launched.emit(message)


LAUNCHPAD_INTRO = (
    "These run in their own window, as their own process — quitting Lab Hub "
    "leaves them running. Each starts from its installed app if there is one, "
    "and from its source checkout otherwise."
)


class AppsTab(QWidget):
    """A page of launch cards. Used for the launchpad and for one-off apps."""

    launched = Signal(str)

    def __init__(
        self,
        settings: config.Settings,
        apps: tuple[launcher.ExternalApp, ...] = launcher.LAUNCHPAD,
        title: str = "Standalone apps",
        intro: str = LAUNCHPAD_INTRO,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings

        area, column = scroll_column()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(area)

        column.addWidget(theme.section_title(title))
        column.addWidget(theme.hint(intro))

        self.cards = []
        for app in apps:
            card = AppCard(app)
            card.launched.connect(self.launched)
            self.cards.append(card)
            column.addWidget(card)

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
