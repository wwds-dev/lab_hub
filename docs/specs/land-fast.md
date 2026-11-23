# Spec: Land takes minutes, and says why anything stays open

Needs: define, architect, plan, build, review, verify, secure, docs, comply

Status: **Define approved by the owner 2026-11-17 ("Approve as recommended"): §5 decisions take the recommended option.** Built, reviewed, secured and verified 2026-11-17; not committed (§10).
In-flight check (`session_start.py --inflight`, 2026-11-17): `land-resolve-all` (document done) owns "Land leaves nothing open" (prep, triage, archive) and `progress-windows` (document done) owns the Land window and `durations.json`. Neither covers how long a Claude merge takes or the stops below. This spec changes `claude_resolve.resolve` and adds two stop kinds to `land-resolve-all` §4.7; it changes neither spec's other behaviour. No other spec matches.

## 1. Problem and evidence
Owner, via the session that started this one: Land all "runs for hours" and "still doesn't land everything".

Measured 2026-11-17 from `~/Library/Application Support/Lab Hub/repo-tidy.log` (Land's only log; `ui/lander.py:105` passes no `log=`) and by timing the planning code read-only. `durations.json` does not exist yet: the installed app was built at 14:44, before the progress-windows merge.

| Part of a Land | Measured |
|---|---|
| Planning all 14 repos (`land_resolve.prep`, `repo_tidy.plan_repo`, `unlanded`) | 9.3 s in total, at most 1.7 s per repo |
| Prep steps (gitleaks scan, commit untracked files) | about 1 s per worktree |
| Plain merge, push, branch delete | up to 3 s each |
| **Claude merge** (`claude_resolve.resolve`) | **4.2 to 11.2 min each**; Claude itself often costs only $0.02 to $0.12 |

The time goes into test suites. A Claude merge runs the repo's whole suite two or three times: on the default branch "first" (`claude_resolve.py:1047`), on the merge, and again after a fix round. Three wastes follow.

1. **The same commit is tested twice.** The default branch's result is cached only when it passes (`_BASE_PASSED`, `claude_resolve.py:960`). Each landed merge moves the default branch to the commit that was just tested, so the next branch tests it again. Seen live: syndustryx `3bb7538` passed its tests at 16:42:29 (quizzical-elion landed), and at 16:42:31 Land started the same suite on `3bb7538` as the base for the next branch. Today's syndustryx run chains 10 Claude merges, so the waste is 9 suite runs of about 4 min each.
2. **A failing default branch is re-tested for every branch.** From 15:03 to 15:15, syndustryx `main` at `3c19622` was tested three times, 234 to 235 s each, and failed each time in the same way ("Patch is already started"). The owner then pressed Stop. No branch can land onto a default branch whose own tests fail, so the 2nd and 3rd runs told nothing new.
3. **Conflicts that Claude Code is not allowed to edit.** Claude Code refuses to write under `.claude/` in the mode Land runs it in. Three syndustryx branches (bundle-backup-prune, clever-banach-ddaeba, objective-mayer-cdd76f) each paid for a base run and a Claude run, and then ended with "CANNOT RESOLVE: write permission to .claude/commands/ship-feature.md was denied". The conflicted file list showed this before any work started. Those branches then go to triage. There, even a "land" verdict ends in an archive tag, because `land._Run._land_one` does not retry a branch it has already tried at the same commit. So useful work is archived instead of landed.

Checked and ruled out (measured as negligible): the `ROUNDS = 3` loop (re-planning takes 0.2 to 1.2 s per repo, and `tried` keeps merges from running twice), `retry_busy`, the per-file gitleaks copies, and landing repos one after another (today every repo except syndustryx finished in under 2 minutes in total).

## 2. User and success measure
User: the owner, pressing Land or Land all on the Apps page.
1. **Fewer suite runs.** A chain of N Claude merges into one default branch runs the suite at most N + 1 times, plus one per fix round. Today it is 2N plus the fix rounds. Tested on a fixture repo with a counting test command and a fake Claude.
2. **Measured before and after.** Before: today's real Land all (wall time per repo from the log; see §7). After: the same fixture chain timed before and after the change, plus the owner's next real Land all timed with the Land window's `durations.json`. Both numbers go in this spec.
3. **A failing default branch costs one suite run per Land, not one per branch.** It ends as one stop per repo, naming the failing test line and the action: "fix `<default>`'s tests, then Land again". The branches waiting on it stay as branches. They are not sent to triage and not archived.
4. **Protected-file conflicts are handled before any test or Claude run** (owner decision §5.1).
5. **Nothing is left open without a reason.** Every item still open after Land all is in the result as a stop that a person must clear: the existing `land-resolve-all` §4.7 list plus the two new kinds in §3. Tested: a fixture lab with one of each ends with every item named in `LandResult.notes`.
6. Full suite green; new logic mutation-checked.

## 3. Behaviour
1. **Tested commits are remembered.** When a Claude merge passes its tests and lands as commit M, Land records M as passing for that repo and test command, exactly as a passing base run is recorded today. The next branch's base run is skipped while the default branch is still at M. The cache stays in memory only, as today: it lasts for the app session.
2. **Failing base runs are remembered, for one Land run.** A base run that fails or cannot run is recorded with its reason for that commit and test command. Every later Claude merge onto the same commit fails at once with that same reason and runs no tests. `land` turns this into one stop for the repo: "`<default>`'s own tests fail in a clean copy (`<error line>`): fix them, then Land again". `triage` skips branches whose only blocker is this stop. The memory is cleared when a new Land starts, so a fix made between two Lands is tested again.
3. **Protected-file conflicts** (Claude Code will not edit them, so Land must never send it one): before the base run, `resolve` checks the conflicted files against the protected list (`.claude/**`). What it does next is owner decision §5.1. Whichever option is chosen, no suite runs and Claude is not paid for an edit it cannot make.
4. The Land window and the tile line show the new stops in the same plain voice as the existing ones. Each stop starts with the action to take ("fix main's own tests, then Land again", "merge it by hand, then Land again"), so the 180-character tile line never cuts it off.
5. **A plain merge that an earlier merge turned into a conflict** is not counted as tried. The next round plans a Claude merge for it. Found in the live run: `claude/vigilant-clarke-86f3df` was skipped with "it now conflicts with main" and then archived without a Claude merge. This is part of the same problem, "it doesn't land everything", and is fixed here.

## 4. Non-goals
- Landing repos in parallel. Deferred: measured savings today are small next to §3.1–3.3, and it needs the Architect gate (concurrency) and an ADR. Measure again after this ships.
- Changing what "the tests pass" means, the merge or fix prompts, the budget, or the model.
- Testing plain (conflict-free) merges. They are untested today and stay that way. Raise it as its own change if wanted.
- Persisting the test cache across app restarts.

## 5. Decisions for the owner
1. **Conflicts in `.claude/` files.** Claude Code will not edit these files in an unattended run.
   - **A (recommended):** For Foundry-owned files (`.claude/commands/**`, `.claude/agents/**`), Land takes the default branch's copy without asking Claude. Foundry's `install.sh --update` overwrites these files anyway, and the next update restores the newest copy. Any other `.claude/` conflict, such as `settings.json` or hooks, is a stop: "conflict in `<file>`, which Land may not resolve: merge it by hand, then Land again".
   - **B:** Every `.claude/` conflict is a stop, and nothing is resolved automatically.
2. **Branches whose only blocker is a failing default branch.** **Recommended:** they stay as branches and are named under the one stop (§3.2). **Alternative:** send them to triage as today, where Claude may archive them.
3. **A "land" verdict on a branch whose merge failed only for a §3 reason.** **Recommended:** it stays as a branch under that stop and is not archived (see §1 item 3). **Alternative:** archive it as today.

## 6. Risks
- **Skipping a base run on a commit whose environment changed** (for example, `.venv` updated between two merges in one Land). The tree is identical and the window is minutes long. Accepted; the merge's own test run still guards every landing.
- **Option 5.1 A drops a branch's edit to a Foundry command file.** The edit is still in the branch's history and in the archive or landed merge's second parent. Foundry owns these files.
- **A flaky suite that fails the base run once** now blocks every branch in that repo for the rest of the run, not just one. Land again re-tests it (§3.2).

## 7. Before measurement (2026-11-17, live Land all in the installed app)
- First run: started 15:01. Every repo except syndustryx was done by 15:03:11, about 2 min for all of them together. syndustryx then spent 12 min on three failing base runs of the same commit (§1 item 2). The owner stopped the run at 15:15.
- Second run: started 15:29. syndustryx only: Claude merges of 4.2, 11.2, 4.2, 9.3, 8.4, 4.5, 8.1 and 9.3 min, with 3 more stopped by `.claude/` conflicts. At 16:46, 12 branches were still not in `main`, so about 9 more merges and the triage were still to come. The run will take about 2.5 h in total.
- One redundant base run, timed live: 16:42:31 to 16:46:30 (240 s), on `3bb7538`, which had passed the same suite at 16:42:29.
- **Expected saving for this run:** about 4 min for each Claude merge after the first (§3.1), 8 min of repeated failing base runs (§3.2), and about 4.5 min for each `.claude/` branch (§3.3). That is roughly 70–80 of the ~150 min. Measured after the build (§2.2).
- Items left open in repos already finished (read-only check, 16:44): `lab_hub` has uncommitted files. That is expected, because sessions are working in it, and Land reports it as a busy or dirty worktree. Everything else was clean. syndustryx gets its own entry here once the run ends.

Working notes: the side-session notes folder, `land-speed-diagnosis.md`.

## 9. Architecture (Architect, 2026-11-17)
No new thread, file, persisted state or module boundary, so there is no gate and no ADR. Both caches are module-level, in-memory structures in `claude_resolve`, the same kind as `_BASE_PASSED`. They are touched only from Land's one worker thread, as `_BASE_PASSED` is today.
- `claude_resolve._BASE_PASSED` also gets `(repo, M, test command)` right after a Claude merge fast-forwards the default branch to M (§3.1). The merge was tested in a clean worktree at exactly M's tree, with the same command and environment links as a base run.
- New `claude_resolve._BASE_FAILED: dict[(repo, tip, command), reason]`, written when a base run fails or cannot run. `resolve()` reads it before making a worktree. `land.land()` clears that repo's entries at the start (`forget_base_failures(repo)`), so each Land re-tests once (§3.2).
- New `claude_resolve.protected(name)` / `foundry_owned(name)`. `resolve()` checks the merge-tree conflict list before any worktree or test. A protected file that is not Foundry-owned ends the merge with the `PROTECTED_STOP` reason. In the temporary worktree, Foundry-owned conflicts take the default branch's copy (`git checkout <default tip> -- :(literal)<path>`, or `git rm` when the default branch deleted it) before Claude runs. Claude is skipped when nothing else conflicts. The merge commit is still tested before it lands (§5.1 A).
- `land._Run` records, for each failed merge, whether its message is a base-failure or protected-file reason (`claude_resolve.blocker_kind`). Those branches are not sent to triage. After the plan-and-apply rounds they become stops: one per repo for a failing default branch (listing the waiting branches), and one per branch for a protected file (§5.2, §5.3).
- Failure modes: a cache entry for a commit that is no longer the tip is never read. A Land started from a tile clears only its own repo's failures. If `git checkout`/`git rm` fails on a Foundry file, the merge fails with that reason and nothing lands.

## 10. Results (2026-11-17)
**Before and after, fixture** (`scratchpad/test_bench_land.py`, the same repo for both: 5 branches that conflict in code, 1 branch that conflicts in a Foundry command file, 1 in `.claude/settings.json`, and a 2 s test suite; old code from `HEAD`):

| | Test runs | Claude Code runs | Wall time | Left open |
|---|---|---|---|---|
| Before | 11 | 9 | 31.9 s | foundry, settings ("conflict markers are left in .claude/commands/ship.md") |
| After | 7 | 5 | 21.9 s | settings, as a stop: "…merge it by hand, then Land again (.claude/settings.json; …)" |

**Before, real** (live Land all of 2026-11-17, §7): the second run took 92 min (15:29:44 to 17:01:31), nearly all of it in syndustryx's 15 Claude merges. syndustryx's suite takes about 240 s, and each merge ran it at least twice. At the end, 7 branches were archived: 6 had a `.claude/commands/ship-feature.md` conflict and Claude's "land" verdict, and 1 (vigilant-clarke) never got a Claude merge (§3.5). With this change, the same run would skip about 14 redundant suite runs (about 56 min) and the 3 repeated failing base runs (12 min in the first run). The six Foundry-file branches would land, or stop with a reason, without paying for a test run and a Claude run first.
**After, real:** not measured. It needs this build installed and the next real Land all. The Land window's `durations.json` will record it.

**Left open after the live Land all (16:44 and 17:28, read-only):**
- `syndustryx`: branch `land/archived-2026-11-17`, made after the run (17:25) by another session that is re-landing the archived branches by hand. Also the worktree `policy-none-rootcause-686617` with an untracked `.claude/` folder; why Land left it is not verified.
- `lab_hub` and `foundry`: uncommitted files from sessions working in them now.
- `imprint-deps`: its checkout is on `fix/app-identity-ci`, 1 commit ahead of its origin. Not verified whether it is an app tile Land all covers.
- The tile-level `LandResult` reasons of that run were not saved anywhere. The installed build predates the Land window and `durations.json`.

**Review** (`code-reviewer`, `docs/audit/land-fast-code-review.md`) and **Secure** (`security-engineer`, `docs/audit/land-fast-security.md`): every P1, P2 and P3 in this change is fixed, with a test each. The exception is security P1, which is pre-existing and not fixed: it waits for an owner decision (§11).
**Verify:** 28 tests in `tests/test_land_fast.py`. Mutation check: 21 of 21 planted mutations killed. The `test_land.py` failure test now asserts the new approved wording (§3.2); its other checks are unchanged.

## 11. Open decision for the owner (from Secure, pre-existing)
Security P1: a branch can change `.claude/settings.json`, hooks or agent prompts **without a conflict**. A plain merge or a Claude merge lands that change unreviewed and pushes it. This change does not cause the gap and does not close it. **Recommended:** a follow-up spec in which Land compares the merge result with the default branch and stops on any changed `.claude/` path that is not a Foundry copy. **Trade-off:** Land's own prep commits agents' untracked `.claude/` files into their branches, so this stop would fire often until prep stops doing that.

## 8. Phases to run
Define (this, GATE: user-visible stops) → Architect: no new threads, state or module boundaries, so no gate expected; a short section in this spec → Plan → Build → Review → Verify (mutation check on both caches and the protected-file check) → Secure (yes: it changes how untrusted merge content is resolved, §5.1) → Document → Comply (tier public, no new data flow; short check) → Release (owner).
Skipped: Case (tier public), Design (no new UI; two new reason lines in existing windows), Launch (no public claim).
