"""Native ebook library and Narrator queue for Lab Hub."""

from __future__ import annotations

import csv
import json
import os
import re
import shutil
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from lab_hub import config
from . import theme

DEFAULT_INPUT = Path.home() / "Documents" / "Files" / "Narrator" / "Books Input"
DEFAULT_OUTPUT = Path.home() / "Documents" / "Files" / "Narrator" / "Books Output"
STATE_PATH = config.SUPPORT_DIR / "narrator_library_state.json"


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def find_catalog() -> Path | None:
    override = os.getenv("EBOOK_CATALOG_PATH")
    if override and Path(override).expanduser().is_file():
        return Path(override).expanduser()
    codex = Path.home() / "Documents" / "Codex"
    matches = list(codex.glob("**/outputs/ebook_catalog.csv")) if codex.is_dir() else []
    return max(matches, key=lambda p: p.stat().st_mtime) if matches else None


class NarratorLibrary(QWidget):
    """Browse the generated ebook catalogue inside Narrator."""

    book_selected = Signal(str)

    def __init__(self, settings: config.Settings, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.books: list[dict[str, str]] = []
        self.state = self._load_state()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        card, card_layout = theme.card()
        card_layout.addWidget(theme.section_title("Ebook library"))
        card_layout.addWidget(theme.hint(
            "Ranked recommendations from your ebook catalogue. Mark books read, "
            "copy selections to Narrator, or load one directly into the converter."
        ))

        controls = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search titles…")
        self.search.textChanged.connect(self.refresh)
        controls.addWidget(self.search, 1)
        self.view = QComboBox()
        self.view.addItems(["Ranked recommendations", "Books I’ve read", "Narrated books"])
        self.view.currentTextChanged.connect(self.refresh)
        controls.addWidget(self.view)
        self.reload_button = QPushButton("Refresh")
        self.reload_button.clicked.connect(self.load_catalog)
        controls.addWidget(self.reload_button)
        card_layout.addLayout(controls)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels([
            "Queue", "Read", "Title", "For you", "Popular", "Praise", "Importance", "Narrated"
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for col in (0, 1, 3, 4, 5, 6, 7):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemChanged.connect(self._item_changed)
        self.table.itemDoubleClicked.connect(lambda *_: self.use_selected())
        card_layout.addWidget(self.table, 1)

        actions = QHBoxLayout()
        self.status = QLabel()
        self.status.setObjectName("hint")
        actions.addWidget(self.status, 1)
        queue_button = QPushButton("Copy queued books to Narrator")
        queue_button.clicked.connect(self.copy_queue)
        actions.addWidget(queue_button)
        use_button = QPushButton("Use selected in Converter")
        use_button.setObjectName("primary")
        use_button.clicked.connect(self.use_selected)
        actions.addWidget(use_button)
        card_layout.addLayout(actions)
        layout.addWidget(card)
        self.load_catalog()

    @staticmethod
    def _load_state() -> dict:
        try:
            state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            return state if isinstance(state, dict) else {"read": {}, "queue": {}}
        except (OSError, json.JSONDecodeError):
            return {"read": {}, "queue": {}}

    def _save_state(self) -> None:
        config.SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(self.state, indent=2), encoding="utf-8")

    def load_catalog(self) -> None:
        path = find_catalog()
        if path is None:
            self.books = []
            self.status.setText("No ebook_catalog.csv found. Generate the ebook dashboard first.")
            self.refresh()
            return
        try:
            with path.open(encoding="utf-8") as handle:
                self.books = list(csv.DictReader(handle))
            self.status.setText(f"{len(self.books)} titles · {path}")
        except OSError as error:
            self.books = []
            self.status.setText(f"Could not read catalogue: {error}")
        self.refresh()

    def _output_folder(self) -> Path:
        return Path(self.settings.narrator_output).expanduser() if self.settings.narrator_output else DEFAULT_OUTPUT

    def _is_narrated(self, book: dict[str, str]) -> bool:
        folder = self._output_folder()
        if not folder.is_dir():
            return False
        keys = (_norm(book.get("title", "")), _norm(Path(book.get("path", "")).stem))
        for output in folder.rglob("*"):
            if output.is_file() and output.suffix.lower() in {".mp3", ".m4b", ".wav", ".aac"}:
                stem = _norm(output.stem)
                if any(key and (key in stem or stem in key) for key in keys):
                    return True
        return False

    def refresh(self) -> None:
        query = self.search.text().casefold().strip()
        view = self.view.currentText()
        visible = []
        for book in self.books:
            path = book.get("path", "")
            narrated = self._is_narrated(book)
            if query and query not in (book.get("title", "") + " " + book.get("genre", "")).casefold():
                continue
            if view == "Books I’ve read" and not self.state.get("read", {}).get(path):
                continue
            if view == "Narrated books" and not narrated:
                continue
            visible.append((book, narrated))

        self.table.blockSignals(True)
        self.table.setRowCount(len(visible))
        for row, (book, narrated) in enumerate(visible):
            path = book.get("path", "")
            queue = QTableWidgetItem()
            queue.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            queue.setCheckState(Qt.CheckState.Checked if self.state.get("queue", {}).get(path) else Qt.CheckState.Unchecked)
            queue.setData(Qt.ItemDataRole.UserRole, path)
            read = QTableWidgetItem()
            read.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            read.setCheckState(Qt.CheckState.Checked if self.state.get("read", {}).get(path) else Qt.CheckState.Unchecked)
            read.setData(Qt.ItemDataRole.UserRole, path)
            title = QTableWidgetItem(book.get("title", "Untitled"))
            title.setData(Qt.ItemDataRole.UserRole, path)
            title.setToolTip(book.get("content_summary", ""))
            values = [queue, read, title]
            values += [QTableWidgetItem(book.get(key, "—")) for key in ("personal_fit", "popularity", "acclaim", "importance")]
            values.append(QTableWidgetItem("✓ Done" if narrated else "—"))
            for col, item in enumerate(values):
                self.table.setItem(row, col, item)
        self.table.blockSignals(False)
        if view != "Ranked recommendations":
            self.status.setText(f"{len(visible)} books in {view.lower()}.")

    def _item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() not in (0, 1):
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        bucket = "queue" if item.column() == 0 else "read"
        self.state.setdefault(bucket, {})[path] = item.checkState() == Qt.CheckState.Checked
        self._save_state()

    def selected_path(self) -> str:
        row = self.table.currentRow()
        if row < 0:
            return ""
        item = self.table.item(row, 2)
        return str(item.data(Qt.ItemDataRole.UserRole)) if item else ""

    def use_selected(self) -> None:
        path = self.selected_path()
        if not path:
            QMessageBox.information(self, "Choose a book", "Select a book first.")
            return
        self.book_selected.emit(path)

    def copy_queue(self) -> None:
        selected = [p for p, checked in self.state.get("queue", {}).items() if checked]
        if not selected:
            QMessageBox.information(self, "Narrator queue", "Mark at least one book in the Queue column.")
            return
        DEFAULT_INPUT.mkdir(parents=True, exist_ok=True)
        copied = existing = skipped = 0
        for value in selected:
            source = Path(value)
            if not source.is_file():
                skipped += 1
                continue
            destination = DEFAULT_INPUT / source.name
            if destination.exists():
                existing += 1
            else:
                shutil.copy2(source, destination)
                copied += 1
        QMessageBox.information(
            self, "Narrator queue",
            f"Copied {copied} book(s). {existing} already present. {skipped} unavailable.\n\n{DEFAULT_INPUT}",
        )

