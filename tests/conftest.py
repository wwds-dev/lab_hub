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


@pytest.fixture(scope="session", autouse=True)
def no_site_checks():
    """Keep the Websites tab off the network for the whole session.

    Its checks start whenever the tab is shown — and a swipe test or a tab
    switch shows it — so a guard per test would leave whichever test happened
    to reveal it reaching altmerch.store. Session-scoped, so it is in force
    before any fixture builds a window. Records what would have been asked.
    """
    from ui import links_tab

    asked: list[str] = []
    original = links_tab.SiteChecker.check
    links_tab.SiteChecker.check = lambda self, site: asked.append(site.key)
    yield asked
    links_tab.SiteChecker.check = original


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


@pytest.fixture(autouse=True)
def _collect_qt_garbage():
    """Destroy each test's abandoned Qt objects before the next test starts.

    Tests build widgets and drop them. Left to the garbage collector, they piled
    up across tests and were destroyed together whenever an allocation happened
    to trigger a collection — sometimes in the middle of a later test — and on
    runs where that timing lined up (reliably, the first run after a test file
    was edited) the interpreter died with SIGSEGV. Collecting after every test
    destroys them one test's worth at a time, in a known place.
    """
    yield
    import gc

    from PySide6.QtCore import QCoreApplication, QEvent

    if QCoreApplication.instance() is not None:
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gc.collect()
