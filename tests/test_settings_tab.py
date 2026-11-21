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


# --- Hidden projects (spec apps-discovery §12.4) ------------------------------
def _hidden_setup(tmp_path, monkeypatch, *folders):
    """A lab folder with these project folders, and the clock fixed."""
    from datetime import date

    from lab_hub import discovery

    lab = tmp_path / "lab"
    for name, readme in folders:
        (lab / name).mkdir(parents=True)
        if readme:
            (lab / name / "README.md").write_text(readme)
    monkeypatch.setattr(discovery, "today", lambda: date(2026, 11, 21))
    return lab


def _labels(tab):
    return [item["label"].fullText() for item in tab.hidden_items]


def test_hidden_projects_lists_live_never_and_not_now_only(qapp, tmp_path, monkeypatch):
    from datetime import date, timedelta

    from lab_hub import discovery

    lab = _hidden_setup(tmp_path, monkeypatch, ("kaila", "# Kaila\n\nAssistant.\n"),
                        ("overseer", "# Overseer\n"), ("lapsed", None), ("scratch", None))
    today = date(2026, 11, 21)
    discovery.dismiss("overseer", "not_now", today)
    discovery.dismiss("kaila", "never", today)
    discovery.dismiss("lapsed", "not_now", today - timedelta(days=15))  # asked again already
    discovery.dismiss("gone", "never", today)  # its folder is gone: nothing to show again

    tab = SettingsTab(config.Settings(lab_root=str(lab)))

    assert _labels(tab) == ["Kaila · hidden for good", "Overseer · not asked until 5 Dec"]
    assert not tab.hidden_empty.isVisibleTo(tab)


@pytest.mark.parametrize(("day", "text"), [
    ((2026, 11, 21), "not asked until 5 Dec"),  # a one-digit day, no leading zero
    ((2026, 12, 20), "not asked until 3 Jan"),  # across the year
    ((2026, 1, 10), "not asked until 24 Jan"),
])
def test_the_date_is_day_and_short_month_whatever_the_month(qapp, tmp_path, monkeypatch, day, text):
    from datetime import date

    from lab_hub import discovery

    lab = _hidden_setup(tmp_path, monkeypatch, ("p", None))
    monkeypatch.setattr(discovery, "today", lambda: date(*day))
    discovery.dismiss("p", "not_now", date(*day))

    tab = SettingsTab(config.Settings(lab_root=str(lab)))

    assert _labels(tab) == [f"p · {text}"]


def test_hidden_projects_card_has_its_heading_and_sits_after_lab_folder(qapp, tmp_path):
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QLabel

    tab = SettingsTab(config.Settings(lab_root=str(tmp_path)))
    tab.resize(900, 3000)
    tab.show()
    qapp.processEvents()

    titles = {
        label.text(): label.mapTo(tab, QPoint(0, 0)).y()
        for label in tab.findChildren(QLabel, "sectionTitle")
    }
    assert titles["LAB FOLDER"] < titles["HIDDEN PROJECTS"] < titles["START AT LOGIN"]
    tab.close()


def test_the_card_stays_with_a_line_when_nothing_is_hidden(qapp, tmp_path):
    tab = SettingsTab(config.Settings(lab_root=str(tmp_path)))

    assert tab.hidden_items == []
    assert tab.hidden_empty.text() == "No hidden projects."
    assert not tab.hidden_empty.isHidden()


def test_a_damaged_answers_file_says_so_instead_of_claiming_nothing_is_hidden(qapp, tmp_path):
    from lab_hub import discovery

    discovery.dismissed_path().parent.mkdir(parents=True, exist_ok=True)
    discovery.dismissed_path().write_text("{half saved")

    tab = SettingsTab(config.Settings(lab_root=str(tmp_path)))

    assert tab.hidden_unreadable.text() == (
        "Your hidden-projects file could not be read, so nothing is hidden.")
    assert tab.hidden_unreadable.objectName() == "hint"
    assert tab.hidden_unreadable.isVisibleTo(tab)
    assert not tab.hidden_empty.isVisibleTo(tab), "'No hidden projects.' would be untrue"
    assert tab.hidden_items == []


def test_the_damaged_file_line_follows_the_file_when_settings_is_shown_again(qapp, tmp_path):
    from lab_hub import discovery

    tab = SettingsTab(config.Settings(lab_root=str(tmp_path)))
    assert tab.hidden_empty.isVisibleTo(tab) and not tab.hidden_unreadable.isVisibleTo(tab)

    discovery.dismissed_path().parent.mkdir(parents=True, exist_ok=True)
    discovery.dismissed_path().write_text("{half saved")
    tab.refresh()
    assert tab.hidden_unreadable.isVisibleTo(tab) and not tab.hidden_empty.isVisibleTo(tab)

    discovery.dismissed_path().write_text("{}")
    tab.refresh()
    assert tab.hidden_empty.isVisibleTo(tab) and not tab.hidden_unreadable.isVisibleTo(tab)


def test_show_again_rewrites_the_file_asks_the_apps_page_and_says_so(qapp, tmp_path, monkeypatch):
    from datetime import date

    from lab_hub import discovery

    lab = _hidden_setup(tmp_path, monkeypatch, ("kaila", "# Kaila\n"), ("overseer", "# Overseer\n"))
    discovery.dismiss("kaila", "never", date(2026, 11, 21))
    discovery.dismiss("overseer", "never", date(2026, 11, 21))
    tab = SettingsTab(config.Settings(lab_root=str(lab)))
    asked, said = [], []
    tab.suggestions_changed.connect(lambda: asked.append(True))
    tab.notice.connect(said.append)

    first = tab.hidden_items[0]["button"]
    assert first.accessibleName() == "Show again, Kaila"
    first.click()

    assert set(discovery.load_dismissed()) == {"overseer"}
    assert _labels(tab) == ["Overseer · hidden for good"]
    assert asked == [True]
    assert said == ["Kaila will be suggested again."]
    # Focus: the next row's button.
    assert tab.focusWidget() is tab.hidden_items[0]["button"]

    tab.hidden_items[0]["button"].click()
    assert discovery.load_dismissed() == {}
    assert tab.hidden_empty.isVisibleTo(tab)
    assert tab.focusWidget() is tab._area


def test_a_failed_show_again_keeps_the_row_and_says_why(qapp, tmp_path, monkeypatch):
    from datetime import date

    from lab_hub import discovery

    lab = _hidden_setup(tmp_path, monkeypatch, ("kaila", "# Kaila\n"))
    discovery.dismiss("kaila", "never", date(2026, 11, 21))
    tab = SettingsTab(config.Settings(lab_root=str(lab)))
    asked = []
    tab.suggestions_changed.connect(lambda: asked.append(True))

    def boom(folder):
        raise discovery.DiscoveryError("cannot write /x: read-only")

    monkeypatch.setattr(discovery, "forget", boom)
    tab.hidden_items[0]["button"].click()

    item = tab.hidden_items[0]
    assert _labels(tab) == ["Kaila · hidden for good"]
    assert item["error"].text() == "Could not save your answer for Kaila: cannot write /x: read-only."
    assert item["error"].objectName() == "stateBad"
    assert asked == []


def test_a_long_name_is_cut_in_the_middle_with_all_of_it_in_the_tooltip(qapp, tmp_path, monkeypatch):
    from datetime import date

    from lab_hub import discovery

    long = "a" * 30 + "-" + "b" * 30
    lab = _hidden_setup(tmp_path, monkeypatch, (long, None))
    discovery.dismiss(long, "never", date(2026, 11, 21))
    tab = SettingsTab(config.Settings(lab_root=str(lab)))
    tab.resize(560, 900)
    tab.show()
    qapp.processEvents()

    item = tab.hidden_items[0]
    assert "…" in item["label"].text() and item["label"].fullText().startswith(long)
    assert long in item["label"].toolTip()
    assert item["button"].width() >= 107
    assert item["button"].isVisible()
    tab.close()


def test_hidden_names_are_plain_text(qapp, tmp_path, monkeypatch):
    from datetime import date

    from lab_hub import discovery

    lab = _hidden_setup(tmp_path, monkeypatch, ("p", "# <b>Bold</b>\n"))
    discovery.dismiss("p", "never", date(2026, 11, 21))

    tab = SettingsTab(config.Settings(lab_root=str(lab)))

    # "<b>" fails the name rule (spec §13.5), so the folder name shows.
    assert _labels(tab) == ["p · hidden for good"]
    from PySide6.QtCore import Qt
    assert tab.hidden_items[0]["label"].textFormat() == Qt.TextFormat.PlainText


def test_an_unchanged_list_is_not_rebuilt_under_the_keyboard(qapp, tmp_path, monkeypatch):
    from datetime import date

    from lab_hub import discovery

    lab = _hidden_setup(tmp_path, monkeypatch, ("kaila", "# Kaila\n"))
    discovery.dismiss("kaila", "never", date(2026, 11, 21))
    tab = SettingsTab(config.Settings(lab_root=str(lab)))
    first = tab.hidden_items[0]["button"]

    tab.refresh()
    tab.refresh()

    assert tab.hidden_items[0]["button"] is first
