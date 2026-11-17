# Review: self-update (code-reviewer, 2026-11-17)

This is an independent, read-only review of the uncommitted `self-update` change. The reviewer could not write files, so the orchestrator saved its findings here unchanged in substance. The playbook `docs/playbooks/code-reviewer.md` is current (last reviewed 2026-10-14).

**Ran:**
- `tests/test_self_update.py`: 31 passed in 7.67 s.
- Two scripts that run the real `HELPER_SCRIPT` against fixture bundles, which reproduced P1-1.
- `stat -f %d`: `/Applications` and `~/Library/Application Support` are on the same device, so each `mv` is a rename.

**Overlap:** P1-1 and P2-2 were found independently of the security review (its P2-1 and P2-2).

## P1-1: Swap and rollback ignore `rm -rf` and `mv` failures

Lab Hub can end up as a folder that is not an app.

**Where:** `lab_hub/self_update.py`. The cleanup of `$staged` and `$backup`, the two swap renames, and the rollback `rm -rf "$target"; mv "$backup" "$target"` are all unchecked.

**Scenario A (reproduced):**
1. The previous `update/previous/Lab Hub.app` cannot be fully removed. The test used a read-only subfolder; in real use, the Finder `.DS_Store` race that `build_app.sh` retries for would do the same.
2. `mv "$target" "$backup"` nests the old app inside it.
3. The new build fails its self-test.
4. The rollback restores the wrong folder.

Result: `Applications/Lab Hub.app/Lab Hub.app/...`, with no executable at the top level. The outcome reads `rolled_back` "the previous build is back", and `open` is called on the broken path.

**Scenario B (reproduced):** the failed new build cannot be fully removed during rollback, which causes the same nesting.

**Also:**
- If the old `.updating` folder cannot be removed, `ditto` merges the new build into its stale files.
- With no old build, the message still says "the old one is back".

**Fix:**
- Check every `rm -rf` and retry it once.
- Require that the destination does not exist before each `mv`.
- Check the restore `mv`. If it fails, write a distinct `broken` outcome that names where the previous build is, and do not call `open`.
- Add tests for each path.

## P2-1: A refused Lab Hub fails the whole Update now

**Where:** `ui/rebuild.py` (the hold-refusal path sets `_failed`), `ui/progress_window.py` (`update_ended`), `ui/apps_tab.py` (`run_updates` returns early).

**Scenario:**
1. Sentinel and Lab Hub are both behind, and Provisio needs Terminal.
2. Another session edits `lab_hub` while Sentinel is building.
3. The hold then refuses Lab Hub.

**Result:**
- The window says "A rebuild failed", although every rebuild that ran succeeded.
- Provisio's Terminal installer does not open.
- The "Rebuilt N apps" message is lost.

Spec §5.3 says Update now *skips* Lab Hub in this case.

**Fix:** give a refusal its own result. Lab Hub is skipped, the row says why, the by-hand installers still open, and there is no restart.

## P2-2: Nothing re-checks the checkout or the bundle at restart

**Where:** `ui/main_window.py` `restart_for_update`. `checkout_blocker` runs only in the hold, before the build.

**Scenario:**
1. The window stays open until "Close and restart", or the restart waits behind a Land.
2. Meanwhile another session switches the shared checkout to a branch, or runs `./build_app.sh` with uncommitted edits.
3. The helper installs that bundle, which is exactly what spec §5.3 forbids.

**Fix:**
- When the build succeeds, copy the bundle into `UPDATE_DIR` and record its commit.
- At restart, run `checkout_blocker` again and require HEAD to match.
- Pass the staged copy to the helper.

## P2-3: Restart emit and MainWindow wiring are untested

**Where:** `restart_requested.emit()` in `run_updates`, and `page.busy_reasons = self.busy_reasons` and `restart_requested.connect` in `MainWindow`.

**Why it matters:** no test covers either.
- If the emit drifts outside the success-only path, Lab Hub would quit and install a stale `dist.noindex` bundle.
- If the wiring is dropped, Lab Hub would build while another page is landing.

**Fix:**
- Add `_FakeRebuild` tests in which the signal is emitted only when the run succeeded with the restart command.
- Add a MainWindow test of the wiring.

## P3

1. **The wait looks stuck after 60 s.** The window shows "No output for 1:00. Still running." because the model is touched only when the hold reason changes. The row also reads "Next · ~N left", with an estimate that assumes the build has started.
   - Fix: touch the model on each poll, and add a held state with no stale warning and no estimate.
2. **Cancel during a wait leaves the stale reason** "Waiting: …" on the row, now "Not rebuilt".
   - Fix: clear the reason when the run ends.
3. **`checkout_blocker` reports "detached HEAD" when git is missing or timed out.**
   - Fix: tell those failures apart.
4. **The failure notice does not name the version it tried to install** (spec §2.5 and §8 say "The update to vX did not install").
   - Fix: write the built version into the outcome file.
5. **When Lab Hub runs from source, its row is "Not now" and counts as "needs you".** Spec §2.7 says it should read "runs the checkout directly", as other source apps do.
6. **Stale docs:**
   - The spec status line says "Nothing built".
   - The ADR still says "proposed".
   - The ADR claims `rm -rf` runs only on target-derived paths, but the helper also runs `rm -rf "$src"`.
7. **The verify skip for Lab Hub's row is not pinned by a test.** Removing it passes every test, after which a test would read the real `/Applications/Lab Hub.app`.
8. **Helper tests are missing for:**
   - a missing source: the case in §9.5 stops at the pre-check, never at `ditto`;
   - an `mv` that fails;
   - a backup path with the wrong name;
   - an old process that exits after the 60 s wait, in which case nothing reopens.
9. **The conditional `Rebuild(..., hold=hold) if hold else Rebuild(...)` exists only for test fakes.**
   - Fix: let the fakes take `**kwargs`.

## Checked and sound

- **Qt lifetime:** the retry timer returns early once the run has ended, and every close route goes through `cancel()`.
- **Busy check and quit:** they run in one GUI-thread call, under an ApplicationModal window.
- **Restart:** it is emitted only after `dialog.succeeded`.
- **Rows:** a held row renders as "Not now"; a refused row as "Not rebuilt" with its reason.
- **New fields:** they all have defaults, and only the launchpad builds the unscoped report.
- **bash 3.2:** the constructs are fine, the values are positional parameters, and every expansion is quoted.

## Resolution

All findings were fixed on 2026-11-17 by the engineer (spec §10): P1-1, P2-1, P2-2, P2-3, and P3 1–9.
- **P3-9:** the test fakes now take `**kwargs`, and `Rebuild` always gets `hold`.
- **P3-6:** the spec status line and the ADR were corrected.
- **Tests:** `tests/test_self_update.py` now has 62 tests.
- **Re-verification:** see the second Verify in `docs/audit/self-update-qa.md`.
