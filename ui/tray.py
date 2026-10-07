"""The menu bar item.

macOS does not send a plain click to a status item that owns a menu — the menu
opens instead. So there is no click-to-open behaviour to write: "Open Lab Hub"
is simply the first item, and the rest of the menu earns its place by launching
the standalone apps without opening the window at all.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from lab_hub import APP_NAME, asset_path, dashboards, launcher, sites

from .web_open import OpenWhenServing

# How long a web app launched from the menu gets to start answering before
# its page is given up on. Matches the tile's own wait.
SERVER_WAIT_SECONDS = 60.0


def available() -> bool:
    return QSystemTrayIcon.isSystemTrayAvailable()


def _icon() -> QIcon:
    """The menu bar glyph, as a template image.

    setIsMask makes macOS recolour it for a light or dark menu bar and for the
    highlighted state. Without it the icon stays black and vanishes into a dark
    menu bar.
    """
    icon = QIcon(str(asset_path("tray.png")))
    icon.setIsMask(True)
    return icon


class Tray(QObject):
    open_requested = Signal()
    menu_opened = Signal()
    quit_requested = Signal()
    launched = Signal(str)
    launch_failed = Signal(str, str)  # app name, message

    def __init__(self, resolve_lab_root, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._resolve_lab_root = resolve_lab_root
        self._openers: dict[str, OpenWhenServing] = {}

        self.icon = QSystemTrayIcon(_icon(), self)
        self.icon.setToolTip(APP_NAME)

        menu = QMenu()

        open_action = QAction(f"Open {APP_NAME}", menu)
        open_action.triggered.connect(self.open_requested)
        menu.addAction(open_action)

        # Top-level apps only. Companions (VPN Agent, Bug Spray, vidforge) are
        # reached from their suite; listing them here as peers makes the menu
        # half again as long and hides what is actually reached for.
        menu.addSeparator()
        for app in launcher.MENU_BAR_APPS:
            action = QAction(app.name, menu)
            action.triggered.connect(lambda _checked=False, a=app: self._launch(a))
            menu.addAction(action)

        # The two link tabs, one submenu each. Websites are fixed; dashboards
        # are re-read from the catalog every time the menu opens, so one added
        # there is here without a restart.
        menu.addSeparator()
        self.sites_menu = menu.addMenu("Websites")
        for site in sites.SITES:
            action = QAction(site.name, self.sites_menu)
            action.triggered.connect(
                lambda _checked=False, s=site: self._open(s.name, s.url)
            )
            self.sites_menu.addAction(action)
        self.dashboards_menu = menu.addMenu("Dashboards")
        self._fill_dashboards()

        menu.addSeparator()
        quit_action = QAction(f"Quit {APP_NAME}", menu)
        quit_action.triggered.connect(self.quit_requested)
        menu.addAction(quit_action)

        # Opening the menu activates the app. That activation must not be
        # mistaken for the user asking for the window back.
        menu.aboutToShow.connect(self.menu_opened)
        menu.aboutToShow.connect(self._fill_dashboards)

        # Held on the instance: a QMenu that only the tray icon references is
        # garbage collected out from under it, and the menu comes up empty.
        self._menu = menu
        self.icon.setContextMenu(menu)

    def show(self) -> None:
        self.icon.show()

    def hide(self) -> None:
        self.icon.hide()

    def notify(self, title: str, message: str) -> None:
        self.icon.showMessage(title, message, _icon(), 4000)

    def _launch(self, app: launcher.ExternalApp) -> None:
        lab_root = self._resolve_lab_root()
        # The desktop apps hand a second launch to the copy already running.
        # A web app would start a second server instead, so open the one that
        # is up.
        if app.served and launcher.is_running(app, lab_root):
            self._open(app.name, app.url)
            return
        try:
            message = launcher.launch(app, lab_root)
        except launcher.LaunchError as error:
            self.launch_failed.emit(app.name, str(error))
            return
        if app.served:
            self._opener(app).start(SERVER_WAIT_SECONDS)
        self.launched.emit(message)

    def _opener(self, app: launcher.ExternalApp) -> OpenWhenServing:
        """One watcher per web app, made on first use and reused after."""
        opener = self._openers.get(app.key)
        if opener is None:
            opener = OpenWhenServing(app, self)
            opener.opened.connect(self.launched)
            opener.gave_up.connect(
                lambda message, name=app.name: self.launch_failed.emit(name, message)
            )
            self._openers[app.key] = opener
        return opener

    def _fill_dashboards(self) -> None:
        """Rebuild the Dashboards submenu from the catalog."""
        self.dashboards_menu.clear()
        try:
            entries = dashboards.load(self._resolve_lab_root())
        except dashboards.CatalogError as error:
            missing = QAction(str(error), self.dashboards_menu)
            missing.setEnabled(False)
            self.dashboards_menu.addAction(missing)
            return
        for entry in entries:
            action = QAction(entry.title, self.dashboards_menu)
            action.setEnabled(entry.available())
            action.triggered.connect(
                lambda _checked=False, e=entry: self._open(e.title, dashboards.target(e))
            )
            self.dashboards_menu.addAction(action)

    def _open(self, name: str, address: str) -> None:
        try:
            launcher.open_url(address)
        except launcher.LaunchError as error:
            self.launch_failed.emit(name, str(error))
            return
        self.launched.emit(f"Opened {name}")
