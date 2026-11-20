# Spec: Land does not commit files a session is still editing

Status: **Define draft, waiting for the owner's gate.** No approval recorded. Branch
`claude/land-live-session-guard`. Design does not apply to slice 1 (no new screen); Architect is a
section here once Define is approved.
In-flight check (`session_start.py --inflight`, 2026-11-20): no unreleased spec, `claude/*` branch
or worktree covers this. `land-folder-link-guard` (document done) guards merges, not commits.
`land-pick-and-time` (build start) owns the Land confirmation's cards and checkboxes, so this spec
leaves that dialog alone (§4). `land-resolve-all` owns prep; this spec adds one stop to it.
Source: `TODO.md` P0 "Land: don't commit another live session's edits (audit H1)"; readiness audit
2026-11-18 H1 (`docs/audit/2026-11-18-readiness-audit.md`).

## 1. Problem
Land prepares each repo by committing its open work ("Lab Hub: commit open work, <time>") and then
pushes. It skips a worktree only when it can see a process whose current folder is inside it
(`lsof -d cwd`: `repo_tidy.busy_dirs`, `in_use`; `land_resolve._worktree_stop_full`).

Two gaps follow from that test, both read in the code on 2026-11-20 (`main` at `ccd1a6f`):

- **A session that works from another folder is invisible.** A Claude Code session opened in
  `~/Documents/lab`, or in a lab-root worktree, edits `active/<app>/...` while its own folder stays
  outside that repo. `in_use` answers no, and prep commits the half-finished files.
- **The main checkout is never tested at all.** `repo_tidy.commit_blocker` runs the busy test only
  under `if not wt.main:`, so tracked changes in a repo's main checkout are always committed.

The result is a commit and a push of someone else's half-done edit. `cc56bb6` and `9e669a1` in this
repo are such commits, and on 2026-11-18 Land committed the suggestion rows another session had
just written in six repos while that session was still working. Nothing was lost in those cases,
but a half-edited file can be pushed to `main` and a session's own later commit then conflicts or
silently duplicates.

## 2. User and success measure
The owner, pressing Land or Land all while agent sessions are open.

1. A tracked file changed less than the quiet time ago: Land does not commit in that worktree and
   does not push that repo. It reports a stop that names the newest file and its age. Shown by a
   test on a temporary repo (file touched 1 minute ago).
2. The same file changed longer ago than the quiet time: Land behaves exactly as today. Shown by
   the same test with the file's time set back.
3. Both hold for the main checkout and for a linked worktree, with no process inside either.
4. Land all still lands every other repo; only the repo with fresh edits is stopped.
5. Thirty days after release: no "Lab Hub: commit open work" commit contains a file that a session
   was editing in the quiet time before it (owner's check at the 30-day review).

## 3. Scope (slice 1)
One new rule, applied wherever Land or Resolve would commit tracked changes or add untracked files
(`repo_tidy.commit_blocker`, `land_resolve._worktree_stop_full`, and the `untracked` step):

> A worktree is **settling** while any file git reports as changed or untracked in it was modified
> less than `QUIET_MINUTES` ago. Land stops at a settling worktree: it commits nothing there, adds
> nothing, and does not merge or push that repo in this run.

- The rule covers the main checkout as well as linked worktrees (closes the second gap).
- The files examined are exactly those `git status --porcelain` lists, capped at a fixed number;
  above the cap the worktree counts as settling (fail closed, like `in_use`).
- A file whose time cannot be read counts as just changed (fail closed).
- The stop text follows the existing stops: "`<file>` changed 3 minutes ago: a session may still
  be working here. Land again in 12 minutes, or commit it yourself." It appears in the existing
  stops list of the confirmation and the Land window; no new control.
- The existing process test stays as it is and runs first.

## 4. Non-goals
- No change to the Land confirmation's layout, cards or checkboxes (`land-pick-and-time` owns
  them). Listing every file to be committed in that dialog is slice 2, after that spec ships.
- No test for "a `claude` process whose folder is an ancestor of the repo". A session is nearly
  always open in `~/Documents/lab`, so that test would stop every Land in every repo.
- No override button in slice 1 (question 3).
- No change to merges, pushes of already committed work, or worktree removal.

## 5. Decisions for the owner (Define gate)
1. **Quiet time.** Recommend **15 minutes**: longer than a pause inside an agent's turn, short
   enough that an evening Land after the sessions stop is not held up. Alternatives: 5 (misses a
   session that is thinking or running tests) or 30.
2. **Main checkout included.** Recommend **yes**. It is where the lab-root sessions write, and the
   one place today's test never looks.
3. **Override.** Recommend **none in slice 1**: wait out the quiet time or commit by hand. A
   "Land anyway" choice per repo belongs in the confirmation that `land-pick-and-time` is
   rebuilding, as slice 2.
4. **Files that change by themselves.** Some tracked files are rewritten by a timer (for example
   Foundry's `dashboard/history/<date>.json`, refreshed within seconds of any change). Under this
   rule such a repo is always settling. Recommend: slice 1 ships without an exception list and the
   stop names the file, so the pattern is visible; if a repo turns out to be stopped every time,
   slice 2 adds a per-repo list of paths the rule ignores. Alternative: add that list now.

## 6. Invariants touched
- Land never loses work and never guesses: every new branch of the rule fails closed.
- Nothing on the UI thread waits: the rule is `stat` calls on a bounded list, inside the existing
  prep pass that already runs off the UI thread.
- Land's commits stay "tracked changes only; untracked files by the `untracked` step's rules".

## 7. Smallest slice and what follows
Slice 1 is §3: one helper (`settling(worktree, now)`), two call sites, the stop text, tests for
measures 1 to 4, and a mutation check on the time comparison and the fail-closed branches.
Estimate: half a day including Review and Verify. Slice 2 (after `land-pick-and-time`): the list of
files to be committed in the confirmation, the per-repo override, and the ignore list if question 4
shows it is needed.

## 8. Risks
- A long quiet time makes Land feel stuck when the owner himself just edited a file. The stop text
  says how long is left.
- A session that last wrote more than the quiet time ago and is still mid-task is not caught. The
  rule narrows the gap; it does not prove a session has finished.
