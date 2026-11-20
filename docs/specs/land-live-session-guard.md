# Spec: Land does not commit files a session is still editing

Status: **Define approved by the owner 2026-11-20 ("Approve as recommended"):** §5 takes the
recommendation for all four decisions (15 minutes, main checkout included, no override, no
exception list in slice 1). Branch `claude/land-live-session-guard`. Design does not apply to
slice 1 (no new screen). Architect: §9, no gate (no new state, concurrency or module boundary).
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
> nothing and does not switch it. A settling main checkout with changed tracked files is reported
> "Not landed". Work that is already committed on other branches is still merged and pushed
> (review P3-6: the first wording said the whole repo stops, which §4 contradicted).

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
- A tool that keeps a file's old time (`cp -p`, `rsync -t`, `mv` from outside the repo, `tar x`)
  hides a fresh change from the rule (review P2-3). Not closed in slice 1: comparing the inode
  change time as well would catch it, at the cost of stops after a `chmod` or an attribute change.
- A deleted file has no time of its own and is timed by the nearest folder that still exists.
  Anything created or removed in that folder, ignored files included, restarts its clock (review
  P3-5): a false stop, never a missed one.

## 9. Architecture (no gate)
No new state on disk, no new thread and no new module boundary, so no Architect gate.
- `repo_tidy.settling(path, now)` is the rule. `_open_files` reads
  `git status --porcelain=v1 -z --untracked-files=all` (one call, the existing 30 s limit);
  `_changed_at` reads one `lstat` per file, at most `SETTLING_MAX_FILES` (2000).
- Call sites: the end of `repo_tidy.commit_blocker` (Resolve's and Land's commit of tracked
  changes; now reached for the main checkout too) and the end of
  `land_resolve._worktree_stop_full` (Land's prep and every re-check before a step). A clean
  worktree has no open files, so removing or archiving one is never held up.
- `repo_tidy._OWN_WRITES` remembers, per worktree and for this process only, when Lab Hub itself
  last finished a prep step there (`land_resolve.apply_step`). A deletion whose folder has not
  changed since that moment is Land's own doing and is not counted; a changed file is always
  counted. Without it Land stopped itself after its untracked step (review P2-1).
- All callers run off the UI thread (`ui/lander.py`'s worker, `repo_tidy_dialogs`' pool).
- The test suite sets `QUIET_MINUTES` to 0 (`tests/conftest.py`): every existing test makes a file
  and lands it at once. `tests/test_land_live_session_guard.py` turns the rule on.

## 10. Review and Verify (2026-11-20)
Review by an independent read-only agent, not the author. No P0 or P1.
| # | Severity | Finding | Outcome |
|---|---|---|---|
| 1 | P2 | Land's untracked step (a quarantine move, a new `.gitignore`) changes a folder's time, so an old deletion read "changed less than a minute ago" and Land stopped itself | Fixed: `_OWN_WRITES`; a test runs the whole Land flow with the rule on |
| 2 | P2 | An intent-to-add rename prints ` R new<NUL>old`; only the first status letter was read, so the next entry was swallowed and a fresh file went unexamined (fail open) | Fixed: both letters; test |
| 3 | P2 | Only the modification time is read; tools that preserve it hide a change | Not fixed in slice 1 (§8); `TODO.md` |
| 4 | P3 | A file dated in the future stopped Land with a misleading age | Fixed: the stop says so; test |
| 5 | P3 | Folder-timed deletions restart on any change in that folder | Accepted (§8) |
| 6 | P3 | §3 said the whole repo stops; §4 said otherwise | Spec corrected (§3) |
| 7 | P3 | No test of the full Land flow or of a linked worktree with the rule on | Added. Measure 4 has no test of its own: Land all plans and lands each repo separately (`land.make_plan`, `land.land` take one repo) |

Verify: 29 tests in `tests/test_land_live_session_guard.py`; the full suite passes with them
(offscreen, exit 0). Mutation: 23 mutants on the rule, its two call sites, the own-write marker and
the parser; 20 killed. The three survivors change nothing observable: `QUIET_MINUTES <= 0` to
`< 0` (zero already means every age passes), `max(0, age)` to `abs(age)` (a time more than a
minute ahead is reported separately, and under a minute both read "less than a minute ago"), and
dropping the "nothing left to time" return (the age is then the whole clock, which passes).
Measures 1 to 3 are met by tests; measure 5 is the owner's 30-day check.
