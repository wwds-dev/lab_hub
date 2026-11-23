"""A tile name that differs from its bundle name (docs/specs/syncorp-tile.md).

SYNDUSTRYX's display name is "SynCorp Inc." but its bundle is `SynCorp.app`, and
the installed build71 is still `SYNDUSTRYX.app` until the owner installs a new build.
"""

from __future__ import annotations

import pytest

from lab_hub import launcher
from lab_hub.launcher import registry

from .fakes import make_bundle

RENAMED = """
[[suites]]
key = "syndustryx"
name = "SynCorp Inc."
bundle = "SynCorp"
legacy_bundles = ["SYNDUSTRYX"]
project = "syndustryx"
entry = "server.py"
summary = "s"
runs_from_source = false
build = "python3 build_desktop.py"
build_output = "dist/SynCorp.app"
"""


def _app(text=RENAMED):
    return registry.parse(text).suites[0]


def test_bundle_fields_are_read_and_default_to_the_name():
    app = _app()
    assert app.name == "SynCorp Inc." and app.bundle_name == "SynCorp"
    assert app.legacy_bundles == ("SYNDUSTRYX",)
    plain = _app(RENAMED.replace('bundle = "SynCorp"\n', "").replace('legacy_bundles = ["SYNDUSTRYX"]\n', ""))
    assert plain.bundle_name == "SynCorp Inc." and plain.legacy_bundles == ()


@pytest.mark.parametrize("line", [
    'bundle = "a/b"', 'bundle = ""', 'legacy_bundles = ["x<y"]', 'legacy_bundles = "SYNDUSTRYX"',
    'legacy_bundles = [1]',
])
def test_bad_bundle_fields_are_refused(line):
    text = RENAMED.replace('bundle = "SynCorp"\nlegacy_bundles = ["SYNDUSTRYX"]\n', line + "\n")
    with pytest.raises(registry.RegistryError):
        registry.parse(text)


def test_installed_bundle_prefers_new_name_then_legacy(tmp_path, monkeypatch):
    apps = tmp_path / "Applications"
    apps.mkdir()
    monkeypatch.setattr(launcher, "APPLICATIONS", apps)
    app = _app()
    assert launcher.bundle_path(app, tmp_path) is None
    make_bundle(apps, "SYNDUSTRYX")
    assert launcher.bundle_path(app, tmp_path) == apps / "SYNDUSTRYX.app"
    make_bundle(apps, "SynCorp")
    assert launcher.bundle_path(app, tmp_path) == apps / "SynCorp.app"
    make_bundle(apps, "SynCorp Inc.")  # the display name never selects a bundle
    assert launcher.bundle_path(app, tmp_path) == apps / "SynCorp.app"


def test_update_installs_under_the_bundle_name(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "Applications")
    command = launcher.registered_build_command(_app(), tmp_path)
    assert str(tmp_path / "Applications" / "SynCorp.app") in command
    assert "SynCorp Inc..app" not in command
    assert "SynCorp before update" in command


def test_a_copy_running_from_the_legacy_bundle_still_counts(tmp_path, monkeypatch):
    apps = tmp_path / "Applications"
    apps.mkdir()
    monkeypatch.setattr(launcher, "APPLICATIONS", apps)
    make_bundle(apps, "SYNDUSTRYX")
    make_bundle(apps, "SynCorp")
    markers = launcher.running_markers(_app(), tmp_path)
    assert str(apps / "SynCorp.app" / "Contents" / "MacOS") in markers
    assert str(apps / "SYNDUSTRYX.app" / "Contents" / "MacOS") in markers


def test_built_bundle_and_messages_use_the_bundle_name(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "none")
    lab = tmp_path / "lab"
    text = RENAMED.replace('runs_from_source = false', 'runs_from_source = false\nbundle_dir = "dist"')
    app = _app(text)
    make_bundle(lab / "syndustryx" / "dist", "SynCorp Inc.")  # display name: ignored
    assert launcher.bundle_path(app, lab) is None
    make_bundle(lab / "syndustryx" / "dist", "SynCorp")
    assert launcher.bundle_path(app, lab) == (lab / "syndustryx" / "dist" / "SynCorp.app").resolve()


def test_local_app_with_bundle_never_selects_applications(tmp_path, monkeypatch):
    apps = tmp_path / "Applications"
    apps.mkdir()
    monkeypatch.setattr(launcher, "APPLICATIONS", apps)
    make_bundle(apps, "SynCorp")
    make_bundle(apps, "SYNDUSTRYX")
    local = registry.parse(RENAMED, local=True).suites[0] if _local_ok() else None
    if local is None:
        pytest.skip("local files may not set build fields")
    assert launcher.bundle_path(local, tmp_path) is None
    assert launcher.legacy_bundle_markers(local) == ()


def _local_ok():
    try:
        registry.parse(RENAMED, local=True)
        return True
    except registry.RegistryError:
        return False


def test_update_never_touches_the_legacy_bundle(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "Applications")
    assert "SYNDUSTRYX" not in launcher.registered_build_command(_app(), tmp_path)
