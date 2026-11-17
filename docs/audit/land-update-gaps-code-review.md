# Code review: land-update-gaps

Review phase (6), read-only, 2026-11-17, by the `code-reviewer` agent (not the author). Saved by the owning session from the agent's report.
Playbook `docs/playbooks/code-reviewer.md`: `status: current`, `last-reviewed: 2026-10-14` (not stale). The app-context Stack, Hot spots, Security surface and Invariants sections are still placeholders.

## Evidence
- Read `git diff` and the untracked spec and test file.
- Targeted tests green:
  - `tests/test_land_update_gaps.py`: 11 passed.
  - `tests/test_self_update.py` and `tests/test_apps_tab.py` (offscreen): all passed.
  - Link tests re-run with `TMPDIR` under the macOS `/var` symlink: pass.
- git 2.56.0 probes:
  - A linked worktree's git dir still applies the common `info/exclude`.
  - Glob characters in the checked path are literal.
  - A leading `:` is parsed as pathspec magic (P3-1).
- Callers of `Rebuild.succeeded`: only `ui/apps_tab.py` and tests. `self_update.py` does not read it. The fakes `_FakeRebuild` and `_FakeRun` lack `ran_to_end` and `failed`.
- Qt flow (by reading):
  - Cancel in the `singleShot(0)` gap ends the run as cancelled, and the pending `_start_next` returns on `_ended`.
  - FailedToStart sends no `finished`, so nothing is counted twice.
  - `name_for` is read before `deleteLater`.
  - `_restart_built` and `built_self` agree.
  - No re-entrancy or use-after-delete defect.

## Findings
P0: none. P1: none.

**P2-1. The Terminal-installer branch after a failure is untested; the old test now covers the cancel path under a misleading name.**
- Where: `ui/apps_tab.py:867-869`.
- Mutation: deleting `by_hand = []` opens Terminal installers after a failed rebuild, against §3.2, and no test catches it.
- Fix: give the fakes `ran_to_end` and `failed`, add the case, and rename the old test.

**P2-2. Residual risk outside the spec: a branch that already contains a committed `.venv` link still destroys main's venv when Land merges it.**
- `folder_link` guards only Land's own untracked step. An agent's own `git add -A` commits the link the same way the 17 Nov run did.
- Suggested follow-up (owner, own spec): an outgoing check that stops a branch adding a mode-120000 entry where the target checkout has a real folder, or a name ignored as a folder. Until then, the docs should say the guard covers files Land commits.

**P3-1.** A link name starting with `:` is checked as a different path (`land_resolve.py:346-347`). Fix: pass `"./" + rel + "/"` (verified).
**P3-2.** `ignored_as_folder` fails open when git cannot run: `rt.git` maps OSError and timeout to rc=1. Fix: treat rc=1 with stderr as "cannot tell".
**P3-3.** The window's end line counts a skipped Lab Hub in the total and omits "Lab Hub itself was not rebuilt" when another app failed (`progress_window.py:971-990`).
**P3-4.** No test for Cancel in the gap after a failure.
**P3-5.** Two comments are stale: `ui/apps_tab.py:814-815` and `lab_hub/progress.py:758`.
**P3-6.** The `getattr` fallbacks in `apps_tab` exist only for out-of-date fakes.
**P3-7.** The result string counts the ignored links but does not name them (spec §2.1 says it names them).
**P3-8.** By design, the rule also leaves out intentional in-repo folder links (like `shopfront/website`): the link stays out of the branch and its line lands on main. The README should say so.

## Checked and sound
- `folder_link`: nested paths, spaces and glob characters, linked worktrees, symlinked `.gitignore` skipped, unreadable links, a link that appears after the preview.
- `.gitignore` files above the root are not read (as git does). Negation rules are evaluated by git itself. The line-break guard matches the nested-repo guard. A swap between the scan and `git add` is caught by `_staged_differs`.
- `Rebuild`: the deferred start, the `_ended` guards, and `succeeded`/`ran_to_end`/`failed` consistency. A broken hold check still ends the run with no restart.
- `commits_further` is used in both places and tested.

Verdict: no P0/P1. Two P2s (an untested branch; a residual risk outside the spec for the owner) and eight P3s.

## Resolution (owning session, 2026-11-17)
| Finding | Status |
|---|---|
| P2-1 | Fixed. The fakes model `ran_to_end`/`failed`; new `test_a_failed_in_app_rebuild_opens_no_terminal_though_the_run_went_on`; the old test renamed to `test_a_cancelled_in_app_rebuild_opens_no_terminal`. Mutation M20 killed. |
| P2-2 | **Owner decision.** Docs now say the guard covers only what Land commits (README, CHANGELOG). The outgoing check for a link a branch already contains is proposed as a follow-up spec. |
| P3-1 | Fixed: `./` prefix. `test_a_name_starting_with_a_colon_is_not_read_as_pathspec_magic`. M06 killed. |
| P3-2 | Fixed: rc 1 with an error counts as "cannot tell". `test_a_git_that_cannot_run_counts_as_ignored`. M05 killed. |
| P3-3 | Fixed: a skipped command is not counted in the total, and the failed line names Lab Hub not rebuilt. `test_a_skipped_lab_hub_is_not_counted_and_is_named_after_another_failure`. M16, M19 killed. |
| P3-4 | Fixed: `test_cancel_right_after_a_failed_rebuild_starts_nothing_more`. |
| P3-5 | Fixed: `run_updates` and `refuse` docstrings. |
| P3-6 | Fixed: `dialog.failed` and `dialog.ran_to_end` read directly. |
| P3-7 | Fixed: the result names the links ("1 link to a folder ignored (venv)"). |
| P3-8 | Documented in the README (a wanted folder link is committed by hand). |
