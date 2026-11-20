# Code review: self-update amendment 1 (snapshot build)

- **Reviewer:** code-reviewer agent (read-only, not the author). Its report was returned to the
  orchestrator, which saved it here; the "Fix" lines were added after the fixes.
- **Date:** 2026-11-20
- **Diff:** `git diff c29f0d2..ae2d84e -- lab_hub/self_update.py ui/apps_tab.py tests/test_self_update.py`
- **Against:** spec `docs/specs/self-update.md` §11–§12, ADR 0006, AGENTS.md.
- **Playbook:** `docs/playbooks/code-reviewer.md`, last reviewed 2026-10-14 (current).

## Evidence run by the reviewer
- `pytest -q tests/test_self_update.py`: 88 passed (full suite not run by the reviewer).
- Real `build_command` under `/bin/zsh -c` and `/bin/bash -c`, with `UPDATE_DIR` under
  `.../Application Support/Lab Hub/update` and the project under `it's a lab/lab_hub`: exit 0 in both;
  built at the recorded SHA with `.venv` active; `planned_commit` round-trips.
- Clone from a detached, dirty source and from a linked-worktree path: both work. The shared repo
  has no `objects/info/alternates`.
- With a global `core.hooksPath` or `init.templateDir` holding a `reference-transaction` hook,
  `git clone` ran it 13 times (P3-1). The owner's global config sets neither today.
- `build_app.sh` works in a clone: every `--add-data` input is tracked; `.venv/bin/activate`
  hardcodes `VIRTUAL_ENV`, so the linked `.venv` works; no `.pth` points at the shared checkout;
  `stamp_version.py` resolves to the snapshot.
- No caller outside tests still uses `checkout_blocker`, `head_commit`, `stage_build(project)` or
  `built_bundle(project)`.

## Findings

### P2-1: a build ahead of `main` was called "behind", and Update now would downgrade it
`lab_hub/self_update.py` (the branch after `commit.startswith(installed)`). Installed from
`claude/feature`, one commit ahead of `main`: the row read "behind", `runs_in_app` True, "Update
now builds <main>", so Update now would install an older build. Also a gap in spec §11.2.4.
**Fix:** when the installed commit is not an ancestor of `main`, no command is offered. Ahead of
`main`: verdict `current`, note "built from <sha>, ahead of main. Update now leaves Lab Hub alone:
... it would replace it with an older build." Diverged: held with the same reason. Tests
`test_a_build_ahead_of_main_is_not_offered_a_downgrade`, `test_a_build_beside_main_is_held_not_replaced`;
spec §11.2.4 amended. Wording is the engineer's default; the owner may change it.

### P3-1: `git clone` still ran global and template hooks
**Fix:** `git -c core.hooksPath=/dev/null clone --template= ...`; test
`test_no_global_or_template_hook_runs_while_the_snapshot_is_made` (global hooksPath and templateDir
with three hooks; no hook runs, no `.git/hooks` in the snapshot).

### P3-2: tests never ran the command through zsh or in a path with spaces
**Fix:** `_build` now runs `/bin/zsh -c` by default;
`test_the_build_runs_in_paths_with_spaces_and_quotes[zsh|bash]` uses
`Application Support/it's Lab Hub/update` and a project path containing `$(touch pwned)`.

### P3-3: a timeout removing the snapshot after staging was reported as "not installed"
**Fix:** the cleanup is best effort (`OSError`/`SubprocessError` ignored).

### P3-4: `update/` was created 0755, not 0700 as §12.2 said
**Fix:** the command runs `/bin/chmod 700` on `update/` and `update/snapshot/`; asserted in the
spaces test.

### P3-5: an installed build with no commit in its stamp gave a "behind" row with no reason
**Fix:** held with "the installed build does not record its commit; build and install it once by
hand with ./build_app.sh --install"; test updated.

### P3-6: housekeeping
- Spec §12.1 named a `SNAPSHOT_DIR` constant the code does not have. **Fixed** in the spec.
- `.venv` shows as untracked in the snapshot (the `.venv/` ignore pattern does not match a symlink).
  Harmless while `stamp_version.py` records no dirty flag. **Not fixed**; noted in §13.
- No test that a refusal leaves the snapshot. **Fixed** (stamp-mismatch test asserts it).
- The `refuse(project)` stub parameter name. **Fixed.**

## Checked and fine (reviewer)
Verdict logic for level-with-main, other branch and held notes; `planned_commit` exact
rebuild-and-compare; `stage_build` checks (symlink, executable, snapshot HEAD, stamp prefix, cleanup
only on success); a recorded SHA no longer on any ref still checks out from a local clone; the hold
only checks the checkout exists.

## Notes (not defects)
- **Bootstrap:** the copy installed now still runs the old checkout-based Update now, so installing
  this version through it may hit the old blocker once. Install it by hand, or at a quiet moment.

## Verdict
No P0 or P1. P2-1 and P3-1..P3-5 fixed (see `docs/audit/self-update-qa.md`, "Verify of amendment 1",
for the mutation check of each fix). OK for Verify.
