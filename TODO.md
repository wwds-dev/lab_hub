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
- [ ] `P1` `bug` `@ai` **Dock icon shown only while a window is open** — *reopened.*
  `ui/dock.py` switches the macOS activation policy (`Regular`/`Accessory`) through
  the Objective-C runtime via ctypes, and that part works: from source the process
  flips between `Foreground` and `UIElement`. Setting `LSUIElement` in the bundle so
  the switch also takes effect under LaunchServices **broke the window entirely** —
  an accessory app cannot materialise one, so `open -a` left Lab Hub running with no
  window at all. That change is reverted; a working window beats a tidy Dock.
  The blocker is measurement: `lsappinfo` reports the *declared* type from
  `Info.plist`, not the live policy, so with `LSUIElement` gone the app always reads
  `Foreground` whatever the runtime call does. Needs a real check of the Dock itself
  (a human looking, or a screen capture of the Dock) before the next attempt.
  The related reopen fix **is** shipped and tested: opening the tray menu, or
  launching an app from it, was reactivating Lab Hub's hidden window;
  `suppress_reopen()` blocks that for 5s. `tests/test_window_lifecycle.py`,
  `tests/test_tray.py`.
- [x] `P1` `bug` `@ai` **Apps tab pointed at a renamed project** — the tile called
  `create_and_publish` no longer resolved (renamed to `imprint`), but
  `Create & Publish.app` was still installed, so the card read *Installed* and
  silently launched a stale build. Worse than a dead tile.
- [x] `P2` `design` `@ai` **Companions nested under their suite** — VPN Agent and Bug
  Spray live inside `sentinel_fork`'s repo, vidforge inside `imprint`'s. They are now
  compact rows indented inside their parent's tile rather than peers of it, so the
  Apps tab mirrors the actual repo structure. Imprint, vidforge and Bug Spray were
  missing from the hub entirely. `tests/test_tab_groups.py`.
- [x] `P3` `design` `@ai` Menu bar lists **top-level apps only** — companions were
  appearing there as peers, making a six-item menu nine items long. `MENU_BAR_APPS`,
  `tests/test_tray.py`.
- [x] `P3` `bug` `@ai` Tab read "Backup_Sync" — Qt treats `&` in a tab label as a
  mnemonic marker. Renamed to "Backup and Sync", with a test forbidding `&` in labels.


## v3 — later

- [ ] `P2` `feature` `@ai` Read each project's `TODO.md` and show an open-item count next to its launch button
- [ ] `P2` `feature` `@me` Decide whether Ebook Converter deserves a tile — its job is
  already the embedded Convert Files tab, so a launch button would be a second door to
  the same thing. Left off for now.
- [ ] `P3` `infra` `@ai` Prune stale bundles: `Sentinel AI.app` (project archived) and
  `Create & Publish.app` (renamed to Imprint) are both still in `/Applications`.
- [ ] `P3` `feature` `@ai` Global search across every project's docs from the hub
- [ ] `P3` `feature` `@ai` Per-app last-launched timestamp and crash count

## Out of scope, deliberately

Lab Hub does not replace the projects it launches. Each keeps its own repo, README, venv and build script. Changing what Sentinel AI does still means changing Sentinel AI.
