"""Pieces every tool tab reuses: a folder field, and the run/log panel."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from lab_hub.tools import Reporter, Result

from . import theme
from .worker import JobWorker

# How many lines of log to keep. Long conversions are chatty and an unbounded
# document eventually costs more to lay out than the work being reported.
LOG_LIMIT = 2000


class FolderField(QWidget):
    """A path box with a Browse button."""

    def __init__(self, placeholder: str = "Choose a folder…", parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.setClearButtonEnabled(True)

        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)

        layout.addWidget(self.edit, 1)
        layout.addWidget(browse)

    def _browse(self) -> None:
        start = self.text() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "Choose a folder", start)
        if chosen:
            self.edit.setText(chosen)

    def text(self) -> str:
        return self.edit.text().strip()

    def set_text(self, value: str) -> None:
        self.edit.setText(value)

    def path(self) -> Path:
        return Path(self.text()).expanduser()


class RunPanel(QWidget):
    """Run/Stop, a progress bar, and the log — plus the worker behind them."""

    running_changed = Signal(bool)

    def __init__(self, run_label: str = "Run", parent=None) -> None:
        super().__init__(parent)
        self._build_job: Callable[[], Callable[[Reporter], Result]] | None = None
        self.worker: JobWorker | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        controls = QHBoxLayout()
        controls.setSpacing(10)

        self.run_button = QPushButton(run_label)
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
        self.progress.setValue(0)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(LOG_LIMIT)
        self.log.setPlaceholderText("Output appears here.")
        self.log.setMinimumHeight(200)

        layout.addLayout(controls)
        layout.addWidget(self.progress)
        layout.addWidget(self.log, 1)

    # ------------------------------------------------------------------
    def bind(self, build_job: Callable[[], Callable[[Reporter], Result]]) -> None:
        """Supply the factory called on each Run.

        It runs on the GUI thread and may raise ValueError to reject the form —
        that becomes a dialog rather than a failed run.
        """
        self._build_job = build_job

    def is_running(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    # ------------------------------------------------------------------
    def start(self) -> None:
        if self._build_job is None or self.is_running():
            return
        try:
            job = self._build_job()
        except ValueError as problem:
            QMessageBox.warning(self, "Not ready to run", str(problem))
            return

        self.log.clear()
        self.progress.setRange(0, 0)  # indeterminate until the tool counts up
        self._set_running(True)

        self.worker = JobWorker(job, self)
        self.worker.log_line.connect(self.append)
        self.worker.progressed.connect(self._on_progress)
        self.worker.succeeded.connect(self._on_succeeded)
        self.worker.failed.connect(self._on_failed)
        self.worker.stopped.connect(self._on_stopped)
        self.worker.start()

    def stop(self) -> None:
        if self.worker is not None:
            self.status.setText("Stopping after the current item…")
            self.stop_button.setEnabled(False)
            self.worker.stop()

    def wait_for_stop(self, msecs: int = 15000) -> None:
        if self.worker is not None:
            self.worker.stop()
            self.worker.wait(msecs)

    # ------------------------------------------------------------------
    def append(self, message: str) -> None:
        self.log.appendPlainText(message)

    def _set_running(self, running: bool) -> None:
        self.run_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        if running:
            self.status.setText("Running…")
        self.running_changed.emit(running)

    def _on_progress(self, done: int, total: int) -> None:
        if total <= 0:
            self.progress.setRange(0, 0)
            return
        self.progress.setRange(0, total)
        self.progress.setValue(done)
        self.status.setText(f"Running… {done}/{total}")

    def _finish(self, message: str) -> None:
        self.progress.setRange(0, 1)
        self._set_running(False)
        self.status.setText(message)
        self.worker = None

    def _on_succeeded(self, summary: str) -> None:
        self.progress.setValue(self.progress.maximum())
        self._finish(f"Done — {summary}.")
        self.append(f"\nDone — {summary}.")

    def _on_failed(self, error: str) -> None:
        self._finish("Failed.")
        self.append(f"\nFailed: {error}")
        QMessageBox.critical(self, "The run failed", error)

    def _on_stopped(self) -> None:
        self.progress.setValue(0)
        self._finish("Stopped.")
        self.append("\nStopped.")


def scroll_column(spacing: int = 18) -> tuple[QWidget, QVBoxLayout]:
    """A centred content column inside a vertical scroll area."""
    from PySide6.QtWidgets import QScrollArea

    inner, layout = theme.column(spacing)
    layout.setContentsMargins(24, 20, 24, 24)

    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setWidget(inner)
    return area, layout
