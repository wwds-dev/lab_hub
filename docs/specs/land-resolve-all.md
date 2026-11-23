# Spec: Land leaves nothing open

Needs: define, architect, plan, build, review, verify, secure, docs

Status: **Define approved by the owner 2026-11-17 ("Approve, use defaults"): §6 decisions take the recommended option.** Phase: Define (`product-manager`). Drafted 2026-11-17 in `lab_hub`.
In-flight check (`session_start.py --inflight`, 2026-11-17): `land-from-tiles` and `land-already-applied` (both document done, not released) own the Land code this extends; both are on `main` (`9e92d1e`, `924a29b`). This spec changes their behaviour only where §4 says, and builds on `main` after them. `tile-resolve` is superseded. No other spec matches.

## 1. Problem and evidence
The owner pressed **Land all (7)** on 2026-11-17. Result: "Landed 2 of 6 repos", plus 25 branches marked "needs your decision". Owner's words: "this is not acceptable result. all open items always have to be resolved".

The failures, measured the same day with `land.make_plan(..., claude=None)` and `git status`:

| Repo | Left open | Cause |
|---|---|---|
| sentinel | 1 untracked file | `docs/foundry/model_use.jsonl` in the main checkout. Land never adds untracked files (`repo_tidy.py:530`, rule from `repo-tidy` §7). |
| autopilot | 1 untracked file | `docs/company/activity.jsonl` in agent worktree `adoring-jemison-e9cfc4`. |
| syndustryx | 31 untracked files in 7 worktrees; 24 branches | Untracked: audit `.diff` files, restore-drill notes, and in 4 worktrees the Foundry `.claude/agents`, `commands`, `settings.json` set. Branches: the main checkout is on `claude/bundle-backup-prune`, not `main`, so all 23 merges are refused ("the checkout is on … not main"). One worktree has a detached HEAD with 2 changed files. |
| backstage | 25 untracked files; 1 branch | The main checkout is on `claude/ui-shell-redesign`, not `main`. |
| shopfront/website | "not a git checkout" | `shopfront/website` is a symlink in git (mode `120000`, target `../../websites/shopfront_website`). The repo has `core.symlinks=false`, so the checkout wrote a 32-byte text file instead. Land looks for `website/.git` and stops (`land.py:187`). The real repo is clean and level with origin. |

## 2. User and success measure
User: the owner, on the Apps page and Backup and Sync.
1. On the real lab, **Land all** ends with every tile showing "Landed" or "Nothing to land". There is no "needs your decision" tail and no "add them yourself". Evidence: a screenshot of the Apps page plus the Land log.
2. A tile shows "Not landed" only for a hard stop from the list in §4.7. That message names the one action the owner must take.
3. No file is lost. Every untracked file ends up committed, or moved to the quarantine folder and listed in the log. Every removed branch can be restored from a local tag. Tested on a fixture lab.
4. No secret is pushed. A fixture file holding a fake AWS key and a `.env` file both end in quarantine, never in a commit. Tested; mutation-checked.
5. The Land dialog's preview shows every new action before Apply, as today: commit untracked, quarantine, switch the checkout to main, rescue a detached HEAD, archive a branch.

## 3. Owner decisions taken (2026-11-17, in chat)
- Untracked files: **"Scan, commit, quarantine"**. Secret-scan each file, commit clean files, and move flagged files out of the repo, adding them to `.gitignore`.
- Branches needing a decision: **"Yes, Claude Code decides"**. Claude Code lands the branches that are still useful and removes stale ones, logged with their SHA so they can be restored.

## 4. Behaviour
Land runs these steps per repo, in this order, before today's commit, merge and push steps. Each step re-checks its own guard.

### 4.1 Find the repo behind a link
If an app's repo path is a regular file that git records as a symlink (mode `120000`), Land follows the target written in it, relative to its folder. Land then lands that repo. Land also repairs the checkout once: it runs `git -c core.symlinks=true checkout -- <path>`, but only if the file's text equals the blob in git, so nothing local is overwritten.

### 4.2 Untracked files (main checkout and every linked worktree)
For each worktree, take the files from `git ls-files --others --exclude-standard`:
- **Quarantine without a scan:** names that are secrets by convention (`.env*` except `.env.example`, `*.pem`, `*.key`, `*.p12`, `id_rsa*`, `*credentials*`, `*.keychain*`), and any file over 10 MB.
- **Scan everything else** with gitleaks (`gitleaks dir --no-banner --report-format json` on a temporary copy holding only those files). A file with any finding goes to quarantine.
- **Quarantine** means: move the file to `~/Documents/lab/.quarantine/<repo>/<date>/<path in repo>` (mode 0700), add that exact path to the repo's `.gitignore`, and write a log line naming the file and the rule or gitleaks rule ID. The finding's secret is never logged.
- **Commit** the clean files and the `.gitignore` change: `git add -- <each path>` (never `-A`), message `Lab Hub: add untracked files, <date>`.
- If gitleaks is not installed or fails, nothing is committed in that repo. This is a hard stop (§4.7).

### 4.3 Main checkout on a feature branch
If the main checkout is not on the default branch:
1. Commit open work there (4.2, then today's tracked commit).
2. If that branch has no worktree of its own, add it to the branches to land.
3. Switch the checkout to the default branch (`git switch <default>`).

Guards: no merge, rebase, cherry-pick or bisect in progress, and no process with its cwd inside the checkout (`lsof`, as for worktree removal). A failed guard is a hard stop.

### 4.4 Detached HEAD with changes
Create `lab-hub/rescue-<date>-<short sha>` at HEAD, switch to it, commit, then treat it as a branch to land.

### 4.5 Agent worktrees in recent use
Committing never deletes anything, so the 24-hour "recent agent use" skip in `repo-tidy` §5 no longer applies to 4.2 and the tracked commit. It still applies to worktree removal. A process inside the worktree still blocks a commit. Land tries that repo again at the end of the same run. If the process is still there, Land reports a hard stop naming the process.

### 4.6 Branches that are still not landed
After today's merges, every branch in `repo_tidy.unlanded` goes to Claude Code (`claude_resolve.MODEL`, today `sonnet`). Claude gets the branch's commit subjects, `git diff --stat` and diff against the default branch (capped at 200 KB), its age, and whether its work already appears in the default branch. Claude must answer with one verdict:
- **land**: today's merge path, including Claude conflict resolution and the test-fix pass. If that still fails, the branch is archived (below) with reason "could not be landed: <one line>".
- **archive**: the work is stale, superseded or abandoned. Create the local tag `archive/<branch>/<date>` at the branch tip, delete the branch, and remove its worktree under today's guards. The tag is never pushed: these repos are public and the work was never published. The Land log and Review branches list each archive, with a **Restore** action that recreates the branch from the tag.

A worktree that cannot be removed (process inside) stays, but its branch is still archived. The worktree is detached at the tag and reported once. Cost uses today's per-branch cap. The triage prompt is small, about $0.05–0.20 per branch, so ~$2–5 for the 25 branches today. The dialog states the total before Apply, as it does today.

### 4.7 Hard stops (the only "Not landed" reasons left)
- gitleaks missing or failing
- Claude Code missing or not signed in, when 4.6 needs it
- a paused git operation (merge, rebase, cherry-pick or bisect)
- a process inside a checkout that 4.3 must switch, or a worktree that 4.5 must commit in
- push rejected by origin
- an app path that is neither a git checkout nor a link to one

Each stop names the repo and the single action that clears it.

## 5. Non-goals
- No push of archive tags, quarantined files or rescue branches that were not landed.
- No change to how branches are merged and tested, or to the Claude merge and fix prompts.
- No deletion of untracked files. Quarantine moves them; nothing is erased.
- No automatic upgrade of gitleaks or Claude Code.

## 6. Open decisions for the owner
1. **Quarantine folder.** Recommend `~/Documents/lab/.quarantine/` (outside every repo, in the lab backup set). Alternative: `~/Library/Application Support/Lab Hub/quarantine/` (not backed up with the lab).
2. **Archived branches.** Recommend local tags `archive/<branch>/<date>`, never pushed. Alternative: keep them as branches renamed `archive/…`, which still show up in branch lists.
3. **Land all with a hard stop.** Recommend: finish every other repo, then report the stops in one dialog. Alternative: stop the whole run at the first one.

## 7. Risks
- **Publishing a secret gitleaks misses.** It is a pattern scanner. Mitigation: the name rules, the size rule, and 4.2's preview list of every file to be committed before Apply. Residual risk: accepted by the owner's choice in §3.
- **Committing into a live agent session's worktree** (4.5). That session sees a cleaner `git status` than expected. Its own next commit still works, and nothing is lost.
- **Switching a main checkout** (4.3) under an editor that holds open files. `lsof` catches shells, not every editor. Git refuses to switch over uncommitted changes, and 4.3 commits first.
- **Claude archiving a branch the owner wanted.** The local tag keeps every commit. Restore is one click, and the log names the reason.

## 9. Architecture (Architect, 2026-11-17)
See ADR `docs/adr/0001-land-quarantine-and-archive-tags.md`.

**Modules.**
- `lab_hub/land_resolve.py` (new) owns the link lookup (4.1), the untracked scan and quarantine (4.2), switching the checkout (4.3), detached rescue (4.4), triage (4.6) and archive and restore. It calls git only through `repo_tidy.git` and writes the Land log through `repo_tidy._log`.
- `lab_hub/land.py` orchestrates. `LandPlan` gains `prep` (planned prep steps), `stops` (hard stops found while planning) and `triage` (how many branches will go to Claude).
- `repo_tidy.plan_repo` and `check` take `land_mode`. When it is on: no untracked skip (prep handles them), commits are allowed in recent agent worktrees, and merges ignore the recent and in-use rules. It is off for bulk Resolve.
- `claude_resolve.claude_argv` and `run_claude` take an optional `tools`, so triage runs read-only.

**State and concurrency.** One repo at a time under `land.claim` (unchanged). Every step re-reads git right before it acts, as before. Quarantine moves use `os.rename` within one volume, and copy then unlink across volumes. The log line is always written before the move.

**Boundaries.**
- gitleaks reads only a temporary copy.
- Claude reads only a temporary folder holding the diff, never the repo.
- No push of tags. Push stays the existing default-branch push.

**Preview.** The confirmation lists every prep step by name, the round-1 actions as today, and one sentence on triage with its cost cap.

## 8. Phases to run
Define (this file, **GATE**), then:
- Architect (new module `lab_hub/land_resolve.py` or extending `repo_tidy`; an ADR for the quarantine and archive-tag model)
- Plan
- Build (tests on fixture repos, no git mocks; gitleaks runs for real in tests, skipped with a reason if it is missing)
- Review
- Verify (mutation check on the scan, quarantine and archive guards)
- **Secure: required** (new file writes and moves, pushes to public repos, untrusted file content sent to a scanner and to Claude)
- Document (README, CHANGELOG)

Comply is skipped: tier `public`, no new public claims, no new data leaves the machine beyond today's Claude Code use.
Radar check: gitleaks flags and version at Architect.
