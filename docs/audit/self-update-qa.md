# Verify: self-update (QA)

Phase: Verify (`qa-engineer`), 2026-11-17. Scope: the uncommitted `self-update` change on `main`
(spec `docs/specs/self-update.md` §2 and §9.5, ADR 0003). Read-only on production and test code:
every mutation ran in a scratch copy of the tree outside the repo (byte-compared with the repo
afterwards: identical), and `git diff --stat` on the repo was unchanged before and after.

Playbook: `docs/playbooks/qa-engineer.md` `last-reviewed: 2026-10-14`, `status: current` (34 days,
not stale). `docs/foundry/app-context.md` still has placeholders for `## Commands` and
`## Test bar`, so no test modes or coverage target are listed; this report used the two modes
below. The venv has no `pytest-timeout`, `pytest-randomly` or `coverage` (playbook practices);
coverage was measured with `coverage` 7.17.3 installed into a scratch folder, not the venv.
The code review (`docs/audit/self-update-code-review.md`) appeared while this ran. Its P1-1
(unchecked `rm -rf`/`mv` in the swap and rollback, reproduced as a nested
`Lab Hub.app/Lab Hub.app`) is a production defect that is still open; QA's gaps S2 and S3 overlap
its P2-3. This Verify has to be repeated after those fixes.

## Verdict

**FAIL.** QA's own blockers are missing tests (QA found no further production defect), and the code review's P1-1 is still open. The suite is green in both modes
and the Qt-free core is well tested: the helper on fixture bundles, the checkout check, the row
and the view (16 of 26 mutants killed). But 10 mutants survived, and three of them sit on the
spec's central promises: the launchpad's build hold never sees Land on the other three pages
or a running tool (S1, §2.4), the "build passed, now restart" link is never executed by any test
(S2, S3, §2.3, §2.5), and the helper's self-test timeout and no-previous-build branch are
untested (S4, S5). Per the playbook a survivor is a missing test. The real-Mac measures (the
`/Applications` swap, the window in front, the title) are **not verified**: they need the
owner's checklist in §6.

## 1. Success measures (§2) against the tests

| § | Measure | Evidence | Gaps |
|---|---|---|---|
| 2.1 | Lab Hub row: installed build, verdict worded like the others, same `Version` comparison | `test_self_update.py::test_lab_hubs_row_builds_without_install_and_restarts`, `::test_lab_hubs_build_runs_last_and_is_named_as_this_app`, `::test_the_launchpad_report_ends_with_lab_hub_and_a_scoped_one_has_none`. Real Mac, read-only (`self_status(root, running=Path('/Applications/Lab Hub.app'))`, `GIT_OPTIONAL_LOCKS=0`): `version v2.172 \| verdict behind \| cmd None`, note "built at v2.172, but the source is 3 commits further on. Update now leaves Lab Hub alone: the checkout has uncommitted changes, maybe another session's work: Land them first." | Every `self_status` test replaces `build_status` with a canned row, so the verdict itself is never computed on a fixture bundle and fixture repo as §2.1 asks; only the real-Mac run above shows it. The installed text is `v2.172`, not the spec's example `v2.172+g8ea789b` (same format as the other rows) |
| 2.2 | Update now includes Lab Hub, last; others unchanged; nothing after a failure or cancel | `::test_lab_hubs_build_runs_last_and_is_named_as_this_app` (kills M5); stop-on-failure is `Rebuild`'s existing behaviour (`test_apps_tab.py` rebuild tests) | No test runs a two-command Update now where the first fails and asserts Lab Hub's command never starts and no restart is requested (S2) |
| 2.3 | Quits only after the build passed its self-test; helper waits, moves aside, installs, self-tests, starts; window in front; title shows new version | Helper: `::test_the_helper_installs_the_new_build_keeps_the_old_and_opens_it`, `::test_an_old_lab_hub_that_never_quits_means_nothing_is_replaced`; quit path: `::test_the_restart_starts_the_helper_then_quits_when_idle`; end state: `::test_a_held_command_waits_then_runs_and_the_row_says_why` ("Close and restart") | `AppsTab.run_updates` emitting `restart_requested` (`ui/apps_tab.py:864-865`) and its connection to `restart_for_update` (`ui/main_window.py:227`) never run in any test (S2, S3). Window in front and title: **not verified** (real Mac, §6) |
| 2.4 | Running work is never killed: no build, no quit, no helper while a Land plans or runs on any page, or a tool runs | `::test_the_apps_tab_hold_waits_for_busy_work_then_checks_the_checkout` (kills M13), `::test_a_held_command_waits_then_runs_and_the_row_says_why` (M14), `::test_cancel_while_held_starts_nothing`, `::test_the_restart_waits_while_anything_runs` (M4), `::test_the_restart_waits_for_a_running_tool` (M15) | The hold test sets `tab.busy_reasons` by hand; nothing checks that `MainWindow` installs its all-pages `busy_reasons` on each page (S1). `AppsTab._own_busy_reasons` (`ui/apps_tab.py:867-872`) is never executed: no test uses a stub `Lander`, as §2.4 asks, and the planning case ("Land is reading the repos") is unchecked (S6). Wording: "Land is running", not "Land is running on 3 repos" |
| 2.5 | Failed build or self-test: no quit, error shown, installed app untouched. Failed install or installed self-test: old bundle back and started; notice on next start | `::test_a_build_that_fails_its_installed_selftest_is_rolled_back` (M2), `::test_the_helper_refuses_a_new_build_with_no_executable`, `::test_a_restart_that_cannot_start_the_helper_keeps_lab_hub_running` (M21), `::test_a_failed_outcome_names_the_version_and_the_log` (M26), `::test_the_outcome_is_read_once` (M6) | "Build fails, so no quit" is not tested at the `run_updates` level (S2). A self-test that hangs (timeout, S4), a self-test failure with no previous build (S5), a failed second `mv` and a failed `ditto` are untested. Notice text omits the version that failed to install: spec "The update to vX did not install; you are on vY", built "The Lab Hub update did not install (<reason>); you are on vY" (`lab_hub/self_update.py:350`) |
| 2.6 | One previous build kept; update log kept; both under Application Support | `::test_a_second_update_replaces_the_kept_previous_build`, `::test_helper_paths_put_everything_but_the_swap_under_the_update_folder`; real path `~/Library/Application Support/Lab Hub/update` (`UPDATE_DIR`) | `start_helper` opens the log with `"w"`, so only the last update's log survives; "the log of each update is kept" is ambiguous; owner to confirm |
| 2.7 | From source, or not the `/Applications` copy: no update | `::test_a_source_run_or_another_copy_offers_no_update` (M16), `::test_helper_paths_refuse_a_source_run_another_copy_and_a_missing_build` (M17). Real Mac: source run note "...it runs from source here, so there is nothing to restart (run ./build_app.sh --install in its checkout)"; another copy "...this copy runs from /tmp/Lab Hub.app, not /Applications/Lab Hub.app" | `running_bundle()`'s frozen branch (`self_update.py:69-77`) is never run by a test; checked by hand: `running_bundle('/Applications/Lab Hub.app/Contents/MacOS/Lab Hub', True)` -> `/Applications/Lab Hub.app`. Wording differs from §2.7 ("runs the checkout directly") and §8 |

§9.5 list: every named case has a test except "the `ditto` source is missing" (covered only by the
earlier no-executable refusal, not a `ditto` failure) and `verify` skipped for the restarting row
(M10 survived).

## 2. Suite

| Run | Command | Result |
|---|---|---|
| Targeted | `.venv/bin/python -m pytest -p no:warnings -o addopts="" -q tests/test_self_update.py tests/test_apps_tab.py tests/test_progress.py tests/test_progress_window.py` | `177 passed in 26.00s` |
| Full, mode 1 | `.venv/bin/python -m pytest -p no:warnings -o addopts="" -q` | `977 passed in 410.04s (0:06:50)` |
| Full, mode 2 (`pytest.ini`: `--strict-markers`, DeprecationWarning from `lab_hub.*`/`ui.*` as errors) | `.venv/bin/python -m pytest` | `977 passed, 10 warnings in 394.20s (0:06:34)` |
| Flake check | `tests/test_self_update.py` four times | `31 passed` each time (7.6-7.9 s) |

Not run: random order (`pytest-randomly` not installed), per-test timeout (`pytest-timeout` not
installed). There is no CI workflow in the repo (`.github/` absent).

## 3. Mutation check

26 mutants, each applied alone to a scratch copy and run against the four targeted files with
`-x`. **16 killed, 10 survived.**

| # | Mutant (file) | Result | Killed by |
|---|---|---|---|
| M1 | pid wait loop dropped: `while false` (`self_update.py:189`) | killed | `test_an_old_lab_hub_that_never_quits_means_nothing_is_replaced` |
| M2 | rollback `mv "$backup" "$target"` after a failed self-test removed (`:246`) | killed | `test_a_build_that_fails_its_installed_selftest_is_rolled_back` |
| M3 | `checkout_blocker` ignores a dirty tree (`:116`) | killed | `test_uncommitted_changes_hold_the_build` |
| M4 | `restart_for_update` skips `busy_reasons` (`main_window.py:409`) | killed, **by a hang** | `test_the_restart_waits_while_anything_runs` opened a real modal `QMessageBox` (it does not patch `helper_paths` or `QMessageBox`) and blocked until the run was killed after 2 min |
| M5 | Lab Hub's command first, not last (`progress.py:617`) | killed | `test_lab_hubs_build_runs_last_and_is_named_as_this_app` |
| M6 | `read_outcome` does not rename (`self_update.py:338`) | killed | `test_the_outcome_is_read_once` |
| M7 | `MainWindow` does not install `busy_reasons` on the pages (`main_window.py:226`) | **survived** | S1 |
| M8 | `restart_requested` on any successful Update now, Lab Hub or not (`apps_tab.py:864`) | **survived** | S2 |
| M9 | installed self-test timeout never fires (`self_update.py:232`) | **survived** | S4 |
| M10 | `verify` reads `/Applications` for the restarting row (`rebuild.py:261`) | **survived** | S7 |
| M11 | helper accepts a backup path not ending in `Lab Hub.app` (`self_update.py:181`) | **survived** | S8 |
| M12 | `_own_busy_reasons` ignores a planning Land (`apps_tab.py:870`) | **survived** | S6 |
| M13 | `_hold_for` ignores busy reasons (`apps_tab.py:884`) | killed | `test_the_apps_tab_hold_waits_for_busy_work_then_checks_the_checkout` |
| M14 | `Rebuild` ignores a hold reason (`rebuild.py:184`) | killed | `test_a_held_command_waits_then_runs_and_the_row_says_why` |
| M15 | `busy_reasons` ignores running tools (`main_window.py:402`) | killed | `test_the_restart_waits_for_a_running_tool` |
| M16 | `self_status` ignores the another-copy check (`self_update.py:150`) | killed | `test_a_source_run_or_another_copy_offers_no_update` |
| M17 | `helper_paths` ignores the another-copy check (`:274`) | killed | `test_helper_paths_refuse_a_source_run_another_copy_and_a_missing_build` |
| M18 | scoped report also gets the Lab Hub row (`apps_tab.py:761`) | killed | `test_the_launchpad_report_ends_with_lab_hub_and_a_scoped_one_has_none` |
| M19 | helper keeps `$src` after success (`self_update.py:241`) | killed | `test_the_helper_installs_the_new_build_keeps_the_old_and_opens_it` |
| M20 | failed self-test with no previous build: no `exit 1`, so it goes on to `open` a missing bundle (`:250`) | **survived** | S5 |
| M21 | restart quits even when the helper cannot start (`main_window.py:429`) | killed | `test_a_restart_that_cannot_start_the_helper_keeps_lab_hub_running` |
| M22 | `if not dialog.succeeded` disabled (`apps_tab.py:837`) | killed, **incidentally** | `test_apps_tab.py::test_a_failed_in_app_rebuild_opens_no_terminal` (the Terminal branch, not the restart) |
| M23 | `restart_requested` emitted before the success check (`apps_tab.py:836`) | **survived** | S2 |
| M24 | `restart_requested` not connected to `restart_for_update` (`main_window.py:227`) | **survived** | S3 |
| M25 | first-start notice not posted to the menu bar (`main_window.py:441`) | **survived** | S9 |
| M26 | failed-outcome notice drops the log path (`self_update.py:351`) | killed | `test_a_failed_outcome_names_the_version_and_the_log` |

## 4. Branch coverage of changed lines

`coverage run --branch` over the four targeted files:
- `lab_hub/self_update.py` (new): 85% (147 statements, 42 branches). Missed: `59` (`is_self`, which nothing calls: dead code), `69-77` (`running_bundle` frozen path), `87-88`, `98-99`, `115` (git status failure), `158` (no `build_app.sh`), `277`, `339-340`. The bash helper is outside Python coverage; its branches are listed under M9, M11, M20 and §1 2.5.
- `lab_hub/progress.py`: changed statements 33/33; branches 13/16 (`BuildModel.hold`/`refuse` on a row not WAITING, and `hold(key, None)` clearing).
- `ui/apps_tab.py`: changed statements 29/34; **missed `766-767`** (own-row failure kept the others), **`865`** (`restart_requested.emit()`), **`869`, `871`** (`_own_busy_reasons` with a running or planning Land).
- `ui/main_window.py`: 43/46; missed `422` (no checkout), `437` (no outcome), `610` (`run()` call site).
- `ui/progress_window.py`: 17/17; branches 6/8. `ui/rebuild.py`: 23/23; branches 9/10 (`_holding` unchanged on a repeated reason).

## 5. Test quality and ranked gaps

Model calls: this change calls no model, so the live-eval and fixture rule does not apply. No test
here needs the network. The helper tests need macOS (`ditto`, `/bin/bash` 3.2, checked:
`GNU bash, version 3.2.57`); fine on the owner's Mac, but they would fail on a Linux runner.

Ranked gaps (P1 first). All are missing tests unless marked otherwise.
1. **S1 (P1), M7.** No test that `MainWindow` gives every Apps page its all-pages `busy_reasons`. Without the wiring, Update now from the launchpad builds Lab Hub while a Land runs on another page or a tool runs, which is §2.4's "on any page" (the restart check still holds the quit). Test: a `window` fixture, stub busy on `backup_sync_tab`, assert `window.apps_tab._hold_for(cmd)(cmd)` names it.
2. **S2 (P1), M8, M23, M22 incidental.** `run_updates` -> `restart_requested` never runs in a test (`apps_tab.py:865` uncovered). Test: a launchpad `AppsTab` with a stub `Rebuild` that succeeds or fails; assert the signal fires only on success and only when the view's `restarts` command was in the run.
3. **S3 (P1), M24.** `restart_requested` -> `restart_for_update` is not connected in any test. One `window`-fixture test emitting the signal with `start_helper`/`quit` patched.
4. **Test fragility (P1).** `test_the_restart_waits_while_anything_runs` and `test_the_restart_waits_for_a_running_tool` leave `helper_paths` and `QMessageBox.warning` unpatched, so a regression opens a real modal dialog and hangs the suite instead of failing (M4). With no `pytest-timeout`, that hang has no limit. Patch both in those tests.
5. **S4 (P2), M9.** No test of an installed copy whose `--selftest` hangs: the fixture's `LAB_HUB_UPDATE_SELFTEST_S=5` is there but never reached. A stub that `sleep 30`s with `SELFTEST_S=1` should end `rolled_back`.
6. **S5 (P2), M20.** No test of a failed self-test with no previous build (`had_old=0`): should write `rolled_back`, exit 1 and open nothing.
7. **S6 (P2), M12.** `_own_busy_reasons` is never run with a stub `Lander` (running / planning / idle), as §2.4 asks; every test replaces it.
8. **§2.1 verdict (P2).** `self_status` tests replace `build_status`; no test computes the verdict from a fixture bundle's stamp against a fixture repo. Verified once on the real Mac above.
9. **S7 (P3), M10.** No test that the restarting row's verify does not read `/Applications` (a stub `verify` that records its calls would do).
10. **S8 (P3), M11.** No test for the helper refusing a backup path not ending in `Lab Hub.app`.
11. **S9 (P3), M25.** `test_the_first_start_after_an_update_says_how_it_went` does not assert `fake_tray.notices`, nor the failed-outcome text.
12. **Weak assertions (P3).** `test_self_update.py:67` `assert proc.wait(timeout=30) is not None` cannot fail (only the timeout can); `test_the_helper_takes_its_values_as_parameters_never_in_its_text` checks a raw string for `{`, which cannot interpolate anyway.
13. **Spec wording (for the owner or Document, not QA blockers).** §2.5/§8 notice lacks the version that failed; §8 end line lacks the version ("Built and tested v2.180."); §2.7/§8 source-run text differs; §5.2's pre-build row text "Will update after Land finishes" is not shown at the review step (the wait shows only once Update now runs); §2.6 log kept only for the last update. The spec's status line still says "waiting for the owner's Architect gate" and "Nothing built", while `approvals.jsonl` records the Architect approval at 15:28.
14. **Dead code (P3).** `self_update.is_self` (`:58`) has no caller.

## 6. Manual checklist for the owner (real Mac)

These cannot run in CI. Record a screenshot or the stated file contents for each.
Updated 2026-11-20 for amendment 1 (spec §11, ADR 0006): Lab Hub now builds in a private clone,
`update/snapshot/lab_hub`, at the `main` commit its row records, so the shared checkout may be
dirty or move during the run; the new item A2 checks exactly that, and D no longer needs a quiet
checkout.
Updated in the second Verify (2026-11-17) for the staged copy, the `broken` outcome, the
review-step wait note and the restart refusal; the support folder is
`~/Library/Application Support/Lab Hub/update/` below.

Preparation
- [ ] Land this change on `main`. The shared checkout may stay dirty or on another branch.
- [ ] Install it once by hand: `./build_app.sh --install`, then menu bar item > Quit, then open Lab Hub from `/Applications`. The copy that runs must already contain self-update, because the update is driven by the old copy.
- [ ] Add one commit to `main` (for example a CHANGELOG line), so the installed build is behind. Note the title bar version (screenshot "before").

A. Update from Check builds
- [ ] Apps page > Check builds: the last row is "Lab Hub (this app)" with the installed version, "N commits further on" and, at the end of its note, "Update now builds <sha7>" with `main`'s commit.
- [ ] Update now: any other behind app rebuilds first; Lab Hub's build runs last in the same window and the live output shows the `git clone` into `update/snapshot/lab_hub`, then `build_app.sh` and its self-test there.
- [ ] End line: "Built and tested. Lab Hub restarts to install the new build when you close this window." Button: **Close and restart**.
- [ ] Click it. Lab Hub first copies the build to `update/staged/Lab Hub.app` (a second or two) and removes `update/snapshot/lab_hub`, then quits; no Terminal opens; within about a minute Lab Hub starts again.
- [ ] If instead a box "Lab Hub was not restarted" appears, note its text. Lab Hub must keep running and `/Applications` must be untouched. Another session's commits or edits must no longer cause it.

A2. Other sessions working meanwhile (amendment 1)
- [ ] During Lab Hub's build, edit a tracked file in the shared checkout without committing, and commit something else to `main` from another session. Then click **Close and restart**: Lab Hub restarts on the commit the row showed (title), not the newer one, and the edit is not in it.
- [ ] `git -C <lab_hub checkout> worktree list` never shows the snapshot, and the checkout has no `dist.noindex/` from this run.
- [ ] Check builds afterwards offers the newer `main` commit. With only uncommitted edits in the checkout, Lab Hub's row is up to date and says the edits are in no build until committed to `main`.

B. Window in front
- [ ] Without clicking the menu bar item or the Dock, the new Lab Hub window is in front and has focus (screenshot "after"). If it is not, note it: the spec's fallback (§6, a menu bar notice "Click to open") was not built.

C. Title and notice
- [ ] The title shows the new version (compare with "before").
- [ ] The status bar shows "Lab Hub updated to vX." for about 30 s, and the menu bar item posts the same notice.
- [ ] `update/outcome.seen` has three lines: `ok`, a sentence, the new version; `update.log` (mode 0600) lists waiting, copying, self-testing; `previous/Lab Hub.app` is the old version; `update/staged/` no longer holds a `Lab Hub.app`; `update/lock` and `/Applications/Lab Hub.app.updating` do not exist.
- [ ] Apps that Lab Hub started in the background (the sync companions) are still running.

D. Forced self-test failure and rollback
- [ ] Add another commit to `main`, run Update now and wait for **Close and restart**. Do not click yet.
- [ ] In Terminal, make the new build fail its self-test: `cd "$HOME/Library/Application Support/Lab Hub/update/snapshot/lab_hub/dist.noindex/Lab Hub.app/Contents/MacOS" && mv "Lab Hub" "Lab Hub.real" && printf '#!/bin/sh\nexit 1\n' > "Lab Hub" && chmod +x "Lab Hub"`.
- [ ] Click **Close and restart**. The stub is staged with the rest of the bundle (the snapshot's HEAD and the stamp still match the recorded commit, whatever the shared checkout did meanwhile). Lab Hub quits and comes back on the **old** version (title).
- [ ] The notice reads "The update to vNEW did not install (the installed copy failed its self-test; the previous build is back); you are on vOLD. Log: <path>", and `outcome.seen` starts with `rolled_back`.
- [ ] `/Applications/Lab Hub.app` is the old build and starts normally; no `/Applications/Lab Hub.app.updating` is left.
- [ ] Nothing to clean up: staging removed the snapshot, stub included.

D2. If a `broken` notice ever appears (do not force it on the real `/Applications`)
- [ ] A `broken` outcome means the helper could not put things right and **opened nothing**, so the notice is seen only when Lab Hub is next started by hand. It reads "The update to vNEW did not install (..., the previous build could not be put back; it is at <support>/update/previous/Lab Hub.app); you are on ...".
- [ ] Recovery: if `/Applications/Lab Hub.app` is missing or does not start, quit any Lab Hub, then in Terminal `mv "$HOME/Library/Application Support/Lab Hub/update/previous/Lab Hub.app" /Applications/` (only when `/Applications/Lab Hub.app` does not exist), and open it. Keep `update.log` for the report.

E. A Land during Update now
- [ ] Start Land all (or a Land on a repo with a long test run) on the Apps page, then open Check builds while it runs: the Lab Hub row's note ends "Will update after this finishes: Land is running." (or "Land is reading the repos" while it plans). Press Update now.
- [ ] Other apps rebuild; the Lab Hub row then reads "Waiting" with the reason "Waiting: Land is running. Lab Hub builds when that finishes", the live output shows `[waiting — ...]` once, and no "No output for 1:00" appears however long it waits; Cancel is available.
- [ ] If the Land leaves the checkout dirty, moves `main` or switches branch, Lab Hub still builds the commit its row recorded and **Close and restart** is offered (amendment 1; before it, the row ended "Not rebuilt").
- [ ] Lab Hub's build starts only after Land finishes; Land completes normally (nothing killed).
- [ ] Repeat with the Land on another page (Backup & sync, Unblock tracker or Backstage) and with a tool (Convert, Images, Video or Narrator) running: the wait must name it too (the wiring is now tested; the end-to-end run is not, see N29 below).
- [ ] Cancel while waiting: the run ends as cancelled, Lab Hub is not built and does not quit.
- [ ] With a tool started after the build but before **Close and restart** (if the modal window allows it at all): the status bar says Lab Hub restarts when it finishes, and it restarts only then.

## Verify of amendment 1: snapshot build (2026-11-20)

Spec §11–§13, ADR 0006. Run by the orchestrating session after the independent code review and
security review (`docs/audit/self-update-snapshot-code-review.md`, `…-security.md`); this pass is
mechanical (mutants, suite, one real build), not an independent judgement.

**Success measures against tests** (`tests/test_self_update.py`):

| §11.2 | Test(s) |
|---|---|
| 1. builds the recorded commit in a snapshot | `test_update_now_builds_the_recorded_commit_in_a_private_snapshot`, `test_lab_hubs_row_builds_main_in_a_snapshot_without_install_and_restarts` |
| 2. checkout cannot block or contaminate | `test_the_shared_checkout_changing_never_blocks_or_enters_the_update` (dirtied/moved × before/after the build), `test_a_dirty_checkout_no_longer_holds_the_update`, `test_on_another_branch_the_row_still_builds_main`, `test_the_apps_tab_hold_waits_for_busy_work_but_not_for_the_checkout` |
| 3. Close and restart installs what was built | `test_close_and_restart_stages_the_recorded_commit_after_the_checkout_moved`, `test_a_build_from_another_commit_is_not_staged`, `test_a_stamp_that_is_not_the_recorded_commit_is_not_staged`, `test_close_and_restart_refuses_a_command_lab_hub_did_not_make` |
| 4. uncommitted work is no reason to update; no downgrade | `test_uncommitted_edits_alone_are_no_reason_to_update`, `test_level_with_main_while_on_another_branch_is_current`, `test_a_build_ahead_of_main_is_not_offered_a_downgrade`, `test_a_build_beside_main_is_held_not_replaced` |
| 5. nothing left behind, no worktree | `test_update_now_builds_the_recorded_commit_in_a_private_snapshot` (snapshot gone, `git worktree list` unchanged) |
| 6. rest unchanged | the 65 earlier tests still pass |

Hardening from review and security: `test_the_build_runs_in_paths_with_spaces_and_quotes[zsh|bash]`,
`test_no_global_or_template_hook_runs_while_the_snapshot_is_made`,
`test_a_symlinked_snapshot_folder_stops_the_build_before_removing_anything`.

**Mutation check.** 15 mutants of `lab_hub/self_update.py`, each planted alone, the module's tests
run, the file restored (SHA-256 compared): all 15 killed.
M1 symlink guard removed · M2 clone without `core.hooksPath=/dev/null` · M3 clone without
`--template=` · M4 no `chmod 700` · M5 build the working tree instead of the commit · M6
`main_commit` reads `HEAD` · M7 staging skips the snapshot-HEAD check · M8 staging skips the stamp
check · M9 snapshot not removed · M10 `planned_commit` trusts any match · M11 level-with-main not
current · M12 ahead-of-main check skipped · M13 ahead treated as diverged · M14 unstamped build not
explained · M15 staging accepts no recorded commit.

**Real build.** `build_command` run through `/bin/zsh -c` against the shared checkout's `main`
(`166be4e`), with `UPDATE_DIR` under a scratch `Application Support/Lab Hub/update` (spaces): the
real `build_app.sh` (PyInstaller, prune, codesign) finished in 122 s, its self-test printed `OK`,
`stage_build` staged v2.228 stamped `166be4e`, the snapshot was removed, and `git worktree list` of
the shared repository showed no new entry. Nothing was installed.

**Suite:** full suite on `4fbaab7`'s code: 1284 passed, 1 skipped (8 min 59 s); `tests/test_self_update.py` 94 passed.

**Not verified:** the real `/Applications` swap from a snapshot build and A2 and D of §6, which the
owner runs on the real Mac.

## Second Verify (2026-11-17)

Scope: the same uncommitted change after the fixes listed in spec §10 (review P1-1, P2-1 to P2-3;
security P2-1, P2-2; QA gaps 1-8). Same rules as the first pass: production and test code
untouched; every mutant ran in a scratch copy outside the repo with `HOME` pointed at an empty
scratch folder (nothing was written there, so no test reaches the real support folder), each
mutated file was restored and byte-compared with the repo afterwards (`cmp`: identical), and the
repo's `git diff --stat` matched the start except `docs/foundry/activity.jsonl`, where another
session (`land-fast`) added two lines at 16:44 and 16:46. Playbook `last-reviewed: 2026-10-14`,
`status: current` (34 days, not stale). `app-context.md` `## Commands` and `## Test bar` are still
placeholders.

### Verdict

**FAIL, narrowly.** No production defect was found, and every fix the review and security asked
for is now covered by a test that fails when the fix is removed. All 12 mutants from the first pass
(M7-M12, M20-M25, adapted to the moved code) are killed, the restart tests can no longer hang the
suite, and both full-suite modes are green. It fails on one P1 missing test: **N29**.
`run_updates` can stop passing the hold to `Rebuild`, and all 208 targeted tests still pass. In that
case Lab Hub would build while a Land runs, which is the central promise of §2.4 and the reason in
§9.4 for holding the build. Below the bar but worth closing: **N10**, because spec §10 says "an EXIT
trap writes an outcome", and no test makes the script stop early. A test for N29 and one for N10
are enough to turn this into a pass. The other survivors are P3; the owner can defer them.

### Suite

| Run | Command | Result |
|---|---|---|
| Targeted (scratch copy) | `.venv/bin/python -m pytest -p no:warnings -o addopts="" -q tests/test_self_update.py tests/test_apps_tab.py tests/test_progress.py tests/test_progress_window.py` | `208 passed in 42.06s` |
| Full, mode 1 | `.venv/bin/python -m pytest -p no:warnings -o addopts="" -q` | `1008 passed in 430.74s (0:07:10)` |
| Full, mode 2 (`pytest.ini`: `--strict-markers`, DeprecationWarning from `lab_hub.*`/`ui.*` as errors) | `.venv/bin/python -m pytest` | `1008 passed, 10 warnings in 414.30s (0:06:54)` |
| Flake check | `tests/test_self_update.py` four times in a row, plus about 40 more runs as mutation baselines under load | `62 passed` each time (19.7-20.1 s); no timing failure seen |

Still not run: random order and a per-test timeout, because `pytest-randomly` and `pytest-timeout`
are not in the venv. There is no CI workflow. The helper tests need macOS (`/usr/bin/ditto`,
`/bin/bash` 3.2), so they would fail on a Linux runner unless they are marked.

### Mutation check

44 mutants, each applied alone. Each ran with `-x`, first against `tests/test_self_update.py`;
each survivor was then re-run against all four targeted files. **35 killed, 9 survived.**

| # | Mutant (file) | Result | Killed by |
|---|---|---|---|
| M7 | pages not given the window's `busy_reasons` (`main_window.py:225-226`) | killed | `test_every_apps_page_asks_the_whole_window_what_is_busy` |
| M8 | `built_self = True` (`apps_tab.py:852`) | killed | `test_the_restart_is_asked_for_only_after_lab_hubs_build_passed[True-skipped2-False]` |
| M9 | self-test timeout never fires (`self_update.py:384`) | killed | `test_a_selftest_that_hangs_is_stopped_and_rolled_back` |
| M10 | `verify` reads `/Applications` for the restarting row (`rebuild.py:281`) | killed | `test_a_held_command_waits_then_runs_and_the_row_says_why` |
| M11 | backup name not checked (`self_update.py:287`) | killed | `test_the_helper_refuses_a_path_that_is_not_a_lab_hub_app[backup]` |
| M12 | planning Land not busy (`apps_tab.py:896`) | killed | `test_a_page_is_busy_while_land_plans_or_runs` |
| M20 | no previous build: opens the target anyway (`self_update.py:368-369`) | killed | `test_a_failed_new_build_with_no_previous_build_opens_nothing` |
| M20b | no previous build: failed new build left installed (`:368`) | killed | same |
| M22 | `if not dialog.succeeded` disabled (`apps_tab.py:846`) | killed | `test_the_restart_is_asked_for_only_after_lab_hubs_build_passed[False-skipped1-False]` |
| M23 | staging and restart requested before the success check (`apps_tab.py:844-845`) | killed | `...[True-skipped0-True]` |
| M24 | `restart_requested` not connected (`main_window.py:227`) | killed | `test_the_restart_signal_reaches_the_window` |
| M25 | first-start notice not posted to the menu bar (`main_window.py:442-443`) | killed | `test_the_first_start_after_an_update_says_how_it_went` |
| N1 | no `gone` check before moving the installed app aside (`self_update.py:338`) | killed | `test_a_previous_build_that_cannot_be_cleared_means_nothing_is_replaced` |
| N2 | no `gone` check before `ditto` into `$target.updating` (`:327`) | **survived** | gap 2 |
| N3 | restore without the executable check (`:361-362`) | **survived** | gap 4 |
| N4 | `stage_build` symlink check dropped (`:219`) | killed | `test_a_symlinked_build_folder_is_not_staged` |
| N5 | `stage_build` commit check reduced to "has a commit" (`:228`) | killed | `test_a_build_from_another_commit_is_not_staged` |
| N6 | `Skipped` sets `_failed` (`rebuild.py:194`) | killed | `test_a_skipped_lab_hub_does_not_fail_the_run` |
| N7 | `helper_env` passes `os.environ` through (`self_update.py:443`) | killed | `test_the_helper_gets_a_fixed_environment` |
| N8 | lock removed (`mkdir -p`, `:296`) | killed | `test_a_second_helper_is_turned_away_while_one_runs` |
| N9 | late reopen removed (`:319`) | killed | `test_an_old_lab_hub_that_quits_late_is_opened_again` |
| N10 | EXIT trap writes nothing on an early stop (`:269`) | **survived** | gap 3 |
| N11 | `helper_paths` takes any bundle, not only the staged copy (`:425`) | killed | `test_helper_paths_take_only_the_staged_copy` |
| N12 | helper's symlinked-source check dropped (`:289`) | killed | `test_the_helper_refuses_a_symlinked_or_identical_new_build` |
| N13 | helper's number check dropped (`:283-285`) | killed | `test_the_helper_refuses_numbers_that_are_not_numbers` |
| N14 | failed move-aside always says `not_replaced` and opens (`:348`) | **survived** | gap 5 |
| N15 | `restart_for_update` ignores busy work (ex-M4, `main_window.py:414`) | killed in 19 s, **no hang** (first pass: a modal hang) | `test_the_restart_waits_while_any_page_lands` |
| N16 | hold returns the blocker (waits forever) instead of `Skipped` (`apps_tab.py:917`) | killed | `test_the_apps_tab_hold_waits_for_busy_work_then_checks_the_checkout` |
| N17 | `BuildModel.hold` never marks the row held (`progress.py:751`) | killed | `test_a_held_command_waits_then_runs_and_the_row_says_why` |
| N18 | every poll repeats the `[waiting — ...]` line (`rebuild.py:209`) | killed | same |
| N19 | Cancel leaves the waiting reason (`rebuild.py:147`) | killed | `test_cancel_while_held_starts_nothing_and_clears_the_wait` |
| N20 | `stage_build` skips the checkout check (`self_update.py:223-225`) | killed | `test_a_checkout_that_changed_after_the_build_is_not_staged` |
| N21 | skipped Lab Hub still restarts (`apps_tab.py:852`) | killed | `...[True-skipped2-False]` |
| N22 | helper accepts source equal to target (`self_update.py:289`) | killed | `test_the_helper_refuses_a_symlinked_or_identical_new_build` |
| N23 | no `free "$target"` check after the move aside (`:345`) | **survived** | gap 5 |
| N24 | restore moves the backup onto a target it did not clear (`:361`) | killed | `test_a_build_that_fails_its_installed_selftest_is_rolled_back` |
| N25 | EXIT trap not installed (`:274`) | killed (the lock is left behind) | `test_the_helper_installs_the_new_build_keeps_the_old_and_opens_it` |
| N26 | `stage_build` ignores a staged folder it could not clear (`:239`) | **survived** | gap 6 |
| N27 | helper's executable check dropped (`:292`) | killed | `test_the_helper_refuses_a_new_build_with_no_executable` |
| N28 | `stage_build` ignores a failed `ditto` (`:243`) | **survived** | gap 6 (`helper_paths` would still refuse the missing bundle later) |
| N29 | `run_updates` passes no `hold` to `Rebuild` (`apps_tab.py:839`) | **survived** | gap 1 |
| N30 | restart does not set `_quitting` (`main_window.py:432`) | killed | `test_the_restart_starts_the_helper_then_quits_when_idle` |
| N31 | `helper_paths` "same folder" check dropped (`:427`) | **survived**, near-equivalent | unreachable while the staged copy must equal `UPDATE_DIR/staged/Lab Hub.app` (defence in depth) |
| N32 | restarting row reads "Installed" (`progress.py:831`) | killed | `test_a_held_command_waits_then_runs_and_the_row_says_why` |

### Success measures (§2) mapped again

| § | Evidence now | Still open |
|---|---|---|
| 2.1 | `test_the_row_is_computed_from_a_real_stamp_and_checkout` (no stubs: stamp one commit behind reads `behind`, `version.behind == 1`), `test_lab_hubs_row_builds_without_install_and_restarts`, `test_the_launchpad_report_ends_with_lab_hub_and_a_scoped_one_has_none` | Real-Mac row text (§6 A) |
| 2.2 | `test_lab_hubs_build_runs_last_and_is_named_as_this_app`, `test_the_restart_is_asked_for_only_after_lab_hubs_build_passed` (passed, failed, skipped), `test_a_skipped_lab_hub_does_not_fail_the_run` | none in tests |
| 2.3 | helper: `..._installs_the_new_build_keeps_the_old_and_opens_it`, `..._never_quits_...`, `..._quits_late_is_opened_again`; app: `test_the_restart_signal_reaches_the_window`, `..._starts_the_helper_then_quits_when_idle`; staging: `test_the_tested_build_is_staged_out_of_the_checkout` | Window in front, title: **not verified** (§6 B, C) |
| 2.4 | `test_a_page_is_busy_while_land_plans_or_runs` (stub `Lander`), `test_every_apps_page_asks_the_whole_window_what_is_busy`, `test_the_restart_waits_while_any_page_lands`, `..._for_a_running_tool`, `test_the_apps_tab_hold_waits_for_busy_work_then_checks_the_checkout`, `test_a_held_command_waits_then_runs_and_the_row_says_why` | **N29**: "no build while busy" is tested on the hook and on `Rebuild`, but not on the call that joins them |
| 2.5 | rollback, hang, no previous build, unremovable previous build (P1-1 A), unremovable failed build reported `broken` (P1-1 B), cannot stage, helper cannot start, notice naming both versions and the log | N2, N3, N14, N23 (rare filesystem failures); N10 (early stop) |
| 2.6 | `test_a_second_update_replaces_the_kept_previous_build`, `test_helper_paths_put_everything_but_the_swap_under_the_update_folder`; log mode 0600 asserted | none |
| 2.7 | `test_a_source_run_reads_as_running_the_checkout`, `test_another_copy_offers_no_update`, `test_helper_paths_refuse_...`, `test_the_running_bundle_is_the_app_around_the_executable` (frozen branch now run) | none |

### Branch coverage of changed lines

`coverage` 7.17.3 (scratch install, not the venv), `run --branch` over the four targeted files:
- `lab_hub/self_update.py` (new): 194/217 statements, 59/70 branches (88%). Missed: `80-81`, `85` (`running_bundle` resolve error, no `.app` parent), `95-96`, `107-108`, `119`, `128` (git cannot run or status fails), `186` (no `build_app.sh`), `203-207` (stamp read failures), `222` (`stage_build` with no executable), `234-235` (version fallback), `240` (N26), `244` (N28), `428` (N31), `497-502` (`read_outcome` OSError). The bash helper is outside Python coverage; the mutation table covers its branches.
- `ui/rebuild.py`: changed 35/35 statements, 8/8 branches. `lab_hub/progress.py`: 39/39, branches 17/20 (`hold`/`refuse` on a row that is not WAITING, `refuse` with no units). `ui/progress_window.py`: 26/26, branches 11/14 (`command_held`/`command_refused` with an unknown key).
- `ui/apps_tab.py`: 54/57. Missed `775-776` (the own-row check raising: the other rows still show) and `884` (`_restart_on` with no checkout).
- `ui/main_window.py`: 44/47. Missed `412` (`restart_for_update(None)`), `439` (no outcome), `612` (the `run()` call site).

### Test quality

- Fixed since the first pass: the restart tests patch `start_helper`, `helper_paths` and `QMessageBox.warning` through the `no_quit` fixture, so N15 (ex-M4) fails in 19 s instead of hanging; the `proc.wait(...) is not None` assertion is gone; the helper tests use an `open` shim and patched module constants, never `/Applications` or the real support folder.
- `_FakeRun` in the `run_updates` tests stores `hooks` but no test reads them. That is why N29 survives.
- `isolated_config` (`tests/conftest.py:38`) patches `config.SUPPORT_DIR`, but `self_update.UPDATE_DIR` was computed from the real folder at import. Every test that reaches it today patches it or the functions that use it, and the scratch-`HOME` runs wrote nothing. Still, a future test that calls `stage_build` or `start_helper` without the `lab` fixture would write to the real `~/Library/Application Support/Lab Hub/update`. P3: patch `UPDATE_DIR` in `isolated_config`.
- `test_the_helper_takes_its_values_as_parameters_never_in_its_text` still checks a raw string for `{`, which cannot interpolate anyway (P3, unchanged).
- Wall-clock: the helper tests rely on 0.25 s polls and 2-3 s limits (`WAIT_S=2`, `_orphan(3)`, `LATE_WAIT_S=3`). They were stable here, including under mutation load, but they are the first tests to suspect on a slow runner.
- Model calls: this change calls no model, so the fixture and live-eval rule does not apply. No test needs the network.

### Ranked gaps (second pass)

1. **N29 (P1).** No test that `run_updates` hands the hold to `Rebuild`. Test: in `test_the_restart_is_asked_for_only_after_lab_hubs_build_passed`, or a new test, have `_FakeRun` keep its hooks; with `tab.busy_reasons = lambda: ["Land is running"]`, assert `hooks["hold"]("build lab hub")` names Land and `hooks["hold"]("echo x") is None`.
2. **N2 (P2).** No test of a leftover `$target.updating` that cannot be cleared. Without the check, `ditto` merges into the stale folder and a mixed bundle is installed; this is the same class as review P1-1. Test: pre-create `Lab Hub.app.updating` beside the fixture target with a 0500 subfolder; expect `not_replaced`, the old marker, and the target opened.
3. **N10 (P2).** Spec §10 says "an EXIT trap writes an outcome if the script stops early", and nothing tests it. Bash 3.2 runs the trap on SIGTERM (checked here). Test: start the helper on a live PID, SIGTERM it during the wait, and expect an outcome file. Also note the trap's text, "the update stopped part-way; the previous build is at $backup", is wrong when it stops during the wait: then nothing has moved and `previous/` may be empty or older (P3 wording).
4. **N3 (P3).** Restore can report `rolled_back` and open a backup that has no executable. Test: a fixture backup without an executable, with the new build failing its self-test, should end `broken`.
5. **N14, N23 (P3).** The failed move-aside path (`not_replaced` vs `broken`, and the `free "$target"` check) is untested; it needs an unmovable `/Applications` bundle, for example a 0500 parent of the fixture target.
6. **N26, N28 (P3).** `stage_build`'s "could not clear" and failed-`ditto` branches are untested (a failing `ditto` argument is already injectable).
7. **N31 (P3).** Near-equivalent; leave it, or test with `UPDATE_DIR` inside the fixture `Applications`.
8. **P3 housekeeping.** Patch `UPDATE_DIR` in `isolated_config`; the `{` assertion; the spec's status line already says "reviewed, verified and secured, with all P1/P2 findings fixed (§10)" before this Verify ended. It should say verify is pending until gap 1 is closed.

### Not verified on the real Mac

All of these need the owner, through §6 (updated above):
- the `/Applications` swap;
- the staged copy at `update/staged/`;
- the window coming to the front, and the title showing the new version;
- the outcome notice in the status bar and the menu bar;
- the forced self-test rollback;
- a Land or a tool running during Update now, on each page;
- the "Lab Hub was not restarted" box when the checkout moves between the build and Close;
- the recovery from a `broken` outcome (§6 D2, by reading only: do not force it).

The sync companions surviving the restart is also unverified.

## Owner's manual check, run 2026-11-17 (sections A–D)

Run by Claude Code in the owner's session, at the owner's request; E was skipped.
Before: installed Lab Hub v2.177 (`5e5a19f`); this commit moves `main` ahead of it.


First attempt (20:58–21:10): stopped before the restart. While Update now was running, the
owner's Lab Hub release in another session installed v2.199 (`a7bcc34`) directly with
`build_app.sh --install`, so the self-update path never ran (no `update/` folder was made).
Rerun from installed v2.199; this commit moves `main` ahead of it.
