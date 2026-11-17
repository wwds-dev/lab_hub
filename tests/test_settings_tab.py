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


def test_every_licence_file_the_app_points_to_exists():
    """build_app.sh bundles these; the self-test and Settings tab look them up."""
    from lab_hub import LICENCE_FILES, licence_paths

    missing = [name for name, path in zip(LICENCE_FILES, licence_paths()) if not path.is_file()]
    assert missing == []


def test_show_licences_reveals_the_notices(qapp, monkeypatch):
    from lab_hub import launcher

    shown = []
    monkeypatch.setattr(launcher, "reveal", shown.append)
    tab = SettingsTab(config.Settings())

    tab._reveal_licences()

    assert [path.name for path in shown] == ["THIRD_PARTY_NOTICES.md"]


def test_build_script_bundles_every_licence_file():
    from pathlib import Path

    from lab_hub import LICENCE_FILES

    script = (Path(__file__).resolve().parents[1] / "build_app.sh").read_text()
    for name in LICENCE_FILES:
        folder = name.rpartition("/")[0] or "."
        assert f'--add-data "{name}:{folder}"' in script, name
