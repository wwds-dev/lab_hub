# Lab Hub — Suggestions

Status: `IDEA` · `CONSIDERING` · `PLANNED` · `DONE` · `REJECTED`

---

| # | Suggestion | Category | Effort | Status |
|---|---|---|---|---|
| 3 | Open-TODO count per project, read from each `TODO.md` | feature | M | CONSIDERING |
| 4 | Documentation search across every project from the hub | feature | L | CONSIDERING |
| 7 | Per-app last-launched timestamp and crash count | feature | M | IDEA |
| 8 | Drag-to-reorder the app list | design | S | IDEA |
| 12 | Websites tab: certificate expiry and response-time trend per site | feature | S | IDEA — the check already holds the reply; a certificate within 14 days of expiry is the next thing that takes a site down unnoticed |
| 13 | Read the Websites list from a catalog beside `dashboard_catalog.json`, the way the Dashboards tab already does | design | S | IDEA — a dashboard added to the catalog appears with no rebuild; a site still needs one, the same trap as #11 on a smaller scale |
| 14 | One "Needs you" inbox across apps: `@me` items, sign-offs waiting, builds behind (extends #3) (portfolio review 2026-11-18) | feature | M | IDEA |
| 15 | Cmd+K palette for apps, actions and docs (builds on #4) (portfolio review 2026-11-18) | feature | M | IDEA |
| 16 | One home for each utility: stop carrying Convert Textfiles and Prepare Images as copies of toolbox's `convert_epub` and `image_tools` (portfolio review 2026-11-18) | design | M | IDEA |
| 17 | Move Land and repo hygiene into the sync tool, so commits and worktree cleanup live in one place (git_autosync #8) (portfolio review 2026-11-18) | design | L | IDEA |
| 18 | Make the repo private and the tier `internal`: nobody else uses the launcher, and the public tier brings the privacy note, name check and sign-off (portfolio review 2026-11-18) | infra | S | IDEA |
| 19 | Lab Hub as Kaila's visual face: a chat and voice bar that answers "what is blocked?" and runs "build and land Imprint" through her guard (portfolio review 2026-11-18) | feature | L | IDEA |

## Done

| Suggestion | When |
|---|---|
| Read the app registry from a file instead of compiling it into the bundle (#11) — `lab_hub/apps.toml`, read from the checkout and re-read on Refresh (Cmd+R) | Oct 2026 |
| Warn when a tile's bundle is behind its checkout (#10) — the tile reads `v2.104 · 5 behind`, and Check builds reports behind / uncommitted / unknown per app | Oct 2026 |
| Trackpad swipe between tabs — two-finger scroll and three-finger native gesture, innermost tabs first, no wrap, yields to a sideways-scrolling table; a vertical swipe changes page unless the page itself scrolls | Oct 2026 |
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
| Fixed the Check builds report dialog being impossible to dismiss (no Escape/close-button route when every button was ActionRole) | Sep 2026 |
