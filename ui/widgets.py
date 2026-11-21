"""Pieces every tool tab reuses: a folder field, and the run/log panel."""

from __future__ import annotations

import html
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
    QSizePolicy,
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
        layout.setSpacing(theme.SPACE_S)

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
        layout.setSpacing(theme.SPACE_M)

        controls = QHBoxLayout()
        controls.setSpacing(theme.SPACE_M)

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


def plain_tip(text: str) -> str:
    """A tooltip that shows `text` as typed. Qt renders a tooltip as rich text
    when it looks like HTML, and this text is git, pytest and Claude output, or
    a name read from a file."""
    return "<qt>" + html.escape(text).replace("\n", "<br>") + "</qt>"


# Widgets taken out of a layout and waiting for `deleteLater`; see `discard_widget`.
_DISCARDED: set = set()


def discard_widget(layout, widget: QWidget) -> None:
    """Take a widget out of a layout and have it deleted once the event loop runs.

    Unparented first: a row taken out with `removeWidget` and left to its parent
    was deleted a second time when the parent went (a segfault seen in the
    suite). Python then owns it, so it is kept alive until Qt has really
    deleted it: it may be the row whose button is mid-click, and dropping the
    last reference there would delete the button under its own signal.
    """
    layout.removeWidget(widget)
    widget.hide()
    widget.setParent(None)
    _DISCARDED.add(widget)
    widget.destroyed.connect(lambda _obj=None, w=widget: _DISCARDED.discard(w))
    widget.deleteLater()


class ElidedLabel(QLabel):
    """One line of plain text that shortens itself instead of widening its row.

    A QLabel's minimum width is its text's width, so a long name (a README
    heading, a folder name) would push a card wider than the window. This one
    keeps the full text, shows as much as fits with an ellipsis, and puts the
    full text in its tooltip while it is cut. It shows the text whole until Qt
    has given it a size, so a label nobody has laid out reads as typed.
    """

    def __init__(
        self,
        text: str = "",
        mode: Qt.TextElideMode = Qt.TextElideMode.ElideRight,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._full = ""
        self._note = ""
        self._mode = mode
        self._sized = False
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.setText(text)

    def fullText(self) -> str:
        return self._full

    def setText(self, text: str) -> None:  # noqa: N802 - Qt override
        self._full = text
        self._elide()

    def setNote(self, note: str) -> None:  # noqa: N802 - mirrors setText
        """Tooltip text that stays whether or not the text is cut."""
        self._note = note
        self._elide()

    def sizeHint(self):  # noqa: N802 - Qt override
        hint = super().sizeHint()
        hint.setWidth(self.fontMetrics().horizontalAdvance(self._full) + 2)
        return hint

    def minimumSizeHint(self):  # noqa: N802 - Qt override
        hint = super().minimumSizeHint()
        hint.setWidth(0)
        return hint

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._sized = True
        self._elide()

    def _elide(self) -> None:
        shown = self._full
        if self._sized:
            shown = self.fontMetrics().elidedText(self._full, self._mode, max(self.width(), 0))
        super().setText(shown)
        parts = ([self._full] if shown != self._full else []) + ([self._note] if self._note else [])
        self.setToolTip(plain_tip("\n".join(parts)) if parts else "")


def scroll_column(spacing: int = theme.SPACE_L, max_width: int | None = None) -> tuple[QWidget, QVBoxLayout]:
    """A centred content column inside a vertical scroll area."""
    from PySide6.QtWidgets import QScrollArea

    inner, layout = theme.column(spacing, max_width)
    layout.setContentsMargins(theme.SPACE_XL, theme.SPACE_XL, theme.SPACE_XL, theme.SPACE_XL)

    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setWidget(inner)
    return area, layout
