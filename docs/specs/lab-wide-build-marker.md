# Spec: every lab app's tile shows its real build and how far behind it is

Status: **Define draft, awaiting the owner's gate.** Phase: Define (`product-manager`). Owner: Lab Hub session, 2026-11-13.
Nothing was built, installed, tagged or pushed. In-flight check (`session_start.py --inflight`, lab_hub and provisio, 2026-11-13): no spec covers this.

## 1. Problem and evidence
The owner asked why the Provisio tile shows `v2.0.174` with nothing behind it, and said every app must be treated the same.
- Tile text comes from `lab_hub/launcher/state.py` `version()` (`:584`): `v<major>.<build>` only. `Version` (`:329`) has no commit field.
- Provisio's own marker is `v<line>.<count>+g<sha7>[-dirty][ (<branch>)]` (`provisio/docs/VERSIONING.md`, ADR-0006). The tile drops everything after the count.
- The commit is already known for some apps: Imprint's `_build_info.json` carries `"commit": "7b41c33"`; `lab_hub/version.py` `info()` reads it. The tile never shows it.
- Provisio's bundle is a launcher stub (`bundle_runs_checkout`, `:359`), so its tile reads the checkout (`checkout_version`). Its Info.plist holds only `CFBundleShortVersionString = 2.0` and its installer stamps no `_build_info.json`.
- Consequence: no tile can say which commit it would open, so "is this the build I made?" is answered only by commit count, which names different code on different branches (the reason Provisio added `+g<sha7>`).

- **Found 2026-11-13, the actual cause of the owner's question.** `/Applications/Provisio.app/Contents/Resources/project_root.txt` is `/Users/as/Releases/provisio`, the release clone, at 153 commits (`c534bbb`). The tile showed `v2.0.174`, the working checkout's count, with no `· N behind`. The installed app is really `v2.0.153+gc534bbb`, 21 commits behind. Frozen-bundle tiles get the `· N behind` suffix (`ui/apps_tab.py:210`); launcher-bundle tiles never do, because `version()` assumes a launcher "runs the checkout, so it cannot be behind it" (`state.py:~330`). That holds only when the recorded root is the working checkout.

## 2. User and success measure
User: the owner, on the Lab Hub window.
Measure (all demonstrable by test or screenshot). Owner, 2026-11-13: "just like the other apps", i.e. one behaviour for all.
0. A launcher-bundle tile reads the build from the root the bundle records (`project_root.txt`), not from the lab's working checkout, and shows `· N behind` against the working checkout's HEAD exactly as a frozen bundle does. Provisio shows `v2.0.153 · 21 behind`.
1. Every tile whose app is in the lab scheme shows `v<major>.<build>+g<sha7>`; the same string is in its tooltip with its origin (bundle stamp or checkout).
2. The same rule for every app and every origin (stamped bundle, launcher bundle, source-only tile). No per-app branches in the tile code.
3. An app with no commit evidence shows `v<major>.<build>` with no `+g` and a tooltip saying the commit is unknown. It never borrows another origin's commit.
4. A checkout with uncommitted changes shows `-dirty`, same grammar as Provisio's marker.
5. The Lab Monitor computes the same string from the same inputs, so dashboard and tile agree.
6. Apps outside the scheme (SYNDUSTRYX, plist release number) keep their current text; the tooltip says why there is no commit.

## 3. Scope
- Lab Hub: `Version` gains `commit` and `dirty`; `version()`, `checkout_version()`, `_stamped_version()` fill them; the tile renders the marker.
- Stamp: `_build_info.json` already has `commit`; make it a required key for `scripts/stamp_version.py` copies. Apps whose installer writes no stamp (Provisio, other launcher-bundle apps) are covered by reading the checkout, so no installer change is needed for them.
- Lab Monitor (`update_lab_project_monitor.py`): same string.
- Each app's own window title keeps its own format; this spec changes the tile and the monitor only.

## 4. Non-goals
- No change to any app's own version string or to `VERSION` files.
- No tags, no release process change, no rebuild or reinstall of any app.
- No new stamp format; the existing `_build_info.json` keys are reused.

## 5. Decisions for the owner
1. **Grammar.** Recommend Provisio's: `v2.0.174+g7274eb0`, with `-dirty` where a checkout is dirty. Alternative: commit in the tooltip only.
2. **Branch suffix** (` (<branch>)` when not `main`) on the tile too? Recommend yes for checkout tiles, since those run whatever is checked out; never for stamped bundles.
3. **Stale warning** stays as is (`behind`), and compares the stamped commit with HEAD, not only counts. Recommend yes.

## 6. Risks
- Shells out to git per tile: keep the existing cached poll (`state.py:423`); one `rev-parse --short` and one `status --porcelain` per app per refresh, not per repaint.
- Shallow or detached checkouts: same rules as Provisio (`unknown` count, commit still shown).
- Tile width: the longer text must fit the card at the minimum window size (screenshot in Verify).

## 7. Phases to run
Define (this file, **GATE**), Architect (module boundary: tile vs `state.py`; no state or concurrency change expected), Plan, Build, Review, Verify, Document. Secure and Comply skipped unless Build adds file writes (none planned). Tier `public` applies to Comply if it is needed.
