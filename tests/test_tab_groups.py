"""The top-level navigation keeps related apps and tools together."""

from __future__ import annotations

from lab_hub import launcher


def _keys(tab):
    return [card.app.key for card in tab.cards]


def test_top_level_tabs_are_grouped(window):
    assert [window.tabs.tabText(i) for i in range(window.tabs.count())] == [
        "Apps",
        "Websites",
        "Dashboards",
        "Backup and Sync",
        "Tools",
        "Settings",
    ]


def test_backup_and_sync_apps_have_their_own_tab(window):
    assert _keys(window.backup_sync_tab) == [
        app.key for app in launcher.BACKUP_SYNC_APPS
    ]
    assert _keys(window.backup_sync_tab) == ["backup_manager", "git_autosync"]
    # No launchpad tile either, so rebuild them from here.
    assert window.backup_sync_tab.check_button.text() == "Check builds"


def test_tools_include_built_in_tools_and_unblock_tracker(window):
    assert [
        window.tools_tabs.tabText(i) for i in range(window.tools_tabs.count())
    ] == [
        "All tools", "Convert Files", "Narrator", "Prepare Images",
        "Unblock Tracker", "Backstage",
    ]
    assert _keys(window.unblock_tracker_tab) == ["unblock_tracker"]


def test_backstage_lives_only_at_the_end_of_tools(window):
    """Backstage is a standalone app kept off the front page (the user's call,
    2026-09-27): its own card at the end of Tools, no Apps tile, no menu bar
    entry."""
    assert _keys(window.backstage_tab) == ["backstage"]
    # Rebuild from here, like the launchpad apps.
    assert window.backstage_tab.check_button.text() == "Check build"
    assert "backstage" not in _keys(window.apps_tab)
    assert "backstage" not in {app.key for app in launcher.MENU_BAR_APPS}
    assert "backstage" in {app.key for app in launcher.APPS}


def test_the_apps_tab_lists_the_suites(window):
    """Only the suites get a tile; their companions are nested inside them.

    `sentinel_ai` is archived and `create_and_publish` was renamed to
    `imprint`, so neither belongs here any more. Provisio and SYNDUSTRYX (the
    Antfarm workstation) joined on 2026-10-07.
    """
    assert _keys(window.apps_tab) == [
        "sentinel", "imprint", "sonar", "provisio", "syndustryx",
    ]


def test_headroom_has_no_tile_of_its_own(window):
    """Headroom is Provisio's `engine/` — a sub-module, reached through
    Provisio like Tunnel is through Sentinel."""
    assert "headroom" not in {app.key for app in launcher.APPS}
    provisio = next(app for app in launcher.APPS if app.key == "provisio")
    assert "Headroom" in provisio.summary


def test_websites_and_dashboards_have_their_own_tabs(window):
    from lab_hub import sites

    assert [card.name.text() for card in window.sites_tab.cards] == [
        site.name for site in sites.SITES
    ]
    assert {site.name for site in sites.SITES} == {
        "altmerch.store", "bookadatewithme.com",
    }
    # The same features as the app pages: a state on every tile and Re-check.
    for tab in (window.sites_tab, window.dashboards_tab):
        assert tab.recheck_button.text() == "Re-check"
        assert all(card.state.text() for card in tab.cards)


def test_agents_are_not_separately_launchable(window):
    """Agents and sub-modules belong to their umbrella app.

    Tunnel and Bug Spray live inside Sentinel, the video pipeline inside
    Imprint, macro and Playmaker inside SONAR. Two doors to the same feature is how
    a standalone VPN Agent window ends up knowing nothing about the Sentinel
    Fork session that should own it.
    """
    from lab_hub import launcher

    listed = {app.key for app in launcher.LAUNCHPAD}

    assert not (listed & {"vpn_agent", "bug_spray", "vidforge", "macro", "playmaker"})


def test_every_launchable_app_is_reachable(window):
    """The flat list behind the menu bar and the self-test must not lose an app
    just because the Apps tab groups them."""
    on_screen = {c.app.key for c in window.apps_tab.cards}
    on_screen |= {c.app.key for c in window.backup_sync_tab.cards}
    on_screen |= {c.app.key for c in window.unblock_tracker_tab.cards}
    on_screen |= {c.app.key for c in window.backstage_tab.cards}

    assert on_screen == {app.key for app in launcher.APPS}


def test_no_tab_label_hides_an_accelerator(window):
    """Qt treats "&" in a tab label as a mnemonic marker, so "Backup & Sync"
    renders as "Backup _Sync" with the S underlined."""
    labels = [window.tabs.tabText(i) for i in range(window.tabs.count())]

    assert not any("&" in label for label in labels)
