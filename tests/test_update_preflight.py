"""Update's safety gate: an app's own preflight must pass against the installed
bundle before anything is replaced (spec update-preflight-gate).
"""

from __future__ import annotations

import os
import subprocess

import pytest

from lab_hub import launcher
from lab_hub.launcher import registry

from .test_launcher import _MAKE_BUNDLE, _git_project

TOML = """
[[suites]]
key = "x"
name = "X"
project = "x"
entry = "server.py"
summary = "s"
runs_from_source = false
build = "python3 build_desktop.py"
build_output = "dist/X.app"
{extra}
"""


def _parse(extra: str):
    return registry.parse(TOML.format(extra=extra)).suites[0]


def test_registry_reads_preflight_and_require_clean():
    app = _parse('preflight = "python3 -m p {installed} {candidate}"\nrequire_clean = true')
    assert app.preflight == "python3 -m p {installed} {candidate}" and app.require_clean is True
    plain = _parse("")
    assert plain.preflight is None and plain.require_clean is False


def test_registry_rejects_bad_values_and_entryless_use():
    with pytest.raises(registry.RegistryError):
        _parse("require_clean = 1")
    with pytest.raises(registry.RegistryError):
        _parse("preflight = 3")
    with pytest.raises(registry.RegistryError):
        registry.parse('[[suites]]\nkey="k"\nname="K"\nproject="k"\nsummary="s"\npreflight="true"\n')


def test_the_real_registry_gates_syndustryx():
    from pathlib import Path

    text = (Path(registry.__file__).parent.parent / "apps.toml").read_text()
    app = next(a for a in registry.parse(text).suites if a.key == "syndustryx")
    assert "desktop.update_preflight" in app.preflight
    assert "{installed}" in app.preflight and "{candidate}" in app.preflight
    assert app.require_clean is True


def _setup(tmp_path, monkeypatch, preflight, *, installed=True, dirty=False, require_clean=False,
           legacy_only=False):
    apps = tmp_path / "Applications"
    apps.mkdir()
    if installed:
        name = "OLD" if legacy_only else "X"
        (apps / f"{name}.app").mkdir()
        (apps / f"{name}.app" / "old").write_text("")
    project = tmp_path / "x"
    _git_project(project)
    if dirty:
        (project / "b.txt").write_text("uncommitted")
    home = tmp_path / "home"
    (home / ".Trash").mkdir(parents=True)
    monkeypatch.setattr(launcher, "APPLICATIONS", apps)
    monkeypatch.setattr(launcher, "installs_dir", lambda: tmp_path / "installs")
    app = launcher.ExternalApp(
        "x", "X", "x", "server.py", "", build=_MAKE_BUNDLE, build_output="out/X.app",
        legacy_bundles=("OLD",), preflight=preflight, require_clean=require_clean)
    command = launcher.registered_build_command(app, project)
    result = subprocess.run(["/bin/sh", "-c", command], capture_output=True, text=True,
                            env={**os.environ, "HOME": str(home)})
    return apps, project, result


def test_a_failing_preflight_installs_nothing_and_shows_its_message(tmp_path, monkeypatch):
    apps, _, result = _setup(tmp_path, monkeypatch, "echo 'designated requirements differ' >&2; exit 3")
    assert result.returncode != 0
    assert "designated requirements differ" in result.stdout + result.stderr
    assert (apps / "X.app" / "old").exists() and not (apps / "X.app" / "new").exists()
    assert not (tmp_path / "installs").exists()
    assert list((tmp_path / "home" / ".Trash").iterdir()) == []


def test_a_passing_preflight_lets_the_install_proceed(tmp_path, monkeypatch):
    apps, _, result = _setup(tmp_path, monkeypatch, "true")
    assert result.returncode == 0, result.stderr
    assert (apps / "X.app" / "new").exists() and not (apps / "X.app" / "old").exists()


def test_the_preflight_gets_the_installed_and_built_bundle(tmp_path, monkeypatch):
    log = tmp_path / "args.txt"
    apps, project, result = _setup(
        tmp_path, monkeypatch, f"printf '%s\\n%s\\n%s' {{installed}} {{candidate}} \"$PWD\" > {log}")
    assert result.returncode == 0, result.stderr
    installed, candidate, cwd = log.read_text().split("\n")
    assert installed == str(apps / "X.app")
    assert candidate == "out/X.app" and os.path.realpath(cwd) == os.path.realpath(project)


def test_the_legacy_bundle_is_checked_when_it_is_the_one_installed(tmp_path, monkeypatch):
    log = tmp_path / "args.txt"
    apps, _, result = _setup(tmp_path, monkeypatch, f"printf %s {{installed}} > {log}", legacy_only=True)
    assert result.returncode == 0, result.stderr
    assert log.read_text() == str(apps / "OLD.app")
    assert (apps / "OLD.app" / "old").exists()  # the legacy bundle itself is never replaced


def test_with_nothing_installed_a_first_install_skips_the_preflight(tmp_path, monkeypatch):
    apps, _, result = _setup(tmp_path, monkeypatch, "exit 9", installed=False)
    assert result.returncode == 0, result.stderr
    assert (apps / "X.app" / "new").exists()


def test_the_preflight_runs_after_the_build_and_before_the_swap(tmp_path, monkeypatch):
    # candidate must exist when the preflight runs
    apps, _, result = _setup(tmp_path, monkeypatch, "test -d {candidate}/Contents && exit 4")
    assert result.returncode == 4 and (apps / "X.app" / "old").exists()


def test_require_clean_refuses_a_dirty_checkout_before_building(tmp_path, monkeypatch):
    apps, project, result = _setup(tmp_path, monkeypatch, "true", dirty=True, require_clean=True)
    assert result.returncode != 0
    assert "uncommitted" in (result.stdout + result.stderr).lower()
    assert (apps / "X.app" / "old").exists()
    assert not (project / "out").exists()  # the build never ran


def test_require_clean_allows_a_clean_checkout(tmp_path, monkeypatch):
    apps, _, result = _setup(tmp_path, monkeypatch, "true", require_clean=True)
    assert result.returncode == 0, result.stderr
    assert (apps / "X.app" / "new").exists()


def test_an_app_without_the_keys_installs_as_before(tmp_path, monkeypatch):
    apps, _, result = _setup(tmp_path, monkeypatch, None, dirty=True)
    assert result.returncode == 0, result.stderr
    assert (apps / "X.app" / "new").exists()
