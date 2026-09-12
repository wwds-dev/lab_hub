"""Closing, hiding and coming back.

This is the most-broken part of the app's history. Two bugs shipped from here:

* the red button quit the whole app instead of leaving it in the menu bar;
* and then, after that was fixed, closing the window re-showed it instantly —
  the reopen handler filtered on Qt's ApplicationActivate event, which closing
  a window also fires, so the window came back visible but never repainted: a
  black rectangle you could not get rid of.

Both were found by hand. These tests are that hunt, written down.
"""

from __future__ import annotations

from PySide6.QtCore import Qt

import pytest
from PySide6.QtCore import QEvent

from ui.main_window import REOPEN_GRACE_MS, TRAY_SUPPRESS_S, _QuitGuard, _Reopener


def test_close_hides_the_window_when_there_is_a_tray(window, fake_tray):
    """The red button must not quit: the menu bar item is the app's home."""
    window.tray = fake_tray
    window.show()
    assert window.isVisible()

    window.close()

    assert not window.isVisible()
    assert not window._quitting  # still running, just not on screen


def test_close_explains_itself_once(window, fake_tray):
    """A window that vanishes without a word looks like a crash."""
    window.tray = fake_tray
    window.show()

    window.close()
    window.show()
    window.close()

    assert len(fake_tray.notices) == 1, "the notice should not nag on every close"
    title, message = fake_tray.notices[0]
    assert "menu bar" in message.lower()


def test_close_without_a_tray_really_closes(window):
    """No menu bar item means hiding would strand the app with no way back."""
    window.tray = None
    window.show()

    window.close()

    assert not window.isVisible()


def test_activation_while_already_active_does_not_resurrect(window, fake_tray, qapp):
    """The black-window regression.

    Closing the window leaves the app frontmost and still emits an activation
    signal. Acting on that re-showed the window in the same breath as closing
    it. Only a real inactive -> active transition may bring it back.
    """
    window.tray = fake_tray
    window.show()
    reopener = _Reopener(window, qapp)
    reopener._was_active = True  # the app never lost focus

    window.close()
    reopener._on_state_changed(Qt.ApplicationState.ApplicationActive)

    assert not window.isVisible(), "closing the window must not re-show it"


def test_close_activation_echo_does_not_resurrect(window, fake_tray, qapp):
    """macOS briefly deactivates and reactivates an app that hides its window."""
    window.tray = fake_tray
    window.show()
    reopener = _Reopener(window, qapp)

    window.close()
    reopener._on_state_changed(Qt.ApplicationState.ApplicationInactive)
    reopener._on_state_changed(Qt.ApplicationState.ApplicationActive)

    assert not window.isVisible(), "the post-close activation echo must be ignored"


def test_switching_back_to_the_app_restores_the_window(window, fake_tray, qapp):
    """Clicking the Dock icon is the other way back in, and must still work."""
    window.tray = fake_tray
    window.show()
    reopener = _Reopener(window, qapp)

    window.close()
    window._hidden_at -= (REOPEN_GRACE_MS + 200) / 1000
    reopener._was_active = False  # the user went to another app
    reopener._on_state_changed(Qt.ApplicationState.ApplicationActive)

    assert window.isVisible()


def test_reopening_a_visible_window_is_harmless(window, fake_tray, qapp):
    window.tray = fake_tray
    window.show()
    reopener = _Reopener(window, qapp)

    reopener._was_active = False
    reopener._on_state_changed(Qt.ApplicationState.ApplicationActive)

    assert window.isVisible()


def test_quit_marks_the_app_as_quitting(window, fake_tray, monkeypatch):
    """Quit from the menu bar is the deliberate exit, unlike closing."""
    from PySide6.QtWidgets import QApplication

    window.tray = fake_tray
    quit_calls = []
    monkeypatch.setattr(QApplication, "quit", lambda: quit_calls.append(True))

    window.quit()

    assert window._quitting
    assert quit_calls == [True]


def test_close_after_quit_is_accepted(window, fake_tray):
    """Once quitting, the close must go through instead of hiding again."""
    window.tray = fake_tray
    window.show()
    window._quitting = True

    window.close()

    assert not window.isVisible()


def test_shutdown_hides_the_tray(window, fake_tray):
    """A menu bar icon left behind after the process goes is a dead icon."""
    window.tray = fake_tray

    window.shutdown()

    assert fake_tray.hidden


def test_present_shows_a_hidden_window(window, fake_tray):
    window.tray = fake_tray
    window.show()
    window.close()

    window.present()

    assert window.isVisible()


def test_closing_while_fullscreen_leaves_fullscreen_first(window, fake_tray, qapp):
    """The stuck-black-screen bug.

    macOS keeps the fullscreen Space when a fullscreen window is hidden, so the
    app vanished and left an empty black screen with no window to close or
    minimise. Dropping out of fullscreen is what releases the Space.
    """
    window.tray = fake_tray
    window.show()
    window.showFullScreen()
    assert window.windowState() & Qt.WindowState.WindowFullScreen

    window.close()

    assert not (window.windowState() & Qt.WindowState.WindowFullScreen), (
        "the fullscreen Space would be left behind, black and empty"
    )


def test_a_normal_window_still_hides_immediately(window, fake_tray):
    """Only the fullscreen path defers; the ordinary close must not lag."""
    window.tray = fake_tray
    window.show()

    window.close()

    assert not window.isVisible()


# ----------------------------------------------------------------------
# The Dock icon follows the window, not the process
# ----------------------------------------------------------------------
def test_closing_the_window_leaves_the_menu_bar_item(window, fake_tray, monkeypatch):
    """The whole point of hiding rather than quitting: the app stays reachable."""
    monkeypatch.setattr("ui.main_window.dock.hide_from_dock", lambda: True)
    window.tray = fake_tray
    window.show()

    window.close()

    assert not fake_tray.hidden, "the menu bar icon must survive a window close"
    assert window.tray is fake_tray


def test_closing_the_window_drops_the_dock_icon(window, fake_tray, monkeypatch):
    """With no window on screen there is nothing for the Dock to point at."""
    calls = []
    monkeypatch.setattr(
        "ui.main_window.dock.hide_from_dock", lambda: calls.append("hide") or True
    )
    window.tray = fake_tray
    window.show()

    window.close()

    assert calls == ["hide"]


def test_a_window_with_no_menu_bar_item_keeps_its_dock_icon(window, monkeypatch):
    """Without a status item the Dock is the only way back — never hide it."""
    calls = []
    monkeypatch.setattr(
        "ui.main_window.dock.hide_from_dock", lambda: calls.append("hide") or True
    )
    window.tray = None
    window.show()

    window._hide_now()

    assert calls == [], "hiding the Dock icon here would strand the app"


def test_showing_the_window_puts_the_icon_back(window, fake_tray, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "ui.main_window.dock.show_in_dock", lambda: calls.append("show") or True
    )
    monkeypatch.setattr("ui.main_window.dock.hide_from_dock", lambda: True)
    window.tray = fake_tray
    window.show()
    window.close()

    window.present()

    assert calls == ["show"]


def test_only_quitting_removes_the_menu_bar_item(window, fake_tray, monkeypatch):
    monkeypatch.setattr("ui.main_window.dock.hide_from_dock", lambda: True)
    window.tray = fake_tray
    window.show()
    window.close()
    assert not fake_tray.hidden

    window.shutdown()

    assert fake_tray.hidden


# ----------------------------------------------------------------------
# Using the menu bar must not drag the window along
# ----------------------------------------------------------------------
def test_launching_from_the_menu_bar_does_not_open_our_window(
    window, fake_tray, qapp, monkeypatch
):
    """Picking SONAR from the menu bar should start SONAR and nothing else.

    Opening the menu activates Lab Hub, and so does the focus change when the
    launched app appears. Both look like "the user switched back to us".
    """
    monkeypatch.setattr("ui.main_window.dock.hide_from_dock", lambda: True)
    window.tray = fake_tray
    window.show()
    reopener = _Reopener(window, qapp)
    window.close()
    window._hidden_at -= (REOPEN_GRACE_MS + 200) / 1000  # past the close grace

    window.suppress_reopen()  # what the tray's menu_opened / launched signals do
    reopener._was_active = False
    reopener._on_state_changed(Qt.ApplicationState.ApplicationActive)

    assert not window.isVisible(), "the hub must stay out of the way"


def test_the_suppression_wears_off(window, fake_tray, qapp, monkeypatch):
    """It is a short grace, not a permanent block — the Dock must still work."""
    monkeypatch.setattr("ui.main_window.dock.hide_from_dock", lambda: True)
    monkeypatch.setattr("ui.main_window.dock.show_in_dock", lambda: True)
    window.tray = fake_tray
    window.show()
    reopener = _Reopener(window, qapp)
    window.close()
    window._hidden_at -= (REOPEN_GRACE_MS + 200) / 1000

    window.suppress_reopen()
    window._suppress_reopen_until -= TRAY_SUPPRESS_S + 1  # time passes
    reopener._was_active = False
    reopener._on_state_changed(Qt.ApplicationState.ApplicationActive)

    assert window.isVisible()


def test_open_lab_hub_still_works_while_suppressed(window, fake_tray, monkeypatch):
    """Suppression must not block the menu item whose whole job is to show it."""
    monkeypatch.setattr("ui.main_window.dock.hide_from_dock", lambda: True)
    monkeypatch.setattr("ui.main_window.dock.show_in_dock", lambda: True)
    window.tray = fake_tray
    window.show()
    window.close()

    window.suppress_reopen()  # the menu was just opened
    window.present()  # "Open Lab Hub" chosen from that same menu

    assert window.isVisible()


def test_showing_the_window_also_brings_the_app_forward(window, fake_tray, monkeypatch):
    """Promoting out of Accessory gives a Dock icon but does not make the app
    frontmost. Without activating, the window is created and then sits behind
    everything — which looks exactly like no window at all."""
    order = []
    monkeypatch.setattr(
        "ui.main_window.dock.show_in_dock", lambda: order.append("promote") or True
    )
    monkeypatch.setattr(
        "ui.main_window.dock.activate", lambda: order.append("activate") or True
    )
    monkeypatch.setattr("ui.main_window.dock.hide_from_dock", lambda: True)
    window.tray = fake_tray
    window.show()
    window.close()

    window.present()

    assert order == ["promote", "activate"], "promote first, then bring forward"


# ----------------------------------------------------------------------
# Quitting from the Dock leaves the menu bar item alone
# ----------------------------------------------------------------------
@pytest.fixture
def quit_guard(window, qapp):
    """A guard on the shared QApplication, taken back off afterwards.

    The QApplication is session-scoped, so a filter left installed would
    outlive its window and every later test would be filtering events through
    a deleted object.
    """
    guard = _QuitGuard(window, qapp)
    yield guard
    qapp.removeEventFilter(guard)


def _quit_event():
    return QEvent(QEvent.Type.Quit)


def test_quitting_from_the_dock_hides_instead(window, fake_tray, qapp, quit_guard, monkeypatch):
    """Dock > Quit means "off my screen", not "shut the whole thing down"."""
    monkeypatch.setattr("ui.main_window.dock.hide_from_dock", lambda: True)
    window.tray = fake_tray
    window.show()

    qapp.sendEvent(qapp, _quit_event())

    assert not window.isVisible()
    assert not window._quitting, "the process must stay up"
    assert not fake_tray.hidden, "the menu bar item is the whole way back in"


def test_the_dock_quit_is_actually_refused(window, fake_tray, qapp, quit_guard, monkeypatch):
    """The subtle half: swallowing the event is not the same as refusing it.

    A QEvent is accepted from the moment it is built, and filtering one out
    leaves that flag set — which macOS reads as "yes, terminate". Only
    ignore() turns applicationShouldTerminate: into NSTerminateCancel.
    """
    monkeypatch.setattr("ui.main_window.dock.hide_from_dock", lambda: True)
    window.tray = fake_tray
    window.show()
    event = _quit_event()
    assert event.isAccepted(), "precondition: events start out accepted"

    qapp.sendEvent(qapp, event)

    assert not event.isAccepted()


def test_the_dock_quit_explains_itself_once(window, fake_tray, qapp, quit_guard, monkeypatch):
    monkeypatch.setattr("ui.main_window.dock.hide_from_dock", lambda: True)
    window.tray = fake_tray
    window.show()

    qapp.sendEvent(qapp, _quit_event())
    window.show()
    qapp.sendEvent(qapp, _quit_event())

    assert len(fake_tray.notices) == 1
    assert "menu bar" in fake_tray.notices[0][1].lower()


def test_without_a_menu_bar_item_quitting_really_quits(window, qapp, quit_guard):
    """Hiding here would leave a running app with no way to reach or stop it.

    Called directly rather than sent: an unfiltered Quit would end the test
    session's own QApplication.
    """
    window.tray = None

    assert quit_guard.eventFilter(qapp, _quit_event()) is False


def test_quitting_from_the_menu_bar_is_not_intercepted(window, fake_tray, qapp, quit_guard):
    """MainWindow.quit is the one real exit; it must not be turned into a hide."""
    window.tray = fake_tray
    window._quitting = True

    assert quit_guard.eventFilter(qapp, _quit_event()) is False


def test_other_application_events_pass_through(window, fake_tray, qapp, quit_guard):
    """The filter sits on every event the application object sees."""
    window.tray = fake_tray

    assert quit_guard.eventFilter(qapp, QEvent(QEvent.Type.ApplicationActivate)) is False


def test_the_menu_bar_quit_still_ends_the_app(window, fake_tray, qapp, quit_guard):
    """The safety net: with the Dock's Quit refused, this is the only way out.

    Runs a real event loop, because the question is whether
    `QApplication.quit()` ends it or is itself turned back into a
    `QEvent.Quit` for the guard to swallow — which would leave an app that
    cannot be quit at all. The failsafe timer is what turns that bug into a
    failed assertion instead of a hung test run.
    """
    from PySide6.QtCore import QTimer

    window.tray = fake_tray
    QTimer.singleShot(0, window.quit)
    QTimer.singleShot(2000, lambda: qapp.exit(99))

    code = qapp.exec()

    assert code == 0, "the menu bar's Quit did not end the event loop"
    assert window._quitting
