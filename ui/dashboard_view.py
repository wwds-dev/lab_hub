"""The Dashboards page: a list on the left, the chosen dashboard showing on the right.

Each dashboard is shown in a web view of its own, created the first time it is chosen
and kept, so switching back finds it where you left it. Links to claude.ai artifacts
need a claude.ai sign-in, which the views keep in a profile of their own under
Application Support (never the browser's). The tiles are still here, one click away,
for anything that will not embed.

QtWebEngine is imported on first use, so the window starts without it, a build
without it still runs, and the tests need not load a browser.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import QSize, QUrl, Signal
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from lab_hub import config, dashboards, launcher

from . import theme
from .tiles import Refreshable

PROFILE_NAME = "LabHubDashboards"


def web_available() -> bool:
    try:
        from PySide6 import QtWebEngineWidgets  # noqa: F401
    except ImportError:
        return False
    return True


_warmed = False


def warm_up_web_engine() -> bool:
    """Start QtWebEngine once, early, so opening Dashboards later cannot leave fullscreen.

    On macOS the first web view of a run takes the window out of native fullscreen
    when it is first shown (verified with PySide6 6.12: lazy first view -> fullscreen
    lost; any earlier view, even a discarded one -> kept). Without this, going
    fullscreen and then opening Dashboards for the first time threw the window back
    to normal size. The view is off the record and deleted at once; the real views
    keep their own persistent profile. Returns True when it started the engine.
    """
    global _warmed
    if _warmed or not web_available():
        return False
    _warmed = True
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
    from PySide6.QtWebEngineWidgets import QWebEngineView

    profile = QWebEngineProfile()  # no name: off the record, nothing written to disk
    view = QWebEngineView()
    page = QWebEnginePage(profile, view)
    view.setPage(page)
    # Page before profile: Qt warns, and on some versions aborts, when a profile goes first.
    page.deleteLater()
    view.deleteLater()
    profile.deleteLater()
    return True


def _real_view_factory(page_owner: QWidget) -> Callable[[], QWidget]:
    """Build web views that share one persistent profile and open new windows outside."""
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
    from PySide6.QtWebEngineWidgets import QWebEngineView

    profile = QWebEngineProfile(PROFILE_NAME, page_owner)
    storage = config.SUPPORT_DIR / "web"
    storage.mkdir(parents=True, exist_ok=True)
    profile.setPersistentStoragePath(str(storage))
    profile.setCachePath(str(storage / "cache"))
    profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)

    class Page(QWebEnginePage):
        def createWindow(self, _type):  # a target=_blank link: the system browser
            holder = QWebEnginePage(profile, self)
            holder.urlChanged.connect(lambda url: (launcher.open_url(url.toString()), holder.deleteLater()))
            return holder

    def make() -> QWidget:
        view = QWebEngineView()
        page = Page(profile, view)
        # The window's own colour until the dashboard paints: the default white
        # flashed for a moment before the first dashboard of a run appeared.
        page.setBackgroundColor(page_owner.palette().color(QPalette.ColorRole.Window))
        view.setPage(page)
        return view

    make.profile = profile  # type: ignore[attr-defined]
    return make


class DashboardViewer(QWidget, Refreshable):
    """The list and the views."""

    opened = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        settings: config.Settings,
        view_factory: Callable[[], QWidget] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self._factory = view_factory
        self._views: dict[tuple[str, bool], QWidget] = {}
        self.entries: tuple[dashboards.Dashboard, ...] = ()
        self._stamp: tuple[str, int] | None = None
        self.prefer_local = False
        self._active = False

        self.list = QListWidget()
        self.list.setMinimumWidth(200)
        self.list.setMaximumWidth(300)
        self.list.currentRowChanged.connect(self._show_row)

        self.stack = QStackedWidget()
        self.message = theme.empty_state("")
        self.stack.addWidget(self.message)

        self.reload_button = QPushButton("Reload")
        self.reload_button.clicked.connect(self._reload_view)
        self.source_button = QPushButton("Show local copy")
        self.source_button.clicked.connect(self._toggle_source)
        self.browser_button = QPushButton("Open in browser")
        self.browser_button.clicked.connect(self._open_in_browser)
        self.reveal_button = QPushButton("Show in Finder")
        self.reveal_button.clicked.connect(self._reveal)
        self.where = QLabel()
        self.where.setObjectName("hint")
        bar = QHBoxLayout()
        bar.addWidget(self.where, 1)
        for button in (self.source_button, self.reload_button, self.browser_button, self.reveal_button):
            bar.addWidget(button)

        right = QWidget()
        column = QVBoxLayout(right)
        column.setContentsMargins(0, 0, 0, 0)
        column.addLayout(bar)
        column.addWidget(self.stack, 1)

        split = QSplitter()
        split.addWidget(self.list)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(split)

        self.reload()

    # ------------------------------------------------------------------
    def lab_root(self) -> Path:
        return self.settings.resolved_lab_root()

    def _catalog_stamp(self) -> tuple[str, int] | None:
        path = dashboards.catalog_path(self.lab_root())
        try:
            return str(path), path.stat().st_mtime_ns
        except OSError:
            return None

    def reload(self) -> None:
        self._stamp = self._catalog_stamp()
        keep = self.current_entry().id if self.current_entry() else None
        try:
            self.entries = dashboards.load(self.lab_root())
            note = "" if self.entries else "The catalog lists no dashboards."
        except dashboards.CatalogError as error:
            self.entries, note = (), str(error)
        self.list.blockSignals(True)
        self.list.clear()
        for entry in self.entries:
            item = QListWidgetItem(f"{entry.title}\n{entry.where_label} · {entry.kind}")
            item.setSizeHint(QSize(0, 48))
            item.setToolTip(entry.description)
            self.list.addItem(item)
        self.list.blockSignals(False)
        self.message.setText(note or "Choose a dashboard.")
        if self.entries:
            row = next((i for i, e in enumerate(self.entries) if e.id == keep), 0)
            self.list.setCurrentRow(row)
            self._show_row(row)
        else:
            self.stack.setCurrentWidget(self.message)
            self._update_bar(None)

    def refresh(self) -> None:
        if self._catalog_stamp() != self._stamp:
            self.reload()

    def recheck(self) -> None:
        self.reload()

    # ------------------------------------------------------------------
    def current_entry(self) -> dashboards.Dashboard | None:
        row = self.list.currentRow()
        return self.entries[row] if 0 <= row < len(self.entries) else None

    def address(self, entry: dashboards.Dashboard) -> str | None:
        return dashboards.embed_address(entry, self.prefer_local)

    def activate(self) -> None:
        """Start loading: nothing is fetched until the page is actually on screen."""
        if not self._active:
            self._active = True
            self._show_row(self.list.currentRow())

    def showEvent(self, event) -> None:  # noqa: N802 - Qt
        super().showEvent(event)
        self.activate()

    def _view_for(self, entry: dashboards.Dashboard) -> QWidget | None:
        address = self.address(entry)
        if address is None or not self._active:
            return None
        key = (entry.id, address.startswith("file:") or "127.0.0.1" in address)
        view = self._views.get(key)
        if view is None:
            if self._factory is None:
                if not web_available():
                    return None
                self._factory = _real_view_factory(self)
            view = self._factory()
            view.setUrl(QUrl(address))
            self._views[key] = view
            self.stack.addWidget(view)
        return view

    def _show_row(self, row: int) -> None:
        entry = self.current_entry()
        self._update_bar(entry)
        if entry is None:
            return
        view = self._view_for(entry)
        if view is None:
            if self.address(entry) is None:
                text = "This dashboard has nothing that can be shown here yet."
            elif not self._active:
                text = "Choose a dashboard."
            else:
                text = "The in-window viewer is not part of this build. Use Open in browser."
            self.message.setText(text)
            self.stack.setCurrentWidget(self.message)
        else:
            self.stack.setCurrentWidget(view)

    def _update_bar(self, entry: dashboards.Dashboard | None) -> None:
        both = bool(entry and entry.url and entry.has_file)
        self.source_button.setVisible(both)
        self.source_button.setText("Show link" if self.prefer_local else "Show local copy")
        self.reveal_button.setVisible(bool(entry and entry.has_file))
        self.browser_button.setEnabled(bool(entry and self.address(entry)))
        self.reload_button.setEnabled(bool(entry and self.address(entry)))
        if entry is None:
            self.where.setText("")
            return
        showing = self.address(entry) or "nothing to show"
        self.where.setText(f"{entry.title} — {entry.where_label}: {showing}")

    def _toggle_source(self) -> None:
        self.prefer_local = not self.prefer_local
        self._show_row(self.list.currentRow())

    def _reload_view(self) -> None:
        view = self.stack.currentWidget()
        if hasattr(view, "reload"):
            view.reload()

    def _open_in_browser(self) -> None:
        entry = self.current_entry()
        address = self.address(entry) if entry else None
        if address is None:
            return
        try:
            launcher.open_url(address)
        except launcher.LaunchError as error:
            self.failed.emit(str(error))
            return
        self.opened.emit(f"Opened {entry.title}")

    def _reveal(self) -> None:
        entry = self.current_entry()
        if entry and entry.path and Path(entry.path).is_file():
            launcher.reveal(Path(entry.path))

    def shutdown(self) -> None:
        """Delete every page before the profile they share — Qt warns, and on some
        versions aborts, when a profile goes first."""
        for view in self._views.values():
            page = view.page() if hasattr(view, "page") else None
            if page is not None:
                view.setPage(None) if hasattr(view, "setPage") else None
                page.deleteLater()
        self._views.clear()


class DashboardsPage(QWidget, Refreshable):
    """The sidebar's Dashboards page: the viewer, or the tiles."""

    opened = Signal(str)
    failed = Signal(str)

    def __init__(self, tiles, viewer: DashboardViewer, parent=None) -> None:
        super().__init__(parent)
        self.tiles = tiles
        self.viewer = viewer
        self.stack = QStackedWidget()
        self.stack.addWidget(viewer)
        self.stack.addWidget(tiles)
        self.toggle = QPushButton("Show as tiles")
        self.toggle.clicked.connect(self._toggle)
        top = QHBoxLayout()
        top.setContentsMargins(16, 12, 16, 0)
        top.addWidget(theme.section_title("Dashboards"))
        top.addStretch(1)
        top.addWidget(self.toggle)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(top)
        layout.addWidget(self.stack, 1)
        for source in (tiles, viewer):
            source.opened.connect(self.opened)
            source.failed.connect(self.failed)

    def _toggle(self) -> None:
        showing_viewer = self.stack.currentWidget() is self.viewer
        self.stack.setCurrentWidget(self.tiles if showing_viewer else self.viewer)
        self.toggle.setText("Show in window" if showing_viewer else "Show as tiles")

    def apply_settings(self, settings: config.Settings) -> None:
        self.tiles.apply_settings(settings)
        self.viewer.settings = settings
        self.viewer.reload()

    def refresh(self) -> None:
        self.stack.currentWidget().refresh()

    def recheck(self) -> None:
        self.tiles.recheck()
        self.viewer.recheck()

    def shutdown(self) -> None:
        self.viewer.shutdown()
