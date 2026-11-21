# QA / Verify, spec `apps-discovery` (phase 7)

Role: `qa-engineer`, read-only for production code. Date 2026-11-21. Branch `claude/apps-discovery-design-38b98a`,
verified commit **668eab2** (HEAD at start). Contract: spec `docs/specs/apps-discovery.md` §2, §6, §7, §12, §13.6.

## Process notes
- Playbook `docs/playbooks/qa-engineer.md`: `status: current`, `last-reviewed: 2026-10-14` (38 days): not stale.
- `docs/foundry/app-context.md` is still the unfilled template: it lists no test modes, Commands or Models-used inventory
  for this feature. "Every mode" therefore means: the repo's own `pytest.ini` suite, `main.py --selftest`, and the
  playbook's `-W error::pytest.PytestDeprecationWarning` run. No linter or type checker is installed (not verified).
- **Tree drift during Verify.** At start `git status` showed only `docs/foundry/activity.jsonl`. Later the real worktree showed
  uncommitted edits to `lab_hub/discovery.py`, `lab_hub/launcher/registry.py`, `main.py` and a new
  `tests/test_apps_discovery_security.py` (the parallel security session; not mine). Everything below that needs an exact
  commit (second full run, order runs, mutation, coverage) ran on a pristine `git archive 668eab2` copy in the scratchpad,
  with a fresh `git init`. Before I finished, the security session committed them as `48c1ee6` (and a docs commit `95869a3`
  landed): **those two commits are not covered by this verdict**; a re-run of the full suite on the new HEAD is needed.
- I did not append to `docs/foundry/activity.jsonl` (tracked file, brief says do not edit tracked files).
- Plugins `pytest-randomly`, `pytest-timeout`, `coverage`/`pytest-cov` are not installed in the venv and the repo has no CI
  config (no `.github/`): the playbook's random-order, per-test timeout and coverage practices are not in force (P2-2).

## 1. Success measure (spec §2 items 1-4 and §6 bullet by bullet)
All tests below were run (60 selected tests, `60 passed`; also green in both full runs).

| Spec | What it demands | Proving test(s) | Result |
|---|---|---|---|
| §2.1 | exactly one suggestion for a new project | `test_discovery.py::test_a_folder_that_passes_every_rule_gives_exactly_one_suggestion` (positive control) + 16 one-breaker rows `test_each_rule_alone_keeps_a_folder_from_being_suggested[...]` | pass |
| §2.1 | Add gives a tile on next refresh, no restart | `test_discovery.py::test_add_writes_the_local_file_and_a_reload_shows_the_tile`; `test_apps_discovery_ui.py::test_add_writes_the_file_gives_a_tile_and_says_so` | pass |
| §2.1 | Not now / Never hide it | `test_apps_discovery_ui.py::test_not_now_hides_the_row_for_fourteen_days`, `::test_never_hides_the_row_for_good_and_says_how_to_undo` | pass |
| §2.1 | today's expected suggestions: Kaila, Overseer, Shopfront HQ, nothing else | no repo test (a test must not read the owner's lab). **My real run, section 4:** exactly those three | pass (by real run) |
| §2.2 | Never = ever; Not now = 14 days (day 13 hidden, day 14 asked) | `test_a_never_answer_hides_a_folder_for_good`, `test_not_now_hides_for_13_days_and_asks_again_on_the_14th` (injected clock) | pass |
| §2.2 | no git call, no network | `test_the_scan_makes_no_subprocess_call` (patched `subprocess.run/Popen/check_output`, `os.system/popen` raise), `test_the_module_imports_no_subprocess_at_all` | pass |
| §2.3 | no-launch tile: no Launch, no state pill | `test_apps_discovery_ui.py::test_a_no_launch_tile_has_no_launch_button_and_no_state_pill`, `::test_pressing_launch_on_a_no_launch_tile_does_nothing` | pass |
| §2.3 | Land where it applies | `::test_a_no_launch_tile_offers_land_like_any_tile` | pass |
| §2.3 | no menu-bar entry | `test_tray.py::test_a_project_with_no_launch_command_has_no_menu_entry`, `test_registry.py::test_only_launchable_apps_are_in_apps_menu_bar_apps_and_launchpad` | pass |
| §2.3 | no Check builds row | `test_launcher.py::test_the_build_report_skips_an_entry_less_app_however_it_is_asked` | pass |
| §2.3 | **Ask Claude** on the tile | not covered, by decision: §14.2 (approved with "Approve as recommended") says no tile button; it stays in the Land window | n/a |
| §2.4 | Lab Hub tile: running build, repo state, Land; no Launch/Bring to front/Stop/Quit | `::test_lab_hub_tile_is_the_last_one_and_is_an_own_card`, `::test_lab_hub_tile_has_no_launch_stop_or_update_buttons`, `::test_lab_hub_tile_shows_the_running_build_and_the_approved_words`, `::test_land_shows_on_lab_hub_tile_when_its_repo_needs_attention`, `::test_check_builds_has_exactly_one_lab_hub_row_with_the_tile_present` | pass |
| §2 last line | Kaila and Lab Hub tiles screenshotted before/after **on the real Mac** | not covered: offscreen renders only (section 5); real-Mac check is open (section 6) | open |
| §6.1 | temp lab: `.git` file, no app-context, `.hidden`, `_x`, symlink out, `lab_hub`, worktree under `.claude/worktrees`, two refreshes | the table above; `test_lab_hub_itself_is_never_suggested`, `test_worktrees_and_nested_repos_are_never_scanned`, `test_two_scans_in_a_row_give_the_same_answer`, `test_apps_discovery_ui.py::test_two_refreshes_in_a_row_leave_the_same_row` | pass |
| §6.3 | Add writes `apps-local.toml`; broken local file leaves list and reports; key clash yields | above + `test_registry.py::test_a_broken_local_file_leaves_the_list_as_it_was_and_says_why` (7 inputs), `::test_an_entry_the_hand_written_file_has_wins_and_says_so` | pass |
| §6.4 | no-launch parses; 9 shipped entries unchanged | `test_registry.py::test_every_shipped_entry_is_launchable_and_passes_the_new_field_rules`, `::test_the_shipped_list_keeps_every_registered_app_as_it_was`; real run lists the 9 | pass |
| §6.5 | Lab Hub tile present, last, shows version string and verdict | `::test_lab_hub_tile_is_the_last_one...`, `::test_the_verdict_line_and_the_behind_suffix`, `::test_the_verdict_arrives_through_the_worker`, `::test_three_polls_call_self_status_zero_times` | pass |
| §6.6 | mutation check on detection rules | section 3 (mine) plus the author's 95 (core review) | pass |
| §6.7 | real run on the Mac | partly: real lab folder run (section 4) and offscreen shots (5); **the real-Mac screenshots are not done** | open |
| §13.6 | self-test ignores a garbage local file | `test_selftest_app_list.py` (6 tests) and `main.py --selftest` below | pass |
| §7 wording | banner/tile/Settings words | `test_discovery_banner.py::test_the_banner_words_tooltips_and_accessible_names`, `test_apps_discovery_ui.py::test_the_no_launch_hint_and_the_name_tooltip_are_the_approved_words`, `test_settings_tab.py::test_hidden_projects_*` (reviewer also checked byte for byte) | pass |
| §12.1.6 width | banner `minimumSizeHint().width() <= 500` in both themes | `test_discovery_banner.py::test_three_long_rows_never_make_the_banner_wider_than_the_column[dark]` / `[light]` | pass |

## 2. Suite, selftest, order
Python 3.11.15, pytest 9.1.1, `QT_QPA_PLATFORM=offscreen`, venv `/Users/as/Documents/lab/active/lab_hub/.venv`.
- **Full suite run 1** (real worktree, started on a clean HEAD, `-qq`): 1718 dots + 1 `s`, 0 F/E, **exit 0**
  (1719 collected: `pytest --collect-only -o addopts=""`).
- **Full suite run 2** (pristine copy of 668eab2, `-W error::pytest.PytestDeprecationWarning -rs`): 1718 dots + 1 `s`,
  0 F/E, **exit 0**; the only skip is `tests/test_converter_drift.py:85` ("imprint is not checked out beside this
  repository"). Only warning: 10 `DeprecationWarning`s from `tests/test_convert_drop.py:75` (`QDragEnterEvent`), pre-existing
  and in the test, not in `lab_hub.*`/`ui.*`.
- `main.py --selftest` (`GIT_OPTIONAL_LOCKS=0`): ends `OK`, **exit 0**; "app list ... (9 apps)", all 9 registered paths `ok`.
- Each feature module alone (13 modules: discovery, registry, discovery_banner, own_verdict, apps_discovery_ui,
  selftest_app_list, settings_tab, launcher, tray, tab_groups, apps_tab, wake_start, self_update): all green.
- Order runs of those 13 files together (673 tests): forward **exit 0**; an interleaved order **exit 0**; **reverse order exit 1,
  1 failure** (P2-1). `tests/test_theme.py tests/test_land_confirm.py`: exit 0 (the review's P3-8 fix holds).

## 3. Mutation check (independent of the author)
Method: `git archive HEAD` copy in the scratchpad with its own `git init`, one string replacement at a time, then
the 12 feature test modules (637 tests, `-x`), reverted after each; the real tree was never edited.
Script: `.../scratchpad/qa_mutate.py`, `qa_mutate2.py`. **68 mutants: 66 killed, 2 survived.** (The author reported 95 / 81;
these are my own, partly different, set.)

| Group | Mutants (killed unless marked) |
|---|---|
| Detection, `discovery.py` | D1 follow symlinks (`entry.is_dir()`), D2 drop dot/underscore rule (killed only by the test that loosens `NAME_OK`, since `NAME_OK` already rejects those names: the rule is redundant by design), D3 drop `NAME_OK`, `.git` must-be-dir weakened, D5 drop app-context lstat, D6 drop realpath-inside, D7 drop `lab_hub` exclusion, D8a/b/c registered same / nested / case, D9 dismissed ignored |
| 14-day clock | C1 14 to 15, C2 day-14 boundary `<=`, C3 same-day not hidden, C4 Never not permanent, C5 future date hides, U13 `dismiss` ignores injected clock |
| Caps and writer | D10 entry cap, D11 README cap, D12 summary 220 to 221, U15 name cap 60 to 600, W1 no quote escape, W2 raw control chars, U16 dismissal answer unchecked |
| Registry merge/clash | R1 nested overlap, R2 case-sensitive, R3 reserved key, R4 key clash, R5 project clash, R6 launchable-first sort, R7 `local_ok` stays True, R8 forgets last good local part, R9 `launchable` always True, R10 menu bar includes no-launch |
| `launchable` guards | L1 `bring_to_front`, L2 `launch`, L3 `bundle_path`, L4 `build_report`, L5 `build_status`, L6 tray, L7 wake-start, L8 Launch visible on no-launch card, L9 `AppCard._launch` |
| PlainText calls | P1 banner labels, P2 tile name, P3 tile summary, P4 version label, P6 local_note label: killed. **P5 Settings error label: SURVIVED** (`ui/settings_tab.py:267`) |
| Scan only at Refresh | S1 poll scans, S2 Refresh does not scan, S3 poll requests the verdict |
| Lab Hub tile | T1 first not last, T2 gets an entry (Launch appears), T3 not an `OwnCard`, U10/U11 verdict line says "up to date" for behind / ahead / uncommitted (U11 needs `test_self_update.py`, which my 12-module list omitted: killed on re-run by `test_the_verdict_line_is_not_up_to_date_for_a_build_ahead_of_main` and the uncommitted twin) |
| Answers and handlers | U1 banner cap 3 to 4, U2/U3 Not now/Never swapped, U4 Add skips `launcher.reload`, U5 Add skips `apps_changed`, U6 status-line days, U7 `hidden()` lists lapsed, U8 lists vanished folder, U9 Show again never forgets, U12 banner rebuilds every time |
| **Survivor** | **U14** `discovery.py:608` (`add` on an already-present key: `_forget_quietly` removed): no test |

Constant mutants D10 (400 to 4000) are killed only by `test_the_constants_are_the_ones_the_spec_names`, not by the behaviour
test (which reads the constant), acceptable and noted.

## 4. Real run, real lab folder, read-only
Script `.../scratchpad/qa_real_run.py`, `python -I`, `config.SUPPORT_DIR` and `CONFIG_PATH` patched to a temp dir before
anything is read, shipped `lab_hub/apps.toml` (this worktree), lab folder `/Users/as/Documents/lab/active`:
```
registry source: .../lab_hub/apps.toml | apps: [sentinel, imprint, sonar, provisio, syndustryx, backstage, backup_manager, git_autosync, unblock_tracker]
local_ok: True local_note: None last_error: None
suggestions: [('kaila','Kaila',None), ('overseer','Overseer',None), ('shopfront','Shopfront HQ',None)]
scan ms (5 runs, whole suggestions() incl. registry.current, 3 README reads): [3.1, 2.11, 1.98, 1.96, 2.12]
folders in lab: backstage backup_manager foundry git_autosync imprint kaila lab_hub overseer provisio sentinel shopfront sonar syndustryx toolbox
tmp support dir contents after: []
```
Exactly Kaila, Overseer, Shopfront HQ; nothing for foundry, toolbox, lab_hub (imprint-base/-deps are not in the folder today).
Names as found in the READMEs: "Kaila", "Overseer", "Shopfront HQ". The scan is about 2 ms for the full `suggestions()` call
(spec §13.3 measured 0.09 ms for the scan alone): no refresh stall. The real `~/Library/Application Support/Lab Hub` listing
is byte-identical before and after all my runs (`ls -la` hash equal), and has no `apps-local.toml` / `apps-dismissed.json`.

## 5. Screenshots: OFFSCREEN RENDERS, NOT the real-Mac check
Qt `offscreen` platform, `QWidget.grab()`, Fusion style, Qt's bundled fonts; **not** the installed app on macOS, so they say
nothing about macOS font widths, the focus ring, retina or VoiceOver. Harness: `.../scratchpad/qa_shots.py` (temp support dir,
`AppsTab.refresh_repos` disabled so the hygiene child does not rewrite `git_autosync/hygiene.json`, `GIT_OPTIONAL_LOCKS=0`;
the repo badges come from the existing `hygiene.json`). In `docs/audit/apps-discovery-verify/` (new, untracked, not staged):
- `apps-page-banner-3-rows-graphite.png`, `apps-page-banner-3-rows-paper.png`: Apps page, banner with the real 3 rows
  (Kaila, Overseer, Shopfront HQ), first-run state, real lab folder.
- `apps-page-after-add-graphite.png`, `apps-page-after-add-paper.png`: after a real click on Kaila's Add to Apps: 2 rows left,
  Kaila tile (before Lab Hub), Lab Hub last.
- `tile-kaila-no-launch-graphite.png`, `tile-kaila-no-launch-paper.png`: Kaila's tile: "1 branch to land", summary, path, hint
  "No launch button: it has no app to open yet.", Land + Open in Terminal, no Launch (343x264 / 339x266 px).
- `tile-lab-hub-graphite.png`, `tile-lab-hub-paper.png`: Lab Hub's tile: `v2.292`, verdict "runs the checkout directly", summary,
  hint "You are using it: it has no Launch button.", Open in Terminal only (no Land: the report has no row needing it).
- `settings-hidden-projects-graphite.png`, `-paper.png` (whole Settings page) and `settings-hidden-projects-card-graphite.png`,
  `-paper.png` (the card): rows "Overseer · hidden for good" (Never) and "Shopfront HQ · not asked until 5 Dec" (Not now,
  answered 2026-11-21), each with Show again.
Harness behaviour worth knowing: `processEvents()` alone never runs `deleteLater`, so after Add the old tiles stayed painted
under the new ones (`set_tiles`, `ui/tiles.py:196-198`, deletes without hiding). With deferred deletes flushed the render is clean.
In the running app the event loop does this at once, so I treat it as a harness artefact, but it is in the section 6 list.

## Findings

### P0
None.

### P1
None.

### P2-1. Test order dependence: `test_own_verdict.py::test_the_real_timer_delivers_the_result_without_a_manual_drain` fails after `test_apps_discovery_ui.py`
Evidence (pristine copy, deterministic): `pytest tests/test_apps_discovery_ui.py tests/test_own_verdict.py` gives
`.........F` / `FAILED tests/test_own_verdict.py::test_the_real_timer_delivers_the_result_without_a_manual_drain`;
the reverse order of all 13 files fails the same single test (`RuntimeError: libshiboken: Internal C++ object (AppCard) already
deleted`, at `ui/tiles.py:227` `equalise`, reached from `QTest.qWait(50)` at `tests/test_own_verdict.py:254`). Inserting
`test_apps_tab.py`, `test_settings_tab.py` or `test_tab_groups.py` between them makes it pass, so the default alphabetical
full run is green by luck of ordering. Cause: `test_apps_discovery_ui.py`'s `_drop_tabs` fixture `shiboken6.delete(tab)`s pages
whose `QTimer.singleShot(0, self.equalise)` (from a `LayoutRequest`, `ui/tiles.py:217-219`) is still queued; the first test
that spins a real event loop runs it on deleted cards. The same test also waits on wall-clock (up to 3 s, real 100 ms timer):
time dependence. Impact: any random-order or `-p xdist` run, or one more test file sorted between them, turns the suite red.
Fix direction (not mine to make): flush `sendPostedEvents(None, DeferredDelete)` and a `processEvents()` in `_drop_tabs` before
deleting, or guard `equalise` with `shiboken6.isValid`; keep the real-timer test but make the page teardown leave nothing queued.

### P2-2. The playbook's flake controls are not in force
No `pytest-randomly`, `pytest-timeout` or coverage tool in the venv, no CI config in the repo (`.github/` absent), and
`pytest.ini` has no `-W error::pytest.PytestDeprecationWarning`. That is why P2-1 was not caught earlier, and why branch coverage
below is a line-trace proxy. I ran the deprecation flag by hand (green). Needs a CI/`harden` decision by the owner.

### P3-1. Mutation survivor: Settings error label not PlainText
`ui/settings_tab.py:267` `error.setTextFormat(Qt.TextFormat.PlainText)` can be removed with every test green. The label carries
"Could not show {name} again: {reason}." (name from a README, reason from the OS). `test_hidden_names_are_plain_text` covers the
row labels only. Add one test with a failing `forget` whose reason looks like markup.

### P3-2. Mutation survivor: `add` on an already-present key
`lab_hub/discovery.py:608` `_forget_quietly(s.folder)` (the branch that returns early when the key is already in the local file)
is untested: a leftover dismissal would stay listed in Settings. Reachable only by a hand-edit. One test.

### P3-3. Uncovered changed lines (line-trace proxy, 41 of 1187 changed executable lines)
No `coverage.py`, so **branch coverage is not measured**. A `sys.settrace` line tracer over 15 test modules found 1146 of 1187
changed executable lines in the feature files executed (96.5%); `ui/apps_tab.py`, `own_verdict.py`, `settings_tab.py`,
`tiles.py`, `tray.py`, `control.py`, `self_update.py`: 0 missed. Missed: `discovery.py:117, 135-136, 258-261, 338-339, 469-470,
579, 582-583, 625-626, 647-648` (OSError / UnicodeDecodeError / TOMLDecodeError handlers), `registry.py:372-373` (local file
OSError), `main.py:227-236` (bundled-list failure branches of the self-test), `ui/main_window.py:345-346` (the "app list was
not read" status line), `ui/discovery_banner.py:144, 187`, `state.py:929` (documented unreachable). The remaining signature
lines (`discovery.py:292, 442-446`, `registry.py:323-324`, `widgets.py:245`) are multi-line `def` headers, not logic.
(`registry.py:253-254` shows as missed but `test_a_value_nested_thousands_deep_is_a_bad_file_not_a_crash` passes: the tracer
loses the line during `RecursionError`.) All are error paths; none is a detection rule.

### P3-4. Offscreen render of the existing "Installed" pill in Paper
In `apps-page-after-add-paper.png` the pill reads like "▪nstalled" (the status dot draws over the "I"). Graphite is fine. This is
on every launchable tile (not touched by this spec) and Qt-offscreen fonts differ, so it is only a pointer for the real-Mac look.

### P3-5. Test quality, checked
- No test calls a model, the network or a subprocess in the feature (grep of the five new test files: no `requests/urllib/socket/
  anthropic/openai/claude`; `discovery.py` imports no `subprocess`). Spec §10 says no model call, so the live eval,
  `model_use.py --purpose eval` and `eval_budget_usd` do not apply: **not applicable**, nothing to record.
- Time dependence only in `test_own_verdict.py:254` (see P2-1). Clock is injected everywhere else (`discovery.today` patched).
- Real files, no filesystem mocks (temp lab folders); the owner's real support folder and lab folder untouched by the suite.
- Reviewers' earlier P2-2/P2-3 (vacuous Land and Check-builds tests) are fixed and covered by the survivors list above (L4 kills).

## 6. What only a human on the real Mac can verify (checklist)
- [ ] Screenshots before/after of Kaila's tile and Lab Hub's tile in the **installed** app, Graphite and Paper (spec §2, §6.7).
- [ ] **Double-click on Add to Apps** with 3 rows: the next row is rebuilt under the pointer; confirm a second press does not
      answer the next project (the UI review could not reproduce it with QTest; mitigation if it does: ignore clicks on a row
      younger than about 300 ms).
- [ ] Keyboard: Tab through the banner in both themes: visible **focus ring** on `QPushButton`, order Add, Not now, Never row by
      row then tiles; Space/Return presses; focus lands on the next row's Add after an answer (Design 12.1.7, 12.1.9).
- [ ] **VoiceOver** over the banner, the two tiles and the Hidden projects card: accessible names "Add to Apps, Kaila" etc.
- [ ] macOS font widths: the three banner buttons (113+87+161 px measured in Qt) and the banner at the 760 px minimum window
      (no sideways scroll); tile text wrapping at 380 px; Settings row at the 548 px minimum.
- [ ] After Add: no stale or doubled tile for a frame (P3 note in section 5); the page scrolls the new tile into view;
      status bar "Added Kaila to Apps." for 8 s.
- [ ] Real first run: banner shows exactly Kaila, Overseer, Shopfront HQ; Cmd+R does not re-ask an answered folder; relaunch keeps
      the answers (files in `~/Library/Application Support/Lab Hub/`).
- [ ] Lab Hub tile on the installed build: the verdict line (installed bundle vs checkout), "N behind" and its tooltip when
      behind, Land when the `lab_hub` row needs it; Check builds still shows exactly one Lab Hub row.
- [ ] Paper theme contrast of `warn` text (3.49:1, existing, out of scope) and the "Installed" pill glyph (P3-4).
- [ ] Menu bar: no Kaila entry; Land all count unchanged by the new tiles.

## Ranked gaps
1. P2-1 order-dependent, time-dependent real-timer test (red under any other order).
2. P2-2 no random order / timeout / coverage / deprecation flag in CI (none exists).
3. P3-1, P3-2 two mutation survivors (one-test fixes).
4. P3-3 error-path lines unexecuted; branch coverage unmeasured.
5. Real-Mac items (section 6), including the double-click and the screenshots the spec requires.
6. Commits `95869a3` (docs) and `48c1ee6` (security fixes to `discovery.py`, `registry.py`, `main.py` plus `tests/test_apps_discovery_security.py`) are newer than the verified 668eab2: re-run the suite and the mutants on them.

Verdict: PASS with fixes
