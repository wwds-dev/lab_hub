# Spec: one-click Land on each tile; retire Check repos, Resolve and Review as separate steps

Status: **Define approved by the owner 2026-11-16 ("approve as recommended").** Phase: Define (`product-manager`), 2026-11-16. Supersedes `docs/specs/tile-resolve.md` (approved earlier the same day) if approved; that spec would then be closed unbuilt.
Nothing built. In-flight check (`session_start.py --inflight`, 2026-11-16): `repo-tidy` (document done, not released) owns the code this reuses; its Resolve engine (`lab_hub/repo_tidy.py`, `claude_resolve`) is kept, only its front end changes.

## 1. Problem and evidence
Owner, 2026-11-16: "check repos doesnt land anything ... resolve etc just makes it complicated and useless", and "overhaul the whole concept".
- A tile shows a yellow badge ("2 unpushed commits · 1 commit behind · 2 branches to land") and has no action.
- **Check repos** (`ui/apps_tab.py:628`) re-runs the report and opens a text dump; it changes nothing.
- Landing needs three more steps: Check repos, then **Resolve…** in that dialog, then a checkbox preview of 28 actions for all 21 repos, then Apply. Screenshot 2026-11-16: the run for SONAR stopped with "tests don't pass on master itself" (an `ImportError` for `macro` in SONAR's own tests): a real SONAR fault, buried in a progress box.
- Nine of 21 repos are flagged today (sonar, lab_hub, sentinel, imprint, backstage, autopilot, foundry, syndustryx, shopfront), most of them app tiles.

## 2. User and success measure
The owner, on the Apps page, who wants work landed, not reported.
1. A tile with something to land shows one primary button, **Land**, beside Launch. No such tile needs another click on another page first.
2. **Land** shows one confirmation in plain words ("sonar: commit 2 files, merge 3 branches into master, push. Land?") with a Details expander for the full action list. One Yes starts it. No checkbox wall.
3. It runs the existing safe actions for that repo only (commit open tracked changes, merge branches into the default branch with Claude Code resolving conflicts and the tests deciding, fast-forward or pull, push, delete landed branches and their clean worktrees) with progress on the tile itself.
4. The result is stated on the tile, never buried: **Landed**, or **Not landed: <the reason in one line>** ("SONAR's tests fail on master: cannot import `macro`") with **Open in Terminal** next to it. Test on fixture repos for: success, failing tests on the default branch, a conflict Claude cannot resolve, a diverged repo.
5. A page-level **Land all (N)** replaces **Check repos**: same confirmation with one line per repo, runs repo by repo, continues past a failure, ends with one summary.
6. **Check repos** and the report dialog are removed. The badges update on their own after Refresh and after every Land (the hygiene check runs in the background; no button).
7. **Review branches** survives only as a link on a tile that still has unlanded branches after a Land ("2 branches need your decision"), opening the existing review table for that repo.

## 3. Scope
- `ui/apps_tab.py`: `AppCard` Land button, in-tile progress and result; page-level Land all; Check repos and `show_repo_report` removed; background hygiene refresh.
- `ui/repo_tidy_dialogs.py`: `CleanupDialog` replaced by the one-line confirm plus Details; `ReviewDialog` kept, opened per repo.
- `lab_hub/repo_tidy.py`: plan and apply are unchanged except the failure reason must be a single plain sentence per repo.
- Tests with real temporary git repos; README and TODO/CHANGELOG.

## 4. Non-goals
- No new git operations and no loosening of the `repo-tidy` §5 guards: a repo that changed since the plan is skipped and reported, never forced.
- No push without the one confirmation. No force-push, no history rewrite, no deleting an unlanded branch without it being named in the confirmation.
- No fix for the SONAR test failure itself; Land reports it.

## 5. Decisions for the owner
1. **Concept.** Recommend: one **Land** per tile plus **Land all**; Check repos and the Resolve dialog go. Alternative: keep Check repos as a status-only button.
2. **Confirmation.** Recommend one confirmation per Land (it pushes and merges). Alternative: none, which is faster but pushes unseen.
3. **Failures.** Recommend Land never stops the whole run at one broken repo: it says why on that tile and moves on.
4. **Review branches** as the per-tile "need your decision" link only. Alternative: remove it and let Land handle every branch.

## 6. Risks
- Land all runs Claude Code on conflicts and tests per repo: slow (minutes). It must be stoppable (keep the existing Stop) and visible per tile.
- Dropping the checkbox preview removes per-action opt-out; Details keeps the list visible, and the tests decide what merges.
- Pushing is outward-facing: the confirmation names the remote branch for every push.

## 7. Phases to run
Define (this file, **GATE**), Architect (module boundary; no state or concurrency change expected, but a background hygiene run and a per-tile worker must not touch the same repo twice: stop at a gate if it does), Plan, Build, Review, Verify, Document. Secure: required, because it pushes and runs a model-driven merge (reuse `repo-tidy`'s reviewed surface; Review/Secure must confirm nothing new is reachable). Comply skipped: tier `public`, no new claims.

## 8. Build, Review and Secure notes (2026-11-16)
Built in `lab_hub/land.py` (plan, sentence, run, result, per-repo claim), `ui/lander.py` (worker thread, signals), `ui/apps_tab.py` (tile Land, outcome, Land all, Stop landing, quiet repo recheck), `ui/repo_tidy_dialogs.py` (Resolve window removed; Review kept), `ui/theme.py` (the amber Land button). `lab_hub/repo_tidy.py` and `claude_resolve.py` are unchanged.
Architect: no gate needed. The per-repo claim in `land.py` is the guard for the case the spec named (a background run and a tile worker on the same repo); one `Lander` runs one job at a time per page and the claim covers two pages. No new persistent state.
Review (`docs/audit/land-from-tiles-review.md`, code-reviewer, independent): 0 P0, 4 P1, all fixed: the wrong error line from pytest's summary (`plain_reason`); no Open in Terminal beside Not landed (now on the tile); the tile found by live report name (now the card held from the click); no stop on quit (`Lander.shutdown`, wired to `aboutToQuit`). P2 fixed: queued re-check after Land, sentence names every push, a raising confirmation no longer leaves "Looking…", the outcome clears on Refresh, tests that survived a broken implementation rewritten.
Secure (`docs/audit/land-from-tiles-security.md`, security-engineer, independent): 0 P0, 0 P1. P2 fixed: git, pytest and Claude output now shows as plain text (labels, message boxes, escaped tooltips); the confirmation names the total Claude cost and the test command and Details names the repo path. Not changed, by the spec's own decision 2: one confirmation instead of the old per-action ticks and a separate Claude dialog, so there is no "land without Claude" choice (Cancel keeps everything as it was). Not changed: a crafted `hygiene.json` can still name any absolute git path, as before this change.

## 9. Scope addition: tests in the temporary worktree need the nested repos (draft, awaiting the owner's gate)
Source: the owner's pasted note from another chat (2026-11-16), "Fresh-worktree test runs", measured there with `git worktree add --detach` and the repo's own `.venv`; the owner chose option 1 for Sonar. Not in the 2026-11-16 Define approval, which listed "no fix for the SONAR test failure itself" as a non-goal; this section reverses that non-goal, so it needs its own approval.
Evidence (from that note, not re-run here):
- **SONAR** fails Land's test-the-default-branch step with `ImportError: cannot import name 'macro'`: `sonar/macro` and `sonar/playmaker` are gitignored nested repos, absent from a fresh worktree, and `sonar/core.py:29` imports both at start-up.
- **Sentinel**: 7 collection errors; `agents/bug_spray` is a git submodule and `git worktree add` leaves it empty.
- **Backstage**: passes in a fresh worktree. **Imprint**: its full run (13-17 min) had not finished in that note.
Change (`lab_hub/claude_resolve.py` `_link_env`, called from `_tests` and so used by Land's conflict path): in the temporary worktree, before the tests run and only for them (unlinked straight after, as the `.venv` link is today):
1. If the repo has submodules, run `git submodule update --init --recursive` in the worktree (no hooks, bounded timeout); if it cannot (no network), link the main checkout's submodule folders instead and say so in the outcome.
2. Link the main checkout's gitignored nested repos (an ignored directory that contains its own `.git`, found with `git ls-files --others --ignored --exclude-standard --directory`) at the same relative path. A path that already exists in the merge is refused, as `_link_env` does now.
Same guards as today: nothing linked is a tracked path; the git-state fingerprint (`_git_state`) still must not change; the link is removed after the run. Stated limitation, from the note: the tests then run against whatever the main checkout's nested repos hold, not a pinned commit.
Success measures: (a) a fixture repo with a gitignored nested repo passes tests that import it, and fails with a plain reason when the nested repo is missing from the main checkout too; (b) a fixture with a submodule gets it initialised or linked; (c) a tracked path of the same name is refused; (d) links are gone after the run, also after a failure; (e) on the real lab, Land on SONAR no longer stops with `ImportError: cannot import name 'macro'` (screenshot of the tile), and Sentinel's tests collect.
Phases: Define (this section, GATE), Build, Review, Secure again (it changes what the test run can reach: required), Verify, Document.
Peer note (2026-11-16, session "Fix test setups in imprint, backstage, sentinel, sonar", relayed, not an approval): imprint's full suite takes about 35 minutes. Land's test step has a fixed timeout (`TEST_TIMEOUT`, `lab_hub/claude_resolve.py`); a repo slower than that stops with a timeout reason, not a failure. Decision for the owner with §9: leave the timeout (Land on imprint then reports "the tests ran longer than N minutes"), or allow a longer per-repo limit read from the repo's `app-context.md`. Recommend leaving it and saying so on the tile; imprint's conflict path is rare.
