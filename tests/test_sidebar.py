"""The sidebar that replaced the top tab row and the Tools sub-tab row."""

from __future__ import annotations

from PySide6.QtWidgets import QStackedWidget, QTabWidget

from ui.sidebar import Sidebar


def test_there_are_no_tab_rows_left(window):
    assert isinstance(window.tabs, QStackedWidget)
    assert isinstance(window.tools_tabs, QStackedWidget)
    # Pages may keep tabs of their own (Narrator, Prepare Images); the window's
    # navigation may not.
    for tabs in window.findChildren(QTabWidget):
        assert tabs.parentWidget() not in (window.centralWidget(), window.tools_tabs)


def test_clicking_a_top_level_entry_shows_its_page(window):
    window.sidebar.button_for(window.dashboards_tab).click()
    assert window.tabs.currentWidget() is window.dashboards_tab
    assert window.sidebar.current_title() == "Dashboards"


def test_tools_are_not_listed_in_the_sidebar(window):
    for index in range(window.tools_tabs.count()):
        assert window.sidebar.button_for(window.tools_tabs.widget(index)) is None


def test_clicking_tools_returns_to_the_overview(window):
    window.tabs.setCurrentWidget(window.tools_tabs)
    window.tools_tabs.setCurrentWidget(window.narrator_tab)
    window.sidebar.button_for(window.tools_tabs).click()
    assert window.tools_tabs.currentWidget() is window.tools_overview


def test_the_selection_follows_a_page_change_made_elsewhere(window):
    """A swipe or a tile's Open button changes the page without the sidebar."""
    window.tabs.setCurrentWidget(window.tools_tabs)
    window.tools_overview.tool_tiles[1].open_button.click()
    assert window.tools_tabs.currentWidget() is window.narrator_tab
    assert window.sidebar.current_title() == "Tools"
    window.tabs.setCurrentWidget(window.settings_tab)
    assert window.sidebar.current_title() == "Settings"


def test_opening_a_page_still_refreshes_it(window, monkeypatch):
    calls = []
    monkeypatch.setattr(window.convert_tab, "refresh_calibre", lambda: calls.append("convert"))
    monkeypatch.setattr(window.dashboards_tab, "refresh", lambda: calls.append("dash"))
    window.tabs.setCurrentWidget(window.apps_tab)

    window.sidebar.button_for(window.dashboards_tab).click()
    window.tabs.setCurrentWidget(window.tools_tabs)
    window.tools_tabs.setCurrentWidget(window.convert_tab)

    assert "dash" in calls and "convert" in calls


def test_refresh_lives_in_the_sidebar(window):
    assert window.refresh_button.parentWidget() is window.sidebar
    assert window.refresh_button.text() == "Refresh"


def test_titles_follow_the_stack_order(qapp):
    from PySide6.QtWidgets import QLabel

    stack = QStackedWidget()
    bar = Sidebar("Test")
    pages = [QLabel(name) for name in ("One", "Two")]
    for page in pages:
        stack.addWidget(page)
        bar.add_page(page.text(), stack, page)
    assert bar.titles(stack) == ["One", "Two"]
    stack.setCurrentIndex(1)
    assert bar.current_title() == "Two"


def test_icons_are_repainted_in_the_new_theme(window, qapp):
    """The selected entry's icon is painted in the theme being switched to."""
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QColor, QIcon

    from ui import theme

    for palette in (theme.DARK, theme.LIGHT, theme.DARK):
        theme.apply(qapp, palette)
        qapp.processEvents()
        icon = window.sidebar.button_for(window.apps_tab).icon()
        image = icon.pixmap(QSize(18, 18), 2.0, QIcon.Mode.Normal, QIcon.State.On).toImage()
        inked = [
            image.pixelColor(x, y)
            for x in range(image.width())
            for y in range(image.height())
            if image.pixelColor(x, y).alpha() == 255
        ]
        assert inked
        assert max(c.lightness() for c in inked) == QColor(palette.text).lightness()
