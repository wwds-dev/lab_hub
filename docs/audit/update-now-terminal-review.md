# Review: update-now-terminal (code-reviewer, independent, read-only)

Spec `docs/specs/update-now-terminal.md`. Reviewed 2026-11-16 on the uncommitted diff. Result: P0 0, P1 2, P2 7.
The reviewer had no file-write tool; the orchestrator saved its report here and recorded what was done.

## P1 — both fixed
1. Exceptions from `run_in_terminal` escaped the Qt slot after the in-app rebuilds had run; a bad command was found only after minutes of rebuilding. **Fixed:** `check_terminal_commands` runs before the first rebuild; `ValueError`, `OSError` and `LaunchError` are caught and shown in a message box (`ui/apps_tab.py` `run_updates`). Tests: `test_a_bad_terminal_command_stops_everything_before_any_rebuild`, `test_a_terminal_that_will_not_open_is_shown_not_swallowed`.
2. A failed `open` was swallowed while the UI said "Opened Terminal". **Fixed:** return code checked for every window, all are tried, a `LaunchError` names the failures; no success message on failure. Test: `test_a_window_that_does_not_open_is_reported_after_trying_every_one`.

## P2
1. Wording hard-coded Provisio and read badly for several apps — **fixed** (generic sentence, "after the rebuilds above succeed" when relevant; the Provisio parenthesis stays, since only Provisio's script was checked).
2. The "Rebuilt…" message was overwritten by the Terminal message — **fixed:** one combined message; a failed rebuild says no windows opened.
3. `open_terminal` docstring contradicted `run_in_terminal` — **fixed.**
4. File not created atomically with its mode — **fixed:** `os.open(O_EXCL|O_NOFOLLOW, 0o700)`, folder created 0700, a linked folder refused, UTF-8.
5. Test gaps (folder mode, default location, two by-hand apps, refusal keeps old files, recheck, messages, open failure) — **fixed**, each with a test. 13 mutants planted over two rounds, all caught.
6. Not verified: Terminal running a Lab Hub-written `.command` file without a quarantine/Gatekeeper prompt; Provisio's `-t 0` check passing in that window; before/after tile screenshot (success measure 6). **Open — needs a run on the real Mac.**
7. Scope: measures 1–5 met, non-goals respected. No CHANGELOG file exists in this repo; the TODO entry carries it.

Suite after the fixes: 670 passed (2026-11-16).
