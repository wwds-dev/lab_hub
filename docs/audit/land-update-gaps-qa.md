# QA: land-update-gaps

Verify phase (7), 2026-11-17.
The `qa-engineer` agent was stopped after about 55 minutes without a report (owner's timebox: 15 minutes more). Its copy of the code also predated the review fixes. The owning session ran the mutation check itself instead, so this phase is **not independent of the author**. That is recorded here as a gap.

## Success measures (spec §2)
| # | Measure | Evidence |
|---|---|---|
| 1 | No folder symlink is committed by Land | `test_a_venv_link_in_an_agent_worktree_is_ignored_not_committed` (the SONAR case end to end: `.gitignore` has only `.venv/`, the main checkout's real `.venv` survives the landing, and `/.venv` is on main); `test_a_link_that_appears_after_the_preview_is_still_not_committed`; `test_a_worktree_whose_only_untracked_entry_is_a_folder_link_is_still_tidied`; plus 13 unit tests of `folder_link` / `ignored_as_folder` |
| 2 | One failing rebuild doesn't stop the others | `test_a_failed_rebuild_does_not_stop_the_others`, `test_a_command_that_cannot_start_fails_and_the_run_still_ends`, `test_cancel_right_after_a_failed_rebuild_starts_nothing_more` |
| 3 | Lab Hub restarts when only another app failed, and not when its own build failed | `test_lab_hub_still_builds_and_restarts_after_another_app_failed`, `test_a_failed_lab_hub_build_asks_for_no_restart`, `test_update_now_restarts_when_only_another_app_failed`, `test_update_now_does_not_restart_when_lab_hubs_own_build_failed`, `test_a_skipped_lab_hub_is_not_counted_and_is_named_after_another_failure` |
| 4 | "1 commit further on" | `test_how_far_behind_reads_right_for_one[1/3]` |
| 5 | Full suite green; mutation-checked | below |

## Suite
- Full suite, `.venv/bin/python -m pytest -q -p no:cacheprovider`: exit 0, run twice (before and after the review fixes, about 8 min each).
- After that, only test files changed. `tests/test_land_update_gaps.py`, `tests/test_self_update.py`, `tests/test_apps_tab.py` and `tests/test_land_resolve.py` were re-run: exit 0.

## Mutation check
22 mutations, planted one at a time in a copy of the repo, with the targeted test files run against each (script: scratchpad `mutate.py`). **22 of 22 killed**, after three gaps the first pass found were closed:
- M03 (an unreadable link counted as "not a folder link") survived. Added `test_a_link_that_cannot_be_read_is_never_committed`.
- M07 (a `.gitignore` that is a link was read) survived, because the outside-the-worktree check also caught it. Added `test_a_gitignore_linked_to_a_file_inside_the_repo_is_not_read_either`.
- M11 (a worktree whose only entry is a folder link gets no prep step) survived. Added `test_a_worktree_whose_only_untracked_entry_is_a_folder_link_is_still_tidied`.
- M21 (restart even though Lab Hub's own build failed) first hung on a modal warning instead of failing. The test now records `QMessageBox.warning` and `stage_build`, so it fails at once.

Covered: every branch of `folder_link` and `ignored_as_folder`, the `./` pathspec, the fail-closed git error, the ignore line without a trailing `/`, the preview and switch paths, the plan sentence, `commits_further`, `Rebuild` continuing, `succeeded`, the skipped total, the restart conditions in the window and in `apps_tab`, the Terminal-installer block, and the `ran_to_end` early return.

## Not verified
- The real app on the Mac: a real Update now with a failing app, and a real Land over a worktree with a `.venv` link. This needs the build installed.
- No independent QA agent verdict (see above).

## Option B (owner decision §10.2, 2026-11-17)
Three more mutations on the new conditions, against `tests/test_land_update_gaps.py`. **3 of 3 killed:**
- B1: drop the absolute-text check.
- B2: drop the outside-the-worktree check.
- B3: stop treating a link loop (`RuntimeError`) as "cannot tell".

`test_land_confirm`, `test_claude_resolve`, `test_claude_resolve_nested`, `test_land_fast`, `test_land_resolve`: all pass.

Verdict: success measures 1–5 met in tests. Real-app check outstanding.
