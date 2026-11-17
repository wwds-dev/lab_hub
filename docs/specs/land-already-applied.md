# Spec: Land recognises a branch whose commits are all already in the default branch as copies

Status: **Define, awaiting owner approval (GATE).** Phase: Define (`product-manager`), 2026-11-17. Slug `land-already-applied` is owned by this session.
In-flight check (`session_start.py --inflight`, 2026-11-17): no listed spec covers this. It touches `lab_hub/repo_tidy.py` `is_landed` / `plan_repo`, the engine of `repo-tidy` and `land-from-tiles` (both "document done", not released); this change is additive to them and does not change their guards.
Nothing built.

## 1. Problem and evidence
`is_landed()` (`lab_hub/repo_tidy.py:141`) only asks `git merge-tree --write-tree`: "would merging give main's own tree?". A branch whose commits reached main as **rebased or cherry-picked copies** (a rebased PR) often fails that test with a textual conflict, because the merge base is old and main has moved on. `plan_repo` then plans a `claude_merge` for it.

Real Land, 2026-11-16, Sentinel, branch `fixes/audit-tier2-2026-10-12`: 19 commits, conflicts in 16 files, sent to Claude Code, "landed" as merge commit `057c1a4` for $1.15, 147 turns and two 5-minute test runs. `git diff 057c1a4^1 057c1a4` is empty: all 19 commits were already in main through an earlier PR as rebased copies (`git cherry <main> <branch>` showed 19 `-`). The merge only recorded the branch as merged, adding a pointless merge commit to history.

## 2. Success measure
1. A local branch with at least one commit not in the default branch's history, where `git cherry <default> <branch>` prints only `-` lines (every commit has a patch-equivalent in the default branch), is planned as **landed**: the same `remove_worktree` (when clean) and `delete_branch` actions and guards as a tree-equal landed branch, reason "every commit is already in `<default>` as a copy". No `claude_merge`, no `merge`, no merge commit, no Claude run, no test run.
2. Test on a real temporary git repo built like the evidence: branch of N commits, main gets rebased copies of them plus later edits that make a plain merge conflict. Before: planned `claude_merge`. After: planned `delete_branch`, nothing merged. `apply` deletes the branch and leaves main's history unchanged (same tip).
3. Negative tests, all still **not** treated as copies: a branch with one commit whose patch is not in main (`+` among the `-`); a branch whose commits are copies but also has a merge commit (see §5); an empty `git cherry` for a non-ancestor (error or unborn) falls back to today's behaviour.
4. Existing behaviour is untouched: ancestor and tree-equal branches stay landed with their old reason; genuinely conflicting branches still go to Claude; clean ones still merge.
5. Suite green in the offscreen mode; mutation check: removing the `+`-line test, or the merge-commit guard, fails a test.

## 3. Scope
- `lab_hub/repo_tidy.py`: a new `applied_copies(repo, default, branch)` helper (runs `git cherry`, requires every line `-`, at least one line, and no merge commits in `default..branch`); `plan_repo` treats such a branch as landed in both loops (skip it in the merge loop; add it in the landed loop with the new reason). `check` re-verifies it at apply time exactly like a landed branch, using the same predicate, so a branch that gained a commit after the plan is skipped, not deleted.
- The confirmation wording in `lab_hub/land.py` / the Details list shows the new reason through the existing `Action.reason`; no UI structure change.
- Tests in `tests/test_repo_tidy.py` with real temporary repos; README, TODO and CHANGELOG.

## 4. Non-goals
- No new git operation: no merge, rebase, cherry-pick or push is added; only the existing delete of the branch (and clean worktree).
- No guess beyond patch-ids: no fuzzy or "similar diff" matching, no matching of squash-merged PRs (a squash makes one commit from many, so `git cherry` shows `+`; those branches stay as today: tree-equal check or Claude).
- No loosening of any `repo-tidy` §5 guard (dirty worktree, busy session, recent agent worktree, branch moved since plan).
- No change to how Claude resolves real conflicts.

## 5. Risks and what the user is told
**`git cherry` matches by patch-id, not by tree.** A `-` line means "main has a commit with the same diff", not "main still contains that work". Main may later have edited or reverted those lines, so the branch's final content can differ from main without any copy being missing from history. Deleting the branch then discards nothing that main does not already have *as a commit*; but if the owner wanted a branch's change to be live and a later main commit undid it, Land would not bring it back. That is the same position as after the old empty merge, and the true state of main is unchanged by Land.
What the user is told (all of it on the Details list and in the log, never silent):
- The reason line says "every commit is already in `<default>` as a copy (matched by patch; later edits on `<default>` are not compared)".
- The line also gives the count: "N commits" and, when the branch tip's tree differs from main's, "its files differ from `<default>` in K files (older versions of work that main has since changed)".
- The branch tip SHA is logged by the existing `delete_branch` step, so `git branch <name> <sha>` restores it.
Other risks:
- **Merge commits in the branch.** `git cherry` skips merge commits, so a conflict resolution recorded in a merge would be invisible. A branch with any merge commit in `default..branch` is not treated as copies and takes today's path.
- **Duplicate patches.** Two commits with equal diffs map to one patch-id; harmless here (the branch is only judged "all matched").
- **Cost of `git cherry`** on a long branch: one extra call per unlanded branch, bounded by the existing git timeout; a timeout or error means "no".

## 6. Decisions for the owner
1. **Show the diff-size line (K files differ).** Recommend yes: it is the honest signal for the §5 risk. Alternative: reason line only.
2. **Delete the branch automatically** like any landed branch (recommended; restorable by SHA from the log). Alternative: list it as "needs your decision" in Review branches instead of deleting.
3. **Merge commits in the branch** disqualify it (recommended, safer). Alternative: ignore merge commits.

## 7. Phases to run
Define (this file, **GATE**), Design/Architect skipped (no UI structure, state or concurrency change; the predicate is a pure git query), Plan skipped (one task), Build (tests first), Review (independent, `code-reviewer`), Verify (mutation check), Secure skipped (no new network, input or write surface; runs only `git cherry` and `git rev-list` on the repo's own refs, with the existing git wrapper), Document, Comply skipped (tier `public`, no new claims).
