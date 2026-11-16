# Review: release-root-behind (code-reviewer, independent, read-only)

Spec `docs/specs/release-root-behind.md`. Reviewed 2026-11-16 on the uncommitted diff. Result: P0 0, P1 1, P2 6.
The reviewer wrote no file; the orchestrator saved its findings here with what was done. The reviewer ran 10 planted
mutants in a scratch copy: 5 killed, 5 survived (root.is_dir, two wording branches, the runbook guard, heading names).

## P1 — fixed
1. "Copy and open Terminal" was offered for a report with only a release-clone move, against §5.1 / measure 3 (show and copy only). **Fixed:** that button needs an in-app or by-hand row; a forward-only report offers Copy commands only. Test: `test_a_release_clone_behind_is_listed_to_move_and_gets_no_update_now`; mutant (button back) is caught.

## P2
1. Note ended at "press Refresh" though the runbook continues (dependencies, selftest) — **fixed** in the note and the dialog heading.
2. A dangling "The runbook" when no runbook file exists, and "first" twice — **fixed:** the note is built with and without the file; test `test_the_note_is_right_for_one_commit_and_without_a_runbook`.
3. `origin/main` is assumed — **fixed in the wording:** "merge and push the source to main first if it is not there". A different remote or default branch still fails safely with a git error; accepted.
4. Wording branches untested and one dead (`behind == 0`) — **fixed:** dead branch removed, singular tested.
5. Measure 4 vacuous: a root app is a `needs_rebuild` row only when its root is behind, so the by-hand Terminal route is no longer reachable for Provisio — **accepted, by design** (§1); README now says so.
6. Measure 5 / integration coverage — **fixed:** `test_a_stale_release_clone_gets_the_move_not_the_installer_and_the_move_works` (real bundle, real git clone, runs the shown command, tile goes current) and `test_no_registered_app_without_a_recorded_root_is_a_forward_row` (registry).

Suite after the fixes: 679 passed (2026-11-16). Secure skipped as in the spec (command displayed, not run; no file write, network or executable content).
Not verified: success measure 6 on the real Mac with a freshly stale clone (the owner did the same move by hand on 2026-11-16).
