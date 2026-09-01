"""Main window: launcher and integrated lab tools."""

from __future__ import annotations

import time

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMainWindow, QMessageBox, QStatusBar, QTabWidget

from lab_hub import APP_NAME, asset_path, config, launcher, login_item

from . import dock, theme, tray
from .apps_tab import AppsTab
from .convert_tab import ConvertTab
from .images_tab import ImagesTab
from .narrator_tab import NarratorTab
from .settings_tab import SettingsTab

# Long enough for macOS's fullscreen-exit animation to finish before the
# window is hidden out from under it.
FULLSCREEN_EXIT_MS = 450
REOPEN_GRACE_MS = 1000
WAKE_POLL_MS = 30_000
WAKE_GAP_SECONDS = 60


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = config.load()
        self.tray: tray.Tray | None = None
        self._quitting = False
        self._warned_about_hiding = False
        self._hidden_at = 0.0

        self.setWindowTitle(APP_NAME)
        self.resize(1020, 820)
        self.setMinimumSize(760, 580)

        self.tabs = QTabWidget()
        self.tabs.tabBar().setExpanding(False)
        self.tabs.tabBar().setDrawBase(False)

        self.apps_tab = AppsTab(self.settings, apps=launcher.PRIMARY_APPS)
        self.backup_sync_tab = AppsTab(
            self.settings,
            apps=launcher.BACKUP_SYNC_APPS,
            title="Backup & Sync",
            intro=(
                "Run backups and keep the lab's repositories synchronized. "
                "Each control center opens in its own window."
            ),
        )
        self.convert_tab = ConvertTab(self.settings)
        self.narrator_tab = NarratorTab(self.settings)
        self.images_tab = ImagesTab(self.settings)
        self.unblock_tracker_tab = AppsTab(
            self.settings,
            apps=launcher.TOOL_APPS,
            title="Unblock Tracker",
            intro="Open the tracker to monitor an Instagram profile's block status.",
        )
        self.settings_tab = SettingsTab(self.settings)

        self.tools_tabs = QTabWidget()
        self.tools_tabs.tabBar().setExpanding(False)
        self.tools_tabs.addTab(self.convert_tab, "Convert Files")
        self.tools_tabs.addTab(self.narrator_tab, "Narrator")
        self.tools_tabs.addTab(self.images_tab, "Prepare Images")
        self.tools_tabs.addTab(self.unblock_tracker_tab, "Unblock Tracker")

        self.tabs.addTab(self.apps_tab, "Apps")
        self.tabs.addTab(self.backup_sync_tab, "Backup & Sync")
        self.tabs.addTab(self.tools_tabs, "Tools")
        self.tabs.addTab(self.settings_tab, "Settings")
        self.setCentralWidget(self.tabs)

        self.setStatusBar(QStatusBar())

        self.apps_tab.launched.connect(self._on_launched)
        self.backup_sync_tab.launched.connect(self._on_launched)
        self.unblock_tracker_tab.launched.connect(self._on_launched)
        self.settings_tab.settings_saved.connect(self._on_settings_saved)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.tools_tabs.currentChanged.connect(self._on_tool_tab_changed)

        # Qt timers pause while macOS sleeps. A large monotonic gap on the next
        # tick is therefore a reliable resume signal without a macOS-only GUI
        # dependency. Keep the three menu-bar apps alive, but never raise them.
        self._last_wake_poll = time.monotonic()
        self._wake_poll = QTimer(self)
        self._wake_poll.setInterval(WAKE_POLL_MS)
        self._wake_poll.timeout.connect(self._check_for_wake)
        self._wake_poll.start()

    # ------------------------------------------------------------------
    # Menu bar item
    # ------------------------------------------------------------------
    def install_tray(self) -> None:
        """Add the menu bar item, if this system has a menu bar to add it to."""
        if not tray.available():
            return
        self.tray = tray.Tray(self.settings.resolved_lab_root, self)
        self.tray.open_requested.connect(self.present)
        self.tray.quit_requested.connect(self.quit)
        self.tray.launched.connect(self._on_launched)
        self.tray.launch_failed.connect(self._on_launch_failed)
        self.tray.show()

    def present(self) -> None:
        """Bring the window up — from the menu bar, or from a second launch."""
        # Back into the Dock first: a window belonging to an Accessory app
        # cannot properly take focus, so the order matters.
        dock.show_in_dock()

        # show(), not showMaximized(): a hidden window remembers its geometry,
        # so summoning it restores whatever size the user last chose instead of
        # overriding it every time.
        self.show()
        self.setWindowState(
            self.windowState() & ~self.windowState().WindowMinimized
        )
        self.raise_()
        self.activateWindow()

    # ------------------------------------------------------------------
    def _on_launched(self, message: str) -> None:
        self.statusBar().showMessage(message, 8000)

    def _on_launch_failed(self, name: str, message: str) -> None:
        # Raised first: a modal warning parented to a hidden window is a modal
        # warning nobody can see.
        self.present()
        QMessageBox.warning(self, f"Could not launch {name}", message)

    def _on_settings_saved(self) -> None:
        self.apps_tab.apply_settings(self.settings)
        self.backup_sync_tab.apply_settings(self.settings)
        self.unblock_tracker_tab.apply_settings(self.settings)
        self.statusBar().showMessage("Settings saved.", 4000)

    def _on_tab_changed(self, index: int) -> None:
        # Calibre may have been installed since startup, and an app may have
        # been built since the tab was last looked at.
        widget = self.tabs.widget(index)
        if widget is self.tools_tabs:
            self._refresh_tool_tab(self.tools_tabs.currentWidget())
        elif widget in (self.apps_tab, self.backup_sync_tab):
            widget.refresh()

    def _on_tool_tab_changed(self, index: int) -> None:
        self._refresh_tool_tab(self.tools_tabs.widget(index))

    def _refresh_tool_tab(self, widget) -> None:
        if widget is self.convert_tab:
            self.convert_tab.refresh_calibre()
        elif widget is self.unblock_tracker_tab:
            widget.refresh()

    def _check_for_wake(self) -> None:
        now = time.monotonic()
        gap = now - self._last_wake_poll
        self._last_wake_poll = now
        if gap >= WAKE_GAP_SECONDS:
            self.start_sync_apps_in_background()

    def start_sync_apps_in_background(self) -> None:
        """Ensure the two sync companions are running without showing them."""
        lab_root = self.settings.resolved_lab_root()
        table = launcher.process_table()
        for app in launcher.BACKUP_SYNC_APPS:
            if launcher.is_running(app, lab_root, table):
                continue
            try:
                launcher.launch(app, lab_root, background=True)
            except launcher.LaunchError as error:
                self.statusBar().showMessage(
                    f"Could not start {app.name} in the background: {error}", 8000
                )

    # ------------------------------------------------------------------
    def _running_panels(self):
        return [
            panel
            for panel in (self.convert_tab.run_panel, self.images_tab.run_panel, self.narrator_tab)
            if panel.is_running()
        ]

    def quit(self) -> None:
        """Really quit — as opposed to closing the window, which only hides it."""
        from PySide6.QtWidgets import QApplication

        running = self._running_panels()
        if running:
            self.present()
            answer = QMessageBox.question(
                self,
                "A tool is still running",
                "Stop it and quit?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._quitting = True
        QApplication.quit()

    def shutdown(self) -> None:
        """Stop worker threads before the process goes. Qt aborts if a QThread
        is destroyed while still running, so this is not optional."""
        for panel in self._running_panels():
            panel.wait_for_stop()
        if self.tray is not None:
            self.tray.hide()

    def _hide_to_menu_bar(self) -> None:
        """Hide the window, leaving fullscreen first if it is in it.

        macOS keeps the fullscreen Space when a fullscreen window is hidden:
        the app vanishes but its Space stays, so you are left staring at an
        empty black screen with no window to close or minimise, and no obvious
        way back. Dropping out of fullscreen first is the only thing that
        releases the Space.

        The hide is deferred because leaving fullscreen is an animated,
        asynchronous transition — hiding in the same breath races it and lands
        back in the same stuck state.
        """
        if self.windowState() & Qt.WindowState.WindowFullScreen:
            self.setWindowState(self.windowState() & ~Qt.WindowState.WindowFullScreen)
            QTimer.singleShot(FULLSCREEN_EXIT_MS, self._hide_now)
            return
        self._hide_now()

    def _hide_now(self) -> None:
        """Hide and timestamp it so macOS's activation echo cannot reopen us."""
        self._hidden_at = time.monotonic()
        self.hide()
        # Nothing left on screen, so nothing for the Dock to point at. The menu
        # bar item is unaffected: a status item does not depend on the
        # activation policy, which is what makes this switch safe.
        if self.tray is not None:
            dock.hide_from_dock()

    def reopen_allowed(self) -> bool:
        """Return whether an activation is late enough to be a real Dock click."""
        return (time.monotonic() - self._hidden_at) * 1000 > REOPEN_GRACE_MS

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        # With a menu bar item present, the red button hides rather than quits —
        # otherwise closing the window would strand a still-running conversion
        # with no way back to its log.
        if self.tray is not None and not self._quitting:
            event.ignore()
            self._hide_to_menu_bar()
            if not self._warned_about_hiding:
                self._warned_about_hiding = True
                self.tray.notify(
                    APP_NAME,
                    "Still running in the menu bar. Quit it from there.",
                )
            return

        running = self._running_panels()
        if running and not self._quitting:
            answer = QMessageBox.question(
                self,
                "A tool is still running",
                "Stop it and quit?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        for panel in running:
            panel.wait_for_stop()
        event.accept()


def run() -> int:
    """Create the application and show the window."""
    import sys

    from PySide6.QtWidgets import QApplication

    from .single_instance import SingleInstance

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontShowIconsInMenus, False)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)

    guard = SingleInstance()
    if not guard.acquire():
        # Another copy is already up and has been told to come forward. Say so
        # on stdout for anyone who started this from a terminal, and go quietly.
        print(f"{APP_NAME} is already running — bringing it to the front.")
        return 0

    theme.apply(app)

    # Closing the window leaves the app in the menu bar, so the last window
    # closing must not end the process.
    app.setQuitOnLastWindowClosed(not tray.available())

    # A packaged .app takes its Dock icon from the bundle; this covers running
    # from source, where there is no bundle to read.
    icon_file = asset_path("icon.icns")
    if icon_file.exists():
        app.setWindowIcon(QIcon(str(icon_file)))

    window = MainWindow()
    window.install_tray()
    guard.activated.connect(window.present)
    app.aboutToQuit.connect(window.shutdown)
    app.aboutToQuit.connect(guard.release)

    _Reopener(window, app)

    # Started by the login agent: stay in the menu bar instead of opening a
    # window nobody asked for. Only honoured when there *is* a menu bar item to
    # retreat to — otherwise the app would run with no way to reach it.
    if login_item.BACKGROUND_FLAG in sys.argv and window.tray is not None:
        # Started by the login agent with no window, so it should not be in the
        # Dock either — it is a menu bar resident until asked for.
        #
        # Deferred to the first turn of the event loop: Qt's cocoa plugin sets
        # its own activation policy while it finishes starting up, and a call
        # made before that simply gets overwritten. Running from source it
        # appeared to work, because nothing there re-asserted it afterwards.
        QTimer.singleShot(0, dock.hide_from_dock)
        window.statusBar().showMessage(f"{APP_NAME} started in the menu bar.", 5000)
        QTimer.singleShot(0, window.start_sync_apps_in_background)
    else:
        # The bundle declares LSUIElement so a login start has no Dock icon;
        # a normal launch shows a window, so it has to promote itself back.
        dock.show_in_dock()
        window.showMaximized()
    return app.exec()


class _Reopener(QObject):
    """Bring the window back when the app is switched to with nothing on screen.

    Watches application *state*, not the ApplicationActivate event. Closing the
    window leaves the app active and still delivers that event, so filtering on
    it re-showed the window in the same breath as closing it — a window that is
    visible but was never repainted, i.e. a black rectangle. A state change only
    fires on a real inactive → active transition, which closing a window is not.
    """

    def __init__(self, window: MainWindow, app) -> None:
        super().__init__(app)
        self._window = window
        self._was_active = app.applicationState() == Qt.ApplicationState.ApplicationActive
        app.applicationStateChanged.connect(self._on_state_changed)

    def _on_state_changed(self, state) -> None:
        active = state == Qt.ApplicationState.ApplicationActive
        became_active = active and not self._was_active
        self._was_active = active
        if (
            became_active
            and not self._window.isVisible()
            and self._window.reopen_allowed()
        ):
            self._window.present()
