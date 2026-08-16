"""The Image tools tab: print sizing, batch rename, small-image sweep.

Three tools, one log. They are variations on "walk a folder of images", so
giving each its own run button and output pane would triple the chrome for no
gain — the inner tabs pick which one Run runs.
"""

from __future__ import annotations

from functools import partial

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QLineEdit,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from lab_hub import config
from lab_hub.tools import images

from . import theme
from .widgets import FolderField, RunPanel, scroll_column

PRINT, RENAME, SWEEP = 0, 1, 2

# "Move", not "Remove" or "Sweep": the sweep relocates files into a subfolder
# rather than deleting them, and a button that overstates what it does is worse
# than a vague one.
RUN_LABELS = {PRINT: "Resize", RENAME: "Rename", SWEEP: "Move"}


def _spin(value: int, low: int, high: int, suffix: str = "") -> QSpinBox:
    box = QSpinBox()
    box.setRange(low, high)
    box.setValue(value)
    if suffix:
        box.setSuffix(suffix)
    box.setMaximumWidth(140)
    return box


class ImagesTab(QWidget):
    def __init__(self, settings: config.Settings, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings

        area, column = scroll_column()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(area)

        self.tools = QTabWidget()
        self.tools.addTab(self._print_page(), "Resize for print")
        self.tools.addTab(self._rename_page(), "Rename in sequence")
        self.tools.addTab(self._sweep_page(), "Move small aside")
        self.tools.currentChanged.connect(self._on_tool_changed)

        run_card, run_layout = theme.card()
        self.run_panel = RunPanel("Resize")
        run_layout.addWidget(self.run_panel)

        column.addWidget(self.tools)
        column.addWidget(run_card, 1)

        self._on_tool_changed(self.tools.currentIndex())

    # ------------------------------------------------------------------
    # Pages
    # ------------------------------------------------------------------
    def _print_page(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 12, 0, 0)

        card, layout = theme.card()
        layout.addWidget(theme.section_title("Print-ready copies"))
        layout.addWidget(
            theme.hint(
                "Writes copies at an exact pixel size with the DPI recorded in "
                "the file. Fit scales the artwork and centres it on a canvas; "
                "Exact stretches it to fill, which distorts anything that is "
                "not already the right aspect ratio."
            )
        )

        form = theme.form()
        self.dpi_input = FolderField("Folder of source images")
        self.dpi_input.set_text(self.settings.dpi_input)
        form.addRow(theme.label("Source folder"), self.dpi_input)

        self.dpi_output = FolderField("Where the print-ready copies go")
        self.dpi_output.set_text(self.settings.dpi_output)
        form.addRow(theme.label("Output folder"), self.dpi_output)

        self.dpi_width = _spin(self.settings.dpi_width_in, 1, 120, " in")
        form.addRow(theme.label("Width"), self.dpi_width)

        self.dpi_height = _spin(self.settings.dpi_height_in, 1, 120, " in")
        form.addRow(theme.label("Height"), self.dpi_height)

        self.dpi_value = _spin(300, 72, 1200, " DPI")
        form.addRow(theme.label("Resolution"), self.dpi_value)

        self.dpi_mode = QComboBox()
        self.dpi_mode.addItem("Fit — scale and centre on a canvas", images.MODE_FIT)
        self.dpi_mode.addItem("Exact — stretch to fill", images.MODE_EXACT)
        self.dpi_mode.setCurrentIndex(0 if self.settings.dpi_mode == images.MODE_FIT else 1)
        form.addRow(theme.label("Mode"), self.dpi_mode)

        self.dpi_background = QComboBox()
        for name in images.BACKGROUNDS:
            self.dpi_background.addItem(name.capitalize(), name)
        index = self.dpi_background.findData(self.settings.dpi_background)
        self.dpi_background.setCurrentIndex(max(0, index))
        form.addRow(theme.label("Canvas colour"), self.dpi_background)

        layout.addLayout(form)
        outer.addWidget(card)
        outer.addStretch(1)
        return page

    def _rename_page(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 12, 0, 0)

        card, layout = theme.card()
        layout.addWidget(theme.section_title("Sequential rename"))
        layout.addWidget(
            theme.hint(
                "Numbers images name_001, name_002, … continuing from the "
                "highest number already in the target folder, so a second batch "
                "never collides with the first."
            )
        )

        form = theme.form()
        self.rename_source = FolderField("Folder holding the new images")
        self.rename_source.set_text(self.settings.rename_source)
        form.addRow(theme.label("Source folder"), self.rename_source)

        self.rename_target = FolderField("Folder the numbering continues from")
        self.rename_target.set_text(self.settings.rename_target)
        form.addRow(theme.label("Target folder"), self.rename_target)

        self.rename_base = QLineEdit(self.settings.rename_base)
        self.rename_base.setPlaceholderText("sweet_poison")
        form.addRow(theme.label("Base name"), self.rename_base)

        self.rename_move = QCheckBox("Also move the renamed files into the target folder")
        form.addRow(theme.label(""), self.rename_move)

        layout.addLayout(form)
        outer.addWidget(card)
        outer.addStretch(1)
        return page

    def _sweep_page(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 12, 0, 0)

        card, layout = theme.card()
        layout.addWidget(theme.section_title("Move small images aside"))
        layout.addWidget(
            theme.hint(
                "Moves thumbnails and junk into a 'Delete' subfolder — moved, "
                "not deleted, because a size filter will sometimes catch "
                "something you wanted."
            )
        )

        form = theme.form()
        self.sweep_source = FolderField("Folder to clean up")
        self.sweep_source.set_text(self.settings.move_source)
        form.addRow(theme.label("Folder"), self.sweep_source)

        self.sweep_width = _spin(self.settings.move_max_width, 1, 10000, " px")
        form.addRow(theme.label("Max width"), self.sweep_width)

        self.sweep_height = _spin(self.settings.move_max_height, 1, 10000, " px")
        form.addRow(theme.label("Max height"), self.sweep_height)

        layout.addLayout(form)
        outer.addWidget(card)
        outer.addStretch(1)
        return page

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------
    def _on_tool_changed(self, index: int) -> None:
        builders = {
            PRINT: self._build_print,
            RENAME: self._build_rename,
            SWEEP: self._build_sweep,
        }
        self.run_panel.bind(builders[index])
        self.run_panel.run_button.setText(RUN_LABELS[index])

    def collect(self) -> None:
        s = self.settings
        s.dpi_input = self.dpi_input.text()
        s.dpi_output = self.dpi_output.text()
        s.dpi_width_in = self.dpi_width.value()
        s.dpi_height_in = self.dpi_height.value()
        s.dpi_mode = self.dpi_mode.currentData()
        s.dpi_background = self.dpi_background.currentData()
        s.rename_source = self.rename_source.text()
        s.rename_target = self.rename_target.text()
        s.rename_base = self.rename_base.text().strip()
        s.move_source = self.sweep_source.text()
        s.move_max_width = self.sweep_width.value()
        s.move_max_height = self.sweep_height.value()

    def _save(self) -> None:
        self.collect()
        config.save(self.settings)

    @staticmethod
    def _require_folder(field: FolderField, what: str):
        if not field.text():
            raise ValueError(f"Choose the {what} first.")
        path = field.path()
        if not path.is_dir():
            raise ValueError(f"That folder does not exist:\n{path}")
        return path

    def _build_print(self):
        source = self._require_folder(self.dpi_input, "source folder")
        if not self.dpi_output.text():
            raise ValueError("Choose an output folder first.")
        destination = self.dpi_output.path()
        if destination == source:
            raise ValueError(
                "The output folder must be different from the source folder — "
                "otherwise the originals are overwritten."
            )
        self._save()
        return partial(
            images.resize_for_print,
            source,
            destination,
            width_in=self.dpi_width.value(),
            height_in=self.dpi_height.value(),
            dpi=self.dpi_value.value(),
            mode=self.dpi_mode.currentData(),
            background=self.dpi_background.currentData(),
        )

    def _build_rename(self):
        source = self._require_folder(self.rename_source, "source folder")
        target = self._require_folder(self.rename_target, "target folder")
        base = self.rename_base.text().strip()
        if not base:
            raise ValueError("Give the files a base name.")
        self._save()
        return partial(
            images.rename_for_print,
            source,
            target,
            base_name=base,
            move=self.rename_move.isChecked(),
        )

    def _build_sweep(self):
        source = self._require_folder(self.sweep_source, "folder to clean up")
        self._save()
        return partial(
            images.move_small,
            source,
            max_width=self.sweep_width.value(),
            max_height=self.sweep_height.value(),
        )
