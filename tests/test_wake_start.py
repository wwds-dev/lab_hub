"""Sleep/resume quietly keeps the backup companions alive."""

from __future__ import annotations

from lab_hub import launcher
from ui import main_window


def test_wake_starts_missing_sync_apps_in_background(window, monkeypatch):
    started = []
    monkeypatch.setattr(launcher, "process_table", lambda: "")
    monkeypatch.setattr(launcher, "is_running", lambda *args: False)
    monkeypatch.setattr(
        launcher,
        "launch",
        lambda app, root, **kwargs: started.append((app.key, kwargs)),
    )

    window.start_sync_apps_in_background()

    assert started == [
        ("backup_manager", {"background": True}),
        ("git_autosync", {"background": True}),
    ]


def test_wake_never_starts_a_sync_entry_with_no_launch_command(window, monkeypatch):
    from lab_hub.launcher import registry

    started = []
    monkeypatch.setattr(launcher, "process_table", lambda: "")
    monkeypatch.setattr(launcher, "is_running", lambda *args: False)
    monkeypatch.setattr(launcher, "launch", lambda app, root, **kw: started.append(app.key))
    registry.use(registry.Registry(backup_sync=(
        launcher.ExternalApp("a", "A", "a", "main.py", "s"),
        launcher.ExternalApp("k", "K", "k", None, "s"),
    )))
    try:
        window.start_sync_apps_in_background()
    finally:
        registry.use(None)

    assert started == ["a"]


def test_short_timer_delay_is_not_treated_as_wake(window, monkeypatch):
    calls = []
    window._last_wake_poll = 100
    monkeypatch.setattr(main_window.time, "monotonic", lambda: 130)
    monkeypatch.setattr(window, "start_sync_apps_in_background", lambda: calls.append(1))

    window._check_for_wake()

    assert calls == []


def test_sleep_sized_timer_gap_is_treated_as_wake(window, monkeypatch):
    calls = []
    window._last_wake_poll = 100
    monkeypatch.setattr(main_window.time, "monotonic", lambda: 161)
    monkeypatch.setattr(window, "start_sync_apps_in_background", lambda: calls.append(1))

    window._check_for_wake()

    assert calls == [1]
