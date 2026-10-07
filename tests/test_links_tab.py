"""The Websites and Dashboards tabs."""

from __future__ import annotations

import json

from lab_hub import config, dashboards, sites

from ui.links_tab import DashboardsTab, SitesTab


def _settings(lab_root) -> config.Settings:
    return config.Settings(lab_root=str(lab_root))


# ----------------------------------------------------------------------
# Websites
# ----------------------------------------------------------------------
def test_building_the_tab_asks_no_site_anything(qapp, tmp_path, no_site_checks):
    """Checks start when the tab is shown, never in the constructor — the
    window builds every tab at startup."""
    before = list(no_site_checks)
    tab = SitesTab(_settings(tmp_path))

    assert no_site_checks == before
    assert all(card.state.text() == "Not checked" for card in tab.cards)


def test_a_check_marks_every_tile_then_reports_each(qapp, tmp_path, no_site_checks):
    tab = SitesTab(_settings(tmp_path))

    tab.check_all()

    assert no_site_checks[-2:] == [site.key for site in sites.SITES]
    assert all(card.state.text() == "Checking…" for card in tab.cards)

    tab._on_checked("bookadatewithme", sites.classify(sites.SITES[1], 404, None, 0.2))
    tab._on_checked("altmerch", sites.classify(sites.SITES[0], 200, None, 0.5))

    assert tab.by_key["altmerch"].state.text() == "Online"
    assert tab.by_key["bookadatewithme"].state.text() == "Error 404"
    assert "no page" in tab.by_key["bookadatewithme"].state.toolTip()


def test_showing_the_tab_again_soon_does_not_ask_again(qapp, tmp_path, no_site_checks):
    tab = SitesTab(_settings(tmp_path))
    tab.refresh()
    asked = len(no_site_checks)

    tab.refresh()

    assert len(no_site_checks) == asked, "a minute has not passed"


def test_recheck_always_asks(qapp, tmp_path, no_site_checks):
    tab = SitesTab(_settings(tmp_path))
    tab.refresh()
    asked = len(no_site_checks)

    tab.recheck()

    assert len(no_site_checks) == asked + len(sites.SITES)


def test_a_site_with_its_files_here_can_show_them(qapp, tmp_path):
    (tmp_path / "altmerch_store").mkdir()
    tab = SitesTab(_settings(tmp_path))

    card = tab.by_key["altmerch"]
    assert card.reveal_button.isEnabled()
    assert card.detail.text().endswith("altmerch_store")
    assert card.detail.toolTip() == str(tmp_path / "altmerch_store")


def test_a_deep_path_is_shortened_to_fit_a_tile():
    """A path is one unbreakable word; at full length the Antfarm
    workstation's set the whole tab's minimum width."""
    from pathlib import Path

    from ui.links_tab import short_path

    deep = str(Path.home() / ".codex/visualizations/2026/10/04/01a108d1/antfarm-workstation.html")

    assert short_path(deep) == "~/.codex/visualizations/…/antfarm-workstation.html"
    assert short_path(str(Path.home() / "Documents/lab/x.html")) == "~/Documents/lab/x.html"


def test_opening_a_site_opens_its_address(qapp, tmp_path, monkeypatch):
    from lab_hub import launcher

    opened = []
    monkeypatch.setattr(launcher, "open_url", opened.append)
    tab = SitesTab(_settings(tmp_path))

    tab.by_key["altmerch"].open_button.click()

    assert opened == ["https://altmerch.store/"]


# ----------------------------------------------------------------------
# Dashboards
# ----------------------------------------------------------------------
def _lab(tmp_path, entries):
    active = tmp_path / "active"
    active.mkdir(exist_ok=True)
    (tmp_path / dashboards.CATALOG_NAME).write_text(json.dumps(entries))
    return active


def test_one_tile_per_catalog_entry(qapp, tmp_path):
    page = tmp_path / "w.html"
    page.write_text("<div></div>")
    active = _lab(tmp_path, [
        {"id": "m", "title": "Monitor", "source": "Claude", "kind": "Live",
         "url": "https://claude.ai/artifact/x", "description": "d"},
        {"id": "w", "title": "Workstation", "source": "ChatGPT", "kind": "Concept",
         "path": str(page), "description": "d"},
        {"id": "g", "title": "Gone", "source": "ChatGPT", "kind": "Report",
         "path": str(tmp_path / "gone.html"), "description": "d"},
    ])

    tab = DashboardsTab(_settings(active))

    assert [card.name.text() for card in tab.cards] == ["Monitor", "Workstation", "Gone"]
    assert [card.state.text() for card in tab.cards] == ["Link", "Local file", "File missing"]
    assert tab.cards[0].meta.text() == "Claude · Live"
    assert not tab.cards[2].open_button.isEnabled()
    # A link has nothing on disk to show in Finder.
    assert tab.cards[0].reveal_button.isHidden()
    assert not tab.cards[1].reveal_button.isHidden()


def test_a_changed_catalog_is_picked_up_without_a_restart(qapp, tmp_path):
    import os

    active = _lab(tmp_path, [{"id": "a", "title": "A", "url": "https://a.test/"}])
    tab = DashboardsTab(_settings(active))
    assert len(tab.cards) == 1

    catalog = tmp_path / dashboards.CATALOG_NAME
    catalog.write_text(json.dumps([
        {"id": "a", "title": "A", "url": "https://a.test/"},
        {"id": "b", "title": "B", "url": "https://b.test/"},
    ]))
    # Make sure the change is visible to an mtime check on a fast filesystem.
    stat = catalog.stat()
    os.utime(catalog, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))

    tab.refresh()

    assert [card.name.text() for card in tab.cards] == ["A", "B"]


def test_a_missing_catalog_says_so_instead_of_showing_nothing(qapp, tmp_path):
    tab = DashboardsTab(_settings(tmp_path / "active"))

    assert tab.cards == []
    assert not tab.notice.isHidden()
    assert "dashboard_catalog.json" in tab.notice.text()


def test_opening_a_dashboard_hands_the_browser_its_target(qapp, tmp_path, monkeypatch):
    from lab_hub import launcher

    active = _lab(tmp_path, [{"id": "a", "title": "A", "url": "https://a.test/"}])
    opened = []
    monkeypatch.setattr(launcher, "open_url", opened.append)
    tab = DashboardsTab(_settings(active))

    tab.cards[0].open_button.click()

    assert opened == ["https://a.test/"]
