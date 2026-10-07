"""The Tools tab's landing page of tiles."""

from __future__ import annotations

from lab_hub import launcher
from lab_hub.tools import convert

from ui.apps_tab import AppCard


def _names(window):
    return [tile.name.text() for tile in window.tools_overview.tool_tiles]


def test_tools_open_on_the_tiles(window):
    assert window.tools_tabs.widget(0) is window.tools_overview
    assert window.tools_tabs.tabText(0) == "All tools"


def test_every_tool_has_a_tile_in_tab_order(window):
    assert _names(window) == ["Convert Files", "Narrator", "Prepare Images"]
    assert [card.app.key for card in window.tools_overview.app_cards] == [
        "unblock_tracker", "backstage",
    ]
    # The standalone tools get the Apps tab's own tile, so Launch, Running
    # and the version behave exactly as they do there.
    assert all(isinstance(card, AppCard) for card in window.tools_overview.app_cards)


def test_open_goes_to_the_tools_page(window):
    for tile, page in zip(
        window.tools_overview.tool_tiles,
        (window.convert_tab, window.narrator_tab, window.images_tab),
    ):
        tile.open_button.click()
        assert window.tools_tabs.currentWidget() is page


def test_a_tool_at_work_says_so(window, monkeypatch):
    monkeypatch.setattr(window.images_tab.run_panel, "is_running", lambda: True)

    window.tools_overview.refresh()

    tile = window.tools_overview.tool_tiles[2]
    assert tile.state.text() == "Running"


def test_convert_without_calibre_says_what_it_needs(window, monkeypatch):
    monkeypatch.setattr(convert, "converter_path", lambda: None)

    window.tools_overview.refresh()

    tile = window.tools_overview.tool_tiles[0]
    assert tile.state.text() == "Needs Calibre"
    assert tile.detail.text() == convert.INSTALL_HINT


def test_an_idle_built_in_tool_claims_nothing_more(window, monkeypatch):
    """Narrator checks its keys and ffmpeg when it starts; *Ready* before
    that would be a guess."""
    window.tools_overview.refresh()

    assert window.tools_overview.tool_tiles[1].state.text() == "Built in"


def test_the_tile_page_has_recheck(window):
    assert window.tools_overview.recheck_button.text() == "Re-check"


def test_no_tool_app_gains_a_menu_bar_entry(window):
    """Backstage stays off the menu bar; a tile here is not a new door there."""
    assert "backstage" not in {app.key for app in launcher.MENU_BAR_APPS}
