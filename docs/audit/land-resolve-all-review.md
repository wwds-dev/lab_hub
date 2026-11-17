# Review: land-resolve-all (2026-11-17)

Reviewer: `code-reviewer` agent, read-only. It is not the author. The playbook is current (last reviewed
2026-10-14).

The reviewer reproduced both P1s with throwaway tests on fixture repos. It ran
`pytest tests/test_land_resolve.py tests/test_land.py tests/test_repo_tidy.py` with real gitleaks, and it
passed.

Verdict as reported: **0 P0, 2 P1, 7 P2, 2 P3.** Bulk Resolve with `land_mode=False` behaves as before.

## Findings (as reported)

**P1-1. An archived branch comes back at every Land.**
- The worktree of an archived branch is detached when it cannot be removed. That happens for a recent
  agent worktree, or one holding an ignored `.env`.
- No branch contains that commit, so the next Land rescues it onto `lab-hub/rescue-…`, triages it and
  archives it again.
- Every Land pays Claude once more, and adds a further $3 `claude_merge` when the repo has a test command.
- Reproduced: 3 Lands gave 3 tags.

**P1-2. The cost and data-flow notice understates paid runs.**
- At preview time, some branches are blocked only by untracked files, or by the checkout being on them.
  The notice prices them only as $0.50 triage.
- After prep, they can go to a $3 `claude_merge` that is pushed without review, and the merge disclosure
  is never shown.
- Reproduced. SYNDUSTRYX could reach about $21 that the notice does not mention.

**P2.**
1. Quarantine moves files and edits `.gitignore` before the detached-HEAD check, so a failed step leaves
   partial changes.
2. The log can name the wrong quarantine path, because a name collision renames the file to `name.2`.
3. Apply re-sorts the files, so files created after the preview are committed without having been listed.
4. Spec 4.5 is not met: a busy worktree is never retried at the end of the run, and the stop does not
   name the process.
5. Restore is undone by the next Land: the restored branch is triaged again.
6. A failing push is retried every round, which can take about 20 minutes on a stalled network.
7. The preview counts nested repos (which are only ignored) as files to commit.

**P3.** The triage prompt lacks "already in the default branch". A tile can read "Landed" while its notes
still show a preview skip saying "land it by hand".

## Status after fixes
| Finding | Status |
|---|---|
| P1-1 | fixed: a detached HEAD that an `archive/*` tag holds is not rescued. Test: `test_an_archived_branch_does_not_come_back_on_the_next_land` |
| P1-2 | fixed: the notice prices every unlanded branch as a possible $3 merge ("up to N branches may be sent"). Test: `test_the_notice_prices_every_branch_that_may_reach_claude` |
| P2-1 … P2-7 | fixed. 1: the branch is checked before anything moves. 2: the final quarantine name is chosen before logging. 3: only files the preview listed are committed (`test_a_file_that_appears_after_the_preview_…`). 4: busy worktrees are retried at the end, and the stop names the process (`test_who_is_in_names_the_process`). 5: a restored branch is kept under `refs/lab-hub/kept/` and left alone (`test_a_restored_branch_is_kept_…`). 6: a refused push is not retried (`test_a_refused_push_is_tried_once_per_land`). 7: nested repos are listed separately |
| P3 (both) | fixed: the triage prompt gives the count of commits already copied, and preview skips no longer appear in the notes of a Landed tile |
