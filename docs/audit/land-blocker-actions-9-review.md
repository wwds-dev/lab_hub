# Review: land-blocker-actions §9 (Close it… on the card, busy line, order note)

Reviewer: `code-reviewer` agent (read-only, not the author), 2026-11-24, with the security pass for signals to processes. Saved by the orchestrator from the reviewer's report; resolutions added by the engineer below each finding.

**Security: no path signals an unconfirmed process.** `close_card` hands the confirmed `card.busy` to the closer; `close_processes` (`land_resolve.py:1022-1060`) only signals a pid a fresh lsof still shows with the same name in that worktree, never nested repos, Lab Hub, its parent, pid 0/1; SIGTERM only. Cancel (default) closes nothing. Process names are plain text everywhere. No P0/P1.

## P2
- **P2-1** "Still running" kept the card's old process list, so a new pid could never be confirmed or closed. **Fixed:** `close_and_look` returns the leftover stops (as `Lander._cleared`); the card's `busy` is replaced. Test `test_a_new_process_is_listed_in_the_next_confirm`, `test_close_and_look_keeps_what_is_left`.
- **P2-2** The busy line flagged worktrees Land does not stop at (a shell in a clean checkout, forever "busy"). **Fixed:** `land_resolve.has_open_work` extracted from `prep`; `busy_now` uses it, so the line and Land's stop apply the same two tests. Test `test_shell_in_a_clean_checkout_is_not_busy`.
- **P2-3** lsof every 5 s while the window is minimised or Lab Hub is in the background. **Fixed:** the tick is skipped unless the window is not minimised and the app is active.

## P3
- **P3-1** Lab Hub's own git (hygiene refresh) could show as busy. **Fixed** for the hygiene QProcess (tick skipped while it runs). Build-check git not covered: rare, one tick.
- **P3-2** A Land from another page was not noticed. **Fixed:** repos with `land.landing(path)` are left out.
- **P3-3** Stale line after a Land or a long-hidden page. **Fixed:** cleared when a Land starts; the page checks on show.
- **P3-4** An exception was shown as "Still running". **Fixed:** "Could not close: …". Tested.
- **P3-5** Cancel did nothing during a close. **Fixed:** disabled while closing. Tested.
- **P3-6** Missing tests. **Partly fixed** (closer leftovers, exception, cancel). `_busy_repos` gating is not tested (needs an active app window offscreen): not verified.
- **P3-7** Confirmation dialog never deleted (pre-existing). **Fixed:** `deleteLater()` after `exec()`.

Process note: `docs/foundry/app-context.md` Commands/Invariants are still template placeholders.
Mutation check (engineer): 5 mutations in the new logic, 5 killed by `tests/test_land_busy_monitor.py`.
