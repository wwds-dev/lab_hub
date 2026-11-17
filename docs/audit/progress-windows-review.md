# Review: progress-windows (uncommitted change on claude/zealous-benz-97c752)

Reviewer: code-reviewer (independent, read-only), 2026-11-17. Saved to this file by the orchestrator, verbatim from the reviewer's report (the reviewer is read-only). Playbook `docs/playbooks/code-reviewer.md` is `status: current`, last reviewed 2026-10-14 (34 days), not stale.
Scope: `git diff` (`lab_hub/land.py`, `ui/lander.py`, `ui/apps_tab.py`, `ui/theme.py`, three test files) plus new `lab_hub/durations.py`, `lab_hub/progress.py`, `ui/progress_window.py`, `ui/rebuild.py`, `tests/test_{durations,progress,progress_window}.py`. Checked against spec §2, §8, §8.15 and AGENTS.md.

**Summary:** 1 P1, 4 P2, 5 P3.

## Evidence run
- Targeted: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -o addopts="" -q -p no:cacheprovider tests/test_durations.py tests/test_progress.py tests/test_progress_window.py tests/test_land.py tests/test_land_ui.py tests/test_apps_tab.py` -> 213 passed in 53.8 s.
- Full suite, same command with no paths: 841 passed, 1 skipped, exit 0, 296.9 s (matches §8.15).
- Scratch scripts (offscreen, real `Rebuild` and `BuildCheckWindow`) for P1-1, P2-1, P2-3, P2-4; results quoted per finding.
- No linter configured or installed in the venv: not run.

## Checks that passed
- **Land behaviour.** `land.py` only adds `StepEvent`s around `repo_tidy.apply` via an error-swallowing `tell()`. `say()` lines, step order, claim/release and "never raises" intact. `confirm_land`, Claude notice and cost cap unchanged. The window's Stop emits `stop_requested`, connected to `lander.stop` (`apps_tab.py:1010`). Tiles still get `card.set_landing` and `show_outcome`. The one intended change: the Land all box is replaced by the window's end state (owner decision 4).
- **Threading.** Worker only calls `SimpleQueue.put` (`lander.py:105-107`). `durations.record` only from GUI-thread slots (`progress_window.py:650`, `rebuild.py:158`).
- **The 19 re-seamed tests.** No `def test_` disappeared from `test_apps_tab.py`, `test_land_ui.py` or `test_land.py`. The only removed `assert` lines in `test_apps_tab.py` are the two runner tests, re-pointed from `_button`/`_log`/`dialog.succeeded` to `cancel_button`/`output_text()`/`rebuild.succeeded` with the same conditions. `test_build_check_dialog_can_be_dismissed` got stronger (also checks Escape). `git diff` of `test_land_ui.py` and `test_land.py` has no removed lines.
- **Button conditions.** `build_check_view` gives the same headline, text and command lists as HEAD's `show_build_report` (`scoped = _build_apps is not None` maps exactly). Conditions and dispatch match the §8.7 table, except Cancel (P2-1).
- **Model edge cases** match §8.6: `fmt_left(60)` "~60 s", `fmt_left(61)` "~2 min"; left never negative; overrun "Taking longer than usual"; stale amber at >= 60 s; percent capped at 99 until finish.

## P1

### P1-1: The Update step hangs for good if a rebuild command fails to start
- **Where:** `ui/rebuild.py:58-65` (no `errorOccurred` handler), `ui/rebuild.py:114-121` (`_start_next`), `ui/progress_window.py:946-950` (`reject` cancels only `if rebuild.running`), `ui/rebuild.py:180-182`.
- **Failure:** `$SHELL` points to a shell that no longer exists, or `QProcess.start` fails otherwise. QProcess emits `errorOccurred(FailedToStart)` but never `finished`, so `_ended` stays False. Cancel/Escape: `rebuild.running` is False so `cancel()` is skipped; the window hides; `_maybe_quit` sees `_ended == False`; `Rebuild.exec()` never returns. `recheck()`, the Terminal handoff and the `launched` message never happen; later Check builds nest one level deeper.
- **Verified:** `SHELL=/nonexistent/shell`, `Rebuild(["echo hi"], w)`, `cancel_button.click()` at 500 ms -> `HUNG: exec() did not return 2.5 s after Cancel {'running': False, 'ended': False, 'btn': 'Cancel', 'visible_after': False}`.
- **Regression:** HEAD's `RebuildDialog._on_button` called `accept()` when NotRunning.
- **Related, not verified:** Escape handled before `QTimer.singleShot(0, _start_next)` fires hides the window, then the build starts unwatched.
- **Fix direction:** handle `errorOccurred` (FailedToStart -> failed, say the error, `command_finished(ok=False)`, `_all_done()`); in `BuildCheckWindow.reject` cancel whenever `not rebuild.ended`; `cancel()` ends directly when nothing runs; test with `SHELL=/nonexistent`.

## P2

### P2-1: Cancel during a rebuild closes the window instead of turning into Close
- **Where:** `ui/progress_window.py:821` (`cancel_button.clicked.connect(self.reject)`), `:946-950`.
- **Failure:** Cancel kills the build and closes the window; the "Cancelled…" line, the row's "The build was stopped." and the output are never seen. Against §8.7 ("turns into Close") and §2.5 ("leaves the rows for reading"); not listed in §8.15.
- **Verified:** `["sleep 30", "echo next"]`, Cancel at 800 ms -> `{'before': 'Cancel', 'visible_after_cancel': False, 'button_after': 'Close', ...}`, `exec()` returned at once.
- **Fix direction:** Cancel while live calls `rebuild.cancel()` only; window stays at Done. Escape and the red button keep kill-and-close. Test it.

### P2-2: A finished Land window is overwritten by a later Land that opened no window
- **Where:** `ui/apps_tab.py:1004`, `:1023-1048`, `:934`.
- **Failure:** Land all ends "Landed 2 of 2 repos."; then Land on a tile with no actions opens no window but feeds the old one: its row turns "Nothing to land", header "repo: Nothing to land", details wiped; "Show progress" opens the stale window; planning lines go to its output.
- **Verified (model level):** before `[('repo','Landed · 0:05'),('other','Landed · 0:05')] Landed 2 of 2 repos.`; after `[('repo','Nothing to land'),('other','Landed · 0:05')] repo: Nothing to land`.
- **Fix direction:** a "window owns the current run" flag set in `_open_land_window`, cleared when no window opens and after `_land_finished`; feed and show the button only while set; UI test.

### P2-3: `durations.load()` raises on a deeply nested file
- **Where:** `lab_hub/durations.py:79-83` catches only `(OSError, ValueError, UnicodeDecodeError)`.
- **Failure:** `"[" * 200000` (195 KiB) -> `RecursionError` out of `load()`/`record()`, against §8.4. `BuildCheckWindow.__init__` raises (Check builds opens nothing); `LandWindow.start` raises after `self.land_window` is assigned (feeds no-op, summary lost, `_update_land_controls()` skipped).
- **Verified:** `load -> RAISED RecursionError`, `record -> RAISED RecursionError`.
- **Fix direction:** catch `RecursionError` (or `Exception`) around read+parse; add to `test_a_broken_file_is_no_history_not_a_crash`.

### P2-4 (predates this change, now claimed fixed): Cancel/Escape stop only the shell, not the build tool it started
- **Where:** `ui/rebuild.py:101-104` (`kill()` signals only `$SHELL -lc`); copy "[cancelled — the running build was stopped]" (`rebuild.py:102`), "The build was stopped." (`progress.py:740`), class docstring.
- **Verified:** `orphan.sh` running `sleep 40`, Escape at 1.5 s; after `exec()` returned, `pgrep -fl "sleep 40"` -> `8790 sleep 40`. Later script steps did not run (zsh exec'd the script), so the leftover is the current child.
- **Fix direction:** own process group and SIGTERM then SIGKILL to the group, or soften the copy. Owner may defer (HEAD also used `kill()`).

## P3
- **P3-1** `ui/progress_window.py:952-954`; `apps_tab.py:777-778`, `:825`: `done(0)` bypasses `reject()` and does not kill a live rebuild. Fix: cancel in `done()`. Not verified at runtime.
- **P3-2** `ui/apps_tab.py:805-809`: `run_updates(window=None)` never deletes the window it creates. Fix: `deleteLater()` after `exec()`.
- **P3-3** `ui/progress_window.py:548-553`, `progress.py:248`: the 500 ms tick runs at the Review step. Fix: require `step != "review"` or a started flag.
- **P3-4** `tests/test_apps_tab.py:1157`: test name claims the Update step and Copy-closes, asserts only `choice == "Update now"`. Fix: rename or add assertions (behaviour covered at `tests/test_progress_window.py:197`).
- **P3-5** `lab_hub/land.py` `step_outcome` with `repo_tidy.py:903` / `claude_resolve.py:372`: Stop during a Claude merge shows a red failed step. Fix: map "not landed — stopped" to `skipped`, or note in the spec.

## Missing tests
FailedToStart (P1-1); Cancel keeps the window open (P2-1); an old Land window is not fed by a later run (P2-2); nested-JSON `durations.json` (P2-3).

## Verdict
Not ready for Verify until P1-1 is fixed or explicitly deferred by the owner. P2-1 to P2-3 should be fixed in the same pass; P2-4 may be deferred by the owner (predates this change). Land and Check builds command paths otherwise unchanged; no existing test weakened.

## Re-review after fixes (code-reviewer, read-only, 2026-11-17)
Saved by the orchestrator from the reviewer's report. Evidence: targeted files 250 passed in 58.0 s (213 before); scratch probes `rr_group.py`, `rr_group4.py` against the real `Rebuild` and `BuildCheckWindow`, offscreen. Full suite not re-run by the reviewer.

**Per finding**
- P1-1 fixed: `ui/rebuild.py:90`, `:216-227` handle `errorOccurred(FailedToStart)`; `cancel()` with nothing running ends the run (`:127-129`); `done()` cancels any unended run (`ui/progress_window.py:963-971`).
- P2-1 fixed: `_cancel_or_close` (`progress_window.py:955-961`) only cancels. Probe (TERM trapped in shell and child): after Cancel the window is visible, button "Close", `ended=True`.
- P2-2 fixed: `_land_window_owns_run` / `_run_window()` (`ui/apps_tab.py:1013-1029`), cleared in a `finally` at `:1066`. `_land_planned` resets the flag before `lander.run`, safe because `Lander.plan` refuses while busy (`ui/lander.py:53-58`).
- P2-3 / Secure P2-1 fixed: `durations.load()` catches `Exception` (`lab_hub/durations.py:105-110`); `_sample` handles `OverflowError` (`:67-76`); read uses `O_NOFOLLOW|O_NONBLOCK`, `S_ISREG`, bounded read (`:79-102`); `record()` goes through `load()`.
- P2-4 / Secure P2-2 fixed (limit: P3-B): `rebuild.py:85-87`, `:133-151`. Probe: with TERM trapped, Cancel blocked 2.00 s, then SIGKILL removed the child; Lab Hub's pgid unchanged.

**New-risk checks:** wrong group or Lab Hub itself: none (pgid = child pid after `setsid`; ESRCH and `processId()==0` fall back to `kill()`). Timer after the window is gone: none (synchronous wait; `singleShot(0, _start_next)` checks `_ended`). No controlling terminal: stdin was already a pipe; lab scripts use no `/dev/tty`, `sudo` or `stty`; Provisio's `[ -t 0 ]` installer already goes to Terminal (`lab_hub/launcher/state.py:1019-1031`). `done()` twice then `exec()` returns cleanly; `cancel()` idempotent via `_ended`. Throttle is a throttle (`1 <= renders <= 11`, `during >= 3`). No test weakened vs `git show HEAD:`. Command paths unchanged (`$SHELL -lc`, `child_env()`, merged channels; HEAD `apps_tab.py:616-650`).

**New findings**
- P3-A `ui/rebuild.py:146-148`: SIGKILL sent to the group even when the poll ended because the group was empty; theoretical pid-reuse race. Fix: SIGKILL only on deadline.
- P3-B `ui/rebuild.py:84-87`: a step that calls `setsid` itself or `set -m` leaves the group and survives Cancel; no lab script does this. Fix: docstring note.
- P3-C (not verified): Lab Hub started from Terminal and stopped with Ctrl-C mid-rebuild: the build survives (own session). Low impact.

**Verdict:** all P1/P2 from Review and Secure fixed; nothing new above P3. Ready for re-Verify.
