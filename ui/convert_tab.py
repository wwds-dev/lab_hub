"""The Convert tab: any document format into any other, via Calibre."""

from __future__ import annotations

from functools import partial
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from lab_hub import config
from lab_hub.tools import convert

from . import theme
from .widgets import FolderField, RunPanel, scroll_column


class DropList(QListWidget):
    """The list of files to convert, which is also the drop target."""

    pathsDropped = Signal(list)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setMinimumHeight(170)

    # Qt only offers the drop if the drag is accepted at every stage, so all
    # three handlers have to agree.
    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt override
        if not event.mimeData().hasUrls():
            super().dropEvent(event)
            return
        paths = [
            Path(url.toLocalFile())
            for url in event.mimeData().urls()
            if url.isLocalFile() and url.toLocalFile()
        ]
        event.acceptProposedAction()
        if paths:
            self.pathsDropped.emit(paths)


class ConvertTab(QWidget):
    """Queue up files and folders, pick a target format, convert them."""

    def __init__(self, settings: config.Settings, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self._sources: list[Path] = []

        area, column = scroll_column()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(area)

        # --- files card --------------------------------------------------
        files_card, files_layout = theme.card()
        # Names the list beneath it, rather than repeating the tab's own name.
        files_layout.addWidget(theme.section_title("Files to convert"))
        files_layout.addWidget(
            theme.hint(
                "Drop files or folders below — or use the buttons. Anything Calibre "
                "reads converts to anything Calibre writes: EPUB, AZW3, MOBI, DOCX, "
                "PDF, TXT, RTF and more."
            )
        )

        self.files = DropList()
        self.files.pathsDropped.connect(self.add_paths)
        files_layout.addWidget(self.files)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        for label, slot in (
            ("Add Files…", self.choose_files),
            ("Add Folder…", self.choose_folder),
            ("Remove", self.remove_selected),
            ("Clear", self.clear_all),
        ):
            button = QPushButton(label)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        buttons.addStretch(1)

        self.count = QLabel()
        self.count.setObjectName("hint")
        buttons.addWidget(self.count)
        files_layout.addLayout(buttons)

        # --- options card ------------------------------------------------
        options_card, options_layout = theme.card()
        form = theme.form()

        self.format_box = QComboBox()
        for output_format in convert.formats.OUTPUT_FORMATS:
            self.format_box.addItem(output_format.label, output_format.ext)
        index = self.format_box.findData(settings.convert_output_ext)
        self.format_box.setCurrentIndex(max(index, 0))
        self.format_box.currentIndexChanged.connect(self._on_format_changed)
        form.addRow(theme.label("Convert to"), self.format_box)

        self.format_note = theme.hint("")
        form.addRow(theme.label(""), self.format_note)

        destination = QWidget()
        destination_row = QHBoxLayout(destination)
        destination_row.setContentsMargins(0, 0, 0, 0)
        destination_row.setSpacing(12)
        self.beside_radio = QRadioButton("Beside the original")
        self.folder_radio = QRadioButton("This folder:")
        group = QButtonGroup(self)
        group.addButton(self.beside_radio)
        group.addButton(self.folder_radio)
        group.buttonToggled.connect(self._on_mode_changed)
        destination_row.addWidget(self.beside_radio)
        destination_row.addWidget(self.folder_radio)
        destination_row.addStretch(1)
        form.addRow(theme.label("Save to"), destination)

        self.output_dir = FolderField("Where converted files should go")
        self.output_dir.set_text(settings.convert_output_dir)
        form.addRow(theme.label(""), self.output_dir)

        self.overwrite = QCheckBox("Overwrite files that already exist")
        self.overwrite.setChecked(settings.convert_overwrite)
        form.addRow(theme.label(""), self.overwrite)

        self.recurse = QCheckBox("Include subfolders when a folder is added")
        self.recurse.setChecked(settings.convert_recurse)
        form.addRow(theme.label(""), self.recurse)

        options_layout.addLayout(form)

        self.warning = theme.hint("")
        self.warning.setVisible(False)
        options_layout.addWidget(self.warning)

        self.calibre = QLabel()
        self.calibre.setObjectName("hint")
        self.calibre.setWordWrap(True)
        options_layout.addWidget(self.calibre)

        # --- run card ----------------------------------------------------
        run_card, run_layout = theme.card()
        self.run_panel = RunPanel("Convert")
        self.run_panel.bind(self.build_job)
        run_layout.addWidget(self.run_panel)

        column.addWidget(files_card)
        column.addWidget(options_card)
        column.addWidget(run_card, 1)

        mode = convert.OutputMode(settings.convert_output_mode)
        self.beside_radio.setChecked(mode is convert.OutputMode.BESIDE_SOURCE)
        self.folder_radio.setChecked(mode is convert.OutputMode.CUSTOM_FOLDER)
        self._on_mode_changed()
        self._on_format_changed()
        self._refresh_list()
        self.refresh_calibre()

    # ------------------------------------------------------------------
    # Sources
    # ------------------------------------------------------------------
    def add_paths(self, paths: list[Path]) -> None:
        """Queue everything convertible under `paths`."""
        found = convert.jobs.collect_sources(paths, recurse=self.recurse.isChecked())
        known = {source.resolve() for source in self._sources}
        added = [path for path in found if path not in known]
        self._sources.extend(added)

        if added:
            self.settings.convert_source_dir = str(added[-1].parent)
        elif not found:
            # Silently dropping a file the user just dragged in looks broken.
            self.run_panel.status.setText(self._nothing_added_reason(paths))
        self._refresh_list()

    def _nothing_added_reason(self, paths: list[Path]) -> str:
        files = [path for path in paths if path.is_file()]
        unsupported = sorted(
            {
                path.suffix.lower() or "(no extension)"
                for path in files
                if not convert.formats.is_convertible(path.suffix)
            }
        )
        if unsupported:
            return f"Calibre cannot read {', '.join(unsupported)} — nothing added."
        if any(path.is_dir() for path in paths):
            scope = "" if self.recurse.isChecked() else " (subfolders are off)"
            return f"No convertible files in that folder{scope}."
        return "Nothing to add."

    def choose_files(self) -> None:
        start = self.settings.convert_source_dir or str(Path.home())
        chosen, _ = QFileDialog.getOpenFileNames(
            self, "Add files", start, convert.formats.file_dialog_filter()
        )
        if chosen:
            self.add_paths([Path(path) for path in chosen])

    def choose_folder(self) -> None:
        start = self.settings.convert_source_dir or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "Add folder", start)
        if chosen:
            self.add_paths([Path(chosen)])

    def remove_selected(self) -> None:
        for row in sorted((self.files.row(item) for item in self.files.selectedItems()), reverse=True):
            if 0 <= row < len(self._sources):
                del self._sources[row]
        self._refresh_list()

    def clear_all(self) -> None:
        self._sources.clear()
        self._refresh_list()

    def _refresh_list(self) -> None:
        self.files.clear()
        for source in self._sources:
            item = QListWidgetItem(f"{source.name}    ({source.suffix.lstrip('.').upper()})")
            item.setToolTip(str(source))
            item.setData(Qt.ItemDataRole.UserRole, str(source))
            self.files.addItem(item)

        total = len(self._sources)
        self.count.setText("No files queued." if not total else f"{total} file(s) queued.")
        self._refresh_warning()

    def _refresh_warning(self) -> None:
        lossy = sorted(
            {
                source.suffix.lstrip(".").upper()
                for source in self._sources
                if convert.formats.is_lossy_input(source.suffix)
            }
        )
        if lossy:
            self.warning.setText(
                f"⚠︎ {', '.join(lossy)} has no reliable text structure — Calibre will "
                "convert it, but expect broken paragraphs and lost formatting."
            )
        self.warning.setVisible(bool(lossy))

    # ------------------------------------------------------------------
    # Options
    # ------------------------------------------------------------------
    def _on_format_changed(self) -> None:
        output_format = self._current_format()
        self.format_note.setText(output_format.note)

    def _on_mode_changed(self) -> None:
        custom = self.folder_radio.isChecked()
        self.output_dir.setEnabled(custom)

    def _current_format(self):
        ext = self.format_box.currentData() or convert.formats.DEFAULT_OUTPUT_EXT
        return convert.formats.OUTPUT_BY_EXT[ext]

    def _mode(self) -> convert.OutputMode:
        return (
            convert.OutputMode.CUSTOM_FOLDER
            if self.folder_radio.isChecked()
            else convert.OutputMode.BESIDE_SOURCE
        )

    # ------------------------------------------------------------------
    def refresh_calibre(self) -> None:
        """Calibre is an external dependency; say so before the user hits Run."""
        binary = convert.converter_path()
        if binary:
            self.calibre.setText(f"Using Calibre at {binary}")
            self.run_panel.run_button.setEnabled(not self.run_panel.is_running())
        else:
            self.calibre.setText(convert.INSTALL_HINT)
            self.run_panel.run_button.setEnabled(False)

    def collect(self) -> None:
        """Write the form back into settings so the next launch remembers it."""
        self.settings.convert_output_ext = self._current_format().ext
        self.settings.convert_output_mode = self._mode().value
        self.settings.convert_output_dir = self.output_dir.text()
        self.settings.convert_overwrite = self.overwrite.isChecked()
        self.settings.convert_recurse = self.recurse.isChecked()

    def build_job(self):
        if not self._sources:
            raise ValueError("Add some files or a folder first.")

        output_dir = None
        if self._mode() is convert.OutputMode.CUSTOM_FOLDER:
            if not self.output_dir.text():
                raise ValueError("Choose the folder to save converted files into.")
            output_dir = self.output_dir.path()
            try:
                output_dir.mkdir(parents=True, exist_ok=True)
            except OSError as problem:
                raise ValueError(f"Cannot write to that folder:\n{problem}") from problem

        self.collect()
        config.save(self.settings)

        return partial(
            convert.convert,
            list(self._sources),
            output_ext=self._current_format().ext,
            mode=self._mode(),
            output_dir=output_dir,
            overwrite=self.overwrite.isChecked(),
        )
