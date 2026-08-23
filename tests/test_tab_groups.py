"""The top-level navigation keeps related apps and tools together."""

from __future__ import annotations

from lab_hub import launcher


def _keys(tab):
    return [card.app.key for card in tab.cards]


def test_top_level_tabs_are_grouped(window):
    assert [window.tabs.tabText(i) for i in range(window.tabs.count())] == [
        "Apps",
        "Backup & Sync",
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


def test_main_apps_no_longer_include_moved_apps(window):
    assert _keys(window.apps_tab) == [
        "sentinel_ai",
        "sentinel_fork",
        "create_and_publish",
        "sonar",
        "vpn_agent",
    ]
