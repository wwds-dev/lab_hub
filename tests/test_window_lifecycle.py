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

from ui.main_window import REOPEN_GRACE_MS, _Reopener


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
