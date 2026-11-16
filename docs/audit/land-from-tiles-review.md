# Review: land-from-tiles (uncommitted, branch claude/land-from-tiles)

Reviewer: code-reviewer (read-only). Playbook last-reviewed 2026-10-14, status current (not stale).
Run: `tests/test_land.py tests/test_land_ui.py` = 30 passed (offscreen). Full suite: all passed, exit 0 (no count line captured).

## P1
1. `lab_hub/land.py:32,49-53` plain_reason picks garbage for the headline SONAR case. `_ERROR_LINE` is
   case-insensitive and matches pytest's summary line, and the loop scans from the last line.
   Input: "not landed — no Claude run: the tests don't pass on master itself ...:\nERROR tests/test_x.py\n
   ImportError: cannot import name macro\n=== 1 error in 0.12s ===" -> reason
   "...(they fail): error in 0.12s ===" (run, output seen). The real cause (ImportError) is dropped. The tests
   (`test_land.py:95-118`, `test_land_ui.py:118`) feed output that ends on the ImportError line, so they pass.
   Fix: drop IGNORECASE or require `\w+(Error|Exception)\b:`; skip lines starting with "=" or matching
   `\d+ (error|failed)`; add a test whose last line is the pytest summary.
2. Spec measure 4 not met: "Not landed: <reason>" has no "Open in Terminal" next to it
   (`ui/apps_tab.py:327-365` show_outcome; grep finds the button only in `repo_tidy_dialogs.py:130`). A
   failed Land with no leftover branch (e.g. tests fail on master, remote rejected) gives the owner no action.
   Fix: add an Open in Terminal link to the tile on not_landed; test it.
3. `ui/apps_tab.py:1067-1080` `_card_for` matches by `hygiene_row.name`, first card only. (a) If two tiles
   share one repo, the second stays on "Looking at the repo…"/no outcome only when it was marked; land_all
   marks only the first, but a later hygiene refresh that sets `hygiene_row = None` (report missing/rewritten)
   mid-Land makes `_card_for` return None, so `repo_done` is dropped and the card stays "Landing…" with a dead
   disabled button until restart (`_landing` is only cleared by show_outcome/set_landing(None)). Fix: key cards by
   repo path captured at request time (store on card as `_landing_repo`), not by the live `hygiene_row`.
   Same hole when `_sync_cards` rebuilds a card mid-Land: the new card has `_landing` False and
   `hygiene_row` None until the next `_apply_hygiene`; progress/outcome are lost for the interval. Evidence
   by reading; not reproduced (no test).
4. App closing mid-Land: `ui/lander.py:72` daemon thread, no closeEvent/aboutToQuit hook anywhere
   (grep: none outside tests). Quitting during a merge or a Claude run kills the thread mid-git (repo left
   in a merge state, temporary copy and a claude subprocess orphaned). `Lander.stop()` exists but nothing calls
   it on close. Fix: on tab/main-window close, `lander.stop()` and join with a short timeout, or block quit
   with a confirmation while `lander.running`. Not run.

## P2
5. `ui/apps_tab.py:1006-1012` `refresh_repos` returns early if a hygiene QProcess is in flight. A refresh
   started before Land ends finishes with pre-Land git state, and `_land_finished`'s refresh is skipped, so a
   landed repo can keep its badge and a live Land button until the next poll. Also `_sync_land` shows Land
   again beside "Landed" while the row is stale. Fix: set a "rerun" flag, re-run when the proc finishes.
6. `ui/apps_tab.py:_land_planned` modal `confirm_land` runs inside the `_drain` slot; any exception in
   `confirm_land`/`run` leaves cards on "Looking…" with `lander.busy` False (thread already cleared). Wrap
   and call `set_landing(None)` on failure.
7. `ui/apps_tab.py:1049` single-card Land that returns "nothing"/not_landed with no actions skips the
   confirmation by design, but `_land_planned` then runs `lander.run` with no check that the repo is the one
   the user clicked after a long modal-free gap; low risk, guards re-run in apply. Informational.
8. Confirmation sentence (`land.py:130-146`) names one push target and one pull target even if the plan has
   several pushes (`by['push'][0]`); spec §6 says the confirmation names the remote branch for every push.
   Fix: list all push targets.
9. Outcome label is never cleared (no `set_landing(None)` path after a later hygiene change): "Landed"
   stays on the tile after new work appears. Minor.
10. `land.claim` covers only `Lander`; `ReviewDialog` (`review_card`) actions are not claimed, so Review
    and Land can touch one repo together. Spec §7 Architect asked for "never the same repo twice".

## Verified OK
- Claim: `land()` claims, and `release` is in a `finally` covering every return and exception (land.py
  233-269). Test `test_the_claim_is_released_after_a_crash` is genuine.
- Disclosure: `confirm_land` sets `informativeText` to `claude_notice` whenever any plan has a
  `claude_merge` action (apps_tab.py `confirm_land`; test 220-245 renders the real QMessageBox with exec
  patched and asserts "Anthropic" and the model). Plain `merge` never calls Claude (repo_tidy.apply: a
  claude_merge that merges cleanly falls to the plain path), so the disclosure matches the data flow.
- `Lander._drain` clears `_thread`/`_running` before emitting, so the callback may start the next job; the
  worker only touches `queue.SimpleQueue` (no Qt objects off-thread). The `Stopper` is replaced per run.

## Tests that survive a broken implementation
- `test_a_diverged_repo_is_not_landed_with_the_reason` (test_land.py:120): accepts landed or not_landed and
  three ahead/behind states. Mutation: make `land()` return "landed" always, or force-push; still passes.
- `test_conflicts_handed_to_claude_are_named_in_the_sentence` (43): all assertions are under
  `if plan.with_claude:`; if plan never produces claude_merge it asserts nothing. Mutation: delete the
  `claude_merge` branch of `sentence` and `claude_notice`: passes unless plan_repo happens to plan one.
- No test for `set_landing(None)` restoring a prior outcome/review link (`_before`), for Stop from the UI,
  for a hygiene refresh or `_sync_cards` mid-Land, or for a second Land click while busy. Mutation: make
  `_before` restore nothing, or drop `_sync_land` from `refresh_hygiene`: suite stays green.
- `test_land_shows_only_on_a_tile_with_work` never checks the button is hidden after a row clears.
- plain_reason parametrised tests contain no pytest-summary case (see P1-1).
