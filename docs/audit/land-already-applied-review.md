# Review: land-already-applied (2026-11-17)

Reviewer: `code-reviewer` (independent, read-only; report saved here by the orchestrator, who has the write tool). Spec `docs/specs/land-already-applied.md`.

**Verdict: 0 P0, 0 P1.** The widened `is_landed` was traced through `plan_repo` (both loops), `check()` for merge, claude_merge, delete_branch and remove_worktree, and `unlanded()`; all use the same predicate. `applied_copies` returns 0 on any git error or timeout, a missing or unborn ref, a merge commit, an empty or whitespace-only commit (`git cherry` prints `+`), or any `+` line. Refs are fully qualified, so no option injection.

| # | Finding | Status |
|---|---|---|
| P2-1 | "files differ" count was a tip-to-tip diff, so it counted files the branch never touched and the wording was false for them | Fixed: only files the branch changed (`default...branch`) that also differ at the tips; test `test_the_differing_file_count_ignores_files_the_branch_never_touched` |
| P2-2 | Work reverted on main is deleted with only a soft warning (accepted spec §5 risk, restorable from the logged SHA) | Wording strengthened: "main may have changed, reverted or rewritten that work" |
| P2-3 | About 3 `git cherry` runs per copy branch per plan | Reduced: the landed loop calls `landed_reason` once (it returns "" when not landed); `check()` repeats the predicate by design |
| P2-4 | Test gaps (Review branches, check() for merge kinds, dirty worktree, odd refs) | Added 4 tests; a branch named `-x` cannot exist (git refuses it) |
| P3 | A branch with main merged into it is refused (spec decision 3, by design); the reason text also goes to the log | Accepted |

Verify (mutation check, run by the orchestrator): dropping the merge-commit guard, the `+`-line test, the three-dot intersection, or the `is_landed` widening each fails tests. Dropping `if not lines` is an equivalent mutant (an empty list returns 0 anyway).
