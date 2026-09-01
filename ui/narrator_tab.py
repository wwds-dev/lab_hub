"""Narrator tab: turn an ebook into an MP3 audiobook from Lab Hub."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from PySide6.QtCore import QProcess
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from lab_hub import config

from . import theme
from .widgets import FolderField, LOG_LIMIT, scroll_column
from .narrator_library import NarratorLibrary

SUPPORTED_BOOKS = "Ebooks (*.epub *.pdf *.mobi *.azw3 *.txt);;All files (*)"
VOICES = ("alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer")


class NarratorTab(QWidget):
    """Own the complete Narrator workflow and its stoppable worker process."""

    def __init__(self, settings: config.Settings, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.process: QProcess | None = None

        area, column = scroll_column()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.sections = QTabWidget()
        self.sections.addTab(area, "Convert")
        self.library = NarratorLibrary(settings)
        self.library.book_selected.connect(self._use_library_book)
        self.sections.addTab(self.library, "Library")
        outer.addWidget(self.sections)

        source_card, source_layout = theme.card()
        source_layout.addWidget(theme.section_title("Book and destination"))
        source_layout.addWidget(theme.hint(
            "Choose an EPUB, PDF, MOBI, AZW3 or text file. Narrator extracts its text, "
            "creates speech with OpenAI, and joins the parts into one MP3."
        ))
        form = theme.form()
        self.input_edit = QLineEdit(settings.narrator_input)
        self.input_edit.setPlaceholderText("Choose a book…")
        input_row = QWidget()
        input_layout = QHBoxLayout(input_row)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.addWidget(self.input_edit, 1)
        choose = QPushButton("Browse…")
        choose.clicked.connect(self.choose_book)
        input_layout.addWidget(choose)
        form.addRow(theme.label("Book"), input_row)

        self.output = FolderField("Where the audiobook should go")
        self.output.set_text(settings.narrator_output)
        form.addRow(theme.label("Save to"), self.output)

        self.voice = QComboBox()
        self.voice.addItems(VOICES)
        self.voice.setCurrentText(settings.narrator_voice)
        form.addRow(theme.label("Voice"), self.voice)

        self.chunk_tokens = QSpinBox()
        self.chunk_tokens.setRange(200, 4000)
        self.chunk_tokens.setSingleStep(100)
        self.chunk_tokens.setValue(settings.narrator_chunk_tokens)
        form.addRow(theme.label("Chunk size"), self.chunk_tokens)
        source_layout.addLayout(form)

        note = theme.hint(
            "Requires OPENAI_API_KEY and ffmpeg. OpenAI usage costs real money. "
            "Interrupted books keep their completed chunks and resume on the next run."
        )
        source_layout.addWidget(note)

        run_card, run_layout = theme.card()
        controls = QHBoxLayout()
        self.run_button = QPushButton("Create Audiobook")
        self.run_button.setObjectName("primary")
        self.run_button.clicked.connect(self.start)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop)
        self.status = QLabel("Idle.")
        self.status.setObjectName("hint")
        controls.addWidget(self.run_button)
        controls.addWidget(self.stop_button)
        controls.addWidget(self.status, 1)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 1)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(LOG_LIMIT)
        self.log.setMinimumHeight(260)
        self.log.setPlaceholderText("Narrator output appears here.")
        run_layout.addLayout(controls)
        run_layout.addWidget(self.progress)
        run_layout.addWidget(self.log, 1)

        column.addWidget(source_card)
        column.addWidget(run_card, 1)

    def _use_library_book(self, path: str) -> None:
        """Load a library selection into the existing conversion workflow."""
        self.input_edit.setText(path)
        self.sections.setCurrentIndex(0)
        self.status.setText(f"Ready: {Path(path).name}")

    def choose_book(self) -> None:
        start = self.input_edit.text() or str(Path.home())
        chosen, _ = QFileDialog.getOpenFileName(self, "Choose a book", start, SUPPORTED_BOOKS)
        if chosen:
            self.input_edit.setText(chosen)

    def is_running(self) -> bool:
        return self.process is not None and self.process.state() != QProcess.ProcessState.NotRunning

    def _validate(self) -> tuple[Path, Path]:
        source = Path(self.input_edit.text().strip()).expanduser()
        output = self.output.path()
        if not source.is_file():
            raise ValueError("Choose an ebook file first.")
        if source.suffix.lower() not in {".epub", ".pdf", ".mobi", ".azw3", ".txt"}:
            raise ValueError("Narrator supports EPUB, PDF, MOBI, AZW3 and TXT books.")
        if not self.output.text():
            raise ValueError("Choose an output folder.")
        if not os.getenv("OPENAI_API_KEY") and not (Path.cwd() / ".env").is_file():
            raise ValueError("OPENAI_API_KEY is not set. Add it to Lab Hub's .env file or environment.")
        if not shutil.which("ffmpeg"):
            raise ValueError("ffmpeg is not installed or is not on PATH.")
        return source, output

    def start(self) -> None:
        if self.is_running():
            return
        try:
            source, output = self._validate()
        except ValueError as error:
            QMessageBox.warning(self, "Narrator is not ready", str(error))
            return

        self.settings.narrator_input = str(source)
        self.settings.narrator_output = str(output)
        self.settings.narrator_voice = self.voice.currentText()
        self.settings.narrator_chunk_tokens = self.chunk_tokens.value()
        config.save(self.settings)

        arguments = [
            "--input", str(source), "--output", str(output),
            "--voice", self.voice.currentText(),
            "--chunk-tokens", str(self.chunk_tokens.value()),
        ]
        if getattr(sys, "frozen", False):
            program = sys.executable
            arguments.insert(0, "--narrator-worker")
        else:
            program = sys.executable
            arguments[:0] = ["-u", "-m", "lab_hub.tools.narrator.converter"]

        self.log.clear()
        self.log.appendPlainText(f"Book: {source.name}\nOutput: {output}\nVoice: {self.voice.currentText()}\n")
        self.progress.setRange(0, 0)
        self.run_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.status.setText("Running…")

        self.process = QProcess(self)
        self.process.setWorkingDirectory(str(Path(__file__).resolve().parents[1]))
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._read_output)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._process_error)
        self.process.start(program, arguments)

    def _read_output(self) -> None:
        if self.process is None:
            return
        text = bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace")
        if text:
            self.log.insertPlainText(text.replace("\r", "\n"))
            self.log.ensureCursorVisible()

    def stop(self) -> None:
        if self.is_running():
            self.status.setText("Stopping…")
            self.stop_button.setEnabled(False)
            self.process.terminate()

    def wait_for_stop(self, msecs: int = 15000) -> None:
        if not self.is_running():
            return
        self.process.terminate()
        if not self.process.waitForFinished(msecs):
            self.process.kill()
            self.process.waitForFinished(3000)

    def _finished(self, exit_code: int, _status) -> None:
        self._read_output()
        self.progress.setRange(0, 1)
        self.progress.setValue(1 if exit_code == 0 else 0)
        self.run_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.status.setText("Done." if exit_code == 0 else f"Stopped or failed (exit {exit_code}).")
        self.process = None

    def _process_error(self, _error) -> None:
        if self.process is not None:
            self.log.appendPlainText(f"\nCould not run Narrator: {self.process.errorString()}")
