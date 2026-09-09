"""The top-level navigation keeps related apps and tools together."""

from __future__ import annotations

from lab_hub import launcher


def _keys(tab):
    return [card.app.key for card in tab.cards]


def test_top_level_tabs_are_grouped(window):
    assert [window.tabs.tabText(i) for i in range(window.tabs.count())] == [
        "Apps",
        "Backup and Sync",
        "Tools",
        "Settings",
    ]


def test_backup_and_sync_apps_have_their_own_tab(window):
    assert _keys(window.backup_sync_tab) == [
        app.key for app in launcher.BACKUP_SYNC_APPS
    ]
    assert _keys(window.backup_sync_tab) == ["backup_manager", "git_autosync"]


def test_tools_include_built_in_tools_and_unblock_tracker(window):
    assert [
        window.tools_tabs.tabText(i) for i in range(window.tools_tabs.count())
    ] == ["Convert Files", "Narrator", "Prepare Images", "Unblock Tracker"]
    assert _keys(window.unblock_tracker_tab) == ["unblock_tracker"]


def test_the_apps_tab_lists_the_suites(window):
    """Only the suites get a tile; their companions are nested inside them.

    `sentinel_ai` is archived and `create_and_publish` was renamed to
    `imprint`, so neither belongs here any more.
    """
    assert _keys(window.apps_tab) == ["sentinel_fork", "imprint", "sonar"]


def test_companions_are_nested_under_their_suite(window):
    """VPN Agent and Bug Spray live inside sentinel_fork's repo, vidforge inside
    imprint's. Listing them as peers would misrepresent the structure."""
    nested = {
        card.app.key: [row.app.key for row in card.companions]
        for card in window.apps_tab.cards
    }

    assert nested == {
        "sentinel_fork": ["vpn_agent", "bug_spray"],
        "imprint": ["vidforge"],
        "sonar": [],
    }


def test_every_launchable_app_is_reachable(window):
    """The flat list behind the menu bar and the self-test must not lose an app
    just because the Apps tab groups them."""
    on_screen = {c.app.key for c in window.apps_tab.cards}
    on_screen |= {r.app.key for c in window.apps_tab.cards for r in c.companions}
    on_screen |= {c.app.key for c in window.backup_sync_tab.cards}
    on_screen |= {c.app.key for c in window.unblock_tracker_tab.cards}

    assert on_screen == {app.key for app in launcher.LAUNCHPAD}


def test_no_tab_label_hides_an_accelerator(window):
    """Qt treats "&" in a tab label as a mnemonic marker, so "Backup & Sync"
    renders as "Backup _Sync" with the S underlined."""
    labels = [window.tabs.tabText(i) for i in range(window.tabs.count())]

    assert not any("&" in label for label in labels)
