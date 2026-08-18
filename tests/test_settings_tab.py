"""The Settings tab's login toggle.

The checkbox is a view onto a file on disk, not a remembered flag, so what
matters is that it reads the truth and that merely looking at the tab never
writes anything.
"""

from __future__ import annotations

import pytest

from lab_hub import config, login_item

from ui.settings_tab import SettingsTab


@pytest.fixture(autouse=True)
def scratch_agent(tmp_path, monkeypatch):
    agents = tmp_path / "LaunchAgents"
    monkeypatch.setattr(login_item, "AGENTS_DIR", agents)
    monkeypatch.setattr(login_item, "PLIST_PATH", agents / f"{login_item.LABEL}.plist")
    bundle = tmp_path / "Applications" / "Lab Hub.app"
    bundle.mkdir(parents=True)
    monkeypatch.setattr(login_item, "INSTALLED_BUNDLE", bundle)
    return agents


def test_the_box_is_clear_when_no_agent_is_installed(qapp):
    tab = SettingsTab(config.Settings())

    assert not tab.at_login.isChecked()
    assert tab.at_login.isEnabled()


def test_the_box_is_ticked_when_an_agent_exists(qapp):
    login_item.enable()

    tab = SettingsTab(config.Settings())

    assert tab.at_login.isChecked()


def test_opening_the_tab_writes_nothing(qapp):
    """Reflecting state must not create it."""
    SettingsTab(config.Settings())

    assert not login_item.is_enabled()


def test_ticking_the_box_installs_the_agent(qapp):
    tab = SettingsTab(config.Settings())

    tab.at_login.setChecked(True)

    assert login_item.is_enabled()


def test_clearing_the_box_removes_the_agent(qapp):
    login_item.enable()
    tab = SettingsTab(config.Settings())

    tab.at_login.setChecked(False)

    assert not login_item.is_enabled()


def test_the_box_is_disabled_when_there_is_no_app_to_start(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(login_item, "INSTALLED_BUNDLE", tmp_path / "nowhere.app")

    tab = SettingsTab(config.Settings())

    assert not tab.at_login.isEnabled()
    assert "not installed" in tab.login_detail.text()
