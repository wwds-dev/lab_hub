"""The menu bar item's signals.

The window-side suppression is only half the fix — it is worth nothing if the
tray never announces that its menu is being used. This covers the wiring.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ui.tray import Tray


@pytest.fixture
def menu_bar_item(qapp):
    return Tray(lambda: Path("/tmp"))


def test_opening_the_menu_is_announced(menu_bar_item):
    """Opening the menu activates the app, and the window must be told so it
    does not mistake that for the user asking for it back."""
    fired = []
    menu_bar_item.menu_opened.connect(lambda: fired.append(True))

    menu_bar_item._menu.aboutToShow.emit()

    assert fired == [True]


def test_the_menu_offers_open_and_quit(menu_bar_item):
    labels = [a.text() for a in menu_bar_item._menu.actions() if a.text()]

    assert any("Open" in label for label in labels)
    assert any("Quit" in label for label in labels)


def test_the_menu_lists_the_top_level_apps(menu_bar_item):
    from lab_hub import launcher

    labels = [a.text() for a in menu_bar_item._menu.actions() if a.text()]

    for app in launcher.MENU_BAR_APPS:
        assert app.name in labels


def test_companions_are_not_in_the_menu(menu_bar_item):
    """VPN Agent, Bug Spray and vidforge are reached from their suite. Listing
    them here as peers makes a six-item menu into a nine-item one."""
    from lab_hub import launcher

    labels = {a.text() for a in menu_bar_item._menu.actions() if a.text()}
    companions = [c.name for s in launcher.SUITES for c in s.companions]

    assert companions, "the fixture would pass vacuously with no companions"
    assert not (labels & set(companions))
