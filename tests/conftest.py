"""Shared fixtures.

Everything runs on Qt's offscreen platform so the suite needs no display and
never steals focus. The window-lifecycle tests deliberately do *not* create a
real QSystemTrayIcon — offscreen has no system tray, and a test that depends on
one would pass or fail based on the machine rather than the code. They inject
`FakeTray` instead; what those tests are checking is `MainWindow`'s branching on
"is there a tray", not Qt's tray implementation.
"""

from __future__ import annotations

import os

import pytest

# Must be set before QApplication exists.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from lab_hub import config  # noqa: E402

from .fakes import FakeTray  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    """One QApplication for the whole session — Qt allows no more than one."""
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Point settings at a scratch file.

    Without this a test run would read — and `config.save` would overwrite —
    the real ~/Library/Application Support/Lab Hub/config.json.
    """
    support = tmp_path / "Application Support" / "Lab Hub"
    monkeypatch.setattr(config, "SUPPORT_DIR", support)
    monkeypatch.setattr(config, "CONFIG_PATH", support / "config.json")
    return support


@pytest.fixture
def fake_tray():
    return FakeTray()


@pytest.fixture
def window(qapp, isolated_config):
    """A MainWindow with no tray installed. Tests add `FakeTray` if they want one."""
    from ui.main_window import MainWindow

    win = MainWindow()
    yield win
    win._quitting = True
    win.close()
    win.deleteLater()
