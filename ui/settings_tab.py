"""The Settings tab — only what the rest of the app cannot work out for itself."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from lab_hub import APP_NAME, config, launcher, login_item

from . import theme
from .widgets import FolderField, scroll_column


class SettingsTab(QWidget):
    settings_saved = Signal()

    def __init__(self, settings: config.Settings, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings

        area, column = scroll_column()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(area)

        card, card_layout = theme.card()
        card_layout.addWidget(theme.section_title("Lab folder"))
        card_layout.addWidget(
            theme.hint(
                "Where the project folders live. Only used to launch an app "
                "from source — an app installed in /Applications is found "
                "without it. Leave blank to detect it automatically, or set "
                f"${config.LAB_ROOT_ENV} in the environment."
            )
        )

        form = theme.form()
        self.lab_root = FolderField("Detected automatically when blank")
        self.lab_root.set_text(settings.lab_root)
        form.addRow(theme.label("Projects folder"), self.lab_root)
        card_layout.addLayout(form)

        self.resolved = QLabel()
        self.resolved.setObjectName("hint")
        self.resolved.setWordWrap(True)
        card_layout.addWidget(self.resolved)

        save = QPushButton("Save")
        save.setObjectName("primary")
        save.clicked.connect(self.save)
        row = QHBoxLayout()
        row.addWidget(save)
        row.addStretch(1)
        card_layout.addLayout(row)

        # --- start at login ---------------------------------------------
        login_card, login_layout = theme.card()
        login_layout.addWidget(theme.section_title("Start at login"))
        login_layout.addWidget(
            theme.hint(
                "Starts Lab Hub, Backup Control Center, and git_autosync in the "
                "background when you log in. Lab Hub also makes sure the two "
                "sync apps are running whenever the Mac wakes. No window opens "
                "until you ask for one. Takes effect at your next login."
            )
        )

        self.at_login = QCheckBox(f"Open {APP_NAME} at login")
        self.at_login.toggled.connect(self._on_login_toggled)
        login_layout.addWidget(self.at_login)

        self.login_detail = QLabel()
        self.login_detail.setObjectName("hint")
        self.login_detail.setWordWrap(True)
        login_layout.addWidget(self.login_detail)

        # --- where things are stored ------------------------------------
        paths_card, paths_layout = theme.card()
        paths_layout.addWidget(theme.section_title("Files"))
        paths_layout.addWidget(
            theme.hint(
                "Settings live outside the app bundle, so reinstalling Lab Hub "
                "does not lose them."
            )
        )
        location = QLabel(str(config.CONFIG_PATH))
        location.setObjectName("hint")
        location.setWordWrap(True)
        location.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        paths_layout.addWidget(location)

        reveal = QPushButton("Show in Finder")
        reveal.clicked.connect(self._reveal)
        paths_row = QHBoxLayout()
        paths_row.addWidget(reveal)
        paths_row.addStretch(1)
        paths_layout.addLayout(paths_row)

        column.addWidget(card)
        column.addWidget(login_card)
        column.addWidget(paths_card)
        column.addStretch(1)

        self._refresh_resolved()
        self._refresh_login()

    # ------------------------------------------------------------------
    def _refresh_login(self) -> None:
        """Read the state off disk rather than trusting a remembered flag.

        The agent is a file the user can delete from Finder or System Settings,
        so the checkbox has to reflect what is actually installed.
        """
        enabled = login_item.is_enabled()

        # setChecked would re-enter _on_login_toggled and rewrite the plist.
        self.at_login.blockSignals(True)
        self.at_login.setChecked(enabled)
        self.at_login.blockSignals(False)

        if enabled:
            self.at_login.setEnabled(True)
            self.login_detail.setText(f"Starting {login_item.target()} at login.")
            return

        available = login_item.bundle() is not None
        self.at_login.setEnabled(available)
        self.login_detail.setText(
            f"Agent: {login_item.PLIST_PATH}"
            if available
            else f"Unavailable — {APP_NAME} is not installed in /Applications yet."
        )

    def _on_login_toggled(self, wanted: bool) -> None:
        try:
            if wanted:
                login_item.enable()
            else:
                login_item.disable()
        except login_item.LoginItemError as error:
            QMessageBox.warning(self, "Could not change this", str(error))
        self._refresh_login()

    def _refresh_resolved(self) -> None:
        root = self.settings.resolved_lab_root()
        found = [app.name for app in launcher.APPS if launcher.source_dir(app, root)]
        detail = ", ".join(found) if found else "no project checkouts found there"
        self.resolved.setText(f"Currently using: {root}  —  {detail}.")

    def _reveal(self) -> None:
        config.SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
        if not config.CONFIG_PATH.exists():
            config.save(self.settings)
        launcher.reveal(config.CONFIG_PATH)

    def save(self) -> None:
        self.settings.lab_root = self.lab_root.text()
        config.save(self.settings)
        self._refresh_resolved()
        self.settings_saved.emit()
