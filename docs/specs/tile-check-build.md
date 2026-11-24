# Spec: a Check build button on each app tile, beside Land

Needs: define, design, build, review, verify, docs

Status: **Define draft, awaiting the owner's gate.** Phase: Define, 2026-11-24.
In-flight check (`session_start.py --inflight`, 2026-11-24): no unreleased spec covers a per-tile build check (`land-*`, `self-update` and `apps-discovery` touch the same file, `ui/apps_tab.py`, but none of them builds or changes this).

## 1. Problem and evidence
Owner, 2026-11-24: "each tile should have its own check builds button just like we already have it with Land."
- **Check builds** exists only as one page-level button (`ui/apps_tab.py:886`) that reports every registered app, Lab Hub last. To check or rebuild one app you must run all of them and wait.
- **Land** already works per tile (`land_button`, `ui/apps_tab.py:185`) and page-wide (**Land all**). Build check has the page-wide half only.
- The machinery for a subset exists: `show_build_report` takes `_build_apps` and scopes the report to those apps (the Backstage and sync-companion tabs use it, with a **Check build** button, `ui/apps_tab.py:909`).

## 2. User and success measure
The owner, on the Apps page.
1. Each tile that has a build to check shows **Check build** beside Land and Launch.
2. Clicking it opens the same Check builds window, for that one app only: same rows, same Review, Update and Done steps, same Copy commands and Ask Claude, same "Needs you" and "Not rebuilt" wording. It never reports or rebuilds another app.
3. The page-level **Check builds** (all apps) stays as it is.
4. Lab Hub's own tile follows the same rule as today's report: its row is Lab Hub's own build and update (spec `self-update`), with the same "will update after this finishes" note when a page is busy.
5. A tile whose app has nothing to build (source-only, no installed bundle, or outside the lab scheme) shows no button, and its tooltip/status already says why; no disabled button without a reason.
6. While Land or a build check runs for that app, the other of the two is disabled on that tile (one job per repo at a time).
Measured by tests: for a fixture of three apps, the tile button reports exactly its own app, and the page button still reports all; a tile with nothing to build has no button.

## 3. Scope
- `ui/apps_tab.py`: `AppCard` gets the button and a `check_build_requested` signal; the page passes the one app to the existing scoped path of `show_build_report`.
- Reuse `launcher.build_report(root, apps)` and `BuildCheckWindow`; no new report logic.
- Tests with the existing fixtures; README, CHANGELOG.

## 4. Non-goals
No change to what a build check compares or what Update now does; no new rebuild commands; no change to Land; the tile's "behind" badge link stays.

## 5. Decisions for the owner
1. **Label.** Recommend **Check build** (singular) on tiles. Alternative: **Check builds** everywhere.
2. **Tiles with nothing to build.** Recommend: no button. Alternative: show it disabled with the reason in its tooltip.

## 6. Risks
Two windows at once: the dialog is application-modal, so only one build check runs at a time; a per-tile click while another build check is open is not possible. Same repo as Land: covered by §2.6 and the existing per-repo claim in `lab_hub/land.py`.

## 7. Phases
Define (this, **GATE**: new user-visible control), Design (small: a button beside two others), Build, Review, Verify, Document. Skipped: Case, Architect (no state, concurrency or boundary change), Secure (no network, input or files), Comply and Launch (no claim changes), Release (owner's call).
