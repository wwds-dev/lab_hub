# Review: land-blocker-actions

Reviewer: `code-reviewer` (independent of the Build session). Read-only. Diff `d93c96d..4e384d3` on `claude/land-blocker-actions-f4b91c`. Playbook `docs/playbooks/code-reviewer.md`: `last-reviewed: 2026-10-14`, `status: current` (38 days old, not stale). `app-context.md` Commands, Invariants and Test bar are still template placeholders, so there was no app-specific invariant to check against.

Saved by the orchestrator from the reviewer's reply (the reviewer is read-only). Fix status is in `## Fixes` at the end.

## Evidence run
- `QT_QPA_PLATFORM=offscreen …/python -m pytest -p no:cacheprovider tests/test_land_blocker_actions.py tests/test_land_confirm.py tests/test_land_network_preflight.py tests/test_handoff.py`: 145 passed.
- The full suite, `test_land.py`, `test_land_fast.py` and the mutation checks were **not run** (another run was in progress; mutation belongs to Verify).
- Probes (scratch tests and a pty script, no repo edits):
  - An interactive `/bin/zsh -i -f` that gets SIGTERM is still alive 3 s later.
  - A process whose folder is in a nested repo (`lab/website`, its own `git init`) is listed by `processes_in` for the main checkout, and `close_processes` sends it SIGTERM.
  - `plain_reason` on a 185-character `for_land` settling reason returns `…, or press Ask C…`.
- Old-text grep: no production caller matches the old action strings any more. The old wording is left only in test inputs (`tests/test_land_confirm.py:95,143,207,280,308,335`, `tests/test_land_ui.py:734-736`, `tests/test_handoff.py:397,407`), which now go through the "no known action" path. That is harmless, but those tests no longer use realistic text.

## Findings

### P1-1. Close it… cannot close the spec's motivating case (an interactive zsh)
`lab_hub/land_resolve.py:1007` sends only SIGTERM. An interactive zsh ignores SIGTERM (probe: still alive after 3 s), and Terminal.app's default shell is zsh.
- **Failure:** shopfront stop "zsh (pid 43789)" → Close it… → confirm → SIGTERM is ignored → after 5 s the row reads "still running after Close it…: zsh (pid 43789): press Close it…" → pressing it again gives the same result, forever. Spec §1 lists this exact case as "a click, Close it…".
- **Tests miss it:** they only spawn `python -c` children, which exit on SIGTERM.
- **Fix (owner decision, since §3.2 says SIGTERM):** send SIGHUP, which is what closing a Terminal window sends, either to shells or as SIGTERM then SIGHUP. Keep the rule against SIGKILL. Add a test that starts `zsh -i` under a pty.

### P1-2. Close it… signals processes in a repo nested in the checkout, and the confirm hides their real folder
`lab_hub/land_resolve.py:996` (and `processes_in` at `:930`, through `in_own_tree` at `:831`) skips nested *worktrees* but not nested *repos*. `handoff._inside`/`_nested_repo` (`lab_hub/handoff.py:228-250`) already guards against this; the Land side doesn't.
- **Real case:** shopfront has `shopfront/website/.git`.
- **Failure:** a dev server or editor in `shopfront/website` is listed on shopfront's main-checkout busy stop. Close it… sends it SIGTERM (probe: `SIGNALS SENT: [(pid, SIGTERM), …]`).
- **The confirm hides it:** `ui/apps_tab.py:1290` shows `"{p} in Main checkout (<target>)"`, the stop's folder, not the process's own folder. §3.2 requires "each cmd (pid) … and its folder" and "never a process whose folder is outside the checkout".
- **Fix:** exclude any folder below a nested `.git` in `in_own_tree`, at least when choosing who to signal; carry each process's own cwd in the listing; show that cwd in the confirm; add a test with a nested repo.

### P2-1. The cut keeps the action only for ": action" endings
`lab_hub/land.py:93` keeps the action only if the reason ends in `": " + action`. Three cases fall through:
- **Settling stop:** `for_land` produces "…Try again in N minutes, or press Ask Claude…" (`land_resolve.py:822`). With a 70+ character file path it is cut to `…, or press Ask C…`.
- **Link stops:** "…: Land again, or press Ask Claude…" fails the same way.
- **Red-main stop:** it keeps its action, but the cut drops "waiting: <branches>" and leaves the parenthesis open.

**Fix:** have `plain_reason` also keep a trailing `ASK_CLAUDE` (and any `STOP_ACTIONS` value) after ", or ", or make those texts end in ": press Ask Claude…". Add tests with long settling and link reasons.

### P2-2. Some stop texts still say "do it yourself", and the §2.1 test can't catch them
- **Link stops:** `lab_hub/land_resolve.py:650` says "remove the link from the branch, then Land again". Yet `BLOCKER_ACTIONS["link"] = ASK` (`:806`).
- **Gitleaks push stop:** `lab_hub/repo_tidy.py:1111` says "remove it from those commits, then Land again".
- **Test-only map:** `BLOCKER_ACTIONS` is used only by the test, so the mapping test is circular.
- **Narrow word scan:** the scan covers only `land.py` and `land_resolve.py`, and only "by hand / in terminal / yourself".
- **Failure:** a branch adding a link over a folder shows a row that tells the owner to edit the branch themselves, with no button. §2.1 says "Each says what clears it".
- **Fix:** end those texts with `": " + ASK_CLAUDE`; check each kind's real stop text against `clearing()` on fixture output.

### P2-3. Restating a row after Close it… throws away the repo's other stops and Ask Claude goals
`ui/lander.py:139` builds the held result from the stops that are left only; `ui/progress_window.py:852` overwrites `results[name]` and recomputes `handoff_goals` from it.
- **Failure:** a repo with a protected `.claude/` conflict plus a busy worktree → Close it… → one process won't quit → the row now says only "still running after Close it…", and Ask Claude's prompt drops the §3.4 goal.
- **Fix:** merge into the old result: replace only the busy stops and keep the rest. Add a UI test with two stops.

### P2-4. Build decision 2 needs the owner: one button press in Land all removes the other repos' rows
`ui/apps_tab.py:1241`: after a successful clear, `_open_land_window(plans)` hides and deletes the multi-repo window.
- **Failure:** the owner presses Close it… on shopfront → shopfront runs in a new one-row window → the other rows, their Ask Claude footer and imprint's Try again are gone until Land all runs again.
- **Fix / ask the owner:** run the single repo inside the existing window (reset only that row), or keep the old window open. Add a test.

### P3-1. After a successful clear, a cancelled or no-op re-plan leaves a stale row
`ui/apps_tab.py:1213-1241`. If the owner cancels the Land confirm, or the plan has no actions, the old row keeps its old text with its button enabled again. Fix: restate the row when the plan is not run.

### P3-2. An empty `lsof` result after signalling counts as "all closed"
`lab_hub/land_resolve.py:1017`: `cwd_listing()` returns `[]` for an empty output. Fix: treat an empty listing as `None` in `close_processes`.

### P3-3. An already-gone pid is logged as closed, and zombie children make it wait the full 5 s
- A `ProcessLookupError` still adds the entry to `sent`, so it is logged "owner closed".
- `_alive` treats a zombie child as alive, so the loop waits the whole `CLOSE_WAIT`.
- Fix: don't add vanished pids to `sent`; reap Lab Hub's own child with `os.waitpid(pid, WNOHANG)`.

### P3-4. The confirm counts Lab Hub itself, and processes started later show as "still running after Close it…"
Fix: drop `os.getpid()` from the confirm, and word the leftovers as "running in it".

### P3-5. Try again also appears on auth failures
"Permission denied (publickey)" or "Repository not found" become "no network?", and Try again can never clear them. Fix: route auth / not-found messages to Ask Claude.

### P3-6. Unsanitised file names in `Stop.label`
Fix: apply `_flat(f, 120)` in `label`.

### P3-7. Test gaps
- `test_no_default_branch_and_no_checkout_point_at_ask_claude` checks the default-branch stop only `if stops:`.
- No tests for: the nested-repo exclusion, an interactive shell, a restate with several stops, the Land all window being replaced, or long `", or press Ask Claude…"` reasons.

### P3-8. Remaining "then Land again" endings outside the spec table
"install or sign in to Claude Code, then Land again" and "Land again, or decide in Review branches": defensible, since Ask Claude can't help without Claude Code. List them as accepted exceptions.

## Spec check
- §2.1: partly met (P2-1, P2-2). §2.2: prompt met and tested on a real conflict fixture; the owner-watched syndustryx run is not done (owner's step). §2.3: existing test unchanged. §3.1: met. §3.2: own pid excluded, lsof failure means no signal, never SIGKILL, closes logged; fails for zsh (P1-1) and nested repos (P1-2). §3.3: met. §3.4: met.

## Build decisions
1. Normal confirm after a clear: agree (Close it… now has two confirms; the owner should note this).
2. Replacing the Land all window: needs the owner (P2-4).
3. Try again on "could not fetch": agree, subject to P3-5.
4. `_claude_blocker` out of scope: agree.

## Architect skip
Partly agree. Reusing the one-job worker thread is fine, but signalling outside processes is a new, irreversible boundary; P1-2 is the kind of gap an Architect pass catches. Recommend a short note on who may be signalled, with which signal.
