# Lab Hub — TODO

> **Legend** — priority `P0` critical · `P1` high · `P2` normal · `P3` low
> categories `security` `bug` `feature` `performance` `design` `docs` `testing` `infra` `research`
> owner `@me` (needs you — accounts, keys, money, judgement) · `@ai` (Claude can do this)

---

## v2 — current

- [ ] `P1` `feature` `@ai` Health check per launched app — show whether its venv resolves and its entry point exists *before* the launch button is pressed
- [ ] `P1` `bug` `@ai` A launched child that dies immediately currently looks identical to one that started fine; surface the exit code
- [x] `P2` `feature` `@me` Decide whether Lab Hub should start at login (LaunchAgent) or stay manual — decided yes: `lab_hub/login_item.py` installs a LaunchAgent, toggled from the Settings tab, and on login it also starts Backup Control Center and git_autosync if they're not already running.
- [ ] `P2` `testing` `@ai` Extend `--selftest` to launch every registered app, not just a sibling sample
- [x] `P3` `design` `@ai` Apps tab: group by category rather than one flat list, now that there are twelve projects — addressed by splitting into three tabs (Apps / Backup & Sync / Tools) instead of grouping within one tab; the Apps tab itself is back down to 5 items (`PRIMARY_APPS`).
- [x] `P1` `bug` `@ai` Red button quit instead of hiding — and the fix for that re-showed the window in the same breath as closing it. Both shipped, with `tests/test_window_lifecycle.py` as the regression.
- [x] `P2` `infra` `@ai` Config written to `~/Library/Application Support/Lab Hub/`, never inside the bundle
- [x] `P2` `feature` `@ai` **Narrator Library** — a second sub-tab browsing the generated ebook catalogue (`ebook_catalog.csv` from Codex's `outputs/`), with per-row Read/Queue checkboxes persisted to `narrator_library_state.json`, a Narrated-books filter (matched against existing audio files, not tracked separately), and one click to load a book into Convert. `ui/narrator_library.py`, `tests/test_narrator_tab.py`.
- [x] `P1` `bug` `@ai` **Dock icon shown only while a window is open** — `ui/dock.py` switches the app's macOS activation policy (`Regular`/`Accessory`) via ctypes; the bundle needs `LSUIElement` set too, or LaunchServices pins the type at launch and the runtime call is ignored. A related reopen bug: opening the tray menu, or launching an app from it, was reactivating Lab Hub's own hidden window — `suppress_reopen()` now blocks that for 5s. `tests/test_window_lifecycle.py`, `tests/test_tray.py`.

## v3 — later

- [ ] `P2` `feature` `@ai` Read each project's `TODO.md` and show an open-item count next to its launch button
- [ ] `P3` `feature` `@ai` Global search across every project's docs from the hub
- [ ] `P3` `feature` `@ai` Per-app last-launched timestamp and crash count

## Out of scope, deliberately

Lab Hub does not replace the projects it launches. Each keeps its own repo, README, venv and build script. Changing what Sentinel AI does still means changing Sentinel AI.
