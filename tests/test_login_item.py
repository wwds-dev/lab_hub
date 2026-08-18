"""Starting at login.

Every test redirects `PLIST_PATH` into tmp_path. Without that, running the suite
would install or remove the user's real login agent — a test that changes the
machine it runs on is worse than no test.
"""

from __future__ import annotations

import plistlib

import pytest

from lab_hub import login_item


@pytest.fixture(autouse=True)
def scratch_agent(tmp_path, monkeypatch):
    agents = tmp_path / "LaunchAgents"
    monkeypatch.setattr(login_item, "AGENTS_DIR", agents)
    monkeypatch.setattr(login_item, "PLIST_PATH", agents / f"{login_item.LABEL}.plist")
    return agents


@pytest.fixture
def installed(tmp_path, monkeypatch):
    bundle = tmp_path / "Applications" / "Lab Hub.app"
    bundle.mkdir(parents=True)
    monkeypatch.setattr(login_item, "INSTALLED_BUNDLE", bundle)
    return bundle


def _agent() -> dict:
    with login_item.PLIST_PATH.open("rb") as handle:
        return plistlib.load(handle)


def test_nothing_is_enabled_to_begin_with(installed):
    assert login_item.is_enabled() is False
    assert login_item.target() is None


def test_enabling_writes_an_agent_that_launches_the_bundle(installed):
    login_item.enable()

    assert login_item.is_enabled() is True
    agent = _agent()
    assert agent["Label"] == login_item.LABEL
    assert agent["RunAtLoad"] is True
    assert str(installed) in agent["ProgramArguments"]


def test_the_agent_asks_for_a_background_start(installed):
    """A menu bar app that throws a window across the screen at every login is
    worse than one that does not start at all."""
    login_item.enable()

    assert login_item.BACKGROUND_FLAG in _agent()["ProgramArguments"]


def test_the_agent_is_valid_plist_macos_will_accept(installed):
    import subprocess

    login_item.enable()

    result = subprocess.run(
        ["plutil", "-lint", str(login_item.PLIST_PATH)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_disabling_removes_it(installed):
    login_item.enable()
    login_item.disable()

    assert login_item.is_enabled() is False
    assert not login_item.PLIST_PATH.exists()


def test_disabling_when_it_was_never_on_is_harmless(installed):
    login_item.disable()  # must not raise

    assert login_item.is_enabled() is False


def test_enabling_twice_does_not_duplicate_anything(installed):
    login_item.enable()
    login_item.enable()

    assert _agent()["ProgramArguments"].count(login_item.BACKGROUND_FLAG) == 1


def test_the_target_is_read_back_from_the_agent(installed):
    """Recomputing it would report where the app is *now*, not where the
    installed agent actually points."""
    login_item.enable()

    assert login_item.target() == installed


def test_without_an_installed_app_there_is_nothing_to_start(tmp_path, monkeypatch):
    monkeypatch.setattr(login_item, "INSTALLED_BUNDLE", tmp_path / "nowhere.app")

    assert login_item.bundle() is None
    with pytest.raises(login_item.LoginItemError) as raised:
        login_item.enable()

    assert "build_app.sh --install" in str(raised.value), "say how to fix it"


def test_a_hand_deleted_agent_reads_as_off(installed):
    """The plist is a file the user can bin from Finder or System Settings."""
    login_item.enable()
    login_item.PLIST_PATH.unlink()

    assert login_item.is_enabled() is False
