"""The app list is data (lab_hub/apps.toml), re-read on Refresh."""

from __future__ import annotations

from pathlib import Path

import pytest

from lab_hub import launcher
from lab_hub.launcher import registry

ONE_APP = """
[[suites]]
key = "a"
name = "A"
project = "a"
entry = "main.py"
summary = "s"
"""


@pytest.fixture(autouse=True)
def _restore_registry():
    yield
    registry.use(None)
    registry.last_error = None


def test_the_shipped_list_keeps_every_registered_app_as_it_was():
    """Moving the list out of code must not change a single tile."""
    found = registry.load(registry.PACKAGE_REGISTRY)

    assert [a.key for a in found.suites] == [
        "sentinel", "imprint", "sonar", "provisio", "syndustryx",
    ]
    assert [a.key for a in found.backup_sync] == ["backup_manager", "git_autosync"]
    assert [a.key for a in found.utilities] == ["unblock_tracker"]
    assert [a.key for a in found.tools_only] == ["backstage"]
    sonar = next(a for a in found.suites if a.key == "sonar")
    assert sonar.service == "Background engine"
    syndustryx = next(a for a in found.suites if a.key == "syndustryx")
    assert syndustryx.bundle_dir == "dist" and syndustryx.runs_from_source is False
    autosync = found.backup_sync[1]
    assert autosync.entry == "packaging/entry_point.py"
    assert found.menu_bar_apps == found.suites + found.backup_sync + found.utilities
    assert found.apps == found.menu_bar_apps + found.tools_only


def test_the_old_constants_read_the_list_in_force():
    registry.use(registry.parse(ONE_APP))

    assert [a.key for a in launcher.SUITES] == ["a"]
    assert [a.key for a in launcher.APPS] == ["a"]
    assert launcher.TOOLS_ONLY_APPS == ()


@pytest.mark.parametrize(
    "text, complaint",
    [
        ("not toml [", "not valid TOML"),
        ("[[suites]]\nkey = 'a'\n", "missing"),
        (ONE_APP + "colour = 'red'\n", "unknown field"),
        (ONE_APP.replace("suites", "nonsense"), "unknown group"),
        (ONE_APP + ONE_APP.replace("[[suites]]", "[[utilities]]"), "used twice"),
        (ONE_APP + "runs_from_source = 'no'\n", "true or false"),
        ("", "lists no apps"),
    ],
)
def test_a_malformed_list_is_refused_with_a_reason(text, complaint):
    with pytest.raises(registry.RegistryError, match=complaint):
        registry.parse(text)


def test_frozen_reads_the_checkout_first_then_the_bundle(tmp_path):
    paths = registry.candidates(tmp_path, frozen=True)

    assert paths == [
        tmp_path / "lab_hub" / "lab_hub" / "apps.toml",
        registry.PACKAGE_REGISTRY,
    ]
    assert registry.candidates(tmp_path, frozen=False) == [registry.PACKAGE_REGISTRY]


def test_reload_picks_up_a_new_app_and_says_so(tmp_path, monkeypatch):
    listing = tmp_path / "apps.toml"
    listing.write_text(ONE_APP)
    monkeypatch.setattr(registry, "candidates", lambda lab_root=None: [listing])
    registry.use(None)
    assert [a.key for a in registry.current().apps] == ["a"]

    assert registry.reload() is False  # nothing changed

    listing.write_text(ONE_APP + ONE_APP.replace('"a"', '"b"').replace('"A"', '"B"'))
    assert registry.reload() is True
    assert [a.key for a in launcher.APPS] == ["a", "b"]


def test_a_broken_edit_keeps_the_last_good_list(tmp_path, monkeypatch):
    listing = tmp_path / "apps.toml"
    listing.write_text(ONE_APP)
    monkeypatch.setattr(registry, "candidates", lambda lab_root=None: [listing])
    registry.use(None)
    registry.current()

    listing.write_text("half saved [[")

    assert registry.reload() is False
    assert [a.key for a in launcher.APPS] == ["a"]
    assert "not valid TOML" in (registry.last_error or "")


def test_a_broken_checkout_copy_falls_back_to_the_next(tmp_path, monkeypatch):
    broken = tmp_path / "broken.toml"
    broken.write_text("nope [[")
    good = tmp_path / "good.toml"
    good.write_text(ONE_APP)
    monkeypatch.setattr(registry, "candidates", lambda lab_root=None: [broken, good])

    registry.use(None)

    assert registry.current().source == good
    assert str(broken) in (registry.last_error or "")


def test_patching_the_facade_reaches_the_part_that_reads_it(tmp_path, monkeypatch):
    """`launcher.X = …` must land where X is read, not on the facade alone."""
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)

    assert launcher.state.APPLICATIONS == Path(tmp_path)
