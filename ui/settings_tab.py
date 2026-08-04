"""The Settings tab — only what the rest of the app cannot work out for itself."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from lab_hub import config, launcher

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
        column.addWidget(paths_card)
        column.addStretch(1)

        self._refresh_resolved()

    # ------------------------------------------------------------------
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
