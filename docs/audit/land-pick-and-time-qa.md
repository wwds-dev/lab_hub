# Verify: land-pick-and-time (QA)

QA engineer (read-only subagent), 2026-11-18. Scope: Build commit `7aacfd2` plus the uncommitted
review fixes (`git diff`), spec `docs/specs/land-pick-and-time.md` §2 items 1-11 and §8.
Playbook `docs/playbooks/qa-engineer.md`: `last-reviewed: 2026-10-14`, `status: current` (35 days, not stale).

**Verdict: PASS with gaps.** No production defect found. Every success-measure item has a test
except two sub-points (Space on the box, the "dimmed / step pills hidden" part of item 2).
62 mutants planted, 49 killed, 13 survived; of the survivors 3 are equivalent or near-equivalent,
10 point to missing tests (ranked below). One review-fix test passes for the wrong reason (G1).

## Method
- All mutations ran in two scratch copies of the working tree (rsync of the repo minus `.git`,
  `.venv`, `build`, `dist.noindex`; `PYTHONDONTWRITEBYTECODE=1`, `__pycache__` cleared), never in
  the repo. A harness applied one exact-string replacement at a time (asserting it matched exactly
  once), ran `.venv/bin/python -m pytest -q -x -p no:cacheprovider <targeted files>`, restored the
  file and asserted the bytes matched. Before the run, the five production files in the scratch
  copy were `cmp`-identical to the repo's.
- Baseline, unmutated scratch copy: `tests/test_durations.py tests/test_progress.py
  tests/test_land_confirm.py tests/test_land_ui.py tests/test_progress_window.py
  tests/test_apps_tab.py` green (2:11 wall). Flake check: `test_durations, test_progress,
  test_land_confirm, test_progress_window, test_land_ui` run three times, green each time; last
  run `231 passed in 85.98s`. Full suite: not run here (the orchestrator runs it).
- Branch coverage of changed lines: **not measured**; neither `coverage` nor `pytest-cov` is in
  `.venv` or `requirements-dev.txt`, and QA does not install packages. Mutation results below are
  the proxy.
- Model use: this spec adds no model call. The new tests use real temporary git repos, fakes for
  `lander.run`/`_open_land_window`, fixed clocks and a fixed wall; no network, no Claude Code
  call. Live eval: not applicable to this change (no model behaviour changed).

## 1. Success measure, item by item
| # | Item | Test(s) | Covered |
|---|---|---|---|
| 1 | Checkbox per card, on by default, accessible name "Land <repo>"; header click or Space toggles | `test_land_confirm::test_every_card_has_a_ticked_box_and_one_card_has_none` (box, default on, name), `::test_a_click_on_the_header_toggles_and_return_still_presses_nothing`, `::test_a_press_dragged_off_the_header_does_not_toggle` | Yes, except **Space**: no test. A scratch probe (`QTest.keyClick(check, Key_Space)`) toggled it (`after Space checked: False`), so behaviour is right, untested. |
| 2 | Unchecked card folds, dimmed, "Left out" pill in place of the step/stop pills; re-check reopens | `::test_unticking_folds_the_card_and_everything_counts_the_rest` (body hidden, "Left out" shown, name disabled, reopen), `::test_a_left_out_name_takes_the_hint_style_and_gets_it_back` | Partly: hiding the step/stop/Claude pills is untested (mutant C12 survived); the card's `out` property has no stylesheet rule anywhere in `ui/` or `lab_hub/` (grep `out=`/`[out`: none), so it dims nothing and its mutant C13 survived. The name is dimmed via object name `hint` (tested). |
| 3 | Title, sentence, Claude panel (lines, total, gone if none), Details, button follow the checked set | `::test_unticking_folds...`, `::test_the_claude_panel_covers_exactly_the_ticked_repos`, `::test_the_chosen_set_reads_as_a_dialog_built_from_it_alone`, `::test_none_ticked_disables_land_until_one_is` ("Land foundry"/"Land" for one), `test_land_ui::test_the_real_dialog_choice_is_what_runs_and_what_is_disclosed` | Yes |
| 4 | Nothing checked: "Nothing chosen", "Tick a repo to land it.", panel hidden, Land disabled, Cancel works | `::test_none_ticked_disables_land_until_one_is` | Yes for the four texts/states; "Cancel still works" in that state is not asserted (Cancel is the unchanged `reject`; low). |
| 5 | Only checked repos run; unchecked untouched, tiles reset at once; window rows only for the run | `test_land_ui::test_land_all_lands_only_the_ticked_repos`, `::test_a_partial_choice_keeps_the_nothing_to_land_rows_in_plan_order`, `::test_the_real_dialog_choice_is_what_runs_and_what_is_disclosed`, `::test_an_empty_choice_is_a_cancel`, `::test_true_from_the_confirmation_still_means_every_repo` | Yes for run set, files untouched and window rows. "At once" is not checked: the `_landing_cards` assertion runs after the Land ended, when `_land_finished` clears the dict anyway (G5). |
| 6 | Single-repo Land shows no checkbox | `test_land_confirm::test_every_card_has_a_ticked_box_and_one_card_has_none` | Yes |
| 7 | Every Land starts all checked; Return presses nothing; Escape cancels | `::test_every_card_has_a_ticked_box...` (fresh dialog all ticked), `::test_a_click_on_the_header_toggles_and_return_still_presses_nothing`, existing Escape test `tests/test_land_confirm.py:266` | Yes |
| 8 | Finished header keeps "Took … · hh:mm to hh:mm"; end title; "Land stopped"; hours format | `test_progress::test_the_end_keeps_the_total_time_and_the_clock_span`, `::test_a_run_over_an_hour_reads_hours`, `::test_fmt_clock` (3599/3600/5525/36000), `::test_every_started_row_has_its_time...` ("Land stopped"), `test_progress_window::test_the_finished_header_keeps_the_time_and_the_run_is_logged`, `test_land_ui::test_a_single_land_ends_with_its_tile_line_in_the_window` | Yes. Title wording is §8.2's owner-approved "Land finished · N repos", not §2's "Landed 6 repos". The end clock time is not pinned against a wall that moves after the end (P3 survived, G3). |
| 9 | Every started repo shows its time in the pill; "Nothing to land"/"Not reached" none | `test_progress::test_every_started_row_has_its_time_and_the_status_word_stays_bare`, `::test_landed_with_branches_left_needs_you...`, `test_progress_window::test_the_finished_header...` (pill "Needs you · 0:04"), `test_land_ui::test_land_all_with_a_failure_says_so_in_the_window_not_a_box` | Yes |
| 10 | Finished rows open on click (▸) into steps with times; folded at start; running row opens itself while live | `test_progress::test_a_finished_row_opens_into_every_step_with_its_time`, `test_progress_window::test_a_finished_row_opens_and_folds_with_its_button`, `::test_two_rows_with_the_same_name_open_one_at_a_time` | Yes. Running-row auto-open is covered by the pre-existing progress tests. |
| 11 | "Earlier:" line, last three, newest first, only when there is one | `test_progress::test_earlier_line_is_the_last_three_newest_first`, `::test_month_names_stay_english_whatever_the_locale`, `test_progress_window::test_the_earlier_line_shows_past_runs_and_not_this_one`, run-log tests in `test_durations.py` | Yes. Format uses commas inside a run (spec §9, review P3-1, for the owner). A stopped run being logged as stopped is untested at the window level (W11, G2). |

Evidence screenshots exist: `docs/audit/land-pick-and-time-confirm.png`, `docs/audit/land-pick-and-time-window.png` (viewed: finished header "Took 14:22 · 13:55 to 14:09", Earlier line, one row opened with step times).

## 2. Mutation check
"Killed by" is the first failing test under `-x`.

### `lab_hub/durations.py`
| ID | Line | Mutation | Tests | Result |
|---|---|---|---|---|
| D1 | 240 | `min(landed, repos)` -> `landed` | test_durations.py | killed (`test_a_bad_run_entry...[bad0]`) |
| D2 | 238 | drop `not isinstance(stopped, bool)` | test_durations.py | killed (`...[bad10]`) |
| D11 | 232 | `strptime("%Y-%m-%dT%H:%M")` -> `fromisoformat` (accepts seconds) | test_durations.py | killed (`...[bad0]`) |
| D12 | 222 | `_count`: `<= RUNS_MAX_REPOS` -> `<` (500 refused) | test_durations.py | **survived** |
| D3 | 258 | `load_runs`: `runs[-RUNS_KEEP:]` -> `runs[:RUNS_KEEP]` | test_durations.py | **survived** |
| D4 | 248 | `load_runs`: `_read(file, RUNS_MAX_BYTES)` -> `MAX_BYTES` (64 KiB cap -> 256 KiB) | test_durations.py | **survived** |
| D5 | 252 | `load_runs`: drop the `version != VERSION` check | test_durations.py | **survived** |
| D6 | 271 | `record_run`: keep only the new run | test_durations.py | killed (`test_run_log_round_trip_keeps_the_last_ten`) |
| D7 | 271 | `record_run`: `[-RUNS_KEEP:]` -> `[:RUNS_KEEP]` | test_durations.py | killed (same) |
| D8 | 274 | `record_run`: write `"stopped": False` | test_durations.py | killed (same) |
| D9 | 172 | `_write_json`: never unlink the temp file | test_durations.py | killed (`test_a_save_that_fails_returns_false_and_cleans_up`) |
| D10 | 160 | `_write_json`: drop `mkdir(parents=True)` | test_durations.py | killed (`test_a_subject_is_sanitised_and_stays_a_key`) |

### `lab_hub/progress.py`
| ID | Line | Mutation | Tests | Result |
|---|---|---|---|---|
| P1 | 72 | `fmt_clock`: `s >= 3600` -> `s > 3600` | test_progress.py | killed (`test_fmt_clock[3600-1:00:00]`) |
| P2 | 73 | `fmt_clock`: minutes `s % 3600 // 60` -> `s // 60` | test_progress.py | killed (same) |
| P4 | 347 | `took_line`: drop the `if self.live: return ""` | test_progress.py | killed (`test_the_end_keeps_the_total_time...`) |
| P3 | 349 | `took_line`: `self.ended_wall or self.wall()` -> `self.wall()` | test_progress.py, test_progress_window.py | **survived** |
| P5 | 429 | `earlier_line`: drop `[::-1]` (oldest first) | test_progress.py | killed (`test_earlier_line_is_the_last_three_newest_first`) |
| P6 | 434 | `earlier_line`: drop ", stopped" | test_progress.py | killed (same) |
| P16 | 432 | `earlier_line`: `_n(run.repos,'repo')` -> `f"{run.repos} repos"` | test_progress.py | killed (same) |
| P7 | 503 | `on_repo_done`: time even when no step ran | test_progress.py | killed (`test_landed_with_branches_left_needs_you...`) |
| P8 | 506 | `on_repo_done`: `self.stopped = self.stopped or stopped` -> `= stopped` | test_progress.py | killed (`test_every_started_row_has_its_time...`) |
| P14 | 515 | `on_repo_done`: status always "Needs you" (no "Stopped") | test_progress.py | killed (same) |
| P9 | 517 | `on_repo_done`: stopped tone stays "warn" | test_progress.py | killed (`test_a_stopped_row_is_muted_not_amber`) |
| P10 | 510 | `on_repo_done`: nothing branch keeps `time_text` | test_progress.py, test_progress_window.py | survived: **near-equivalent** (a "nothing" result has no actions, so no step of it can have started) |
| P12 | 568 | `openable`: drop `not self.live` | test_progress.py | killed (`test_a_finished_row_opens_into_every_step...`) |
| P11 | 569 | `openable`: `any(u.started …)` -> `True` | test_progress.py + test_progress_window.py | killed (`test_progress_window::test_a_finished_row_opens_and_folds_with_its_button`); survived test_progress.py alone, see G7 |
| P17 | 414 | `_steps_all`: drop the `WAITING` skip | test_progress.py, test_progress_window.py | survived: **equivalent** (an openable row has `ended` set, and `on_repo_done` turns every WAITING unit to SKIPPED first) |
| P13 | 593 | end title: never "Land stopped" | test_progress.py | killed (`test_every_started_row_has_its_time...`) |
| P15 | 591 | live title says "Land finished" | test_progress.py | killed (`test_percent_counts_and_stages...`) |

### `ui/land_confirm.py`
| ID | Line | Mutation | Tests | Result |
|---|---|---|---|---|
| C1 | 295 | `chosen()`: ignore the tick | test_land_confirm.py | killed (`test_unticking_folds...`) |
| C2 | 175 | `RepoCard.chosen`: `check is None or` -> `check is not None and` | test_land_confirm.py | killed (`test_every_card_has_a_ticked_box...`) |
| C3 | 315 | `_sync`: Land always enabled | test_land_confirm.py | killed (`test_none_ticked_disables_land...`) |
| C4 | 304 | `_sync`: never remove the old ClaudeBox | test_land_confirm.py | killed (`test_the_claude_panel_covers_exactly...`) |
| C10 | 309 | `_sync`: panel from all cards, not `chosen` | test_land_confirm.py | killed (same) |
| C5 | 301 | `_sync`: `headline(chosen)` without `offered` | test_land_confirm.py | killed (`test_none_ticked_disables_land...`) |
| C6 | 56 | `headline`: `if offered` -> `if not offered` (none-chosen branch) | test_land_confirm.py | killed (`test_headline_counts_the_stops`) |
| C7 | 313 | `_sync`: Details from all cards | test_land_confirm.py | killed (`test_unticking_folds...`) |
| C11 | 314 | `_sync`: button counts all cards | test_land_confirm.py | killed (same) |
| C14 | 316 | `_sync`: drop `_refit()` | test_land_confirm.py | killed (`test_folding_cards_gives_their_room_back`) |
| C8 | 240 | checkbox from 1 card (`> 1` -> `>= 1`) | test_land_confirm.py | killed (`test_every_card_has_a_ticked_box...`) |
| C9 | 179 | `_toggled`: body never folds | test_land_confirm.py | killed (`test_unticking_folds...`) |
| C12 | 180 | `_toggled`: step/stop/Claude pills stay visible when left out | test_land_confirm.py | **survived** |
| C13 | 188 | `_toggled`: `out` property never "true" | test_land_confirm.py | **survived** (dead property: no QSS rule uses it) |

### `ui/apps_tab.py` `_land_planned`
| ID | Line | Mutation | Tests | Result |
|---|---|---|---|---|
| A3 | 1211 | `answer is True` -> `if answer` (a list means all) | test_land_ui.py | killed (`test_land_all_lands_only_the_ticked_repos`) |
| A1 | 1216 | nothing-to-land kept even on Cancel (`p.nothing and ids` -> `p.nothing`) | test_land_ui.py | killed (`test_a_partial_choice_keeps_the_nothing_to_land_rows...`) |
| A2 | 1216 | nothing-to-land dropped from a partial pick | test_land_ui.py | killed (same) |
| A6 | 1222 | left-out/cancelled tiles not reset (`set_landing(None)` dropped) | test_land_ui.py | killed (`test_cancelling_the_confirmation_changes_nothing`) |
| A5 | 1224 | left-out repo not popped from `_landing_cards` | test_land_ui.py | survived: **near-equivalent** today (`_landing_cards` only feeds `_card_for`, and results never arrive for a left-out repo); its assertion is weak (G5) |
| A7 | 1225 | Cancel falls through (`if not picked` disabled) | test_land_ui.py | killed (`test_a_partial_choice_keeps_the_nothing_to_land_rows...`) |
| A8 | 1204 | `confirm_land` returns all plans on Land, ignoring `chosen()` | test_land_ui.py | killed (`test_the_real_dialog_choice_is_what_runs_and_what_is_disclosed`) |
| A4 | 1229 | `from_land_all` computed after narrowing | test_land_ui.py | killed (`test_land_all_narrowed_to_one_repo_still_opens_the_window`) |

### `ui/progress_window.py`
| ID | Line | Mutation | Tests | Result |
|---|---|---|---|---|
| W1 | 800 | finish guard: drop `first_finish` | test_progress_window.py | killed (`test_the_finished_header_keeps_the_time_and_the_run_is_logged`) |
| W2 | 800 | finish guard: drop `ran` | test_progress_window.py | **survived** (G1) |
| W3 | 801 | logged `repos` counts "Nothing to land" rows | test_progress_window.py | killed (`test_the_finished_header...`) |
| W11 | 802 | logged `stopped` always False | test_progress_window.py | **survived** |
| W4 | 631 | `_open` by index -> any open row opens all | test_progress_window.py | killed (`test_two_rows_with_the_same_name_open_one_at_a_time`) |
| W5 | 591 | `_row_opened` always index 0 | test_progress_window.py | killed (same) |
| W10 | 585 | `_open` not cleared by `start()` | test_progress_window.py | **survived** |
| W6 | 257 | header times hidden when finished | test_progress_window.py | killed (`test_the_finished_header...`) |
| W7 | 464 | pill without the time | test_progress_window.py | killed (same) |
| W8 | 439 | opener always visible | test_progress_window.py | killed (`test_a_finished_row_opens_and_folds_with_its_button`) |
| W9 | 746 | `start()` passes `earlier=""` | test_progress_window.py | killed (`test_the_earlier_line_shows_past_runs_and_not_this_one`) |

## 3. Ranked gaps (QA reports; the engineer fixes)
1. **G1 (P2, a test that cannot fail).** `tests/test_progress_window.py::test_a_land_where_nothing_ran_is_not_logged` (the review P3-4 fix) passes for the wrong reason. `_land_window` uses a `Clock` that never moves, so `elapsed()` is 0 and `durations.record_run` refuses the entry (`_sample` needs > 0 s) whether or not the `ran` guard at `ui/progress_window.py:800` exists. Mutant W2 (`if first_finish and ran:` -> `if first_finish:`) survived. Fix: advance the clock (e.g. `clock.t += 30`) before `finish` so only the guard keeps the log empty.
2. **G2 (P3).** A stopped Land is never checked to be logged as stopped (`ui/progress_window.py:802`, W11 survived), yet the Earlier line shows ", stopped" from that flag. Add a window test: a stopped result, then `durations.load_runs()[-1].stopped is True`.
3. **G3 (P3).** `took_line`'s end time (`lab_hub/progress.py:349`, `self.ended_wall or self.wall()`) is not pinned: both tests hold the wall still after `finish()`. P3 survived. Move `wall.t` after `finish()` in `test_the_end_keeps_the_total_time_and_the_clock_span` and assert the span still ends at 14:09.
4. **G4 (P3).** Item 2's "Left out pill in place of the step and stop pills" is untested (C12 survived), and the `out` property set in `RepoCard._toggled` (`ui/land_confirm.py:188`) has no stylesheet rule, so the card itself is not dimmed (only its name is). Either add the QSS rule plus a test or drop the property; and assert `not pill.isVisibleTo(card)` for the in-pills when unticked.
5. **G5 (P3, weak assertion).** `test_land_all_lands_only_the_ticked_repos` asserts `"repo" not in tab._landing_cards` only after the run finished, when `_land_finished` (`ui/apps_tab.py:1279`) has cleared the dict anyway; "tiles go back at once" (item 5) is not checked during the run. A5 survived (near-equivalent today). Assert the left-out tile's state right after `land_all_button.click()`, before `pump`.
6. **G6 (P3).** `_open` is not proven to be cleared by `start()` (`ui/progress_window.py:585`, W10 survived; §8.2 requires it). A second `start()` on the same window would open row N of the new run if row N was open before. Test: open row 0, `start()` again, finish, assert row 0 folded.
7. **G7 (P3, run-log hardening not pinned).** `load_runs` (`lab_hub/durations.py:248-258`): the 64 KiB cap (D4), the version check with a non-empty `runs` list (D5), and "last 10" of a hand-edited file over 10 (D3) all survived; the "hostile" cases are over 64 KiB, so they test the cap and the parser at once and neither alone. `_count`'s inclusive 500 (D12) is untested. Add: a valid 70 KiB file -> `[]`; `{"version": 2, "runs": [good]}` -> `[]`; 12 entries on disk -> the last 10; `repos: 500` accepted.
8. **G8 (P4).** Item 1's Space key and item 4's "Cancel still works with nothing chosen" have no test (Space verified by a scratch probe only). P11's `any(u.started …)` is only caught by the window test, not by `test_progress.py` (its "never reached" row has no `ended`, so it never reaches that clause).

Equivalent or near-equivalent survivors, not counted as gaps: P10, P17, A5 (see tables).

## 4. Restoration proof
No file in the repo was edited by QA; all mutations were in scratchpad copies and each was
restored and byte-checked there. `git diff --stat -- lab_hub ui tests` in the repo, before and after:
```
 lab_hub/progress.py           |  9 +++++-
 tests/test_land_confirm.py    | 31 ++++++++++++++++++++
 tests/test_land_ui.py         | 67 +++++++++++++++++++++++++++++++++++++++++++
 tests/test_progress.py        | 26 +++++++++++++++++
 tests/test_progress_window.py | 30 +++++++++++++++++++
 ui/apps_tab.py                |  3 +-
 ui/land_confirm.py            | 10 ++++++-
 ui/progress_window.py         | 21 +++++++-------
 8 files changed, 184 insertions(+), 13 deletions(-)
```
Identical to the stat taken at the start (`TODO.md` 25 lines, also unchanged). Both scratch copies'
five production files were `cmp`-identical to the repo's after the last mutant.
Other files changed in the worktree during this session (`docs/specs/land-pick-and-time.md`,
`docs/audit/land-pick-and-time-review.md`, new `docs/audit/land-pick-and-time-security.md`) were
written by concurrent sessions, not by QA.

## 5. Verify follow-up (2026-11-18)
Tests only; no production file changed. Each new or fixed test was run once against its planted
mutant in a scratch copy (the five production files `cmp`-identical to the repo's afterwards):
every mutant below was killed.

| Gap | Test | Mutant killed |
|---|---|---|
| G1 | `test_progress_window::test_a_land_where_nothing_ran_is_not_logged` (clock now advances 30 s before `finish`) | W2: `if first_finish:` without `ran` |
| G2 | `test_progress_window::test_a_stopped_land_is_logged_as_stopped` | W11: `stopped` logged as `False` |
| G3 | `test_progress::test_the_end_keeps_the_total_time_and_the_clock_span` (wall moves to 15:30 after `finish`) | P3: `took_line` uses `self.wall()` |
| G4 | `test_land_confirm::test_an_unticked_card_hides_its_step_stop_and_claude_pills` | C12: in-pills stay visible |
| G5 | `test_land_ui::test_land_all_lands_only_the_ticked_repos` (`_landing_cards` read inside the faked `confirm_land` and `lander.run`) | A5: left-out repo not popped |
| G6 | `test_progress_window::test_a_second_start_forgets_which_rows_were_open` | W10: `start()` keeps `_open` |
| G7 | `test_durations`: `test_a_valid_run_log_over_the_64_kib_cap_reads_as_no_runs`, `..._of_another_version_..._even_with_good_runs`, `test_a_hand_edited_run_log_keeps_its_last_ten`, `test_the_repo_count_limit_is_500_inclusive` | D4, D5, D3, D12 (and 501 accepted) |
| G8 | `test_land_confirm::test_space_toggles_the_tick_box`, `::test_cancel_still_works_with_nothing_ticked` (asserts the `rejected` signal; `result()` is 0 before any answer, so it cannot prove Cancel) | box not checkable; Cancel not wired to `reject` |

Not addressed (not in scope): the dead `out` property (G4's second half, C13) is left as is; it is
production code and the owner has not chosen between a QSS rule and dropping it.
Full suite: `.venv/bin/python -m pytest -q`, every test passed (all dots, 100%, no F or E); the Cancel test was tightened after that run and re-run alone (`tests/test_land_confirm.py`, green).
