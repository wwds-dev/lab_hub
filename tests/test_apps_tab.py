"""The launch cards.

The point of showing running state is that clicking Launch on something already
open is the wrong thing to do — it either opens a second copy or appears to do
nothing. So what these check is that the button changes what it *does*, not just
what it says.
"""

from __future__ import annotations

from lab_hub import launcher

from ui.apps_tab import AppCard


def _installed(tmp_path, monkeypatch, name="SONAR"):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    (tmp_path / f"{name}.app").mkdir(parents=True, exist_ok=True)
    return launcher.ExternalApp("sonar", name, "sonar", "main.py", "summary")


def test_an_idle_app_offers_to_launch(qapp, tmp_path, monkeypatch):
    app = _installed(tmp_path, monkeypatch)
    card = AppCard(app)

    card.refresh(tmp_path, table="/bin/zsh\n")

    assert card.state.text() == "Installed"
    assert card.launch_button.text() == "Launch"
    assert card.launch_button.isEnabled()


def test_a_running_app_offers_to_raise_it(qapp, tmp_path, monkeypatch):
    app = _installed(tmp_path, monkeypatch)
    card = AppCard(app)

    card.refresh(tmp_path, table=f"{tmp_path}/SONAR.app/Contents/MacOS/SONAR\n")

    assert card.state.text() == "Running"
    assert card.launch_button.text() == "Bring to front"
    assert card.launch_button.isEnabled()


def test_the_button_raises_rather_than_relaunching(qapp, tmp_path, monkeypatch):
    """The behaviour that matters: a second copy is what we are avoiding."""
    app = _installed(tmp_path, monkeypatch)
    card = AppCard(app)
    card.refresh(tmp_path, table=f"{tmp_path}/SONAR.app/Contents/MacOS/SONAR\n")

    called = []
    monkeypatch.setattr(
        launcher, "bring_to_front", lambda a, root: called.append("raise") or "raised"
    )
    monkeypatch.setattr(
        launcher, "launch", lambda a, root: called.append("launch") or "launched"
    )

    card._launch()

    assert called == ["raise"]


def test_a_running_source_app_cannot_be_raised(qapp, tmp_path, monkeypatch):
    """No bundle to address, so the button says so instead of failing."""
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "none")
    project = tmp_path / "sonar"
    project.mkdir()
    (project / "main.py").write_text("pass\n")
    app = launcher.ExternalApp("sonar", "SONAR", "sonar", "main.py", "summary")
    card = AppCard(app)

    card.refresh(tmp_path, table=f"/usr/bin/python3 {project}/main.py\n")

    assert card.state.text() == "Running"
    assert card.launch_button.text() == "Running"
    assert not card.launch_button.isEnabled()
    assert "Dock" in card.launch_button.toolTip()


def test_a_missing_app_cannot_be_launched(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "none")
    app = launcher.ExternalApp("ghost", "Ghost", "ghost", "main.py", "summary")
    card = AppCard(app)

    card.refresh(tmp_path, table="")

    assert card.state.text() == "Not found"
    assert not card.launch_button.isEnabled()
