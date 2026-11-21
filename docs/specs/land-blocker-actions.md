# Spec: a Resolve button for conflicts Land may not resolve (`.claude/` files)

Status: **Define, awaiting owner approval (GATE: user-visible).** Phase: Define (`product-manager`). Drafted 2026-11-21 in `lab_hub`.
In-flight check (`session_start.py --inflight`, 2026-11-21): no unreleased spec owns this. `land-resolve-all` and `land-from-tiles` (both document done) own the Land code this extends; `land-network-preflight` (build, another session, uncommitted edits in `land.py`) touches `land.py` too, so this builds after it is merged. `tile-resolve` is superseded.
Nothing built.

## 1. Problem and evidence
Owner, 2026-11-21: "'merge by hand' is a real blocker, since I don't know which prompt would resolve that."
The Land screen shows, for syndustryx: "no Claude run: a conflict in .claude/ that Land may not resolve: merge it by hand, then Land again (.claude/settings.json; Claude Code may not edit .claude/ files)".

Cause (measured, `git merge-tree` in syndustryx): branch `todo/ci-runner-2026-11-13` changes `.claude/settings.json` and so does `main`. Land is right not to let an unattended Claude edit it (`claude_resolve.protected`, `claude_resolve.py:995`): a branch could use that file to widen permissions or add hooks. Foundry's own `.claude/agents/` and `.claude/commands/` are already settled automatically (`FOUNDRY_OWNED`). That leaves the owner with a dead end: no button, no command, no prompt to give.

## 2. User and success measure
User: the owner, on the Land result (Apps page, Backup and Sync).
1. Every stop of this kind shows a **Resolve…** button on its row. Pressing it opens a dialog that lists each conflicted `.claude/` file with what `main` has and what the branch changes (screenshot, real syndustryx case).
2. The owner picks per file and presses Apply. Land then merges, tests and fast-forwards as for any Claude merge; the branch lands or ends in a normal "Not landed" with its own reason. Evidence: a fixture repo with a `.claude/settings.json` conflict ends "Landed" after one click; the real syndustryx branch lands or stops for a different reason.
3. Nothing is chosen without the owner. Claude Code still never edits a `.claude/` file; only the owner's choice does. Tested: with no choice recorded the stop is unchanged; a mutation that applies a default without a click fails the test.
4. The choice and the file names are written to the Land log ("owner chose: keep main's .claude/settings.json").
5. The text "merge it by hand" is gone from the stop; it names the button instead.

## 3. Behaviour
**Dialog.** One row per conflicted protected file, three choices, **Keep main's** preselected (the safe one):
- **Keep main's**: the branch's change to that file is dropped.
- **Take the branch's**: the file becomes the branch's copy.
- **Combine** (JSON files only, e.g. `settings.json`): a deterministic merge: arrays such as `permissions.allow/deny` and `hooks` are the union; a key both sides changed to different values is listed and the owner picks the side for that key. No Claude run.
The dialog shows the change under each choice as a diff, and marks lines that add a permission or a hook ("this widens what Claude Code may do").
**Apply.** Land's existing temporary-worktree merge (`claude_resolve.resolve`) takes the owner's choice for those files exactly as `_take_default` does for Foundry-owned ones, then continues with Claude for the remaining ordinary conflicts, then tests, then fast-forwards. The choice is bound to the branch SHA and default SHA shown; if either moved, the dialog says so and asks again.
**Other shapes** (rename into `.claude/`, delete-versus-edit, binary): the dialog offers Keep main's and Take the branch's only; Combine is off.

## 4. Scope
`claude_resolve.py` (accept owner choices for protected files), `land.py` / `land_resolve.py` (carry the choice, keep the stop's branch and SHA), `ui/` (the button and `ProtectedConflictDialog`), tests on fixture repos (no mocks of git), README, CHANGELOG, TODO.

## 5. Non-goals
No Claude edit of `.claude/` files, in any mode. No change to which files are protected, to the Foundry-owned rule, or to the "base tests fail" and "folder link" stops. No new git operations beyond what `resolve` already runs. No bulk "keep main's for everything" button in this change.

## 6. Decisions for the owner
1. **Per-file choice or one button.** Recommend per-file (Keep main's / Take the branch's / Combine). Alternative: one **Keep main's** button; simpler, but it silently drops a branch's settings change.
2. **Combine for JSON in this change.** Recommend yes, since `settings.json` is the case that is blocking. Alternative: ship Keep/Take now, Combine later.
3. **Where the button sits.** Recommend on the stop row in the Land result, and on the tile that shows the stop. Alternative: result row only.

## 7. Risks
- A `settings.json` merge can widen permissions. Mitigation: owner-only choice, Keep main's preselected, widening lines marked, the choice logged.
- The branch or default moves between preview and Apply: handled by the SHA check (§3).
- Builds on `land.py` while `land-network-preflight` is in flight: build waits for its merge.

## 8. Phases to run
Define (this file, **GATE**), Design (the dialog), Architect (small: where the choice is carried; ADR not expected), Plan, Build, Review, Verify, Secure (the choice writes a security-relevant file: required), Document. Comply skipped: tier `public`, no new claims.
