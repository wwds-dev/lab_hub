# Lab Hub — Suggestions

Status: `IDEA` · `CONSIDERING` · `PLANNED` · `DONE` · `REJECTED`

---

| # | Suggestion | Category | Effort | Status |
|---|---|---|---|---|
| 3 | Open-TODO count per project, read from each `TODO.md` | feature | M | CONSIDERING |
| 4 | Documentation search across every project from the hub | feature | L | CONSIDERING |
| 7 | Per-app last-launched timestamp and crash count | feature | M | IDEA |
| 8 | Drag-to-reorder the app list | design | S | IDEA |
| 10 | Warn when a tile's bundle is newer or older than its checkout | feature | M | IDEA — would have caught `Create & Publish.app` still launching after the rename |
| 11 | Read the app registry from a file instead of compiling it into the bundle | design | M | IDEA — renaming a launched app currently degrades its tile to *Source only* until Lab Hub itself is rebuilt, and the fault looks like it belongs to the renamed app. Twice now: `Create & Publish` → `Imprint`, then `Sentinel Fork` → `Sentinel` |

## Done

| Suggestion | When |
|---|---|
| Pre-flight health check per app — `launcher.readiness()`; a checkout with no interpreter, or a bundle that lost its executable, disables Launch and says why on the tile | Sep 2026 |
| Exit code and captured output shown when a launched child dies immediately — a source run has both, a bundle has neither so the tile waits at *Starting…* then turns to *Did not start* via the `log show` predicate | Sep 2026 |
| Apps tab with launch buttons | Aug 2026 |
| Menu-bar integration and single-instance guard | Aug 2026 |
| Convert Files / Prepare Images / Unblock Tracker tabs (vendored tools) | Aug 2026 |
| `--selftest` that starts a real PySide6 child before installing — under every registered app's own venv since Sep 2026, not one sibling sample | Aug 2026 |
| Running-state on each card, with *Bring to front* instead of a duplicate launch | Aug 2026 |
| Umbrella apps only — agents and sub-modules get no tile and no menu bar entry (the companion rows tried first were removed) | Sep 2026 |
| Dock icon only while a window is open; menu bar lists top-level apps only | Sep 2026 |
| Start-at-login via LaunchAgent, plus auto-start Backup Control Center/git_autosync and a post-wake recheck | Aug 2026 |
| Backup & Sync tab split out of Apps; Narrator tab added to Tools | Aug 2026 |
| Narrator Library sub-tab — browse the ebook catalogue, mark read/queued, filter to narrated books, load straight into Convert | Sep 2026 |
| Dock icon follows the window (hidden while no window is open); tray-menu and app-launch reopen suppression so using the menu bar doesn't reactivate Lab Hub's own window | Sep 2026 |
