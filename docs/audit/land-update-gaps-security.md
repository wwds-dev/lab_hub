# Security review: land-update-gaps

Phase: Secure (8), read-only, 2026-11-17, by the `security-engineer` agent. Saved by the owning session from the agent's report.
Scope: the uncommitted diff (`git diff` plus the untracked `tests/test_land_update_gaps.py`) and spec `docs/specs/land-update-gaps.md`.

**Playbook:** `docs/playbooks/security-engineer.md` has `last-reviewed: 2026-11-11` and `status: current`, so it is not stale.
**App context:** the `## Security surface` section in app-context is still a placeholder. Scope here came from the spec, the diff and earlier audits (`land-resolve-all-security.md`, `self-update-security.md`).

## Threat model (for this change)
**Assets:**
- Secrets in the home folder (`~/.ssh`, `~/.aws`, `.env`).
- Main checkouts and their virtualenvs.
- The public GitHub repos that Land pushes to.
- The installed `/Applications/Lab Hub.app`.

**Trust boundaries:**
- Agent worktree contents are untrusted: names, symlinks and their targets, nested `.gitignore` files.
- The git dir's config and hooks are trusted at the same level as every other Land git call (accepted earlier as land-resolve-all P3-5).
- The other apps' `build_app.sh` scripts are trusted, but they can fail.
- Lab Hub's own bundle is trusted only after three checks: its build exits 0, `stage_build` re-checks it, and the helper self-tests the installed copy.

**Entry points touched:**
- `sort_untracked` → `folder_link` → `ignored_as_folder` (a git subprocess on a temporary mirror folder).
- `_apply_untracked` (adds to `.gitignore` and commits it).
- `Rebuild._failed_one` (the run continues after a failure).
- `update_ended` and `run_updates` (the restart decision).

## Findings
No P0, P1 or P2 findings. Three new P3s and one pre-existing P3.

### P3-1 (new): `check-ignore` reads the name as a pathspec, so a leading `:` is parsed as magic
- **Where:** `lab_hub/land_resolve.py:346-347`.
- **Scenario:**
  - `:(exclude)xx/` exits 128 ("pathspec magic not supported"), which counts as ignored (fail-closed).
  - `:/name` is read as top-level magic, so git checks a different path and the answer can be wrong.
- **Impact:** low. At worst a link to a file is committed, as today. A link to a folder is still caught by `is_dir()`.
- **Fix:** pass `"./" + rel + "/"`. Verified that this is matched literally. `--literal-pathspecs` is refused by check-ignore.

### P3-2 (new): "never committed" only holds for the state at the moment Land checks
- **Where:** `folder_link` (`land_resolve.py:309-322`) together with `_staged_differs`.
- **Scenario:** a link to a file, or a dangling link with no trailing `/`, is committed. Its target later becomes a folder, or is swapped between the sort and `git add`.
- **Impact:** a folder link on `main` after all. That breaks spec §2.1 as worded. Only the link text is committed, so this is an availability risk of the SONAR `.venv` kind, not a leak.
- **Fix (owner):**
  - A: reword §2.1 to "at the time Land checks".
  - B: also ignore in place any untracked symlink whose stored text is absolute or that resolves outside the worktree. This closes PE-1 too.

### P3-3 (new, informational): the mirror copy can follow a parent folder swapped for a symlink
- **Where:** `land_resolve.py:336-343`. The check only looks at the last path component.
- **Impact:** negligible. The copy goes into a 0700 temporary folder that is deleted afterwards, git runs with `-q`, and only a yes/no answer changes. The agent can already steer that answer through its own `.gitignore`. `rel` comes from `ls-files`, so there is no `..` and no absolute part, and `joinpath` cannot escape.
- **Fix (optional):** skip a `src` that does not resolve inside `worktree.resolve()`.

### PE-1 (pre-existing, P3, accepted earlier as land-resolve-all P3-3): a symlink to a file outside the repo is still committed
- Spec §3.1 keeps this on purpose.
- Only the link text is committed, not the target's bytes. `scan()` scans `os.readlink()`, and `hash-object --no-filters` stores the link text.
- The link text, for example `/Users/<user>/.ssh/id_ed25519`, reveals the username and folder layout in a public repo.
- In the main checkout, any tool that follows symlinks (packagers, `cp -R` without `-P`, agents) would read the real file. This path is latent, not demonstrated.
- Fix: P3-2 option B (owner decision).

## Assessed with no finding
- **Repo config cannot run code through check-ignore.** Verified on git 2.56.0: neither a `core.fsmonitor` script nor a `post-index-change` hook ran, and no marker file appeared. `--no-index` reads no index, runs no filters and no pager, and with `--git-dir` git does no discovery. It still reads `info/exclude` and `core.excludesFile`, the same trust as the other Land git calls.
- **Ignore-line injection:** the leading `/` disarms `!` and `#`. Glob characters and a trailing space are escaped. CR and LF are refused and the step is skipped. The `/name` line without a trailing `/` matches the link (tested end to end).
- **TOCTOU between preview and apply:** the apply step re-sorts, commits only `preview ∩ now`, and checks the staged blob and mode. A test covers a file that becomes a folder link. The remaining window is P3-2.
- **Check order:** `folder_link` runs before `secret_by_name`, so a folder link named `.env` is ignored in place rather than quarantined. Nothing is committed either way. `is_dir()` only calls `stat`, so a FIFO target cannot block Land.
- **`git add -- .gitignore` stages unscanned tracked edits.** This is pre-existing (quarantine and nested repos already reach it). The outgoing `gitleaks git` scan before every push mitigates it.
- **Update now continuing:**
  - The builds are independent, and Lab Hub's own build is last.
  - Its hold check runs `checkout_blocker` again (on `main`, clean).
  - Shared caches are guarded by the self-tests and the helper's rollback.
  - Terminal installers still do not open after any failure.
- **The restart cannot be fooled:**
  - `_restart_built` is set only when `command_finished(ok=True)` fires for exactly `view.restarts`.
  - `apps_tab` needs `ran_to_end`, the command not skipped and not in `failed`.
  - `stage_build` checks that the bundle path has no symlinks, the checkout is clean and on `main`, and the stamp's commit is HEAD.
  - The window's label is only a label; if it disagreed with the `apps_tab` gate, nothing would be installed (fail-safe).

## Dependencies
No manifest changed. `pip-audit` is not installed, so the OSV querybatch API was queried for the 43 packages in `.venv`: 0 advisories. Nested venvs were not checked.

## Tests run
`tests/test_land_update_gaps.py`: 11 passed. The full suite was not run by this agent.

## Non-security note
`ui/apps_tab.py:814`: the `run_updates` docstring still says a failed run "stops rather than going on".

**Verdict: PASS. No P0, P1 or P2 issue. P3-1 has a one-line fix. P3-2 and PE-1 are an owner decision.**

## Resolution (owning session, 2026-11-17)
| Finding | Status |
|---|---|
| P3-1 | Fixed (`./` prefix), tested, and mutation M06 killed. |
| P3-2 | **Owner decision** (option A: reword; option B: also ignore absolute or outside-the-worktree links). §2.1 stays as worded until the owner decides. |
| P3-3 | Fixed: `src.resolve().is_relative_to(worktree.resolve())`. `test_a_gitignore_reached_through_a_swapped_folder_is_not_read`. M08 killed. |
| PE-1 | **Owner decision**, together with P3-2 option B. |
| Non-security note (stale docstring) | Fixed. |
