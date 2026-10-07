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


def test_the_menu_lists_only_umbrella_apps(menu_bar_item):
    """No agent or sub-module gets its own menu entry."""
    labels = {a.text() for a in menu_bar_item._menu.actions() if a.text()}

    assert not (labels & {"VPN Agent", "Bug Spray", "vidforge"})
    # Backstage is reached from the Tools tab only, by choice.
    assert "Backstage" not in labels


def test_the_menu_has_the_websites(menu_bar_item):
    from lab_hub import sites

    labels = [a.text() for a in menu_bar_item.sites_menu.actions()]

    assert labels == [site.name for site in sites.SITES]


def test_the_dashboards_come_from_the_catalog_each_time(qapp, tmp_path):
    """Re-read on every opening, so a dashboard added to the catalog is in the
    menu without restarting Lab Hub."""
    import json

    from lab_hub import dashboards

    active = tmp_path / "active"
    active.mkdir()
    catalog = tmp_path / dashboards.CATALOG_NAME
    catalog.write_text(json.dumps([{"id": "a", "title": "A", "url": "https://a.test/"}]))
    item = Tray(lambda: active)
    assert [a.text() for a in item.dashboards_menu.actions()] == ["A"]

    catalog.write_text(json.dumps([
        {"id": "a", "title": "A", "url": "https://a.test/"},
        {"id": "b", "title": "B", "path": str(tmp_path / "gone.html")},
    ]))
    item._menu.aboutToShow.emit()

    actions = item.dashboards_menu.actions()
    assert [a.text() for a in actions] == ["A", "B"]
    assert not actions[1].isEnabled(), "a missing file cannot be opened"


def _web_app(launcher):
    """A served app. Provisio was the registry's one until it became a native
    app (2026-10-07); the menu bar's web-app handling is kept and tested here."""
    return launcher.ExternalApp(
        "provisio", "Provisio", "provisio", "scripts/run-framework.mjs", "",
        url="http://localhost:5173/", runtime="node", args=("dev",),
    )


def test_a_running_web_app_is_opened_not_started_again(qapp, monkeypatch):
    """A second launch would start a second server on the next port."""
    from lab_hub import launcher

    provisio = _web_app(launcher)
    monkeypatch.setattr(launcher, "is_running", lambda app, root, table=None: True)
    calls = []
    monkeypatch.setattr(launcher, "open_url", lambda url: calls.append(("open", url)))
    monkeypatch.setattr(launcher, "launch", lambda app, root: calls.append(("launch",)))
    item = Tray(lambda: Path("/tmp"))

    item._launch(provisio)

    assert calls == [("open", provisio.url)]


def test_a_stopped_web_app_is_started_then_opened(qapp, monkeypatch):
    from lab_hub import launcher

    provisio = _web_app(launcher)
    monkeypatch.setattr(launcher, "is_running", lambda app, root, table=None: False)
    monkeypatch.setattr(launcher, "launch", lambda app, root: "launched")
    item = Tray(lambda: Path("/tmp"))

    item._launch(provisio)

    assert item._openers["provisio"].waiting
    item._openers["provisio"].stop()
