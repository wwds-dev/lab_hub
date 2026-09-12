# Lab Hub — TODO

> **Legend** — priority `P0` critical · `P1` high · `P2` normal · `P3` low
> categories `security` `bug` `feature` `performance` `design` `docs` `testing` `infra` `research`
> owner `@me` (needs you — accounts, keys, money, judgement) · `@ai` (Claude can do this)

---

## v2 — current

- [x] `P1` `feature` `@ai` **Health check per app, before the button is pressed** —
  `launcher.readiness()` answers "would this start at all", where `status()` only
  answered "where from". Catches a checkout with no `.venv` and no `python3` on PATH,
  and a bundle that is still a directory but has lost its executable; either disables
  Launch and says why on the tile. The executable is read from `CFBundleExecutable`
  rather than assumed to match the app's name — Sentinel is an applet wrapper
  whose binary is `applet`, and assuming would have called a working app broken.
  `tests/test_launcher.py`, `tests/test_apps_tab.py`.
- [x] `P1` `bug` `@ai` **A child that dies at startup no longer looks like one that
  worked.** A source run was already death-watched and reports its exit code and
  captured output. The gap was the installed bundle: started through `open`, it is not
  our child, so there is no code to read. The tile now says *Starting…* and waits for
  the process to appear; if it has not within `LAUNCH_CONFIRM_SECONDS` it says *Did not
  start* and the status bar names where the output went — the `log show` predicate for a
  bundle, the captured temp file for a source run. Reported once, not on every poll.
  `tests/test_apps_tab.py`.
- [x] `P2` `feature` `@me` Decide whether Lab Hub should start at login (LaunchAgent) or stay manual — decided yes: `lab_hub/login_item.py` installs a LaunchAgent, toggled from the Settings tab, and on login it also starts Backup Control Center and git_autosync if they're not already running.
- [x] `P2` `testing` `@ai` **`--selftest` probes every registered app**, not one
  sibling sample: a real `QApplication` under each app's own venv, with the scrubbed
  child environment. The env is shared but the Qt build on the other side of it is each
  project's own, so each venv is its own answer. Judgement call worth knowing about: it
  probes each app's *interpreter* rather than running the app — launching six GUI apps
  on every build would not survive being run, and the crash it guards against happens
  inside `QApplication()` before any app reaches its own code. No checkout or no venv is
  reported as skipped, never as a pass.
- [x] `P3` `design` `@ai` Apps tab: group by category rather than one flat list, now that there are twelve projects — addressed by splitting into three tabs (Apps / Backup & Sync / Tools) instead of grouping within one tab; the Apps tab itself is back down to 5 items (`PRIMARY_APPS`).
- [x] `P1` `bug` `@ai` Red button quit instead of hiding — and the fix for that re-showed the window in the same breath as closing it. Both shipped, with `tests/test_window_lifecycle.py` as the regression.
- [x] `P2` `infra` `@ai` Config written to `~/Library/Application Support/Lab Hub/`, never inside the bundle
- [x] `P2` `feature` `@ai` **Narrator Library** — a second sub-tab browsing the generated ebook catalogue (`ebook_catalog.csv` from Codex's `outputs/`), with per-row Read/Queue checkboxes persisted to `narrator_library_state.json`, a Narrated-books filter (matched against existing audio files, not tracked separately), and one click to load a book into Convert. `ui/narrator_library.py`, `tests/test_narrator_tab.py`.
- [x] `P1` `bug` `@ai` **Dock icon shown only while a window is open** — done, and
  verified in the packaged app across all four states (login start, app launched from
  the menu bar, window opened, window closed). Three pieces were needed: `LSUIElement`
  in the bundle (LaunchServices pins the type from `Info.plist`, so the runtime switch
  alone is ignored once packaged), the policy switch in `ui/dock.py`, and — the piece
  that was missing — `dock.activate()`, because promoting out of `Accessory` gives a
  Dock icon but does not make the app frontmost, so the window was created and left
  sitting behind everything. That looked like "no window", which is why this was
  reverted once as impossible. `--selftest` prints the true reading via
  `dock.current_policy()`; use that. The note here used to blame `lsappinfo` for
  that wrong turn, which was unfair — its `ApplicationType` does track the live
  policy (`Foreground` with the window up, `UIElement` once hidden, against one
  running pid). It could only ever show a switch that was actually happening, and
  back then it was not. `tests/test_window_lifecycle.py`.
- [x] `P1` `design` `@ai` **Quitting from the Dock hides Lab Hub instead.** The Dock
  icon only exists while a window does, so Quit there — and ⌘Q — means "off my
  screen", not "shut it down"; both used to take the menu bar item with them. macOS
  sends these through `applicationShouldTerminate:`, which Qt delivers as a
  `QEvent.Quit` to the application object; `_QuitGuard` answers with `event.ignore()`.
  Returning `True` alone does not refuse it: a `QEvent` starts out accepted and
  filtering one leaves that flag set, which macOS reads as consent. The menu bar's own
  **Quit Lab Hub** is the single real exit and bypasses the event entirely; a test runs
  a real event loop with a failsafe timer to prove it, because the failure mode here is
  an app that cannot be quit. Verified against the installed bundle: the quit Apple
  Event came back `-128` (cancelled), the pid survived and its type went
  `Foreground` → `UIElement`. `tests/test_window_lifecycle.py`.
- [x] `P1` `bug` `@ai` **Apps tab pointed at a renamed project** — the tile called
  `create_and_publish` no longer resolved (renamed to `imprint`), but
  `Create & Publish.app` was still installed, so the card read *Installed* and
  silently launched a stale build. Worse than a dead tile.
- [x] `P2` `design` `@ai` **Umbrella apps only — agents are not separately launchable.**
  Tunnel and Bug Spray live inside Sentinel (`sentinel_fork/agents/`), the video
  pipeline inside Imprint, macro and Playmaker inside SONAR. Lab Hub lists the three
  umbrella apps and nothing below them, in the Apps tab and the menu bar alike. The
  nested-companion rows tried in between are gone: they still offered a second door to
  a feature that belongs to its parent app. `/Applications/VPN Agent.app` is still
  installed and **stale** (built Aug 17; the source has commits through Sep 9). It is
  not orphaned — `build_app.sh` and the spec moved along with the source to
  `sentinel_fork/agents/vpn_agent`, so it rebuilds from there. Not deleted: VPN Agent
  is essential to Sentinel and is being worked on elsewhere.
  `tests/test_tab_groups.py`, `tests/test_tray.py`.
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
- [x] `P3` `infra` `@me` **Stale bundles pruned** (2026-09-12, by hand): `Sentinel AI.app`
  (project archived), `Create & Publish.app` (renamed to Imprint), `vidforge.app`
  (Imprint imports the same pipeline as its Video mode) and `VPN Agent.app` (stale, and
  a second door to an agent that belongs inside Sentinel). None was referenced by a
  LaunchAgent, and no source was touched: VPN Agent rebuilds from
  `sentinel_fork/agents/vpn_agent/build_app.sh`, vidforge from its own repo, and
  Sentinel AI is archived but fully pushed to GitHub.
- [ ] `P3` `feature` `@ai` Global search across every project's docs from the hub
- [ ] `P3` `feature` `@ai` Per-app last-launched timestamp and crash count

## Out of scope, deliberately

Lab Hub does not replace the projects it launches. Each keeps its own repo, README, venv and build script. Changing what Sentinel AI does still means changing Sentinel AI.
