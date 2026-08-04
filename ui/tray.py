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

from lab_hub import APP_NAME, asset_path, launcher


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
    quit_requested = Signal()
    launched = Signal(str)
    launch_failed = Signal(str, str)  # app name, message

    def __init__(self, resolve_lab_root, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._resolve_lab_root = resolve_lab_root

        self.icon = QSystemTrayIcon(_icon(), self)
        self.icon.setToolTip(APP_NAME)

        menu = QMenu()

        open_action = QAction(f"Open {APP_NAME}", menu)
        open_action.triggered.connect(self.open_requested)
        menu.addAction(open_action)

        # Mirrors the Apps tab, launchpad only — the menu bar is for the things
        # reached for without thinking.
        menu.addSeparator()
        for app in launcher.LAUNCHPAD:
            action = QAction(app.name, menu)
            action.triggered.connect(lambda _checked=False, a=app: self._launch(a))
            menu.addAction(action)

        menu.addSeparator()
        quit_action = QAction(f"Quit {APP_NAME}", menu)
        quit_action.triggered.connect(self.quit_requested)
        menu.addAction(quit_action)

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
        try:
            message = launcher.launch(app, self._resolve_lab_root())
        except launcher.LaunchError as error:
            self.launch_failed.emit(app.name, str(error))
            return
        self.launched.emit(message)
