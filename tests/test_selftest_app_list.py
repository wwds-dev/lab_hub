"""The self-test judges the app list that ships, never the owner's own file.

The self-update helper runs `--selftest` on the installed copy and puts the
previous build back when it fails (ADR 0003). The owner's `apps-local.toml` is
not part of the build, so a typo in it must not be able to undo an update
(spec apps-discovery §13.0, ADR 0007).
"""

from __future__ import annotations

import pytest

from lab_hub.launcher import registry

import main


@pytest.fixture(autouse=True)
def _restore_registry():
    registry.use(None)
    registry.last_error = None
    yield
    registry.use(None)
    registry.last_error = None


def _write_local(text: str) -> None:
    path = registry.local_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_a_clean_app_list_has_no_problems(capsys):
    assert main._app_list_problems() == []

    out = capsys.readouterr().out
    assert "app list:" in out and "app list used:" in out
    assert "added projects:" not in out


@pytest.mark.parametrize("garbage", [
    "half saved [[",
    '[[suites]]\nkey = "a/b"\nname = "X"\nproject = "../x"\nsummary = "s"\n',
    '[[utilities]]\nkey = "x"\nname = "X"\nproject = "x"\nsummary = "s"\n',
])
def test_a_broken_local_file_is_printed_and_never_a_problem(capsys, garbage):
    _write_local(garbage)

    problems = main._app_list_problems()

    assert problems == []
    assert registry.local_ok is False and registry.last_error is None
    out = capsys.readouterr().out
    assert "added projects:" in out and "Your added projects file was ignored" in out


def test_a_clash_in_the_local_file_is_printed_and_never_a_problem(capsys):
    shipped = registry.load(registry.PACKAGE_REGISTRY).suites[0]
    _write_local(f'[[suites]]\nkey = "{shipped.key}"\nname = "X"\nproject = "x"\nsummary = "s"\n')

    assert main._app_list_problems() == []
    assert f"{shipped.key} is already in apps.toml" in capsys.readouterr().out


def test_a_broken_apps_toml_is_still_a_problem(monkeypatch, tmp_path, capsys):
    broken = tmp_path / "broken.toml"
    broken.write_text("nope [[")
    monkeypatch.setattr(registry, "candidates",
                        lambda lab_root=None: [broken, registry.PACKAGE_REGISTRY])
    registry.use(None)

    problems = main._app_list_problems()

    assert any("an app list was skipped" in p for p in problems)


def test_the_selftest_itself_asks_that_function(monkeypatch):
    """`selftest` must put `_app_list_problems()` into its `problems`, so the
    two cannot drift apart."""
    import inspect

    assert "_app_list_problems()" in inspect.getsource(main.selftest)
