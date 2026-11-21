# Verify: land-blocker-actions

QA engineer (`qa-engineer`), read-only. Diff `d93c96d..2b49d6b` on `claude/land-blocker-actions-f4b91c`.
Playbook `docs/playbooks/qa-engineer.md`: `last-reviewed: 2026-10-14`, `status: current` (38 days, not stale).
`app-context.md` `## Commands` and `## Test bar` are still template placeholders, so the only test mode
known is the one the orchestrator gave (offscreen Qt, one run). Nothing in the worktree was edited apart
from this report. Mutants were planted only in a copy (`rsync`, no `.git`) in the session scratchpad.

## Verdict: FAIL (mutation gaps), no product defect found
- The §2 success measures are met by tests (one owner step still open, see §2.2).
- The full suite is green: `1418 passed, 1 skipped`.
- 73 mutants were planted: 48 killed, 25 survived. 4 of the survivors are equivalent or cannot be reached,
  which leaves **21 real survivors**. Most are in the same-window re-run (owner decision P2-4), the Close it…
  confirm and the Ask Claude… wiring from the Land window. By the playbook, a survivor is a missing test.
- I found no wrong behaviour in the code. Every gap below is a missing test, not a bug.

## 1. Success measures (spec §2) and behaviour (§3)
| Measure | Test(s) | Mutation evidence | Met? |
|---|---|---|---|
| §2.1 no stop row ends in "by hand" / "in Terminal" / "yourself" | `test_no_string_in_lands_stop_code_says_by_hand_or_in_terminal` (AST scan of `land.py`, `land_resolve.py`), plus the updated text tests in `test_land_folder_link_guard.py`, `test_land_confirm.py`, `test_land.py`, `test_land_fast.py` | M71 (a link stop says "land it by hand" again): killed | yes |
| §2.1 every `STOP_ACTIONS` entry and `blocker_kind` value has a clearing action | `test_every_stop_action_has_a_clearing_action`, `test_every_blocker_kind_has_a_clearing_action` (it reads `blocker_kind`'s return literals from its AST, so a new kind fails here) | M68 (new kind, no mapping), M69 (entry mapped to "manual"), M70 (`BLOCKER_ACTIONS` without `link`), M72 ("…in Terminal" entry): all killed | yes |
| §2.2 the prompt for a `.claude/settings.json` conflict names branch, file and goal | `test_the_protected_stop_on_a_real_conflict_names_branch_file_and_goal` (real git conflict, `handoff.prompt`), `test_names_in_a_goal_cannot_break_out_of_their_quotes` | M57, M59, M60, M62, M29, M52, M53: killed. **M73 survives**: Ask Claude… from the Land window drops the goals and no test notices (P2-4) | at function level only; the owner-watched syndustryx run is **not verified** (owner's step) |
| §2.3 Claude Code never edits `.claude/` in an unattended Land | `tests/test_land_fast.py::test_a_protected_conflict_costs_no_test_and_no_claude`, `::test_which_files_are_protected_and_which_are_foundrys`, `::test_a_protected_conflict_is_a_stop_per_branch_and_is_never_archived` | M63 (case-sensitive match), M64 (pre-check `blocked = []`), M66 (`protected()` always False): killed. M65 (second guard after the real merge, `claude_resolve.py:1220`): survives (P3-6) | yes |
| §3.1 Try again | `test_a_network_result_offers_try_again_and_carries_its_stop`, `test_try_again_checks_origin_and_changes_nothing_while_it_is_down`, `test_try_again_on_the_land_window_lands_once_origin_answers`, `test_the_network_stop_says_what_failed`, `test_a_refused_origin_is_not_a_network_stop` | M15, M16, M26, M27, M44: killed | yes |
| §3.2 Close it… | the ten `test_close_it_*` / `test_a_process_that_will_not_exit_*` / `test_one_*` tests, `test_the_worker_closes_then_says_what_is_left` (real children, real `lsof`) | M01, M03, M04, M06, M07, M09–M14, M20, M50: killed. M05, M08 survive (P3-1, P3-2) | yes |
| §3.3 texts | `test_the_protected_and_red_main_texts_are_the_specs`, `test_clearing_names_the_button`, `test_the_red_main_stop_*` | M17, M19, M28: killed | yes |
| §3.4 prompt lines | as §2.2 | M56: killed. M54, M55, M58 survive (P3-5) | yes |

Review and security fixes that have tests: P1-2 / sec P2-1 (nested repo:
`test_close_it_never_signals_a_process_in_a_separate_repo_inside_the_checkout`; M01, M06, M20 killed),
P2-1 (`test_a_long_or_press_reason_keeps_its_action`; M21–M23 killed), P2-3
(`test_restating_after_close_it_keeps_the_repos_other_stops`; M30–M32 killed), P3-1
(`test_a_cancelled_land_after_a_clear_leaves_try_again_on_the_row`; M43 killed), P3-2
(`test_an_empty_lsof_reading_after_the_signal_is_not_all_closed`; M09 killed), P3-4
(`test_one_started_after_the_confirm_is_running_not_ignored`), P3-5 (refused origin), P3-6 (label),
owner "Option 1" (`test_one_that_ignores_close_it_is_named_and_the_owner_closes_its_window`; M12, M13 killed).

These fixes have **no test**: P1-2's "the confirm shows each process's own folder" (M46), P2-4's row reset
(M36–M40, M45), sec P3-2's parent-pid exclusion (M05) and P3-3's "gone already is not logged as closed" (M08).

## 2. Full suite
```
cd <worktree> && QT_QPA_PLATFORM=offscreen /Users/as/Documents/lab/active/lab_hub/.venv/bin/python -m pytest -p no:cacheprovider
1418 passed, 1 skipped, 10 warnings in 967.07s (0:16:07)
EXIT=0
```
- **The run was not alone.** `ps aux | grep -c "[p]ytest"` counted 8 pytest processes from other sessions
  when it started. That explains 16 min against the usual ~12. Later, another session's suite (worktree
  `intelligent-wright-6029ac`, from 04:31) overlapped my mutation runs. Under that load the suite still
  passed.
- `tests/test_land_fast.py::test_a_landed_merge_is_not_tested_again_as_the_next_base` **did not recur**. It
  passed in the full run, in the `test_land_fast` group baseline, and in every mutant run that reached it:
  M61, M63, M64, M65, M66 and M67. I did not find its root cause. The guard that fires is
  `claude_resolve._git_state` (`claude_resolve.py:913`), which hashes `config`, `hooks` and `info` by mtime
  and content, so any process touching the fixture repo's git dir trips it. That fits interference from a
  concurrent loop better than a defect in this change.
- The 10 warnings are a pre-existing deprecation in `tests/test_convert_drop.py:75`.
- The mutation subsets passed on the unmutated copy before any mutant ran:
  - `test_land_blocker_actions.py`: 51 passed, 0 skipped (`-rs`), so the lsof tests really ran.
  - The groups R (163 s), U (78 s), H (12 s) and C (168 s) all exited with rc 0.

## 3. Mutation check (73 planted: 48 killed, 25 survived)
How it was run: each mutant replaced exactly one source snippet (checked to occur once) in the scratch copy.
The first pass ran `tests/test_land_blocker_actions.py -x`. Survivors then ran against a wider group:
- R: `test_land_resolve`, `test_land`, `test_land_confirm`, `test_land_ui`, `test_land_live_session_guard`, `test_land_update_gaps`
- U: `test_land_ui`, `test_progress`, `test_progress_window`, `test_apps_tab`, `test_handoff_ui`, `test_repo_tidy_ui`
- H: `test_handoff`, `test_handoff_ui`
- C: `test_land_fast`, the four `test_claude_resolve*` files, `test_land`, `test_land_folder_link_guard`

The file was restored after each mutant. The copy was checked with `cmp` against the worktree afterwards:
identical. Every kill was by a test related to that mutant; none were unrelated failures.

Killed (48):
- `in_nested_repo`: M01, M03
- `never` set and filters in `close_processes`: M04, M06, M07, M09, M10, M11
- `Closed`: M12, M13, M14
- `refused` / `clearing` / `for_land`: M15, M16, M17, M19
- `_worktree_stop_full`: M20
- `plain_reason` tail keeping: M21, M22, M23
- `land`: M25–M29
- `LandWindow.restate` merge: M30, M31, M32
- Row view: M41
- `AppsTab._rerun_planned` cancel and the same-window path: M43, M44
- `Lander._cleared`: M50
- `handoff._name` and `blocker_goals`: M52, M53, M56, M57, M59, M60
- `claude_resolve`: M61, M62, M63, M64, M66, M67
- §2.1 mapping: M68–M72

Survived (25), and why each matters:
| # | Mutant (file) | Note |
|---|---|---|
| M02 | `in_nested_repo` "not under root" returns False (`land_resolve.py:973`) | not reachable: every caller filters with `in_own_tree` first; defence in depth |
| M05 | `never` without `os.getppid()` (`land_resolve.py:1047`) | real gap (P3-1) |
| M08 | an already-gone pid counted as sent and logged "owner closed" (`:1059`) | real gap (P3-2) |
| M18 | `clearing` matches the action anywhere, not as the ending (`:829`) | real gap (P3-3; security P3-3 spoofing) |
| M24 | `plain_reason` `at > 0` changed to `at >= -1` (`land.py:97`, after `:96`) | equivalent: `len - (-1) <= 100` cannot hold for a reason over 180 characters |
| M33 | `LandWindow.rerun` keeps the old result (`progress_window.py`) | close to equivalent: `on_repo_done` overwrites it, and `lander.busy` blocks a click meanwhile |
| M34 | `finish` after a re-run counts only the re-run result | real gap (P2-1) |
| M35 | `finish` after a re-run records a second `durations` run | real gap (P2-1) |
| M36–M40 | `LandModel.rerun`: units, state, run end, reason/action not reset; first row instead of the named one (`progress.py:529-549`) | real gap (P2-1) |
| M45 | `_rerun_planned` never calls `window.rerun` (`apps_tab.py`) | real gap (P2-1): the whole same-window reset can go and every test passes |
| M42 | `_rerun_planned` accepts only `True`, not the plan list | real gap (P2-2) |
| M46 | `confirm_close` shows the stop's folder, not the process's own cwd | real gap (P2-3) |
| M47 | `confirm_close` lists Lab Hub's own pid | real gap (P2-3) |
| M48 | `_land_held` keeps `_rerun_name` | real gap (P3-4) |
| M49 | `clear_land_row` without the `lander.busy` guard | real gap (P3-4) |
| M51 | `Lander.clear` accepts any action | not reachable: the UI only emits "retry" and "close" |
| M54, M55, M58 | `_name` 120-character cap; `blocker_goals` 10-file cap; no-files fallback text | real gaps (P3-5) |
| M65 | the second `.claude/` guard after the real merge (`claude_resolve.py:1220`) | real gap (P3-6); the first guard (M64) is killed |
| M73 | `AppsTab` Ask Claude… does not pass `window.handoff_goals` (`apps_tab.py:985`) | real gap (P2-4) |

## 4. Coverage of the changed lines
There is no coverage tool in the venv (no `coverage`, `pytest-cov`, `mutmut`, `pytest-randomly` or
`pytest-timeout`), and I installed nothing. So I measured **line** coverage of the changed lines with a
`sys.settrace` plugin, over the blocker, land, land_fast, confirm, preflight, link-guard, handoff,
land_ui, progress_window and land_resolve tests (rc 0):
**472/533 changed executable lines run (88.6%).**

Not run:
- `ui/apps_tab.py`: 66/95. **`confirm_close` (`:1326-1350`) never runs, because every test replaces it.**
  Also not run: the early returns of `clear_land_row` (`:1272-1287`), including the "Not now: Land is still
  running" box, and the `except` in `_rerun_planned`.
- `lab_hub/land_resolve.py`: 146/165. Not run:
  - the `OSError` branches of `in_nested_repo`, `_alive`, `close_processes` and `_same_dir`
  - `ProcessLookupError` at `:1059` (M08)
  - "it has unresolved conflicts" (`:877`): the fixture's conflict hits "merge is in progress" first
  - the "lsof failed" text (`:879`)
- `ui/lander.py` 35/38 (its `except` path), `lab_hub/claude_resolve.py` 13/16 (the fallback paths of
  `protected_files` / `protected_names`), `lab_hub/land.py` 59/61, `lab_hub/progress.py` 25/27,
  `ui/progress_window.py` 92/95, `lab_hub/handoff.py` 35/35.

Branch coverage was not measured. The uncovered lines above are the untaken branches I found.

## 5. Test quality
Good:
- Git is real everywhere: fixture repos, real conflicts, real worktrees, a real nested `git init`.
- Close it… uses real child processes (`spawn`), the real `lsof` and real SIGTERM, and asserts the exit
  signal (`proc.wait(5) == -SIGTERM`).
- Try again uses the real Land worker against an origin path that does not exist.
- The UI tests drive the real `AppsTab`, `Lander` thread and `LandWindow`.
- §2.1 is checked against the source itself (AST), not against a copied list.

Weaker:
- Every re-run and confirm test stubs `confirm_land` to return `True` or `[]`, but the real dialog returns
  a list of plans (M42).
- `confirm_close` is always replaced, so the safety confirm itself is untested (M46, M47).
- The P2-4 tests assert only the end state ("Landed", same window, two rows), so the reset in between can
  be deleted unnoticed (M45).
- `_spy_kill` passes signals on to the real `os.kill`. The "never signal" tests list pid 2, pid 999999 and
  the pytest pid itself, so a regression would send a real SIGTERM to those pids (pytest would kill itself;
  others get EPERM or ESRCH). The negative tests should use a spy that does not pass the signal on.
- One git fake: `test_a_refused_origin_is_not_a_network_stop` monkeypatches `repo_tidy.git` for
  `ls-remote` only (spec §4 says no git mocks). It is narrow and hard to avoid, since an auth error needs a
  server. Acceptable; noted.
- No live model is called. The UI tests use `no_claude` (`availability` returns None), and
  `test_land_fast` uses the `stub` Claude. This change adds no model call, so no live eval applies; none
  was run, and `plan.toml` has no `eval_budget_usd` for this spec.

Flake risk, judged low to medium:
- The Close it… tests that send SIGTERM to a test child wait the full `CLOSE_WAIT` (5 s): the child becomes
  a zombie the test process has not reaped yet, and `_alive` counts it as alive. These tests take about
  5.8 s each, and the timing asserts are loose (`< 5 s` with `wait=0.6`).
- `_listed()` relies on `lsof` seeing a child immediately after it prints "ready". If `lsof` misses it under
  load, the test errors with `StopIteration` rather than passing wrongly.
- No failure in 1 full run plus about 100 subset runs under heavy concurrent load.
- Not checked: random order and per-test timeouts (the plugins are not installed).

Found on the side, not in this diff: `tests/test_land_resolve.py::test_a_file_that_appears_after_the_preview_is_not_committed_and_land_says_not_landed`
(commit `3cd5dd7`) fails when the pytest temp path is long. With `--basetemp` in the session scratchpad, the
reason (which starts with the path) is cut at 180 characters before the word "untracked". It passes with
the default temp path.

## 6. Gaps, ranked
No P0 and no P1.

- **P2-1. Same-window re-run (owner, P2-4) is tested only by its end state.** Survivors M34–M40 and M45:
  removing `window.rerun(plan)` entirely leaves every test green. Needed: a test that, after Try again or
  Close it… in a two-repo window, asserts while the re-run is in progress that:
  - the repo's row is reset (WAITING or RUNNING, new units, no reason or button)
  - the other row is unchanged
  - the Stop button shows

  and at the end, that the window line counts both rows and `durations` has one entry for the window.
- **P2-2. `_rerun_planned` is never tested with the real dialog's answer type** (M42). `confirm_land`
  returns `dialog.chosen()`, a list, and the tests use `True`. Needed: confirm returning `[plan]` (lands)
  and `[other]` / `[]` (cancel path).
- **P2-3. The Close it… confirm (`AppsTab.confirm_close`, `apps_tab.py:1323-1350`) never runs in a test**
  (M46, M47; 0 of 25 lines). Review P1-2 asked that it show each process's own folder. Needed: an
  offscreen test that opens it with a nested-repo or worktree process and Lab Hub's own pid, and checks
  `informativeText()`:
  - it shows the process's own cwd
  - Lab Hub's pid is not listed
  - Cancel is the default button

  The test closes the box with a `QTimer`.
- **P2-4. Ask Claude… from the Land window is not tested end to end for the §3.4 goal** (M73). Needed: a
  `test_handoff_ui`-style test that, from a Land window holding a protected-conflict result, asserts the
  launched prompt contains "What Lab Hub asks for" and the backticked branch and file.
- P3-1. Lab Hub's parent pid is never signalled (security P3-2 fix) but untested (M05). A fake `listing` and
  a spy that does not pass signals on make it testable without signalling anything.
- P3-2. "Gone already is not logged as closed" (review P3-3) is untested (M08). A fake `kill` raising
  `ProcessLookupError` covers it.
- P3-3. `clearing` matching only the ending (security P3-3) is untested (M18). Add a reason that quotes
  ": press Try again" in its middle.
- P3-4. `_land_held` resetting `_rerun_name` (M48) and the "Not now" busy guard in `clear_land_row` (M49)
  are untested.
- P3-5. `handoff._name`'s 120-character cap, the 10-file cap and the "the conflicted .claude/ files"
  fallback are untested (M54, M55, M58).
- P3-6. The second `.claude/` guard after the real merge (`claude_resolve.py:1220`) is untested (M65). §2.3
  still holds through the pre-check (M64 killed).
- P3-7. `_spy_kill` passes signals to real pids in the "never signal" tests (see §5).
- P3-8. The §2.1 scan checks only for banned words. Generic step failures (raw git or gitleaks errors via
  `plain_reason`) end in no clearing sentence at all; they rely on the Ask Claude… footer. Review P2-2
  noted the narrow scan.
- P3-9. Process: `app-context.md` `## Commands` / `## Test bar` are empty (no listed test modes, no
  coverage target), and the venv has no `pytest-timeout`, `pytest-randomly` or coverage tool (playbook
  practice). That is why branch coverage, random order and timeouts are not verified here.
- P3-10. A pre-existing test is path-length fragile (see §5); not part of this change.

## Evidence files (session scratchpad, not kept)
Kept under `/private/tmp/claude-501/-Users-as-Documents-lab-active-lab-hub--claude-worktrees-blissful-newton-43a5f3/215b4ece-cd7e-40e0-8098-561eb39bc977/scratchpad/`:
- `full_suite.log`
- `mut_run1.log`, `mut_run2.log`, `mutants3.jsonl` (the mutation runs)
- `tools/mutants.py` (every mutant's exact before and after text)
- `linecov.json`

## Fixes (orchestrator, after Verify)
Added by the Build session; QA's verdict above is unchanged. Tests only, no production code changed.
- `tests/test_land_blocker_actions.py`, new:
  - `test_a_rerun_resets_only_its_own_row_and_the_window_counts_every_row` (P2-1, P2-2: checks the row mid-re-run, the other row untouched, Stop shown, "Landed 2 of 2 repos.", one `durations` run; the confirm returns the plan list)
  - `test_a_rerun_the_owner_leaves_out_of_the_confirm_does_not_land` (P2-2)
  - `test_the_close_it_confirm_shows_each_process_folder_and_never_lab_hub` (P2-3: the real `confirm_close`, `exec` replaced; own cwd shown, own pid left out, Cancel the default)
  - `test_ask_claude_from_the_land_window_carries_the_protected_goal` (P2-4)
  - `test_a_rows_button_while_land_runs_says_not_now_and_a_held_row_forgets_the_rerun` (P3-4)
  - `test_close_it_never_signals_lab_hubs_parent` (P3-1), `test_a_process_gone_before_the_signal_is_not_logged_as_closed` (P3-2), `test_clearing_reads_only_the_ending_not_an_action_quoted_inside` (P3-3), `test_goal_names_and_file_lists_are_capped_and_a_stop_without_files_still_has_a_goal` (P3-5)
  - P3-7: `_spy_kill(forward=False)` in the four "never signal" tests.
- `tests/test_land_fast.py::test_the_merge_itself_still_stops_a_protected_conflict_the_precheck_missed` (P3-6; only the pre-check's file list is replaced, the merge is real).
- Re-run of the 21 real survivors with QA's own `tools/mutants.py` and runner, in the scratch copy re-synced to the worktree, first subset (`test_land_blocker_actions.py`; `test_land_fast.py` + `test_claude_resolve.py` for M65): **21 of 21 killed** (M05, M08, M18, M34–M40, M42, M45–M49, M54, M55, M58, M65, M73).
- Touched groups: `test_land_blocker_actions`, `test_land_fast`, `test_handoff_ui`, `test_land_ui`, `test_progress_window`, `test_progress`: 244 passed, exit 0.
- P3-8, P3-9, P3-10: in `TODO.md` under "Land blocker actions".
- Not re-run: the full suite after these test-only additions (QA's full run, 1418 passed, stands for the production code, which did not change).
