# QA: land-folder-link-guard

Phase: Verify (7), 2026-11-18 to 2026-11-20, run by the owning session. The independent checks were Review and Secure, each done by a different agent. This report records the commands that were run and what they printed.
Spec: `docs/specs/land-folder-link-guard.md`. Tests: `tests/test_land_folder_link_guard.py` (44 tests, all against real temporary git repos, with no git mocks).

## Success measures (§2)
| Measure | Evidence |
|---|---|
| 1. The SONAR case cannot recur | `test_land_stops_a_branch_whose_venv_link_would_replace_the_real_venv`. Through `land.land()`: `.venv/bin/python` is intact, `main` and `origin/main` have not moved, the branch is kept and not archived, Claude is never asked, and the stop names `.venv`. The file variant is covered by `test_a_plain_file_named_like_the_folder_is_stopped_too`. |
| 2. Every route is covered | Plan: `test_the_preview_shows_the_branch_as_not_merged`. Merge re-check: `test_the_merge_re_checks_when_the_folder_appeared_after_the_preview`. Claude merge before start: `test_a_claude_merge_is_never_started_for_such_a_branch`. Claude fast-forward: `test_claudes_fast_forward_is_checked_too`. Switch: `test_preps_switch_stops_…`, `…_holds_every_branch…`, `…_when_main_moves_while_it_is_checked`. Pull: `test_a_pull_checks_what_it_fetched_before_it_moves`, `test_a_pull_link_stop_holds_every_branch_and_archives_none`. |
| 3. A wanted link still lands | `test_a_wanted_link_inside_the_repo_still_lands` (end to end) and `test_a_wanted_link_inside_the_repo_passes`. |
| 4. Full suite green, new logic mutation-checked | See below. |

## Full suite
- 60186bf (the reworked code): `.venv/bin/python -m pytest -q -p no:cacheprovider` passed, 1289 tests, 1 skipped, 0 failed (exit 0).
- The final tree, after `main` was merged in and the M29/M32 tests were added: see the line at the end of this file.
- The first run, at 585e3b3, failed one test: `test_a_symlink_out_of_the_repo_is_refused_before_claude`. That failure was intended: the branch is now refused at plan time. The test was updated to expect that, and it still asserts that Claude never runs (review P1-1).

## Mutation check
Each mutation was applied to a copy of the code made with `git archive` and tested with `tests/test_land_folder_link_guard.py` plus the updated Claude test. M01–M27 ran on 60186bf. M28–M32 ran on the final tree, which has the same four guard modules (`git diff 60186bf HEAD -- lab_hub/{land_resolve,repo_tidy,claude_resolve,land}.py` is empty).

| Result | Mutations |
|---|---|
| Killed | M01 real-folder check · M02 mode column · M03 `blocker_kind` link · M04 triage filter · M05 pull check after fetch · M06 switch check · M07 Claude fast-forward check · M08 `check()` merge · M09 ignored name · M10 outside the repo · M11 display filter · M12 "and N more" boundary · M13 conflicted merge tree · M14 plan skip · M15 tracked check · M16 diff failure read as no links · M17 parent link · M18 absolute target · M19 files skipped · M20 link chain · M21 case folding · M22 `.git` target · M23 the branch's `.gitignore` · M24 pull hold · M25 switch hold · M26 triage ignores hold · M27 orphan branch · M29 file over an untracked file · M30 unreadable link text · M31 `is_link_stop` too loose · M32 switch re-read of the tip |
| Killed by timeout | M28 hop limit removed: the `a ↔ b` link cycle loops forever |
| Survived | none |

Three mutations survived earlier runs and are killed now:
- M12 (the "and N more" boundary): `test_the_stop_names_three_paths_and_counts_the_rest` was extended with four- and three-link cases.
- M29 (file over an untracked file): `test_a_new_file_over_a_local_file_is_left_to_git` was added.
- M32 (switch re-read of the tip): `test_the_switch_stops_when_main_moves_while_it_is_checked` was added.

## Not verified
- The Qt rendering of the stop text, and a real Land run on the owner's Mac.
- CI. The repo has no CI for this branch; the local suite is the check.
- `submodule.recurse=true` (security, not verified).

## Final tree suite
- Final tree (`ca9ee3b` plus the M29/M32 tests), `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q -p no:cacheprovider`, 2026-11-20: 1327 passed, 1 skipped, 0 failed (exit 0).
