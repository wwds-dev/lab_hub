# Verify: progress-windows (QA)

Phase: Verify (`qa-engineer`), 2026-11-17. Scope: the uncommitted `progress-windows` change on
`claude/zealous-benz-97c752` (spec `docs/specs/progress-windows.md` §2, §8.12, §8.15). Read-only:
no production or test file was edited; mutations ran in a scratch copy of the tree outside the
repo, and the worktree's `lab_hub/`, `ui/`, `tests/` checksums and `git diff` were compared
before and after (identical).

Playbook: `docs/playbooks/qa-engineer.md` `last-reviewed: 2026-10-14`, `status: current` (34 days:
not stale). Its model-testing bullet is marked baseline (Foundry v9, not radar-verified).

## Verdict

**FAIL.** QA's own blockers need only tests; production fixes still open are review P1-1 and finding 9 (review P2-2). The suite is green twice
(841 passed, 1 skipped, both runs) and the Qt-free core is well tested (40 of 48 mutants killed,
the survivors mostly boundary or masked cases). But 7 of 13 UI mutants survived, including
three on the very behaviours the spec singles out: the 10-renders-a-second throttle can turn
into a debounce that never renders under steady output, the alive tick can stop entirely, and
Escape can stop killing the build, all with the suite green. Per the playbook a survivor is a
missing test. Success measure §2.6 (screenshot on the real lab) is not yet evidenced (task 8).
The code reviewer's P1-1 (`docs/audit/progress-windows-review.md`) is also still open, so this
Verify must be repeated once the review fixes and the missing tests are in.

## 1. Success measures (§2) against the tests

| § | Measure | Tests that prove it | Gaps |
|---|---|---|---|
| 2.1 | Land window: non-modal, close hides, bar and percent, elapsed, left, done around, counts, one row per repo with stage track, running repo expanded with its step timer, reason line, collapsed live output, Hide, Stop | `test_progress.py::test_percent_counts_and_stages_for_two_repos_with_a_failure_and_a_stop`, `::test_landed_with_branches_left_needs_you_and_a_clean_land_is_landed`; `test_progress_window.py::test_the_running_row_opens_into_its_steps_with_its_own_timer`, `::test_closing_the_land_window_hides_it_and_stop_is_a_signal`, `::test_no_history_says_estimating_and_history_gives_time_left`; `test_land_ui.py::test_the_land_window_opens_after_the_confirmation_and_follows_a_two_repo_land`, `::test_hide_keeps_landing_show_progress_brings_it_back_and_its_stop_stops`, `::test_a_single_land_ends_with_its_tile_line_in_the_window`, `::test_cancelling_the_confirmation_opens_no_window` | "done around" never tested with an estimate that crosses a minute (LF5 survived); live output collapsed by default is not asserted; stage state `partial` (`progress.py:447-448`), ">5 earlier steps" (`:348-350`), "and N more" (`:367-368`) and "Not reached" (`:472-473`) never run |
| 2.2 | Check builds window replaces the box and `RebuildDialog`: step header, verdict rows, bar/percent/times/counts, rebuilding app expanded into stages with its own time left, up-to-date apps on one line, live output, every existing button and path | The 19 re-seamed tests in `test_apps_tab.py` (diff checked: the only removed `assert` lines are the 4 that moved from `dialog._button`/`dialog.succeeded` to `cancel_button`/`rebuild.succeeded`); `test_progress.py::test_build_check_view_keeps_the_headlines_and_text`, `::test_review_then_stages_advance_on_markers_and_samples_are_returned`, `::test_a_jump_marks_the_skipped_stage_not_seen`, `::test_a_run_with_no_marker_is_one_rebuilding_stage_and_records_no_stages`, `::test_stage_history_shows_four_stages_from_the_start_and_estimates_by_rebuild`, `::test_static_rows_say_their_verdict_in_words`; `test_progress_window.py::test_review_shows_the_box_buttons_and_escape_answers_none`, `::test_review_button_answers_and_copy_closes_update_stays`, `::test_a_terminal_only_and_a_no_command_app_say_what_happens`; `test_apps_tab.py::test_stage_chips_advance_on_the_lab_hub_markers_and_verify_shows_the_version`, `::test_a_build_with_no_marker_shows_one_rebuilding_stage` | The step header (Check, Review, Update, Done; `StepHeader.set_step`) is never asserted; `test_apps_tab.py:1157` `test_update_now_moves_the_window_to_its_update_step_and_copy_closes_it` asserts only `choice == "Update now"`, neither the Update step nor the Copy-closes behaviour in its name |
| 2.3 | Alive signal: animated dots, spinner on the running row, "Last activity Ns ago", amber "No output for 1:00. Still running." at 60 s | `test_progress.py::test_activity_text_at_59_and_60_seconds` (59.9 s vs 60.0 s, exact strings); `test_progress_window.py::test_the_activity_line_turns_amber_after_a_minute` (text and `stateWarn` object name) | **Nothing tests that the dots, spinner or clocks move without events**: the 500 ms tick never fires in any test (`Dots` paint and `_on_tick` paths uncovered); TH4 (tick never starts) and TH5 (tick never renders) both survived. Stale text is only checked via direct `draw()` calls |
| 2.4 | Estimate from recorded durations (median of last 5), "Estimating…" with no history, minutes above 60 s, never negative, overrun says "Taking longer than usual" | `test_durations.py` (median 1..5, sixth drops oldest, lenient load, caps); `test_progress.py::test_fmt_left` (60 -> `~60 s`, 61 -> `~2 min`), `::test_the_estimate_is_none_until_every_remaining_unit_has_history`, `::test_left_counts_down_never_goes_negative_and_overrun_is_said`, `::test_durations_subjects_match_the_model`; `test_land_ui.py` two-repo test checks samples were written | A running step with no history is not tested to say "Estimating…" (LF4 survived: it would show `~0 s left`); failed/skipped Land steps are not tested to stay out of `durations.json` at the window (REC1 survived) |
| 2.5 | Ends clearly in one line; Land all keeps "Landed N of M repos" in the window; rows stay | `test_land_ui.py::test_land_all_with_a_failure_says_so_in_the_window_not_a_box` (no box, outcome, details, plain text), `::test_a_single_land_ends_with_its_tile_line_in_the_window`; `test_progress.py` (finish -> 100 %, outcome) | Check builds end lines (`update_ended`: "Done. Every app was rebuilt…", "A rebuild failed…", "Cancelled…", `progress_window.py:925-937`) are asserted nowhere; ESC4 survived (a cancel that reads as "failed") |
| 2.6 | Model unit-tested with fake clocks and fixture events; UI tested in existing patterns; screenshot of both windows on the real lab | Met for the first two: `Clock` counters and `StepEvent` fixtures throughout `test_progress.py`, `_counter()` in `test_land.py`, injected `clock`/`wall` in `test_progress_window.py` | **Screenshot on the real lab: not done** (§8.15 says offscreen PNGs only; task 8 open). Not verified on a real display or a real `build_app.sh` run |

## 2. Test quality

Good:
- The model tests are deterministic: a counter clock and a fixed wall clock (`WALL = 14:00:00`) drive every number; assertions are exact strings and exact numbers (`percent == 33`, `samples == {"build": 40, "package": 5, "install": 2, "verify": 1, "rebuild": 47}`), so a wrong value fails.
- Boundaries the spec names are pinned on both sides: 59.9 s vs 60 s stale, `fmt_left(60)` vs `fmt_left(61)`, 21600 s cap inclusive, 99 % cap then 100 % on finish.
- `build_stage` is tested on real lines copied from each script plus the negatives the spec asked for (`INFO: Building EXE`, `Built-in`, `<b>Built: x</b>`, lowercase `pyinstaller`).
- `durations` tests use `path=` or the autouse `isolated_config`, so nothing touches the owner's Application Support.
- No network, no model, no Claude Code call in any new test; the only subprocesses are local `echo`, `printf`, `sleep`, `touch`, `false` (`test_apps_tab.py:1062-1150`).

Weak:
- `test_progress_window.py:54` `test_renders_are_throttled_to_ten_a_second` asserts `1 <= renders <= 11`. The lower bound of 1 lets a debounce pass (TH2), which is exactly the failure that would make the window look frozen under steady output. It also depends on wall time (1 s real loop); it passed in all 10 runs here (2 full suites, 3 under load, 5 alone).
- The Escape and Close regression tests (`test_apps_tab.py:1062`, `:1084`) use `sleep 30` and only assert the end state after `rebuild.exec()` returns. If `cancel()` stops killing (ESC3), `exec()` simply waits the 30 s for `sleep` to end and every assertion still holds; the run took 63 s instead of 3 s. "Kills it" is in the test name but not asserted.
- `test_progress.py:194` `done_around == "14:00"` with 20-25 s left from 14:00:00 cannot tell `wall() + left` from `wall()` (LF5).
- `test_apps_tab.py:1157`: name promises more than it checks (see 2.2).

## 3. Mutation check

Method: a small harness (scratch, not in the repo) applied one exact-string mutant at a time to a copy of the tree
(outside the repo), ran the named tests with `-x`, restored the file. Command per mutant:
`QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -o addopts= -q -x -p no:cacheprovider <tests>`.
Tests: SO/EV `tests/test_land.py`; DU `tests/test_durations.py tests/test_progress.py`;
BS/MO/LF/ST/FL/PC/LS `tests/test_progress.py tests/test_progress_window.py`; TH/RW
`tests/test_progress_window.py` (+`tests/test_land_ui.py` for TH4/TH5/REC1); ESC/REC2
`tests/test_apps_tab.py -k "escape or close_button or rebuild or stage_chips or no_marker"`;
LA1 `tests/test_land_ui.py`.

**61 planted, 46 killed, 15 survived.**

| ID | file:line | Mutation | Result |
|---|---|---|---|
| SO1 | `lab_hub/land.py:259` | `step_outcome`: drop `.lower()` | killed (`test_step_outcome[  Skipped — guard]`) |
| SO2 | `land.py:260` | `step_outcome`: skipped -> `"failed"` | killed |
| SO3 | `land.py:259` | drop `.lstrip()` | killed |
| SO4 | `land.py:302` | end event outcome from `step_outcome(True, …)` | killed |
| EV1 | `land.py:301` | end event `started = clock()` | killed |
| EV2 | `land.py:275` | `events` callback no longer wrapped in try | killed |
| BS1 | `lab_hub/progress.py:101` | drop `with PyInstaller` marker | killed |
| BS2 | `progress.py:102` | unanchored `Built: ` | killed (`<b>Built: x</b>`) |
| BS3 | `progress.py:110` | markers case-insensitive | killed |
| BS4 | `progress.py:104` | `hecking…` -> `Checking…` | killed |
| BS5 | `progress.py:103` | drop `Running self-test` | killed |
| MO1 | `progress.py:708` | monotonic guard `<=` -> `<` | killed |
| MO2 | `progress.py:708` | monotonic guard removed | killed |
| MO3 | `progress.py:714` | skipped stage marked done | killed |
| DU1 | `lab_hub/durations.py:109` | median -> mean | killed |
| DU2 | `durations.py:33` | `KEEP = 6` | killed |
| DU3 | `durations.py:146` | keep oldest 5 (`[:KEEP]`) | killed |
| DU4 | `durations.py:99` | load keeps all samples, not last 5 | **survived** |
| DU5 | `durations.py:145` | re-recorded subject not moved to newest | killed |
| DU6 | `durations.py:34` | `MAX_SUBJECTS = 201` | killed |
| DU7 | `durations.py:148` | eviction loop at 250 | **survived** (masked by the load cap) |
| DU8 | `durations.py:103` | load does not cap subjects | **survived** (masked by record's eviction) |
| DU9 | `durations.py:79` | no size check | killed |
| DU10 | `durations.py:35` | size cap 512 KiB | killed (300 KiB fixture) |
| DU11 | `durations.py:82` | `ValueError` not caught | killed |
| DU12 | `durations.py:84` | version not checked | killed |
| DU13 | `durations.py:70` | `0 <= value` | killed |
| DU14 | `durations.py:95` | kind whitelist not applied on load | killed |
| DU15 | `durations.py:132` | temp file not unlinked on error | killed |
| LF1 | `progress.py:286` | `left` may go negative | killed |
| LF2 | `progress.py:285` | overrun `>=` median | **survived** (boundary) |
| LF3 | `progress.py:275` | waiting unit without history counts 0 | killed |
| LF4 | `progress.py:281` | running unit without history counts 0 | **survived** |
| LF5 | `progress.py:295` | `done_around` ignores `left` | **survived** |
| LF6 | `progress.py:296` | "Estimating…" wins over overrun | **survived** |
| ST1 | `progress.py:262` | stale `>` 60 | killed |
| ST2 | `progress.py:28` | `STALE_AFTER = 61` | killed |
| ST3 | `progress.py:227` | output does not reset last activity | killed |
| FL1 | `progress.py:64` | `fmt_left` `>= 60` | killed |
| FL2 | `progress.py:65` | `round` instead of `ceil` | killed |
| FL3 | `progress.py:63` | negative not clamped | killed |
| PC1 | `progress.py:334` | cap 100 instead of 99 | killed |
| PC2 | `progress.py:330` | no 100 % on finish | killed |
| PC3 | `progress.py:334` | `ceil` instead of floor | killed |
| PC4 | `progress.py:420` | stopped repo's units not skipped | killed |
| PC5 | `progress.py:877` | stage fraction `/3` | killed |
| LS1 | `progress.py:441` | Land stage: failed outranks running | **survived** |
| TH1 | `ui/progress_window.py:47` | `RENDER_MS = 10` | killed |
| TH2 | `progress_window.py:538` | drop `not isActive()`: throttle becomes debounce | **survived** |
| TH3 | `progress_window.py:538` | render while hidden | killed |
| TH4 | `progress_window.py:550` | tick never starts | **survived** |
| TH5 | `progress_window.py:543` | tick does not render | **survived** |
| RW1 | `progress_window.py:575` | not drawn when shown again | killed |
| REC1 | `progress_window.py:649` | record failed/skipped Land steps too | **survived** |
| ESC1 | `progress_window.py:948` | `reject()` does not cancel | killed (`test_escape_during_a_rebuild…`) |
| ESC2 | `ui/rebuild.py:115` | `_start_next` ignores `_cancelled` | **survived** (near-equivalent: a killed build exits non-zero) |
| ESC3 | `rebuild.py:103` | `cancel()` does not kill | **survived** (tests 63 s instead of 3 s) |
| ESC4 | `rebuild.py:96` | `cancel()` does not set `_cancelled` | **survived** (run reads "failed", not "Cancelled") |
| REC2 | `rebuild.py:152` | no samples recorded after exit 0 | killed |
| LA1 | `ui/lander.py:124` | `step` signal not emitted | killed |

Restore check: `diff -rq` of the scratch copy against the worktree's `lab_hub/ ui/ tests/` empty;
worktree `shasum lab_hub/*.py ui/*.py tests/*.py` identical before and after.

## 4. Suite

| Run | Command | Result |
|---|---|---|
| 1 | `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -o addopts="" -q -p no:cacheprovider` | **841 passed, 1 skipped, 10 warnings in 287.38 s** |
| 2 | `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -p no:cacheprovider` (pytest.ini mode: `-q --strict-markers`, its `filterwarnings`) | **841 passed, 1 skipped, 10 warnings in 297.17 s** |
| extra | `tests/test_progress_window.py tests/test_progress.py tests/test_durations.py tests/test_apps_tab.py`, 3 times, with suite 2 running beside it | 152 passed ×3 (11.3 s, 8.9 s, 8.7 s); then `tests/test_progress_window.py` alone 10 passed ×5 |

Skip: `test_converter_drift.py:85` (Imprint not checked out beside this worktree; environmental,
pre-existing). Warnings: 10 `DeprecationWarning`s from `tests/test_convert_drop.py:75`
(`QDragEnterEvent` constructor), pre-existing, not this change.

Modes: app-context `## Commands` is unfilled, so it lists no mode; `pytest.ini` defines one (with
`--strict-markers`); the spec says offscreen. Both were run. Not available: `pytest-timeout`,
`pytest-randomly`, `pytest-cov` are not installed in `.venv` (only `pytest 9.1.1`), and the repo
has no CI workflow, so the playbook's random-order and per-test-timeout runs were not possible.

## 5. Coverage of changed code

No coverage tool is installed and none was installed. Measured with a stdlib `sys.settrace`
line-and-arc tracer (scratch, not in the repo) over the six test files that touch the change (213
tests). Branch figures are approximate: a decision line counts as one-way if only one successor
line was seen.

| File | Lines hit | Uncovered changed lines (meaning) |
|---|---|---|
| `lab_hub/durations.py` | 97/99 | 133-134 (unlink of the temp file itself failing) |
| `lab_hub/land.py` | 208/216 | none in the change (75-76, 133, 142, 149, 175, 231-232 pre-existing) |
| `lab_hub/progress.py` | 674/683 | 348-350 (>5 finished steps), 367-368 ("and N more"), 448 (`partial` stage), 473 ("Not reached"), 620 (`missing` category), 724-725, 751 (unknown key) |
| `ui/progress_window.py` | 741/762 | 108-109 (`Dots.advance`, never called anywhere: dead code), 163-171 (status icons `needs`/`terminal`/`unknown`/`nothing` painting), 668-669 (window-computed "Landed N of M"), model-None guards |
| `ui/rebuild.py` | 120/126 | 169-170 (a version read that raises must not end the run: untested), 99, 138, 174 (re-entry guards) |
| `ui/lander.py` | 92/97 | none in the change |

## 6. Models

The change calls no model. No new test needs the network or a model server. The app's only model
caller (Narrator) is untouched, so no live eval applies to this change; none was run or needed.

## 7. Findings (ranked)

| # | Sev | Where | Finding |
|---|---|---|---|
| 1 | P1 | `tests/test_apps_tab.py:1062`, `:1084` | The regression tests for the P1 Escape defect do not assert the kill. With `cancel()` not killing (ESC3), both pass; the build runs to the end unwatched behind a hidden window, which is the defect's main harm. Add a bound (for example `exec()` returns within 5 s of Escape, or the process exit status is `CrashExit`). |
| 2 | P1 | spec §2.6, §9 task 8 | Success measure not fully demonstrated: no screenshot of either window on the real lab, no real `build_app.sh` run, nothing on a real display. Owned by task 8; blocks "done", not this Verify's test fixes. |
| 3 | P2 | `tests/test_progress_window.py:54-66` | The throttle test passes a debounce (TH2): with lines arriving under 100 ms apart, `changed()` would restart the timer forever and the window would never render, the exact frozen look §2.3 and §6 guard against. Assert a minimum render count during a 1 s flood (for example `>= 5`). |
| 4 | P2 | `ui/progress_window.py:541-553` | No test lets the 500 ms tick fire: TH4 (tick never starts) and TH5 (tick never renders) survive; dots, spinner, elapsed and "Last activity Ns ago" moving without events (§2.3) are unverified. Pump ~1.2 s with no events and assert `renders >= 2` and the dots' phase changed. |
| 5 | P2 | `ui/progress_window.py:649` | REC1 survived: nothing checks that a failed or skipped Land step is not written to `durations.json` (§8.4). `test_land_all_with_a_failure_says_so_in_the_window_not_a_box` could assert `"merge" not in durations.load().get("repo:repo", {})`. |
| 6 | P2 | `lab_hub/progress.py:280-283` | LF4 survived: a running step with no history and no waiting steps would show `~0 s left` instead of "Estimating…" (§2.4) and the suite would not notice. |
| 7 | P2 | `lab_hub/progress.py:295` | LF5 survived: `done_around` is never tested with an estimate that changes the minute. |
| 8 | P2 | `ui/progress_window.py:925-937` | Check builds end lines and the step header (Check/Review/Update/Done) are asserted nowhere (§2.2, §2.5); ESC4 (a cancel reported as a failure) survives. |
| 9 | P2 | `ui/apps_tab.py:1023-1048` | Confirms review P2-2 (`docs/audit/progress-windows-review.md`) by a run. A later single-tile Land with nothing to do opens no window but still feeds the previous, finished `land_window`: verified in a scratch test, its outcome changed from "repo: Landed" to "repo: Nothing to land" and the row from "Landed · 0:00" to "Nothing to land". The "Show progress" button also shows that old window during the no-op run. |
| 10 | P3 | `tests/test_apps_tab.py:1157` | Same as review P3-4. `test_update_now_moves_the_window_to_its_update_step_and_copy_closes_it` checks neither the Update step nor Copy closing. |
| 11 | P3 | `lab_hub/progress.py:441-448`, `:348-350`, `:367-368`, `:472-473` | LS1 survived (failed vs running in one stage); `partial` stage, ">5 earlier steps", "and N more", "Not reached" never run. |
| 12 | P3 | `lab_hub/durations.py:99`, `:103`, `:148` | DU4 (load keeps more than 5 samples from a hand-edited file), DU7/DU8 (the two subject caps mask each other; each alone is untested). LF2 (overrun at exactly the median), LF6 (overrun vs "Estimating…" precedence) and ESC2 (near-equivalent) also survived. |
| 13 | P3 | `ui/rebuild.py:167-170` | A version read that raises is not tested to leave the run going. |
| 14 | P3 | `ui/progress_window.py:107-109` | `Dots.advance()` is never called (the header sets `dots.phase` directly): dead code. |
| 15 | P3 | `.venv`, repo | No `pytest-timeout`, `pytest-randomly`, coverage tool or CI; app-context `## Commands` and `## Test bar` are unfilled. The playbook's random order, per-test timeout and coverage gates cannot run (a `/harden` item, not this change's). |

| 16 | P1 (review's) | `ui/rebuild.py` | Review P1-1 (the Update step hangs if a command fails to start) is open and no test covers a `FailedToStart` command; the green suite says nothing about it. This Verify ran on the code as it stands; after the review fixes land, re-run the suite and the ESC/TH/REC mutants above. |

No P0. Findings 1 and 3-8 are fixed by adding or tightening tests; no production change is needed
for them. Finding 9 is a small production fix (clear or ignore `land_window` for a run that did
not open one), for the engineer.

## 8. Not done here
- Activity log (`log_activity.py . verify start|done`) not written: the orchestrator limited this
  session to this one file.
- No production or test file edited; nothing committed.

## Re-verify after fixes (2026-11-17)

Re-run of Verify (`qa-engineer`, read-only) on the fixes in spec §8.15 "Fixes after
Review/Verify/Secure". No production or test file was edited. Mutants ran only in a scratch
copy outside the repo; that copy's `lab_hub/`, `ui/`, `tests/` were `diff -rq`-identical to the
worktree after the run. `git diff` plus checksums of untracked files were taken before and after:
code and test files are unchanged. The only differences came from other sessions working at the
same time, not from this one: `README.md` and a new `CHANGELOG.md` (Document) and
`docs/audit/progress-windows-review.md` (re-review appendix). Playbook `qa-engineer.md`
`last-reviewed: 2026-10-14`, `status: current` (not stale).

### Verdict

**PASS for Verify**, with the §2.6 real-lab screenshot **pending** (task 8, the orchestrator's
job; it does not fail this pass, but the change is not "done" until it exists). Every P1 and P2
from the first Verify is fixed, and each fix has a test that kills the mutant it was written
for. The code reviewer's P1-1 is fixed, and the re-review reports nothing open above P3. The
suite is green twice: 878 passed, 1 skipped. Of the 15 earlier survivors, 14 are now killed and
1 is equivalent. On the new code, 21 of 25 mutants are killed; the 4 survivors are P3 (see below).

### 1. Earlier findings: status

| # | Sev | Status | Evidence |
|---|---|---|---|
| 1 | P1 | **fixed** | `test_apps_tab::_exec_bounded` (watchdog, `exec()` must return in time); `test_escape_during_a_rebuild_kills_it_and_the_next_command_never_starts` and `test_the_close_button_during_a_rebuild_kills_it_too` assert `took < 5`. ESC3 (cancel does not kill) is now killed. |
| 2 | P1 | **pending (not this pass)** | §2.6 screenshot of both windows on the real lab, plus a real `build_app.sh` run: task 8, orchestrator. |
| 3 | P2 | **fixed** | `test_progress_window::test_renders_are_throttled_to_ten_a_second` now asserts `during >= 3`. TH2 (debounce) killed. Measured: `during` = 9 and total renders 10-11 in each of 8 runs in parallel (lots of headroom above 3). |
| 4 | P2 | **fixed** | `test_progress_window::test_the_tick_moves_the_dots_and_the_clocks_with_no_events`. TH4 and TH5 killed. |
| 5 | P2 | **fixed** | `test_progress_window::test_only_a_finished_land_step_is_recorded`. REC1 killed. |
| 6 | P2 | **fixed** | `test_progress::test_a_running_step_with_no_history_says_estimating`. LF4 killed. |
| 7 | P2 | **fixed** | `test_progress::test_done_around_adds_the_time_left_to_the_wall_clock`. LF5 killed. |
| 8 | P2 | **fixed** | `test_progress_window::test_the_check_builds_step_header_and_end_lines`; end lines added to `test_apps_tab::test_the_rebuild_dialog_runs_the_commands_in_order` and `::test_a_failed_rebuild_stops_the_run`. ESC4 killed (by the Cancel test). |
| 9 | P2 | **fixed** | `test_land_ui::test_a_later_land_that_opens_no_window_leaves_the_finished_one_alone`. WO1 (window fed regardless of ownership) killed. |
| 10 | P3 | fixed | Renamed to `test_apps_tab::test_update_now_hands_its_open_window_to_the_rebuild`, with assertions added. |
| 11 | P3 | mostly fixed | LS1 killed (`test_a_stage_with_a_failed_step_and_a_running_one_is_running`). `partial`, ">5 earlier" and "and N more" are covered by `test_a_long_step_list_folds_earlier_steps_and_the_rest`. Still open: "Not reached" (`lab_hub/progress.py:488`) is asserted by no test (grep finds 0 hits in `tests/`). |
| 12 | P3 | fixed | DU4, DU7, DU8, LF2 and LF6 killed by the tests named in §8.15. ESC2 still survives, but is now **equivalent**: `_start_next` returns on `_ended` first, and every cancel path reaches `_all_done()` (`ui/rebuild.py:127-129`, `_finished`). |
| 13 | P3 | fixed | `test_apps_tab::test_a_version_read_that_raises_does_not_end_the_run`. |
| 14 | P3 | fixed | `Dots.advance` removed (`grep "def advance" ui/progress_window.py`: none). |
| 15 | P3 | open (not this change) | Still no `pytest-timeout`, `pytest-randomly`, coverage tool or CI. A `/harden` item. |
| 16 | P1 (review's) | **fixed** | `test_apps_tab::test_a_command_that_cannot_start_ends_the_run_as_failed`, `::test_escape_after_a_command_could_not_start_returns`, `::test_escape_before_the_first_command_starts_runs_nothing`. FS1-FS4 and CK2 killed. |

### 2. Mutation check

Method: same as §3. One exact-string mutant at a time, applied to the scratch copy and checked
to match exactly once. For each mutant, `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -o addopts= -q -x
-p no:cacheprovider` ran `tests/test_durations.py tests/test_progress.py
tests/test_progress_window.py tests/test_apps_tab.py tests/test_land_ui.py tests/test_land.py`
(250 tests; unmutated copy: 250 passed), with a 240 s hang limit, and the file was restored.
**41 planted (40 single and 1 combined), 36 killed, 5 survived.**

| ID | Where | Mutation | Result (first failing test) |
|---|---|---|---|
| DU4 | `durations.py` load | keep all samples | killed `test_load_keeps_only_the_last_five_samples_of_a_hand_edited_file` |
| DU7 | `durations.py` record | evict at 250 | killed `test_record_writes_at_most_two_hundred_subjects` |
| DU8 | `durations.py` load | no subject cap | killed `test_load_of_a_hand_edited_file_keeps_the_newest_two_hundred` |
| LF2 | `progress.py` `left` | overrun `>=` | killed `test_at_exactly_the_median_it_is_not_yet_taking_longer` |
| LF4 | `progress.py` `left` | running unit with no history counts as known | killed `test_a_running_step_with_no_history_says_estimating` |
| LF5 | `progress.py` `_times` | `done_around` ignores `left` | killed `test_done_around_adds_the_time_left_to_the_wall_clock` |
| LF6 | `progress.py` `_times` | Estimating checked before overrun | killed `test_overrun_is_said_even_when_a_later_step_has_no_history` |
| LS1 | `progress.py` `_stages` | failed outranks running | killed `test_a_stage_with_a_failed_step_and_a_running_one_is_running` |
| TH2 | `progress_window.py` `changed` | throttle becomes debounce | killed `test_renders_are_throttled_to_ten_a_second` |
| TH4 | `progress_window.py` `_sync_tick` | tick never starts | killed `test_the_tick_moves_the_dots_and_the_clocks_with_no_events` |
| TH5 | `progress_window.py` `_on_tick` | tick does not render | killed (same test) |
| REC1 | `progress_window.py` `on_step` | record failed/skipped Land steps | killed `test_only_a_finished_land_step_is_recorded` |
| ESC2 | `rebuild.py` `_start_next` | ignore `_cancelled` | **survived** (equivalent, see #12) |
| ESC3 | `rebuild.py` `cancel` | no `_stop_group()` | killed `test_escape_during_a_rebuild_kills_it_and_the_next_command_never_starts` |
| ESC4 | `rebuild.py` `cancel` | `_cancelled` not set | killed `test_cancel_during_a_rebuild_stops_it_and_leaves_the_window_at_done` |
| FS1 | `rebuild.py` `_error` | handler does nothing | killed `test_a_command_that_cannot_start_ends_the_run_as_failed` |
| FS2 | `rebuild.py` `_error` | `_failed` not set | killed (same) |
| FS3 | `rebuild.py` `_error` | no `_all_done()` | killed (same) |
| FS4 | `rebuild.py` `_error` | row not told it failed | killed (same) |
| CK1 | `progress_window.py` `_cancel_or_close` | Cancel closes the window | killed `test_cancel_during_a_rebuild_stops_it_and_leaves_the_window_at_done` |
| CK2 | `rebuild.py` `cancel` | nothing running: run not ended | killed `test_escape_before_the_first_command_starts_runs_nothing` |
| CK3 | `progress_window.py` `done` | no cancel before closing | killed `test_escape_during_a_rebuild_kills_it_and_the_next_command_never_starts` |
| PG1 | `rebuild.py` `__init__` | no `CreateNewSession` | killed `test_cancel_stops_what_the_build_started_not_only_the_shell` |
| PG2 | `rebuild.py` `_stop_group` | no SIGTERM to the group | killed (same) |
| PG3 | `rebuild.py:148` | no SIGKILL after the grace | **survived** |
| PG4 | `rebuild.py` `_signal_group` | `os.kill` instead of `os.killpg` | killed (same) |
| HF1 | `durations.py` `_read` | no `O_NONBLOCK` | killed `test_a_fifo_at_the_path_is_not_read_and_does_not_hang` |
| HF2 | `durations.py` `_read` | no `S_ISREG` check | killed (same) |
| HF3 | `durations.py` `_read` | no `O_NOFOLLOW` | killed `test_a_symlink_or_a_directory_at_the_path_is_not_read` |
| HF4 | `durations.py` `load` | catch only `OSError` | killed `test_a_broken_file_is_no_history_not_a_crash[]` |
| HF5 | `durations.py` `_sample` | `OverflowError` not caught | killed `test_a_huge_integer_sample_is_dropped_not_raised` |
| HF6 | `durations.py` `_read` | no size check after reading (file grew between `fstat` and `read`) | **survived** |
| WO1 | `apps_tab.py` `_run_window` | ignore the ownership flag | killed `test_a_later_land_that_opens_no_window_leaves_the_finished_one_alone` |
| WO2 | `apps_tab.py` `_land_finished` | flag not cleared at finish | **survived** (masked by WO3's line) |
| WO3 | `apps_tab.py` `_land_planned` | flag not cleared at plan | **survived** (masked by WO2's line) |
| WO2+3 | both lines | both removed | killed `test_a_later_land_that_opens_no_window_leaves_the_finished_one_alone` |
| WO4 | `apps_tab.py` `_open_land_window` | flag never set | killed `test_the_land_window_opens_after_the_confirmation_and_follows_a_two_repo_land` |
| TH1 | `progress_window.py` | `RENDER_MS = 10` | killed `test_renders_are_throttled_to_ten_a_second` |
| TH6 | `progress_window.py` | `RENDER_MS = 1000` | killed (same: the `during >= 3` bound) |
| TH3 | `progress_window.py` `changed` | render while hidden | killed `test_a_hidden_window_updates_its_model_and_draws_nothing` |
| TH8 | `progress_window.py` `_sync_tick` | tick at Review | killed `test_nothing_ticks_at_review` |

What the survivors mean:
- PG3 (P3): the process-group test's child (`sleep`) dies on SIGTERM, so the SIGKILL fallback
  for a tool that ignores or traps SIGTERM is never run by any test. A fix would be one test whose
  child is `bash -c 'trap "" TERM; sleep 47'`, asserting it is gone within about 3 s.
- HF6 (P3): the guard against a file growing between `fstat` and `read` is a race that is hard
  to set up in a test. It is defence in depth (`fstat` already checks the size), so the risk is
  low.
- WO2 and WO3 (P3): two resets of the same flag cover for each other; removing both is caught.
  The behaviour is pinned; neither line on its own is.
- ESC2: equivalent (see #12).

### 3. Suite and flakiness

| Run | Command | Result |
|---|---|---|
| 1 | `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -o addopts="" -q -p no:cacheprovider` (mutation harness running at the same time) | **878 passed, 1 skipped, 10 warnings in 318.99 s**, exit 0 |
| 2 | `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -p no:cacheprovider` (pytest.ini mode: `--strict-markers`, `filterwarnings` error on `lab_hub.*`/`ui.*` deprecations; harness running at the same time) | **878 passed, 1 skipped, 10 warnings in 289.44 s**, exit 0 |
| flake | `tests/test_progress_window.py` 5 times in a row | 15 passed ×5 (4.76-4.97 s) |
| flake | `-k throttled` 3 in parallel; then 8 in parallel with a print of `during` (scratch copy) | all passed; `during` = 9 in all 8 runs, total renders 10 (7 runs) and 11 (1 run) |

Skip and warnings are as in the first Verify (`test_converter_drift.py:85`, environmental; 10
`QDragEnterEvent` deprecations in `tests/test_convert_drop.py:75`, which existed before this change).

On flakiness: the lower bound (`during >= 3`) has plenty of margin. The upper bound
(`renders <= 11`) was reached exactly in 1 of 8 runs under load. Arithmetic keeps renders at
or below 11 when no single event-loop turn stalls for more than about 100 ms; a longer stall in
the flood's last turn could make 12. Low risk, P3: watch it if CI is ever added.

### 4. Success measures §2 against the tests (updated)

| § | Covered by | Status |
|---|---|---|
| 2.1 Land window | first Verify's list, plus `test_land_ui::test_a_later_land_that_opens_no_window_leaves_the_finished_one_alone` and `test_progress::test_a_long_step_list_folds_earlier_steps_and_the_rest`, `::test_done_around_adds_the_time_left_to_the_wall_clock` | met by tests (P3: "Not reached" row status not asserted) |
| 2.2 Check builds window | first Verify's list, plus `test_progress_window::test_the_check_builds_step_header_and_end_lines`, `test_apps_tab::test_update_now_hands_its_open_window_to_the_rebuild`, `::test_cancel_during_a_rebuild_stops_it_and_leaves_the_window_at_done`, `::test_a_command_that_cannot_start_ends_the_run_as_failed`, `::test_the_open_in_terminal_tooltip_is_plain_text` | met by tests |
| 2.3 Alive signal | `test_progress::test_activity_text_at_59_and_60_seconds`, `test_progress_window::test_the_activity_line_turns_amber_after_a_minute`, `::test_the_tick_moves_the_dots_and_the_clocks_with_no_events`, `::test_renders_are_throttled_to_ten_a_second`, `::test_nothing_ticks_at_review` | met by tests |
| 2.4 Estimate | `test_durations.py`, plus `test_progress::test_a_running_step_with_no_history_says_estimating`, `::test_at_exactly_the_median_it_is_not_yet_taking_longer`, `::test_overrun_is_said_even_when_a_later_step_has_no_history`, `test_progress_window::test_only_a_finished_land_step_is_recorded`, `test_apps_tab::test_a_failed_build_records_no_durations` | met by tests |
| 2.5 Ends clearly | `test_land_ui::test_land_all_with_a_failure_says_so_in_the_window_not_a_box`, `::test_a_single_land_ends_with_its_tile_line_in_the_window`, `test_progress_window::test_the_check_builds_step_header_and_end_lines`, end lines in `test_apps_tab::test_the_rebuild_dialog_runs_the_commands_in_order` / `::test_a_failed_rebuild_stops_the_run` / the Cancel test | met by tests |
| 2.6 Tests and screenshot | fake clocks and fixture events throughout; real-lab screenshot of both windows | tests met; **screenshot pending** (orchestrator, task 8) |

### 5. Coverage, models, test quality

- Coverage was not measured again (still no coverage tool, and none was installed). Every new or
  fixed branch listed in §8.15 had a mutant planted on it above; the only fixed line without a
  test is "Not reached".
- Models: unchanged from §6. No new test needs the network or a model. The `https://x.example`
  in `test_progress.py:447` is a fixture string for OSC stripping, not a request.
- Test quality: the new tests assert exact strings and states. Real subprocesses are bounded by
  `_exec_bounded` watchdogs, so a regression fails the test instead of hanging the suite. Fake
  clocks drive the model tests. The diff of `tests/` removes only the 4 `assert` lines moved to
  new seams in the first Build (`_button` -> `cancel_button`, `succeeded` -> `rebuild.succeeded`),
  which the first Verify already checked.

### 6. Remaining findings (ranked)

| # | Sev | Finding |
|---|---|---|
| R1 | P1 (pending, not this pass) | §2.6 real-lab screenshot of both windows (and a real `build_app.sh` run): task 8, orchestrator. Blocks "done", not Verify. |
| R2 | P3 | PG3: SIGKILL fallback after the grace period is untested (needs a child that traps TERM). |
| R3 | P3 | "Not reached" row status (`lab_hub/progress.py:488`) asserted by no test. |
| R4 | P3 | WO2 and WO3 each survive alone (they mask each other); the pair is killed. |
| R5 | P3 | HF6: the size check after reading is a race guard; untested. |
| R6 | P3 | Throttle test upper bound `<= 11` was reached exactly once in 8 loaded runs; small headroom. |
| R7 | P3 | Tooling: no `pytest-timeout`, `pytest-randomly`, coverage tool or CI (a `/harden` item, existing before this change). |

No P0. No open P1 from Verify, Review or Secure. Activity log not written (this session was
limited to this file); nothing committed.
