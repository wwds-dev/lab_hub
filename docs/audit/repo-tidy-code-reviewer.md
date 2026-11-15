# Code review: repo-tidy (2026-11-15)

Reviewer: `code-reviewer` subagent (independent of the author), read-only. Scope: uncommitted work on `claude/repo-tidy`:
`lab_hub/repo_tidy.py`, `ui/repo_tidy_dialogs.py`, `ui/apps_tab.py`, both test files, the spec. 28 tests passed.
Read-only `plan()` on the real lab proposed about 50 branch deletions and 12 worktree removals.

No P0. One P1.

## P1
- **Removing a "clean" worktree deletes its gitignored files** (`repo_tidy.py` `is_clean` ignores ignored files; `git worktree remove` without `--force` still deletes them). Reproduced with an ignored `.env`. On the real lab the plan would remove `archive/fixes_2026-10-12/imprint`, which holds ignored `data/` (chats, kdp_reports, model_watch.json). Fix: block on ignored entries outside a regenerable allowlist, same in Review; test with an ignored `.env`.

## P2
1. Push does not require a clean checkout (spec §5 says it must). Fix: `tracked_clean` in plan and check; test.
2. Closing Clean up during Apply leaves the batch running unseen; `changed` stays False; a second Apply can start; the non-daemon worker delays quit. Fix: block Close/Esc while busy.
3. The `lsof` guard fails open: on failure `busy_dirs()` returns `()`. Fix: return None and treat it as "may be in use".
4. Restore promise not guaranteed: `_log` swallows `OSError` and the delete proceeds; `branch -D` drops the branch reflog, so commits are only kept until gc (~2 weeks), not ~90 days. Fix: write the log first and abort on failure; correct the copy.
5. Review actions run git (and lsof) on the UI thread. Fix: route through the worker.

## P3
- Delete is not compare-and-delete: apply re-reads the tip after `check()`. Fix: delete with `git update-ref -d refs/heads/<b> <sha>` and log the planned SHA.
- A worktree paused mid-rebase/bisect looks detached and clean and can be removed. Fix: skip when its gitdir has `rebase-merge`, `rebase-apply` or `BISECT_LOG`.
- Push/fetch use `origin` while counts use `@{upstream}`. Fix: skip unless upstream is `origin/<default>`.
- Pull allows untracked files (safe with `--ff-only`, but differs from the spec wording).
- Review buttons stay enabled during a reload.

## Test gaps
Ignored files in a worktree, push when dirty, lsof failure, log-write failure, Close during Apply, Review "Remove worktree" UI flow with the recent-agent warning, paused rebase.

## Checked and fine
Moved branch caught by SHA; diverged never synced; main, locked and missing worktrees never removed; branch names after `--` and via `refs/heads/`, no shell; merge-tree conflict or error counts as not landed; push re-fetches first.
