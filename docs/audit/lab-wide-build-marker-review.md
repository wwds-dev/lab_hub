# Review: lab-wide build marker (branch claude/build-marker-tiles-1a353e)

Reviewer: code-reviewer (read-only), 2026-11-13. Playbook `code-reviewer.md` last-reviewed 2026-10-14, status current (not stale).
Scope: uncommitted diff + `tests/test_build_marker.py`, against spec `docs/specs/lab-wide-build-marker.md` measures 0-4 and 6.
Verified: `.venv/bin/python -m pytest tests -q` in the worktree: all pass (1 skipped). Edge cases below were found by reading, not by running a repro, unless stated.

## P1

### P1-1 (downgraded to P2 after checking callers: refresh is on demand, `apps_tab.py:154,166,647,769`, not a timer) Uncached git subprocesses on every tile refresh
`lab_hub/launcher/state.py:575-605` (`_commits_behind`), called at `:738` (frozen bundle) and `:752` (launcher bundle).
Each refresh of each tile runs `git cat-file -e` and `git rev-list --count built..HEAD` (2 subprocesses, 10 s timeout each, on the GUI thread via `ui/apps_tab.py:191`, refreshed at `:647` and `:769`) with no cache. Before the change the frozen path used only `_commit_count`, which is cached on the HEAD stamp. Spec section 6 says "keep the existing cached poll... not per repaint". Only `_head_commit`, `_commit_count` and `_is_dirty` are cached and tested for it; `_commits_behind` has no caching test.
Fix: cache on `(source, built_commit, _head_stamp(source))`, like `_COUNT_CACHE`; add a test counting `subprocess.run` calls across repeated `version()` calls.

### P1-2 `build_status` says "runs the checkout directly, always what the source says" for a launcher bundle that runs a different root
`state.py:~890-898` (checkout-origin branch of `build_status`). For a launcher bundle whose recorded root is the release clone and is level (`behind == 0`) or `behind_unknown`, the verdict is `current` with the text above. That is false: the bundle runs the release clone, not the source. `behind_unknown` is never consulted in `build_status` (grep: only `apps_tab.py` reads it), so the Build report shows "current" where the spec says "unknown rather than guess".
Failure: unrelated-history root (the test `test_launcher_root_with_a_commit_unknown...`) -> tile says "cannot be told", build report says `current`.
Fix: in `build_status`, return `unknown` when `found.behind_unknown`; reword the checkout message when `found.detail` is a recorded root that is not the working checkout. Add a test for `build_status` with `behind_unknown`.

### P1-3 A recorded root that is unusable silently shows the working checkout's build (a guess)
`state.py:~744-760`. If `project_root.txt` points at a missing dir, a dir without `entry`, a non-git dir, or a repo with no VERSION/`## vN` (so `installed.known` is False), the code falls through to `checkout_version(project)` and the tile shows the working checkout's number and commit, with detail "from the checkout at <project>". Launch will actually run the recorded root (or fail). That reproduces the original bug (a tile naming code the button does not open), and contradicts "say 0 or unknown rather than guess". The test `test_launcher_bundle_with_a_missing_root_falls_back_to_the_checkout` locks the guess in rather than checking for an "unknown/missing root" signal; it asserts only `text` and `not stale`.
Fix: when a bundle records a root and it cannot be read, return a Version with no number (or `behind_unknown=True` and a note naming the root), and test missing, non-git and VERSION-less roots.

## P2

### P2-1 Shallow release clone gives a wrong build number with a trustworthy-looking commit
`state.py:515-531` / `:686-696`. `rev-list --count HEAD` in a shallow clone counts only the fetched depth, so the tile reads e.g. `v2.0.001+gc534bbb`. The commit is right, the number is wrong, and nothing says so. Spec section 6 asks for an `unknown` count for shallow checkouts. `behind` itself is fine (commit based; if the working checkout is shallow and lacks the built commit, a launcher gets `behind_unknown`, a frozen bundle falls back to count subtraction). No shallow test. Fix: detect `git rev-parse --is-shallow-repository` (cached with the head commit) and drop or flag the count. Not verified by running.

### P2-2 Frozen-bundle fallback compares counts across histories
`state.py:597-603`: with a built commit unknown to the working checkout, `counts_comparable` defaults True, so `current - built` is returned (e.g. a stamp from another branch, or a shallow working checkout). The spec says counts name different code on different branches; the launcher path returns unknown here, the frozen path guesses. Inconsistent with "one rule for all" (measure 2). Fix: pass `counts_comparable=False` when the stamp has a commit; keep the count fallback only when the stamp has none.

### P2-3 `-dirty` on a launcher bundle at a release clone is not the dirty state of what is "behind"
`state.py:686-696`. Fine in principle, but `git status` runs on the GUI thread (15 s timeout) for every tile's first refresh and after each 10 s TTL; refresh is on demand (Refresh button, settings change, construction), so the cost is bounded. Not measured.

### P2-4 Detached HEAD and hex-ambiguity
`_commits_behind` uses `cat-file -e <short>^{commit}`; an ambiguous 7-char prefix in a large repo makes `known` False and silently yields unknown/count fallback. Rare; no test. Detached HEAD works (`_head_stamp` uses the HEAD file mtime; `rev-list HEAD` works) but is untested, and no branch name is shown (branch suffix intentionally not built).

### P2-5 Tests that would still pass if the code were broken
- `test_dirty_check_runs_git_status_once_per_window` and the TTL test call `_is_dirty` directly. If `checkout_version` called `dirty_checkout` uncached, no test fails (`test_checkout_with_uncommitted_changes_shows_dirty` clears the cache itself).
- `test_head_commit_is_cached_against_head` counts every `subprocess.run`; `_head_stamp` does no subprocess, so ok, but it would not notice a second git call added elsewhere in `version()`.
- `test_launcher_bundle_with_a_missing_root_falls_back_to_the_checkout` asserts the guess (see P1-3).
- `test_launcher_root_with_a_commit_unknown...` ends with `assert work.exists()`, which tests nothing.
- No test of `behind` when the installed root is ahead of the working checkout (expected 0), of a non-git or shallow root, of detached HEAD, or of a launcher root equal to the working checkout via a symlink (`_same_dir` resolves; untested).
- Measure 1's "same string in its tooltip": tooltip test checks the sha, not the full marker string.

## P3 / notes
- `README.md` says "`stamp_version.py` now refuses to stamp without a commit" -- supported (`scripts/stamp_version.py:31-34`, tested).
- `-dirty` appears on the tile only when the origin is a checkout; a frozen bundle never shows it (matches spec decision 2 wording and measure 4).
- Measure 5 and the branch suffix are out of scope as stated.
