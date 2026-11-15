# Spec: Check repos can clean up what is safe and list the rest for review

Status: **Define/Architect approved 2026-11-15 ("Approve as recommended"); Build, Review and Secure done, fixes applied.** Owner: Lab Hub session, 2026-11-15.
Nothing built. In-flight check (`session_start.py --inflight`, 2026-11-14): no spec covers Check repos.
Owner's choice so far (2026-11-15): "Safe cleanup", then "Cleanup + review list". Merging branches into main is out of scope (it would bypass review and QA).

## 1. Problem and evidence
Check repos (`ui/apps_tab.py:838`, report from `git_autosync/scripts/hygiene.py`) says what has not landed but offers no way to act on it. The owner asked for a button.
Measured on 2026-11-15 from `git_autosync/hygiene.json` (generated 19:52 UTC), 11 repos flagged:
- 42 local branches not merged into the default branch. Only **4** have all their changes already in main (checked with `git merge-tree --write-tree <main> <branch>` giving main's own tree). The other 38 hold real unlanded work; 24 of them are in syndustryx.
- 45 linked worktrees, 31 of them clean.
- Sync: sentinel has diverged (1 unpushed, 1 behind) with 1 uncommitted file; foundry is 3 behind with 5 uncommitted files. Neither is safe to sync automatically today.
So safe cleanup alone clears little; most of the backlog needs a decision per branch.

## 2. User and success measure
The owner, on the launchpad. Success:
1. **Clean up** on a fixture lab (temp repos built by the tests) removes exactly the landed branches, the clean worktrees on those branches, fast-forwards a clean repo that is only behind, and pushes a repo that is only ahead; it leaves every other case untouched. One test per guard in section 5.
2. **Review branches** lists every unlanded branch with repo, commits ahead, last commit date and subject, and its worktree; each row's actions behave as in section 4, tested on fixtures.
3. On the real lab, after Clean up, the 4 landed branches are gone and Check repos re-runs on its own and shows the new state (screenshot).
4. Every branch deleted is written to a log with its tip SHA, so it can be restored with `git branch <name> <sha>`.

## 3. Scope
- Two buttons in the Check repos dialog: **Clean up…** and **Review branches…**.
- A new module `lab_hub/repo_tidy.py`: read-only planning, and an apply step that re-checks each action just before running it.
- Tests with real temporary git repos (no mocks of git).

## 4. Design
**Clean up…** opens a preview: one checkbox row per action, grouped by repo, all ticked, each saying in plain words what happens ("Delete branch `claude/x`: its changes are already in main", "Remove worktree `.claude/worktrees/y`: no uncommitted changes, its branch is landed", "Pull 2 commits (fast-forward)", "Push 1 commit"). A second, unticked-by-default group lists what is skipped and why ("diverged", "uncommitted files", "a process is running in it"). Buttons: **Apply** (default off if nothing is ticked), **Cancel**. Apply runs in the background with a log like Update apps, then re-runs Check repos.

**Review branches…** opens a table of unlanded branches (repo, branch, commits ahead of main, last commit date, subject, worktree path or "none"). Row actions:
- **Open in Terminal**: the worktree if it has one, else the repo, via the existing `launcher.open_terminal`. Changes nothing.
- **Delete branch…**: a confirmation naming the branch and its N commits (subjects of up to 5), stating they leave main's history and can be restored from the log. Disabled while the branch is checked out in any worktree.
- **Remove worktree…**: only enabled when the worktree is clean and nothing runs in it; the branch stays.
No merge action.

## 5. Architecture and safety rules
- Lives in Lab Hub (`lab_hub/repo_tidy.py`), not git_autosync: Lab Hub already runs git (`dirty_checkout`), and git_autosync's hygiene report stays read-only. **Decision for the owner (A1)**: confirm this, or move the write side into git_autosync (`scripts/tidy.py`) and have Lab Hub call it, at the cost of a change in a second repo.
- Plan reads only. Apply re-checks every guard right before each command; a changed repo is skipped and reported, never forced.
- **Landed branch**: local branch, not the default branch, not checked out in any worktree, and `git merge-tree --write-tree main branch` returns main's tree. Deleted with `git branch -D` only after that check passes again at apply time.
- **Worktree removal**: linked worktree only (never the main checkout), not locked, no uncommitted or untracked files, no rebase/merge/cherry-pick/bisect in progress, no ignored files except regenerable ones (`.venv`, `node_modules`, `__pycache__`, caches, `build`, `dist`): `git worktree remove` deletes ignored files without asking (review P1). No process may have its current directory inside it (`lsof -d cwd`, a fresh snapshot per removal); if `lsof` fails, nothing is removed.
- **Pull**: default branch checked out and tracking `origin/<default>`, no uncommitted tracked changes (untracked files are allowed: `--ff-only` aborts rather than overwrite one), behind > 0, ahead = 0: `git pull --ff-only origin <default>`.
- **Push**: default branch tracking `origin/<default>`, no uncommitted tracked changes, ahead > 0, behind = 0 after a fresh `git fetch`: `git push origin refs/heads/<default>`. Never `--force`, never a non-default branch, never a remote branch deleted.
- Remote branches are never touched.
- Every action and its result goes to `~/Library/Application Support/Lab Hub/repo-tidy.log` (mode 0600, one line per entry). A branch delete writes its log line first and stops if it cannot; it keeps a backup ref `refs/lab-hub-tidy/<sha>` so gc never prunes the commits; and it deletes with `git update-ref -d refs/heads/<b> <planned sha>`, so a branch that moved is not deleted.
- git runs with a cleaned environment (no inherited `GIT_*`, `DYLD_*`, `PYTHON*`, `QT_*`) and every credential prompt off (`GIT_TERMINAL_PROMPT=0`, `GCM_INTERACTIVE=never`, `ssh -oBatchMode=yes`); `worktree list` is parsed with `-z`.
- Git runs off the UI thread (a worker thread running git as child processes), with timeouts; Clean up cannot be closed while it applies.
- Concurrent agent sessions share these repos: the re-check at apply time plus the `lsof` guard are what keep a running session safe.

## 6. Non-goals
Merging branches, opening or merging PRs, committing uncommitted files, stashes, rebasing diverged branches, deleting remote branches.

## 7. Risks
- A branch deleted by mistake from Review branches: confirmation names its commits; the log keeps the SHA, and the backup ref keeps the commits until the owner deletes it (`git update-ref -d refs/lab-hub-tidy/<sha>`). The branch's own reflog does not survive `branch -D`/`update-ref -d`.
- `lsof` misses a session that has no process inside the worktree at that moment (an idle Claude session keeps no shell there): `git worktree remove` still refuses dirty or untracked work, so the loss is the checkout, not its work. Owner decision **A2**: also skip any worktree under `.claude/worktrees/` touched in the last 24 hours? Recommended yes.
- Push publishes commits: only the default branch, only when already strictly ahead, only after the owner ticks it in the preview.

## 8. Phases to run
Define, Design, Architect (this file; **GATE**: it changes git state across repos), Plan, Build, Review (`code-reviewer`), Verify (`qa-engineer`, mutation check), Secure (`security-engineer`: destructive file and git writes, subprocess input from branch names), Document (README, TODO). Comply skipped: no new data, network or legal surface beyond `git push` to the owner's own remotes. Release: rebuilding Lab Hub stays with the owner.
Estimate: Build 45–90 min agent time, plus Review/Verify/Secure 15–25 min.
