"""Graphite and Paper, and switching between them while the app runs."""

from __future__ import annotations

import pytest
from PySide6.QtGui import QPalette

from lab_hub import config
from ui import theme


@pytest.fixture
def restore_theme(qapp):
    """Theme state is application-wide; put it back for the next test."""
    before = theme.mode()
    yield qapp
    theme.apply(qapp, mode=before)


def _window_colour(app) -> str:
    return app.palette().color(QPalette.ColorRole.Window).name().upper()


def test_the_two_palettes_are_the_agreed_ones():
    assert theme.GRAPHITE.window == "#101012"
    assert theme.GRAPHITE.sidebar == "#0B0B0D"
    assert theme.GRAPHITE.card == "#18181B"
    assert theme.GRAPHITE.card_border == "none"
    assert theme.GRAPHITE.radius == 14
    assert theme.GRAPHITE.accent == "#5EE0B0"
    assert theme.GRAPHITE.primary_text == "#06231A"
    assert theme.GRAPHITE.warn == "#E8B04A"

    assert theme.PAPER.window == "#F7F5F0"
    assert theme.PAPER.card == "#FBFAF7"
    assert theme.PAPER.card_border == "1px solid #E6E2D8"
    assert theme.PAPER.radius == 10
    assert theme.PAPER.text == "#1C1B19"
    # No accent colour: the primary button is ink on paper.
    assert theme.PAPER.primary == "#1C1B19"
    assert theme.PAPER.primary_text == "#F7F5F0"
    assert theme.PAPER.status_style == "dot"
    assert (theme.PAPER.ok, theme.PAPER.idle, theme.PAPER.warn) == (
        "#3F8F5B", "#C9C4B8", "#B7791F",
    )


def test_the_scale_is_the_agreed_one():
    assert (theme.SPACE_XS, theme.SPACE_S, theme.SPACE_M, theme.SPACE_L, theme.SPACE_XL) == (
        4, 8, 12, 16, 24,
    )
    assert theme.FONT_SMALL < theme.FONT_BODY < theme.FONT_TITLE


@pytest.mark.parametrize(("mode", "expected"), [("light", "PAPER"), ("dark", "GRAPHITE")])
def test_a_forced_mode_picks_its_palette(mode, expected, qapp):
    assert theme.palette_for(mode, qapp) is getattr(theme, expected)


def test_an_unknown_mode_means_system(qapp):
    assert theme.normalise_mode("sepia") == "system"
    assert theme.normalise_mode(None) == "system"
    assert theme.palette_for("sepia", qapp) is theme.palette_for("system", qapp)


def test_switching_applies_live(restore_theme):
    app = restore_theme
    theme.apply(app, mode="dark")
    assert theme.active() is theme.GRAPHITE
    assert _window_colour(app) == theme.GRAPHITE.window
    assert theme.GRAPHITE.accent in app.styleSheet()

    theme.apply(app, mode="light")
    assert theme.mode() == "light"
    assert theme.active() is theme.PAPER
    assert _window_colour(app) == theme.PAPER.window
    assert theme.PAPER.card in app.styleSheet()
    assert theme.GRAPHITE.accent not in app.styleSheet()


def test_status_markers_follow_the_palette():
    """Graphite draws a tinted pill, Paper a dot — and only on flagged labels."""
    assert 'QLabel#stateOk[status="true"]' in theme.stylesheet(theme.GRAPHITE)
    assert "background-image" not in theme.stylesheet(theme.GRAPHITE).split(
        'QLabel#stateOk[status="true"]'
    )[1].split("}")[0]
    paper = theme.stylesheet(theme.PAPER).split('QLabel#stateOk[status="true"]')[1]
    assert "background-image" in paper.split("}")[0]


def test_the_theme_defaults_to_system():
    assert config.Settings().theme == "system"


def test_the_settings_switch_applies_and_persists(window, restore_theme):
    app = restore_theme
    tab = window.settings_tab
    assert tab.appearance_buttons["system"].isChecked()

    tab.appearance_buttons["dark"].click()
    assert theme.active() is theme.GRAPHITE
    assert _window_colour(app) == theme.GRAPHITE.window
    assert config.load().theme == "dark"

    tab.appearance_buttons["light"].click()
    assert theme.active() is theme.PAPER
    assert tab.appearance_buttons["light"].isChecked()
    assert not tab.appearance_buttons["dark"].isChecked()
    assert config.load().theme == "light"

    tab.appearance_buttons["system"].click()
    assert config.load().theme == "system"
    assert theme.mode() == "system"


def test_the_switch_reflects_the_saved_setting(qapp):
    from ui.settings_tab import SettingsTab

    tab = SettingsTab(config.Settings(theme="dark"))
    assert tab.appearance_buttons["dark"].isChecked()
    assert not tab.appearance_buttons["system"].isChecked()
