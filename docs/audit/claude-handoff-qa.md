# QA verify: claude-handoff (commits 69aa809, 5021155 on 4bb2278)

Role: `qa-engineer` agent, read-only. Date: 2026-11-18. Playbook `docs/playbooks/qa-engineer.md` is current (last reviewed 2026-10-14). app-context's `## Commands` and `## Test bar` are unfilled, so no test modes or coverage target are named. QA ran the one known mode twice.

## Verdict
**FAIL at this gate, with no P0 or P1.**
- **Passes:**
  - The full suite is green twice.
  - Success measures §2.1–2.6 are mostly shown by tests.
  - No test calls a live model, the network, or the real support folder.
- **Blocks:**
  - 13 real mutants survived.
  - 5 P2 gaps.
  - §2.7 (the real-Mac check) is not verified.

## 1. Full suite
- **Run 1:** 1160 passed, 1 skipped, 10 old `QDragEnterEvent` deprecation warnings (`tests/test_convert_drop.py:75`), process exit 0.
- **Run 2:** with `-W error::pytest.PytestDeprecationWarning`, run alone: the same result, exit 0.
- **Timing:** both took about 8 minutes, against the author's earlier ~2.5 min runs. The security review was running at the same time; the cause was not established.

## 2. Test plan (T = `tests/test_handoff.py`, U = `tests/test_handoff_ui.py`)
| Measure / fix | Tests | Status |
|---|---|---|
| §2.1 shown only for qualifying rows | T:34-50, T:296, U:63, U:78, U:103 | Partial: the Update-step gate is untested (P4 survives); "Not rebuilt" is never produced through `BuildModel.refuse` |
| §2.2 disabled while a job runs | U:92, U:204, U:271, U:288, U:340, U:355 | Gap: "Update now is rebuilding" is never run (A3 survives) |
| §2.3 confirmation | U:135, U:204 | Partial: folder label not asserted; cost sentence checked by substring only; real dialog's Cancel not tested |
| §2.4 one session per repo | T:178, T:54, T:258, U:173 | Met |
| §2.5 prompt text | T:100, T:322, T:135, T:127, U:173, U:247 | Met with caveats: the snapshot embeds `LIMITS` itself; the amended clause of limit 4 is not asserted; `LIMITS` differs from spec §4.2 in two places |
| §2.6 reuse | U:150, U:404 | Partial: the "already running (pid N)", "Also running here" and "could not tell" lines are not asserted (`ui/handoff_dialog.py:78-82` never runs) |
| §2.7 real Mac | owner steps below | Not verified |

Review fixes:
- **Met:** P2-1, P2-2, P2-3, P2-5, P2-6, P2-7, P3-4 and P3-6 are shown by tests.
- **Partial:** P1-1 (the rules are not pinned), P2-4 (`command_dir` is under-tested).
- **Not tested:** P3-1, P3-3, P3-5 and P3-7.

### §2.7 Owner check on a real Mac
Precondition: Lab Hub running from a build of this branch, and Claude Code signed in.
1. **Before shot.** Open Check builds. Find a real "Needs you" row, such as Provisio's release clone. Take a screenshot.
2. **Tooltip.** Hover **Ask Claude…**: it names a row count and says sessions are paid. Press it.
3. **Confirmation.** Check:
   - one Provisio block, its name in bold;
   - its folder is Provisio's main checkout (hover for the full path);
   - the row reads exactly as in the window;
   - the cost sentence is shown;
   - the button reads **Open 1 session**.
4. **Open.** Press **Open 1 session**. One Terminal window opens. The window shows "Opened Claude Code in Terminal for provisio. Press Refresh when the session is done."
5. **Session details.** In the session, check:
   - **Name:** `/status` shows `Lab Hub: provisio`.
   - **Folder:** `pwd` (after its prompt) is Provisio's main checkout.
   - **First message:** it is Lab Hub's prompt, with the row word for word, the command line, the line naming the added folder, "Done looks like", and the six limits.
6. **Push asks.** Ask it to run `git push --dry-run`. Expected: a permission prompt. Answer No.
7. **Sign-off refused.** Ask it to run `python3 docs/foundry/tooling/legal_gate.py sign`. Expected: refused by a deny rule, with no prompt offered. Note the message.
8. **Optional:**
   - an Edit to `docs/legal/signoff.jsonl` is refused;
   - `/permissions` lists Lab Hub's ask and deny rules;
   - in imprint or sentinel, `python3 -c 'print(1)'` still asks.
9. **Finish the session.** Work through the row, then check `/cost`. Close the session. Check that its `.command` file is gone from `~/Library/Application Support/Lab Hub/claude-handoff/<stamp>-1/`.
10. **After shot.** Press Refresh: the Provisio row reads "Up to date". Take a screenshot.
11. **Record the cost.** `python3 docs/foundry/tooling/model_use.py . --purpose eval --cost-usd <n>`.

## 3. Mutation check
Scratch worktree, one mutant at a time on `tests/test_handoff.py tests/test_handoff_ui.py`; baseline 51 passed. The scratch worktree has since been removed.

**53 planted: 38 killed, 15 survived.** Two survivors are equivalent (M3, M32), so 13 are real.

Real survivors:
- **M8:** `extra_dirs` keeps subfolders inside the repo (harmless).
- **M10–M13:** `command_dir` stops checking that the folder exists, that it is absolute, the `cd --` form, or that the first word is `cd`.
- **M35:** `_prune`'s `>` becomes `>=`.
- **M36–M38:** the SETTINGS rules for `git tag` ask, the install asks and the `Write` deny can be dropped.
- **M41:** `base.chmod(0o700)` can be dropped.
- **M42:** `O_EXCL|O_NOFOLLOW` can be dropped.
- **P4:** the step gate in `_Run.handoff_rows` can be dropped.
- **A3:** `_handoff_jobs` can ignore a live rebuild.

QA's scratch-only probe tests killed M10, M12, M13, P4 and A3.

## 4. Coverage of changed lines
No coverage tool is installed, so QA used a stdlib tracer. Line coverage only:
- `handoff.py` 223/233, missed:
  - `top_level` fallback;
  - unbalanced quote in `command_dir`;
  - `_inside` OSError;
  - `_prune` OSError;
  - `_new_folder` exhausted.
- `handoff_dialog.py` 100/104, missed lines 78-82.
- `progress_window.py` 80/80.
- `apps_tab.py` 89/90, missed line 929.
- `lander.py` and `main_window.py`: all lines hit.

## 5. Test quality
- **Fakes:** fakes replace `find_claude`, `cwd_listing` and `run_in_terminal`. The support folder is isolated. No time dependence.
- **Assertions that cannot fail:**
  - T:171 compares `settings.json` with the same constant;
  - T:121 embeds `LIMITS` in its own snapshot.

## 6. Models
- Lab Hub makes no model call of its own here.
- **No live eval:** there is no `model_use.py --purpose eval` record and no `eval_budget_usd` for this milestone. The §2.7 session is the de facto live check; record its cost (step 11).
- **Models-used table:** the app-context row is due at Document.

## 7. Findings
**P2**
1. **"Never during Update now" is untested.** P4 and A3 survive, and `apps_tab.py:929` never runs.
2. **The permission rules are not pinned.** M36–M38 survive. Assert SETTINGS against a literal dict.
3. **`command_dir` rules are untested.** M10–M13 survive. Add parametrized cases.
4. **§2.7 is not verified.** Release waits for it.
5. **No live-eval record.**

**P3**
1. Dialog text for §2.3 and §2.6 is not asserted.
2. Review fixes P3-1, P3-3, P3-5 and P3-7 have no test.
3. `LIMITS` is not word for word with spec §4.2:
   - limit 3 says "this session" where the spec says "that session";
   - limit 5 drops "(§4.3)".
4. M41 and M42 (hardening) have no test.
5. Small gaps: M8, M35, the `top_level` fallback, `_new_folder` exhaustion, and `BuildModel.refuse` rows.
6. Infrastructure from before this change:
   - no CI;
   - no pytest-timeout, pytest-randomly or coverage;
   - app-context Commands and Test bar unfilled.

## Not verified
- Branch coverage.
- §2.7 and every real-CLI behaviour.
- The live eval.
- The mutant that drops the limit-4 clause (inferred, not run).

## Status
Fixed 2026-11-18 (the owner: "Fix as proposed"), apart from the items marked open below.
- **P2-1.** New tests: `test_never_during_update_now_even_with_a_needs_you_row`; `_handoff_jobs` with a live rebuild.
- **P2-2.** `test_settings_ask_before_push_and_deny_sign_off` pins SETTINGS against a literal dict.
- **P2-3.** `command_dir` tests: parametrized cases plus a relative folder that exists; `git -C` is now read too.
- **P2-4 and P2-5.** Still open: they need the owner's real-Mac session (§2.7 steps above, including the cost record).
- **P3-1.** Dialog text asserted: cost, pid warning, also running, could not tell, command, added access.
- **P3-2.** Covered:
  - tooltip row count;
  - repo name with `&` and the elided folder;
  - a `plain`-changed name finds its folder;
  - Refresh after opening.
- **P3-3.** `LIMITS` now equals spec §4.2. A test reads the spec and compares, so the two cannot drift.
- **P3-4 and P3-5.** Tests for:
  - `chmod`, `O_EXCL|O_NOFOLLOW` and the `_prune` boundary;
  - the `top_level` fallback;
  - a refused rebuild offered at Done;
  - a repo subfolder not added.
- **P3-6.** Infrastructure: still open, from before this change.

**Mutation re-check** (author, 2026-11-18, scratch copy): every real survivor above was planted again (M8, M10–M13, M35–M38, M41, M42, P4, A3), plus four new mutants on the security fixes. All 17 are killed. M11 was killed only after the relative-folder test was added.
