# Code review: land-fast (2026-11-17)

Reviewer: `code-reviewer` agent, read-only. It is not the author. Scope: `lab_hub/claude_resolve.py`, `lab_hub/land.py` and `tests/test_land_fast.py`, uncommitted. Playbook last reviewed 2026-10-14. The reviewer ran `tests/test_land_fast.py`: 23 passed.

| # | Sev | Finding | Disposition |
|---|---|---|---|
| 1 | P1 | `_take_default` decided from `d:<path>`. A branch that renames `docs/x.md` to `.claude/commands/x.md` while `main` edits `docs/x.md` gets `git rm`, and the merge loses `main`'s file and its edit. The reviewer reproduced this. | Fixed. The decision now comes from the index stages: stage 2 present and the path at the tip means checkout; stages exactly {1, 3} and the path missing at the tip means `git rm`; any other shape is a protected stop. Test: `test_a_rename_into_a_foundry_folder_is_a_stop_not_a_deletion`. |
| 2 | P2 | `blockers()` ran only before triage. A stop met inside `_land_one`, the post-triage `actions()` or `retry_busy` was archived or left without a note. | Fixed. Triage skips archiving a branch that is now blocked, and `blockers()` is idempotent and runs again after `retry_busy`. Test: `test_a_stop_found_while_triage_lands_a_branch_is_not_archived`. |
| 3 | P3 | The 180-character cap on reasons could cut the action ("fix them…") from the stop text. | Fixed. Both stops now start with the action. |
| 4 | P3 | `blocker_kind` matched a substring anywhere, including quoted test output. | Fixed. It matches only at the start, after the "not landed — " prefix. Test: `test_only_the_start_of_a_message_names_a_blocker`. |
| 5 | P3 | After a fix round, the commit cached in `_BASE_PASSED` had been tested in a copy that was not clean. | Fixed. A commit is cached only when no fix round ran. Test: `test_a_merge_fixed_in_a_second_round_is_tested_again_as_the_next_base`. |
| 6 | P3 | The blocker reason always replaced the result reason, even when an earlier stop was more basic. | Fixed. A blocker reason is used only when the first stop is a blocker. |

Checked by the reviewer with no finding: thread safety (one Land worker), file-name handling (`-z` everywhere), the guards after skipping Claude, and that a stopped run is never cached as a failure.
