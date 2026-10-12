"""The Convert Video tab: change a folder of videos to another format and size."""

from __future__ import annotations

from functools import partial

from PySide6.QtWidgets import QCheckBox, QComboBox, QLineEdit, QVBoxLayout, QWidget

from lab_hub import config
from lab_hub.tools import video

from . import theme
from .tiles import Refreshable
from .widgets import FolderField, RunPanel, scroll_column


class VideoTab(QWidget, Refreshable):
    def __init__(self, settings: config.Settings, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings

        area, column = scroll_column()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(area)

        card, card_layout = theme.card()
        card_layout.addWidget(theme.section_title("Convert videos"))
        card_layout.addWidget(
            theme.hint(
                "Converts every video in the source folder to another format and, "
                "optionally, another size. Heights never upscale; a custom "
                "width×height overrides the height and can stretch the picture."
            )
        )

        form = theme.form()
        self.source = FolderField("Folder of videos")
        self.source.set_text(settings.video_input)
        form.addRow(theme.label("Source folder"), self.source)

        self.output = FolderField("Where the converted videos go")
        self.output.set_text(settings.video_output)
        form.addRow(theme.label("Output folder"), self.output)

        self.format = QComboBox()
        for ext in video.FORMATS:
            self.format.addItem(ext.upper(), ext)
        self.format.setCurrentIndex(max(0, self.format.findData(settings.video_format)))
        form.addRow(theme.label("Format"), self.format)

        self.resolution = QComboBox()
        for name in video.HEIGHTS:
            self.resolution.addItem(name.capitalize() if name == video.ORIGINAL else name, name)
        self.resolution.setCurrentIndex(max(0, self.resolution.findData(settings.video_resolution)))
        form.addRow(theme.label("Height"), self.resolution)

        self.custom_size = QLineEdit(settings.video_custom_size)
        self.custom_size.setPlaceholderText("1280x720 (optional)")
        self.custom_size.setMaximumWidth(200)
        form.addRow(theme.label("Custom size"), self.custom_size)

        self.overwrite = QCheckBox("Replace files that already exist")
        self.overwrite.setChecked(settings.video_overwrite)
        form.addRow(theme.label(""), self.overwrite)

        card_layout.addLayout(form)

        run_card, run_layout = theme.card()
        self.run_panel = RunPanel("Convert")
        self.run_panel.bind(self._build)
        run_layout.addWidget(self.run_panel)

        column.addWidget(card)
        column.addWidget(run_card, 1)

    def collect(self) -> None:
        s = self.settings
        s.video_input = self.source.text()
        s.video_output = self.output.text()
        s.video_format = self.format.currentData()
        s.video_resolution = self.resolution.currentData()
        s.video_custom_size = self.custom_size.text().strip()
        s.video_overwrite = self.overwrite.isChecked()

    def _build(self):
        if not self.source.text():
            raise ValueError("Choose the source folder first.")
        source = self.source.path()
        if not source.is_dir():
            raise ValueError(f"That folder does not exist:\n{source}")
        if not self.output.text():
            raise ValueError("Choose an output folder first.")
        video.parse_size(self.custom_size.text())  # fail here, not mid-run
        if video.ffmpeg_path() is None:
            raise ValueError(video.INSTALL_HINT)
        self.collect()
        config.save(self.settings)
        return partial(
            video.convert_videos,
            source,
            self.output.path(),
            fmt=self.format.currentData(),
            resolution=self.resolution.currentData(),
            custom_size=self.custom_size.text(),
            overwrite=self.overwrite.isChecked(),
        )
