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

## 9. Amendment 2026-11-15: Resolve commits open work
Owner: "check repos button should also offer a button to resolve in the app. commit, etc whatever is open and safe to resolve"; approved the plan below with "Yes, build it".
- **Clean up…** is renamed **Resolve…**.
- New action **Commit**: in a repo's main checkout, and in a linked worktree that passes the worktree guards (not in use, not a recent agent worktree, `lsof` working), commit *tracked* changes only (`git add -u`, message `Lab Hub: commit open work, <date>`). Skipped: a detached HEAD, a merge/rebase/cherry-pick/bisect in progress, unresolved conflicts. Untracked files are never added; they are listed as left for the owner, because `lab_hub` and others are public repos and a non-ignored secret would be published by the push.
- When the main checkout is committed on its default branch tracking `origin/<default>` and is otherwise level or only ahead, a **Push** follows in the same preview; it still re-checks (fresh fetch, clean, not behind) before running. Behind plus local changes is left alone (it would diverge).
- Commits run the repo's own hooks; a hook that refuses stops that commit.

## 10. Amendment 2026-11-16: Resolve merges what merges cleanly
Owner, after Resolve left 42 unlanded branches: "this is getting exhausting … add a button to check repos that resolves all issues"; chose "Commit, add merging". Dry run before: 14 of 42 merged without conflicts, 28 conflicted.
- New action **Merge**: an unlanded branch is merged into the default branch (`git merge --no-ff`, message `Lab Hub: merge <branch>`, the exact commit seen in the preview) when it merges with no conflicts (`git merge-tree`), the main checkout is on the default branch with no uncommitted tracked changes (or a commit of them runs first), no merge/rebase/conflict in progress, and the default branch is not behind origin. A failed merge is aborted.
- Skipped, with the reason shown: a branch whose worktree has uncommitted or untracked files, a paused operation, a process inside, or agent use in the last 24 hours (work in progress); a branch committed in the same run (the next Resolve merges it); a branch that conflicts (left for a person: Review branches → Open in Terminal).
- After a merge, the branch's worktree (if removable) and the branch are deleted, and the default branch is pushed (same push re-checks as before).
- This puts agent work into main without review; that is the owner's explicit choice for this tool.

## 11. Amendment 2026-11-16: Resolve lands conflicting branches with Claude
Status: **Define/Architect approved 2026-11-16 ("Approve as recommended": A3 sonnet, A4 $3, A5 yes); Build, Review and Secure done, fixes applied (§11.10); A6 accepted as is 2026-11-16 ("Accept A6 as is").** Spec owner: this session (side session of the Lab Hub session).
Owner's choice (relayed by the Lab Hub session): the app resolves conflicts itself by running Claude Code with no window, accepting the token cost and that agent work lands in the default branch without review, with tests as the safety check. No Terminal, no manual steps.
Evidence: a read-only dry run on 2026-11-16 left 12 branches that conflict with their default branch (Sonar 6, Provisio 3, Imprint 2, Sentinel, Autopilot, Backstage, Shopfront, Foundry master 3; numbers overlap repos). §10 skips each one as "land it by hand".

### 11.1 What the owner sees
- In the Resolve preview, a branch that §10 would skip only because it conflicts becomes a row **"Resolve conflicts with Claude: `<branch>` into `<default>` — N commits, conflicts in K files; tests: `<command>`"**. The test command shown is the one Lab Hub will run itself (§11.4). A conflicting branch with no test command found stays a skip: "conflicts, and no test command found in docs/foundry/app-context.md".
- These rows are ticked like the others. Apply asks once more when any of them are ticked: "N branches will be sent to Claude Code (model M, at most $B each, $N×B in total). Code from these repos goes to Anthropic as in any Claude Code session. Merged results land in `<default>` and are pushed without review once the tests pass." Buttons: **Resolve with Claude**, **Apply without them**, **Cancel**.
- While a branch runs, the log shows one line per step (worktree made, merge started, Claude's tool calls as one short line each: "edited src/x.py", files left with conflicts, tests running, test result, landed or why not) and, at the end, Claude's turns and cost as the CLI reports them (`num_turns`, `total_cost_usd` in the `result` event). A **Stop** button ends the running Claude or test process (its whole process group), discards that branch's temporary worktree and skips the rest. The window still cannot be closed mid-apply.
- After a branch lands, its worktree (if §5's removal guards pass) and the branch are deleted, and the default branch is pushed, exactly as after a §10 merge.

### 11.2 Guards (plan, and re-checked right before each branch)
The §10 merge guards, unchanged:
- Target: the main checkout is on the default branch, has no uncommitted tracked changes, no paused operation or conflicts, and is not behind origin.
- Source: the branch's worktree is clean, has no paused operation, has no process inside (`lsof`, fresh snapshot), and has not been used by an agent in the last 24 hours. The branch was not committed to in this run.
- The branch tip is the one seen in the preview.
Added:
- The branch still conflicts. If it now merges cleanly, the plain §10 merge path runs instead: no Claude.
- `claude` is found (`~/.local/bin/claude`, then PATH) and `claude --version` runs. If not, every Claude row is a skip: "Claude Code not found".
- At most one Claude run at a time across all repos.

### 11.3 How one branch is resolved (Apply)
1. **Temporary worktree.** `git worktree add --detach <tmp> <default tip>`, where `<tmp>` is `~/Library/Application Support/Lab Hub/resolve/<repo>-<random>`: outside the repo and outside `.claude/worktrees/`, so no other rule or session treats it as theirs. Lab Hub records the default tip D and the branch tip B.
2. **Lab Hub starts the merge, not Claude:** `git merge --no-ff --no-commit B` in `<tmp>`, giving the list of conflicted files.
3. **Claude resolves only the conflicts.** Runs in `<tmp>` with no window:
   `claude -p <prompt> --output-format stream-json --verbose --restricted --safe-mode --strict-mcp-config --tools Read,Edit,Write,Glob,Grep --permission-mode acceptEdits --permission-prompts none --no-session-persistence --model <M> --max-budget-usd <B>`.
   - It gets no Bash, no web access and no MCP servers.
   - `--restricted` confines its file tools to `<tmp>` and refuses writes to git files.
   - `--safe-mode` skips the repo's CLAUDE.md, hooks, plugins and skills, so nothing in the branch can add instructions or run code.
   - The environment is `_env()`, without `ANTHROPIC_*` overrides other than the owner's login.
   - The prompt names the branch, the default branch and the conflicted files. It says to keep both sides' intent and to remove every conflict marker. If a conflict cannot be resolved safely, Claude ends with a line `CANNOT RESOLVE: <reason>`.
   - Time limit: 20 minutes, after which the process group is killed.
4. **Lab Hub checks the result itself.** It requires all of the following:
   - Claude exited with 0 and did not end with `CANNOT RESOLVE`.
   - No file has conflict markers (`git diff --check` and a scan of the formerly conflicted files for `<<<<<<<`, `=======`, `>>>>>>>` lines).
   - Nothing outside the worktree changed.
   - No file was changed beyond the conflicted ones, unless the change is needed to make the tests pass (see step 5). Those extra files are listed in the log.

   Lab Hub then stages with `git add -u` plus the conflicted paths (never untracked files Claude created outside them) and commits `Lab Hub: merge <branch> (conflicts resolved by Claude Code)`. The commit has parents D and B.
5. **Tests, run by Lab Hub, not by Claude** (§11.4), in `<tmp>`, with the repo's regenerable environment linked in (`.venv`, `venv`, `node_modules` symlinked from the main checkout if present, because a fresh worktree has none). The environment is `_env()` plus `QT_QPA_PLATFORM=offscreen` and `CI=1`. Time limit: 30 minutes per command. If they fail, Claude gets one more run with the failing output (same flags, budget counted against the same cap) and the tests run again. Still failing: Lab Hub runs the same command once on D. If D fails too, the reason says "`<default>` already fails these tests" so the owner knows the branch is not to blame.
6. **Land.** All of these must hold:
   - The merge commit M has D and B as ancestors (`merge-base --is-ancestor`).
   - The default branch still points at D, and the branch still at B.
   - The main checkout guard (§11.2) still holds.

   Then `git merge --ff-only M` in the main checkout. The §10 follow-ons (remove worktree, delete branch, push) run with their own re-checks.
7. **Always:** `git worktree remove --force <tmp>` (our own folder only, checked by path prefix) and `git worktree prune`. Every step goes to `repo-tidy.log`: Claude's final message (flattened), cost, turns, test command and exit code, and the landed SHA.

   Any failure leaves the branch, its worktree and the default branch exactly as they were.

### 11.4 Test command
- From the repo's `docs/foundry/app-context.md`, the `Run tests` line under `## Commands`: every backticked span on that line that is not a placeholder (`<cmd>`), runs from the repo root, and parses with `shlex` into an optional `VAR=value` prefix and a program plus its arguments. All of them must pass.
- A span with shell syntax (`| ; & $ \` > <` or a `cd`) is not run. The row then says which span was rejected.
- Without a usable line, a default, picked in order:
  - `.venv/bin/python -m pytest -q` if there is a `tests/` folder and a `.venv`;
  - `python3 -m pytest -q` if there is a `pytest.ini`, a `[tool.pytest` section or a `conftest.py`;
  - `python3 -m unittest discover -s tests` if there is a `tests/` folder;
  - `npm test` if `package.json` has a `test` script and `node_modules` exists.
- Otherwise there is no test command and the branch is not landed.
- The command and where it came from ("app-context" or "default") are shown in the preview row, so the owner sees before Apply what will decide each landing.

### 11.5 Security notes (Secure phase required)
- **Agent permissions.** The headless agent has write access, limited to its temporary worktree and file tools. Lab Hub, not the agent, runs every git command and the tests. Only Lab Hub's own checks decide whether anything lands.
- **Untrusted content.** Branch content (agent-written) is input to Claude. Prompt injection inside the branch can at worst write bad code into the merge. The tests and the "only conflicted files plus test fixes" check limit this. The owner has accepted that what passes lands unreviewed.
- **Tests run repo code**, as they already do whenever an agent works in these repos. No network rule is added.
- **Pushing.** Never a force-push. Push only via the existing push action and its fresh-fetch re-check.
- **Concurrency.** Branch names reach git only after `--`, or as `refs/heads/<b>` that `check-ref-format` has validated.

### 11.6 Owner decisions
- **A3 Model:** `sonnet`, recommended (conflict resolution is routine coding; cheaper), or `opus`.
- **A4 Cap per branch:** `--max-budget-usd 3`, recommended. A branch that hits the cap is not landed.
- **A5 Extra files:** may Claude change files other than the conflicted ones in its test-fix round? Recommended: yes, listed in the log.

### 11.7 Non-goals
Branches that are in progress (§11.2 source guard), rebasing, force-pushing, PRs, resolving conflicts in a repo whose checkout is not on its default branch (SYNDUSTRYX stays held back), and repos with no test command.

### 11.8 Success measure and tests
Tests use real temporary git repos with a stub `claude` script on PATH that edits files as told by an env var and prints stream-json:
1. **Success:** stub resolves the conflict, tests pass → the default branch is fast-forwarded to a merge of D and B, the branch and its worktree are deleted, the push runs, the log has the cost line.
2. **Tests fail** twice → nothing changes, reason shown; plus the "default already fails" variant.
3. **CLI error**, a non-zero exit or `CANNOT RESOLVE` → nothing changes, Claude's reason shown.
4. **Branch moved** after the preview → skipped before Claude runs; the default branch moved during the run → not landed.
5. **Busy worktree** (process inside, or recent agent use) → skip.
6. **Markers left**, or a file outside the conflict set changed in the first round → not landed.
7. **Stop** mid-run kills the stub, removes `<tmp>`, nothing changes.
8. Test command parsing: app-context line, placeholder, shell syntax rejected, each default.

On top of the tests:
- A mutation check on the guards in §11.2, §11.3 step 4 and step 6.
- The full suite green.
- A read-only dry run on the real lab listing each Claude row with its test command, and each skip with its reason.

### 11.9 Phases
Define and Architect (this section; **GATE**: it runs a write-capable agent and changes git state across repos), Plan, Build, Review (`code-reviewer`), Verify (`qa-engineer`, mutation check), **Secure** (`security-engineer`), Document (README, TODO, CHANGELOG).

Comply is skipped. There is no new personal data. Repo code goes to Anthropic under the owner's existing Claude Code use; say if you want that reviewed. Design is folded into §11.1 (one row type, one confirmation, the existing log). Release and the rebuild stay with the owner.

Estimate: Build 60–90 min agent time; Review, Verify and Secure 20–30 min; dry run 5 min.

### 11.10 Build notes after Review and Secure (2026-11-16)
The review findings (`docs/audit/resolve-with-claude-code-review.md`, `docs/audit/resolve-with-claude-security.md`) changed or narrowed parts of §11.3–11.5:

**Conflict markers.** Lab Hub does not run `git diff --check` and does not scan for `=======` (a Markdown underline). A conflicted file fails if it has more `<<<<<<< `, `>>>>>>> ` or `|||||||` lines than either side had already. A file that cannot be read counts as failed. File names are read with `-z`, so non-ASCII names are checked too (review P0).

**"Nothing else changed".** Every untracked file is compared before and after each Claude run, ignored ones included (security P1-1). Lab Hub also checks that the temporary worktree's `.git` file is unchanged. Every git call there names `--git-dir` and `--work-tree` explicitly, with hooks off (`core.hooksPath=/dev/null`, `--no-verify`), so a rewritten `.git` cannot redirect a commit (review P1-1).

**Environment links.** `.venv`, `venv` and `node_modules` are linked in only while tests run, never during a Claude run. If one already exists in the merge, the branch fails. A `.venv/…` program runs from the main checkout's own environment.

**The tests:**
- They run with an allowlisted environment: no SSH agent, tokens or API keys.
- If the shared git `config`, `hooks` or `info` change during a test run, the branch is not landed.
- Everything the tests started is killed when they end.
- A test program that cannot run (missing, timed out) is reported as such and not sent to Claude.

**Test-command parsing** also rejects:
- full-path shells and other banned programs (`sh`, `env`, `git`, `rm`, …);
- absolute paths and `..`;
- `VAR=` prefixes for `PATH`, `DYLD_*`, `LD_*`, `PYTHON*`, `NODE_*` and `GIT_*`.

**The fix round (A5)** may change source files, but not tests, test folders or test configuration (`conftest.py`, `pytest.ini`, `pyproject.toml`, `setup.cfg`, `tox.ini`, `package.json`, the test program itself). A change to any of these fails the branch (review P2-1).

**Sign-in.** Claude Code runs without the `ANTHROPIC_*` and `CLAUDE*` variables of whatever session started Lab Hub, so it must be signed in once (`claude auth login`). If it is not, the preview says so once.

**Stop** skips everything after the running step. A branch already landed stays landed, and its push waits for the next Resolve.

**Open for the owner (security P1-2, residual):** the tests still run the branch's code as you, with network access and write access to your home folder. The allowlisted environment, the git-state fingerprint and the process-group kill narrow this, but do not confine it. Confining it fully means running the tests under `sandbox-exec` (no network except loopback, no writes outside the temporary worktree and `$TMPDIR`), which may break test suites that write elsewhere. **Decision A6 (owner, 2026-11-16, "Accept A6 as is"):** accepted as is; no sandbox. This residual risk stays open and is the owner's accepted risk.

## 12. Amendment 2026-11-16: Resolve wastes nothing on branches it cannot land

Status: **approved by the owner 2026-11-16 ("Build fixes 1–4")**, after the first real run (11 conflicting branches, 1 landed, about $3.90). Of the 10 that stopped, 9 stopped because the tests could not run in the temporary copy, not because of the merge.

1. **Work folder without spaces.** Temporary worktrees go under `~/Library/Caches/LabHub/resolve` (the per-user temp folder if that path holds whitespace), not `Application Support`. Tests that build paths from URLs (provisio) broke on the space.
2. **Tests on the default branch first.** Before Claude runs, the test command runs on the default branch's tip in the temporary worktree. Anything but a pass stops the branch at no Claude cost, with the reason: "the tests don't pass on main itself in a temporary copy: …" (missing pytest, `python` not found, an ignored nested repo such as `sonar/macro` missing). The copy is then reset (`reset --hard`, `clean -ffdx`) before the merge. Since the default branch now passes by construction, the later "already fails on main" re-run is dropped.
3. **Claude may delete a conflicted file** that one side already deleted (a modify/delete conflict). It cannot delete files itself, so it names them in its reply, one `DELETE: <path>` line each; Lab Hub removes only files that are in the conflict list and missing from one of the two tips, with `git rm`, and fails the branch on any other name. Merge round only; the fix round still may not delete or add.
4. **Say what is open, and why.**
   - The tile counts things, not problem kinds: "6 branches · 2 worktrees to land" instead of "2 to land" (from git_autosync's problem lines; anything unrecognised still counts as one item).
   - Review branches gets a "Last Resolve" column: the reason the last Resolve gave for that branch, shown only while the branch is still at the commit it tried. Its header text no longer says Lab Hub merges nothing.
   - Check repos says in one line what Resolve does and that Review branches shows why the rest is open; the Resolve tooltip mentions merging.

Tests: work root has no whitespace; a branch whose default branch fails or cannot run its tests stops with no Claude call (stub counts calls); the copy is clean before the merge; `DELETE:` removes a modify/delete file and lands, refuses a file both sides kept, a file outside the conflict and a path with `..`; badge texts for every problem line git_autosync writes; the log parser returns the last reason only for the matching commit; the Review dialog shows it. Phases: Define (this), Build, Review, Verify (mutation check), Document. Secure is light: `DELETE:` is new untrusted input from Claude and is checked against the conflict list.

### 12.5 Build notes after Review (2026-11-16)

- **A main-branch pass is reused** for the next branch into the same tip and test command, within one Lab Hub run.
- **`DELETE:`:**
  - The path is literal (`:(literal)`), and repeated lines count once.
  - The prompt allows a deletion only when the other side's changes to the file are already elsewhere or no longer matter, and asks Claude to say why.
  - Reviewer P2-3: such a deletion can drop the other side's edits to that file. They stay in history through the merge's second parent.
  - **Open for the owner (A7):** keep this, or refuse every deletion. Refusing makes fix 3 inert, since git reports a modify/delete conflict only when the keeping side changed the file.
- **Badge:**
  - A diverged repo shows both counts ("2 unpushed commits · 1 commit behind").
  - Lines it does not recognise are summed ("2 items").
- Review: `docs/audit/resolve-wasteless-code-review.md` (0 P0/P1; P2s fixed or mitigated). 19 mutations caught.
