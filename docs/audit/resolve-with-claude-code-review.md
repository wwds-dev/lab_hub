# Code review: resolve-with-claude (spec repo-tidy §11)

Reviewer: `code-reviewer` subagent, read-only, 2026-11-16. Saved verbatim in substance by the
orchestrating session (the reviewer is read-only). Suite at review time: 94 passed in the three
repo-tidy test files; the real Claude CLI was not run.

## P0
- **P0-1** Conflict markers land when a conflicted file's name is non-ASCII: `unmerged` is read
  without `-z` (git quotes the name), `markers_left` treats the unreadable quoted path as
  "deleted". Reproduced: `main` got `café.txt` with markers. Fix: `-z`; fail closed on read errors.

## P1
- **P1-1** Claude rewriting the temporary worktree's `.git` file makes Lab Hub's own `add`/`commit`
  land on the main checkout's default branch before the landing check rejects it. Reproduced with
  a stub. Fix: explicit `--git-dir`/`--work-tree` for every temporary-worktree git call; check
  `.git` and the default tip before committing.
- **P1-2** The "nothing outside the worktree changed" check in §11.3 is missing: ignored files are
  not compared, and the `.venv` symlink is present during the fix round, so writes reach the main
  checkout's real `.venv`. Fix: links only during test runs; snapshot untracked *and* ignored files
  around each Claude run.

## P2
- **P2-1** The fix round may edit test files and test configuration (conftest, pytest.ini, …) and
  so defeat the only safety check. Fix: reject such changes.
- **P2-2** One exception (malformed stream-json, `symlink_to`) aborts the whole batch and hides
  branches that already landed. Fix: per-action try/except; defensive parsing.
- **P2-3** Guards with no test: landing branch-moved, parent check, landing target blocker,
  fix-round new files/markers, timeouts, UI Stop.

## P3
- **P3-1** An environment failure ("not found") is sent to Claude as failing tests and blamed on
  the default branch.
- **P3-2** Banned programs pass when given with a full path; an absolute program path leaves the
  worktree.
- **P3-3** The test command is read again after `check()`; compare once more.
- **P3-4** `timed_out` is inferred from elapsed time, not from the timer.
- **P3-5** `killpg` may hit a reused process group after the child is reaped.
- **P3-6** The marker count compares against the larger side's count; a fixture with markers can
  hide a real one. Spec mentions `=======` and `git diff --check`, code does not.
- **P3-7** Stop's wording ("nothing half-done is kept") does not cover a branch already landed
  whose push is then skipped.

## Checked, not findings
Stop/attach race handled; progress queue thread-safe; close blocked during Apply; `_cleanup`
refuses paths outside its root; landing check cannot be bypassed via refs alone.

## Resolution
See the "Fixes" section appended below by the building session.

## Fixes (building session, 2026-11-16)
Tests are in `tests/test_claude_resolve.py`.

| Finding | Status | Fix | Test |
|---|---|---|---|
| P0-1 | Fixed | Conflicted names read with `-z`; `markers_left` treats a file it cannot read as failed. | `test_markers_in_a_non_ascii_file_name_are_caught` |
| P1-1 | Fixed | Every git call in the temporary worktree passes `--git-dir`, `--work-tree` and `core.hooksPath=/dev/null`. The `.git` file is checked after each Claude run. Before committing, the default tip and HEAD are checked. | `test_tampering_changes_nothing[dotgit]` |
| P1-2 | Fixed | Untracked and ignored files are compared around every Claude run. The environment folders are linked only while tests run, and a planted one fails the branch. | `[venv]`, `[ignored]` |
| P2-1 | Fixed | The fix round may not touch tests or test configuration. | `[bad_then_cheat]` |
| P2-2 | Fixed | Each action in the UI worker has its own try/except. Stream-json is parsed defensively. Any exception inside `resolve` is reported as a failure, with cleanup. | `test_malformed_stream_json_does_not_crash` |
| P2-3 | Fixed | Tests added for the landing checks (branch moved, default branch moved), fix-round new files, the timeout, and Stop at the start of apply. | Second mutation run, below |
| P3-1 | Fixed | `run_tests` reports `env` / `timeout` / `fail`; only `fail` goes to Claude. | `test_a_missing_test_program_is_not_sent_to_claude` |
| P3-2 | Fixed | The program's basename is checked; absolute paths and `..` are rejected. | Shell-syntax parametrize |
| P3-3 | Fixed | The test command is compared again just before the run. | — |
| P3-4 | Fixed | `timed_out` is set by the timer callback. | — |
| P3-5 | Mitigated | The group is killed only while the leader is unreaped. One final `killpg` runs after reaping, to catch leftovers; macOS has no `waitid` to avoid this. | — |
| P3-6 | Accepted, spec aligned | See §11.10. | — |
| P3-7 | Fixed | The Stop wording now says that a landed branch stays and its push waits. | — |

## Mutation check (Verify, 2026-11-16)
Each guard was disabled one at a time and the claude_resolve and repo_tidy tests were run against it. 26 mutations in all; 25 were caught, either in the full run or in a targeted re-run after tests were added.

The one survivor is #23, which disables the test-command check in `check()`. `apply()` makes the same comparison again just before the run (the fix for P3-3), so the test still sees the branch skipped. Disabling both together is caught.

Survivors of the first pass that are caught after new tests:
- the HEAD^1/HEAD^2 parent check;
- the banned-program check by basename.
