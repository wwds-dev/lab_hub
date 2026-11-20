# Code review: land-folder-link-guard

Phase: Review (6). Read-only, 2026-11-18, by the `code-reviewer` agent, which did not write the code. Saved by the owning session from the agent's report.
Scope: commit 585e3b3 and spec `docs/specs/land-folder-link-guard.md`.
**Playbook:** `docs/playbooks/code-reviewer.md`, `status: current`, last reviewed 2026-10-14. It is not stale. App-context Commands, Invariants and Test bar are placeholders, so the review checked the change against the spec and AGENTS.md.

## What was run
- `tests/test_land_folder_link_guard.py`: 23 passed.
- `test_land`, `test_land_resolve`, `test_repo_tidy`, `test_claude_resolve` and the new file together: 1 failed (P1-1).
- The other Land, Claude-resolve, handoff and progress test files all passed.
- Probe tests against real temporary repos, kept in the session scratchpad.
- **Not verified:** the rest of the suite, the mutation check, CI.

## P1
**P1-1. The suite is red.** `tests/test_claude_resolve.py:494` `test_a_symlink_out_of_the_repo_is_refused_before_claude` fails with `StopIteration`. It fails at 585e3b3 and passes at 7829d53.
- Why: `plan_repo` now skips the branch at plan time (§5.2 A), so no `claude_merge` action exists for the test to find.
- Fix: expect the plan-time skip, and keep the assertion that Claude never ran.

**P1-2. A pull or switch link stop makes every other branch get triaged and archived. The pull's link stop also vanishes from the result.**
- Code: `triage` (`land.py:660-718`). `_land_one` cannot plan a merge while the target is blocked, so each branch falls through to the archive. The "not pulled" skip (`repo_tidy.py:666`) is plan-only and never becomes a stop.
- Probe (pull): `feat` was asked about with "main is 1 behind origin: pull it first" and archived. The result reason did not mention the link.
- Probe (switch): `feat` was archived; `claude/redesign` also cost a verdict call.
- Fix: put a repo-level stop on the pull or switch link stop, and don't triage branches whose only reason is that blocked target. Test both cases with a second ordinary branch.

## P2
**P2-1. "Land again" after fixing the remote keeps stopping.** The pull is judged on a stale `refs/remotes/origin/X` before anything fetches, so the fix the stop asks for never takes effect.
- Fix: let the check after the pull's own fetch decide, or fetch in `check()` as push does.

**P2-2. A branch with a non-UTF-8 path crashes `plan_repo`, and with it Land and Tidy's preview.**
- `rt.git` decodes strictly, so `UnicodeDecodeError` escapes `land()`, which promises it never raises.
- This also applies to link text.
- Fix: read as bytes; a path git cannot decode becomes a stop.

**P2-3. Check-then-use gap in the pull and the switch.** Each checks a ref by name, then moves to that same name, so a fetch in between lands an unchecked commit.
- Fix: run `rev-parse` once, then check and move to that SHA.

## P3
- **P3-1:** an orphan branch (`gh-pages`) becomes a permanent "may add a link that git cannot check" stop, because `merge-tree` refuses unrelated histories.
- **P3-2:** stop wording.
  - Spec §3.3 has a comma ("a link at .venv, a name ignored as a folder").
  - While the pull is held, branches show "pull it first", which points at the very command that would replace the folder.
- **P3-3:** a second `merge-tree` runs per branch per plan round. `--write-tree` writes objects, so §8's "read-only" is loose.
- **P3-4:** missing tests:
  - a second branch beside a pull or switch stop;
  - non-UTF-8 paths;
  - a stale ref after the remote is fixed;
  - an orphan branch;
  - triage with `claude=None` and a mix of branches;
  - `merge_link_stop` with no worktrees.

## Checked and fine
- `diff-tree -z` parsing.
- A conflicted merge-tree keeps the link entry and stops.
- A merge-time and a plan-time link stop never reach the verdict or the archive.
- The Claude fast-forward checks the same SHAs it moves to.
- Apart from P2-1 and P2-3, the pull rewrite matches `git pull --ff-only`.
- A wanted in-repo link lands.
- Control characters are replaced and paths are cut at 120 characters.

## Disposition (owning session)
See `docs/specs/land-folder-link-guard.md` §9.
