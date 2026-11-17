# Spec: Land and Update now gaps found in the 17 Nov Land all

Status: **Define approved by the owner 2026-11-17 ("Approve as recommended"): §5 takes the recommended options.** Built, reviewed, verified, secured and documented 2026-11-17; not committed. Open for the owner: §10. Owner: this session (`land-update-gaps`).
In-flight check (`session_start.py --inflight`, 2026-11-17): `land-fast` (document done, on `main` as `2c5c465`) already covers items 1 and 2 of the task below, see §1. `land-resolve-all` owns the untracked-file step; this spec changes one rule in it (§3.1). `self-update` (on `main` as `5e5a19f`; its worktree is clean) owns Update now's self-update; this spec changes only what happens after a failed rebuild (§3.2). No other in-flight spec, branch or worktree touches these files.

## 1. What is already fixed (no build here)
The installed Lab Hub (v2.175, `baa2f52`) predates `land-fast`. The 17 Nov run used the old code. On `main` now:
1. **`.claude/` conflicts.** Before any test or Claude run, Land checks the conflicted files. In a Foundry app, a conflict in `.claude/commands/**` or `.claude/agents/**` takes the default branch's copy, without Claude (`claude_resolve.foundry_owned`, owner decision land-fast §5.1 A). Any other `.claude/` conflict, such as `settings.json` or hooks, is a stop: "merge it by hand, then Land again". Tested in `tests/test_land_fast.py:154` (`test_a_foundry_file_conflict_takes_mains_copy_without_claude`), which is exactly the syndustryx case: `ship-feature.md` conflicts and the branch lands.
2. **Base suite once per base commit.** `_BASE_PASSED` remembers a passing (repo, tip, command) for the app session, including each commit a Claude merge just landed. `_BASE_FAILED` remembers a failing one for the rest of the Land, so a failing `main` costs one suite run per Land, and its branches stay as branches under one stop. It is tested (land-fast §2.1, §10: 11 → 7 test runs on the fixture).

**Why Claude Code can't simply be granted `.claude/`:** Land runs `claude --restricted --permission-prompts none` (`claude_resolve.py:152`). The installed CLI (2.1.304, `claude --help`) says restricted mode "lets only a person or the configured permission handler approve writes to settings, git and tool-configuration files". An allow rule in `--settings` doesn't count. Granting it would need either dropping `--restricted` (which loses the shell and settings lockdown) or a `--permission-prompt-tool` MCP server that approves those writes. Both weaken the sandbox, so neither is proposed.

**One gap is left (decision §5.1):** taking `main`'s copy drops the branch's side of a Foundry file. On 17 Nov you merged the six branches by hand and kept the incoming "0e. Work in flight" step. Under the rule above that step would have been lost until the next `install.sh --update` on `main` restored it.

## 2. User and success measure
User: the owner, running Land / Land all and Check builds → Update now.
1. **No directory symlink is ever committed by Land.** Tested with the SONAR case: a worktree whose `.gitignore` has only `.venv/` and an untracked `.venv` symlink to a folder. After Land's untracked step, `git ls-files .venv` is empty, the symlink is still in place, and the result names it.
2. **One failing rebuild doesn't stop the others.** Tested with three commands, the first failing: commands 2 and 3 run, Lab Hub's own build (last) runs, and the window ends with "1 of 3 rebuilds failed" naming it.
3. **Lab Hub still restarts into its new build when only another app failed** (and does not when its own build failed). Tested.
4. "1 commit further on" (singular) in both places. Tested.
5. Full suite green; new logic mutation-checked.

## 3. Behaviour
1. **Untracked symlinks** (`land_resolve.sort_untracked`). An untracked path that is a symlink is never committed when either:
   - its target, followed, is a directory (or a broken link whose stored text ends in `/`); or
   - the repo's ignore rules would ignore that name if it were a directory (`git check-ignore --no-index` on `<name>/`). This is the `.venv/` case.

   Such a link is handled as in decision §5.2. A symlink to a regular file that no rule ignores is committed as today.
2. **Update now keeps going** (`ui/rebuild.Rebuild`). A command that exits non-zero or cannot start is marked failed in its row, with one line in the output ("[SONAR's rebuild exited with code 1 — going on with the next]"), and the next command starts. Cancel still stops everything. Lab Hub's own build still waits for Land as today (self-update §5.2).
   - End line: "Done" when all passed. Otherwise "N of M rebuilds failed: <apps>. See the live output." (bad tone, output opened).
   - If Lab Hub's own build passed, it still restarts into the new build, and the end line says so. If Lab Hub's build failed, it doesn't restart, as today.
   - `apps_tab` summary: "Rebuilt and reinstalled K apps; N failed (<apps>)." Terminal installers (`by_hand`) still open only when nothing failed, as today.
3. **Wording:** `launcher/state.py:1267` and `ui/apps_tab.py:295` say "1 commit" for one.

## 4. Non-goals
- Changing what Land does with symlinks that are already tracked.
- Changing the order of rebuilds, or running them in parallel.
- Re-landing branches that the 17 Nov run archived (they were merged by hand).
- Persisting the base-test cache across app restarts (land-fast §4).

## 5. Decisions for the owner
1. **Foundry-file conflicts** (the gap in §1).
   - **A (recommended): keep land-fast's rule; build nothing.** Foundry owns these files, `install.sh --update` restores the newest copy, and the branch's edit stays in its history. It costs nothing more.
   - **B: Claude merges a staged copy.** Land copies each conflicted Foundry file to a path outside `.claude/` in the temporary worktree, Claude resolves it with the other conflicts, and Land copies the result back before the tests. This keeps both sides, as your hand merge did. The cost is about 1–1.5 h more build, and Security must review it, since a branch's prompt text then reaches `.claude/` through Claude's merge. The same text can already reach `.claude/` today through a plain merge (land-fast §11).
2. **A directory symlink in the untracked step** (extended by §10.2 B to links that are absolute or leave the repo).
   - **A (recommended): ignore it in place.** Land adds an exact line (`/.venv`, without a trailing `/`, so it matches the link) to the branch's `.gitignore`, commits that, and leaves the link alone. The agent's worktree keeps its venv, and nothing is left open.
   - **B: move it to quarantine.** This moves the link (not its target) out of the worktree, which breaks the worktree's venv until it is re-linked.
3. **Lab Hub's restart after another app failed.** **Recommended:** restart into the new Lab Hub build, because it was built and tested. **Alternative:** don't restart when anything failed.

## 6. Risks
- A `.gitignore` line added by §5.2 A lands on `main` with the branch. `/.venv` is harmless there, because `main` already ignores the real folder.
- `git check-ignore --no-index` on a name with a trailing `/` must behave as a directory match. This is verified in a test before it's relied on.
- Going on after a failure means a later app may build on a broken shared tool. The builds are independent `cd … && ./build_app.sh` commands (`rebuild.py:12`), so this is accepted.

## 9. Architecture (Architect, 2026-11-17)
No new thread, persisted state or module boundary, so no gate and no ADR.
- `land_resolve.folder_link(worktree, rel)` is called by `sort_untracked` before the size and secret checks. It returns True for a symlink that resolves to a folder, a link whose stored text ends in `/`, a link that cannot be read, or one `ignored_as_folder` says yes to. git refuses `check-ignore` on a path behind a symlink ("beyond a symbolic link", checked on git 2.x), so `ignored_as_folder` copies the `.gitignore` files along the path (regular files only, as git reads them) into an empty temporary folder and runs `git --git-dir=<worktree's git dir> --work-tree=<copy> check-ignore --no-index -q -- <rel>/`. `info/exclude` and `core.excludesFile` still apply through the git dir. Any answer but "not ignored" counts as ignored.
- `Sorted.links` and `Step.links` carry them. `_apply_untracked` adds `ignore_line(rel)` (no trailing `/`) for each and commits only `.gitignore`. The apply step re-sorts, so a file that became a link after the preview is not committed either.
- `ui/rebuild.Rebuild` gets `failed: list[str]` and `ran_to_end`. `succeeded` now means `ran_to_end and not failed`. A non-zero exit or FailedToStart calls `_failed_one`, which starts the next command on the next event-loop turn. Cancel and a raising hold check still end the run as before.
- `BuildCheckWindow` tracks `_restart_built` (Lab Hub's own command finished ok) and `name_for(command)`. `update_ended(how, failed, total)` names the failed apps and keeps the restart when Lab Hub's build passed.
- `apps_tab.run_updates` uses `ran_to_end` for the early return and `failed` for the summary. Terminal installers open only when nothing failed.

## 7. Phases to run
Define (this, GATE: user-visible behaviour) → Architect: no new thread, state or module boundary, so a short section here and no gate → Plan → Build → Review → Verify (mutation check) → Secure (yes: untracked file handling and what gets committed) → Document (README, CHANGELOG) → Comply: tier public with no new data flow, so a short check → Release (owner).
Skipped: Case (tier public), Design (no new UI; changed text lines in the existing window), Launch (no public claim).

## 8. Note for the owner
`docs/foundry/app-context.md` still has 8 unfilled placeholders (lines 7–45: summary, stack, commands, docs, state, security surfaces, test rules, never-do list). Foundry warns about this before Build. Nothing here depends on them.

## 10. Open decisions for the owner (from Review and Secure)
1. **A link that an agent already committed on its branch** (review P2-2). Land's guard covers only files Land commits. A branch that already contains a `.venv` link still replaces main's venv when it lands. **Recommended:** a follow-up spec: an outgoing check that stops a branch adding a symlink where the target checkout has a real folder or a name ignored as a folder.
2. ~~**Links whose target changes after Land checks, and links pointing outside the repo**~~ (security P3-2, PE-1). **Decided by the owner 2026-11-17 ("Build option B"), built:** `never_commit_link` (renamed from `folder_link`) also holds back any untracked symlink whose text is absolute or that resolves outside the worktree, and any link that cannot be resolved (a loop). Relative links to files inside the repo are committed as before. Tests: `test_a_link_that_is_absolute_or_leaves_the_repo_is_never_committed` (4 cases), `test_an_absolute_link_into_the_repo_still_counts`, `test_a_link_loop_is_never_committed`, and the end-to-end `test_a_link_to_a_secret_outside_the_repo_is_ignored_and_never_pushed`. Mutations B1–B3 killed.
