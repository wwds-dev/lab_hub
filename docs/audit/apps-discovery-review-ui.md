# Review, spec `apps-discovery`, part 2 (UI): code-reviewer

Phase 6 (Review). Read-only: no tracked file edited; mutation runs were done on `git archive` copies in the scratchpad, not in this tree.
Scope: `git diff 93d1b07..0742e82` (`ui/own_verdict.py`, `ui/discovery_banner.py`, `ui/widgets.py`, `ui/apps_tab.py`, `ui/tiles.py`, `ui/main_window.py`, `ui/settings_tab.py`, `tests/conftest.py`, `tests/test_own_verdict.py`, `tests/test_discovery_banner.py`, `tests/test_apps_discovery_ui.py`, `tests/test_settings_tab.py`, `tests/test_tab_groups.py`). The core (registry, discovery, state, control) is the other reviewer's file, `docs/audit/apps-discovery-review-core.md`.
Reviewed against: spec §4-§7, §12, §13, ADR 0007 (accepted), AGENTS.md.

Process notes
- `docs/playbooks/code-reviewer.md`: `status: current`, `last-reviewed: 2026-10-14` (38 days): not stale.
- `docs/foundry/app-context.md` is still the unfilled template: no domain risks, hot spots or commands are named there, so the review rests on the spec and the code.
- Targeted run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_own_verdict.py tests/test_discovery_banner.py tests/test_apps_discovery_ui.py tests/test_settings_tab.py -p no:cacheprovider` gives 87 passed; `git status` clean afterwards; the real `~/Library/Application Support/Lab Hub/` has no `apps-local.toml` or `apps-dismissed.json` (the tests did not touch it).
- No linter is installed in the venv (no ruff, pyflakes, mypy): lint and types not verified.
- Rendered the banner (3 rows plus "and 2 more", long name, long sentence, an inline error), Kaila's tile and Lab Hub's tile (behind, 126 commits) offscreen at 380 and 440 px in Graphite and Paper. No overlap, clipping or sideways growth (the one apparent overlap while experimenting was my harness giving the host window too little height). Reported minimum widths: banner 414 (dark) / 420 (light) against the 500 limit; tiles 298-300 and Lab Hub 280-282 against 380.

## Verdict: PASS with fixes
No P0 or P1. Three P2 (one is the unbuilt Design 12.5-F note; two are tests that cannot fail for what they claim). Eight P3. None needs a bigger model; all are small.

## P0
None.

## P1
None.

## P2

### P2-1. Corrupt `apps-dismissed.json`: Design 12.5-F not built, and Settings then states something untrue
- Where: `ui/settings_tab.py:125` and `:216-230` (empty state), `lab_hub/discovery.py:199-205` (`load_dismissed` returns `{}` for a corrupt file, nothing else is exposed); spec §12.5 table row and §12.7 F (approved with §14.3 "approve all").
- Scenario: the file is damaged (half-saved edit, bad JSON). Every earlier "Never" answer reappears as a banner row, and Settings > Hidden projects says "No hidden projects." although the owner hid several. The first new answer renames the bad file to `.bad` (core, correct), so nothing is lost, but nothing tells the owner why the questions came back. The approved line "Your hidden-projects file could not be read, so nothing is hidden." is never shown.
- Should it block? No. It is a surprise, not a loss: the file can only cause extra questions (ADR 0007 §4), the `.bad` copy keeps the data, and the approved sentence is in the spec for whoever builds it. Fix before the Verify screenshots only if cheap; otherwise the owner defers it explicitly (Definition of done: P2 needs no deferral note, but it should be on the TODO). The author said so in commit `bca1c39`.
- Fix direction: add one small read API to `discovery` (for example `dismissed_state() -> "ok" | "absent" | "unreadable"`, using `_snapshot` and `_parse_dismissed(...) is None`), show F as a `hint` line in the card when `unreadable`, and hide "No hidden projects." in that state. Test: write garbage, build `SettingsTab`, assert the F text and that the empty line is not shown.

### P2-2. `test_land_shows_on_lab_hub_tile_when_its_repo_needs_attention` ends in a vacuous assertion and starts a real worker
- Where: `tests/test_apps_discovery_ui.py:397-412`, the assert at `:410`: `assert tab.lander.busy or card.land_button.text() in ("Land", "Landing…")`.
- Scenario: the Land button's text is always "Land" or "Landing…", so the assert holds whether `land_requested` is wired or not. The click does start a real `Lander` thread (`land_card` -> `lander.plan`, `ui/apps_tab.py:1440-1448`) on an empty temp folder, ended only by `lander.shutdown(0.1)`; nothing waits for it, so it can run into the next test.
- Fix direction: patch `tab.lander.plan` with a recorder and assert it received `[("lab_hub", row.path)]`; no real thread. The first half of the test (button visible, badge "2 files to land") is good and stays.

### P2-3. `test_check_builds_has_exactly_one_lab_hub_row_with_the_tile_present` cannot fail for the double count it guards
- Where: `tests/test_apps_discovery_ui.py:425-445`, the stub at `:430`: `monkeypatch.setattr(launcher, "build_report", lambda *a, **k: ())`.
- Evidence (mutation, scratch copy): `lab_hub/launcher/state.py` `build_report` changed to append `self_update.SELF` to `chosen` (Lab Hub counted twice). The test still passed (`.`). With `build_report` stubbed to `()` the only possible row is the one `show_build_report` appends itself.
- Fix direction: let the real `build_report` run over a temp registry (`registry.use(...)`) that contains one launchable app, and assert exactly one `Lab Hub` row plus that app's row. Keep the `OWN_TILE`-present assertion. (The core reviewer may already have a registry-level test; this one is still the only UI-level guard and should not be vacuous.)

## P3

### P3-1. Banner and Lab Hub verdict stay on the old lab folder after Settings changes it
- Where: `ui/main_window.py:318-326` (`_on_settings_saved` calls `apply_settings`, not `refresh_all`), `ui/apps_tab.py:1017-1022` (`apply_settings` does not call `_scan` or `_request_own_verdict`).
- Scenario: lab folder A offers Kaila; the owner points Settings at folder B; the banner still shows Kaila; Add writes `project = "kaila"` into `apps-local.toml` (`discovery.add` takes no lab root and does not check the folder exists), giving a tile "no folder at B/kaila" that the UI cannot remove (spec §8 Out). The Lab Hub verdict is likewise for A until Refresh.
- Fix direction: call `self._scan()` and `self._request_own_verdict()` in `apply_settings` (a lab-folder change is a Refresh moment), or have `add` refuse when `<lab_root>/<folder>` is gone. Test: change the lab root on a page with a banner row, assert the rows follow.

### P3-2. A project's `VERSION` text is shown as rich text on the tile (spec §12.6 says all file-derived text is plain)
- Where: `ui/apps_tab.py:136` (`self.version = QLabel()`, no `setTextFormat`), `:345` and `:351` (text and tooltip, the tooltip not through `plain_tip`); source `lab_hub/launcher/state.py:748-770` (`_major` returns the raw file content unless it has a 3-digit tail). Newly reachable for any folder the owner adds or a scan suggests.
- Reproduction: a folder whose `VERSION` is `<b>BOLD</b>`: `state._major(path)` returns `'<b>BOLD</b>'`, and `PySide6.QtGui.Qt.mightBeRichText("v<b>BOLD</b>.007")` is `True`, so the auto-format label renders it. Impact is cosmetic (QLabel does no network fetch and no script), but it breaks the stated invariant and the Design contract.
- Fix direction: `self.version.setTextFormat(Qt.PlainText)` next to the `hygiene` label (one line), and `plain_tip(...)` on the tooltip at `:334` and `:351`. Test: an `AppCard` whose version text looks like markup.

### P3-3. Settings "Hidden projects" trusts the folder key from the JSON file
- Where: `lab_hub/discovery.py:264-283` (`hidden` only checks that `lab_root/<key>` exists), `ui/settings_tab.py:235` (`discovery.describe(lab_root / folder)` reads that README).
- Reproduction (scratch dirs, patched `config.SUPPORT_DIR`): dismissal key `"../outside"` with `outside/README.md` = `# Outside Secret Name`: `hidden(lab)` lists it and `describe(lab / "../outside")` returns `('Outside Secret Name', ...)`. The file is the owner's own, so no attacker is implied; it is the one place a name that did not pass `NAME_OK` reaches a label and a file read.
- Fix direction: in `hidden()` (core) skip keys that do not fullmatch `NAME_OK` or that contain a path separator. Cross-reference for the core review.

### P3-4. Show again: the status line can promise something that will not happen, and a README name can hide which folder is meant
- Where: `ui/settings_tab.py:235` (name from the README heading, the author's deviation), `:266-286` (`"{name} will be suggested again."`).
- Scenario A: a project hidden with Never is later added by hand to `apps-local.toml` or loses `docs/foundry/app-context.md`; it still lists as hidden (folder exists), Show again succeeds and says "Kaila will be suggested again", but `scan` will not suggest it. Scenario B: two folders whose README headings read the same show two identical rows, and the folder name appears nowhere (the tooltip is only set while the label is cut).
- The name deviation itself is fine: it matches the approved example "Kaila · hidden for good" (the folder is `kaila`), and the label stays plain text. Judged acceptable.
- Fix direction: put the folder name in the label tooltip (`ElidedLabel.setNote`); optionally say "Kaila is no longer hidden." when the rescan produced no row for it. Low priority.

### P3-5. Wording the owner has not approved, and two oddities in the behind line
- "Could not show {name} again: {reason}." (`ui/settings_tab.py:274`): coined by the author; the Design says only "inline stateBad line in that row (same as 12.1.10)". Same pattern as the approved C lines; the owner should confirm it.
- "will be suggested again." is **approved** (12.7 B "Kaila will be suggested again."; the owner's "Approve as recommended" covered §14.3 "approve all"), so the author's flag on it is not needed.
- `" · behind"` with no count (`ui/apps_tab.py:674`, when `row.version.behind` is 0): new, unspecified.
- Behind tooltip (`ui/apps_tab.py:675`): the approved sentence is there, but appended to `version.tooltip()` instead of standing alone. Design 12.3.2 and 12.3.3 pull in both directions, so this is a defensible merge; the exact text is `…commit/date…\nA newer build is ready to install: use Check builds.`
- When the tile is behind it shows "v2.279 · 126 behind" and, on the next line, "126 commits older than its source" (rendered, both themes): the same fact twice. Design 12.3.3 uses the verdict words only for the up-to-date and runs-from-source cases.
- "A newer build is ready to install" is shown for every `verdict == "behind"`, including rows `self_status.held(...)` has taken the command from (`lab_hub/self_update.py:230-235`: verdict stays "behind", `command=None`), where Check builds will say "Update now leaves Lab Hub alone". The row note is in the verdict line's tooltip, so the owner can find out; the claim is the approved wording. Flagged for the owner, not a bug.
- The failed-verdict reason lives in the tooltip of a blank 15 px line (`ui/apps_tab.py:684-690`; measured geometry `QRect(20, 51, 358, 15)`, text `''`): as specified, but nobody will hover an invisible strip.
- Lab Hub's tile has no name tooltip (`name_tip = ""`, `ui/apps_tab.py:~650`): spec §7 puts the registry-advice tooltip on "a project with no launch command", and §5 says Lab Hub is "the same no-launch kind". Omitting it is right (the advice is false for Lab Hub: its key is reserved), but it is a deviation from the letter; record it.

### P3-6. `OwnVerdict`: sound, with small robustness and test gaps
Judged against the brief's list (`ui/own_verdict.py`):
- Qt off-thread: none. `_work` (`:80-84`) calls `self_update.self_status` and `self._events.put`; `self_update` and `launcher.state` import no PySide (grep); `self_status` does not read the registry (only `build_report` does). The signal is emitted from `_drain` on the GUI thread via the 100 ms timer.
- Coalescing: `_again` keeps the latest root; a burst costs one extra run (test and mutation B: dropping it fails `test_a_burst_of_requests_costs_one_extra_run`). The older run's result is still delivered before the follow-up's, so the line can show a pre-Refresh answer for a moment (harmless).
- Exceptions: `except Exception` is the intended catch-all; blank line, reason kept. A `BaseException` in the worker would leave `_thread` set forever (no result, timer firing every 100 ms, later requests only set `_again`). `self._thread` is also assigned before `start()` (`:72-76`), so a failing `start()` has the same effect. Both are far-fetched; a `try/finally` that always puts a result, or assigning after `start()`, closes them. Subprocess calls have timeouts (`self_update.GIT_TIMEOUT_S`, and 10-60 s in `state.py`), so a hung git cannot wedge it for ever.
- Shutdown and quit: `aboutToQuit` -> `shutdown` (`ui/apps_tab.py:776`) sets `_closed`, drops `_again`, stops the timer; late results are discarded in `_drain`; the daemon thread touches nothing else. Signals after the window is gone: the timer and slot die with the parent; the thread only holds a Python reference. No use-after-free found.
- The amended comment at `lab_hub/launcher/state.py:682-686` is accurate: the caches (`_COUNT_CACHE`, `_COMMIT_CACHE`, `_SHALLOW_CACHE`, `_DIRTY_CACHE`, `_BEHIND_CACHE`, `_ROOT_BEHIND_CACHE`) are plain dicts with set-and-get, no `.clear()`/`.pop()` anywhere in `lab_hub/` (grep), so a value computed twice is the same value and no `KeyError` window exists. No other "GUI thread only" claim in `lab_hub/` (grep).
- Test gaps (mutations on a scratch copy): dropping `self._timer.stop()` from `shutdown()` survives all four files (A2: `test_after_shutdown...` asserts `not _timer.isActive()` after the timer was already stopped by a drain, and the in-flight half asserts nothing about the timer). The `aboutToQuit.connect(self._own_verdict.shutdown)` wiring (`ui/apps_tab.py:776`) has no test. Tests call `_drain()` directly, so the real 100 ms timer path is untested. Fix direction: assert `not other._timer.isActive()` right after `other.shutdown()`; one test that pumps the event loop (`QTest.qWait`) until `ready` fires.

### P3-7. `discard_widget` (`ui/widgets.py:210-229`): the fix is right; its keep-alive is untested
- Judgement: unparenting first (`setParent(None)`) removes the double delete; keeping the Python wrapper in `_DISCARDED` until `destroyed` fires keeps a row that is inside its own button's `clicked` from being freed under the signal; the set is emptied by the `destroyed` lambda, so no leak while the event loop runs. No use-after-free or leak found.
- Mutation E (drop `setParent(None)`, the set and the connect): the suite crashes (segfault), so the regression test is real. Mutation F (drop only the `_DISCARDED` keep-alive): all three files pass, so the "mid-click" rationale in the docstring is not pinned by any test. Fix direction: a test that holds no other reference to the row, clicks a button inside it, and replaces the row from the handler (the existing `test_a_row_can_be_replaced_from_inside_its_own_button_click` keeps the row alive through `banner.rows[0]` and the bound method).

### P3-8. Test-suite hygiene
- `pristine_theme` (`tests/conftest.py:100-119`): judged correct for the new tests: it restores mode, style, palette and stylesheet in the right order (style first, since `setStyle` resets the palette). Confirmed the author's claim on a scratch copy of HEAD: `pytest tests/test_theme.py tests/test_land_confirm.py` fails `test_details_round_trip_stays_on_the_screen` (alone it passes; the full suite passes only because `test_land_confirm` sorts before `test_theme`). The root cause is `tests/test_theme.py:13-17` (`restore_theme` restores the mode only). Not in this diff, but one line fixes it: use `pristine_theme` there (or make `restore_theme` delegate to it). Any reordering of the suite would hit it.
- `tests/test_apps_discovery_ui.py:325`: `assert BEHIND_TIP in tip or plain_tip(BEHIND_TIP) in tip` is an either/or that is true for either form; pin the one the code produces (`plain_tip(version.tooltip() + "\n" + BEHIND_TIP)`).
- `tests/test_apps_discovery_ui.py:30-31`: `REAL_SUGGESTIONS` and `_REAL_REQUEST` are captured at import and imported across test modules (`from .test_own_verdict import _REAL_REQUEST`, `from .test_discovery import make_project`). Works today (imports run at collection, before the autouse patch); a conftest-level helper would remove the cross-module coupling.

## Brief items with no finding (evidence)
1. Thread (item 1): see P3-6.
2. Scan only at startup and Refresh (item 2): `_scan` is called from `AppsTab.__init__` (`ui/apps_tab.py:817`), `recheck` (`:1345`), `rescan` (Settings Show again), and the three answer handlers; `refresh` (the 3 s poll) and `showEvent` do not call it. `test_the_page_scans_at_startup_and_on_refresh_but_never_on_the_poll` and `test_three_polls_call_self_status_zero_times` check it. `recheck` is also reached after Update now (`:1129`), which is when a fresh Lab Hub verdict is wanted. Rebuild only on change: `SuggestionBanner.set_suggestions` compares tuples of frozen `Suggestion`s (`ui/discovery_banner.py:131-150`); `Show again` rebuilds only when the shown list changed (`ui/settings_tab.py:216-224`). Focus after answers: next row's Add, else the last row, else the page scroll area; tested. `discard_widget`: P3-7.
3. Wording and plain text (item 3): §7 strings checked byte for byte against `ui/discovery_banner.py:34-45`, `ui/apps_tab.py:99-109`, `lab_hub/self_update.py:80-86` and `ui/settings_tab.py:28-31`: the banner lead-in, the three buttons and three tooltips, the no-launch hint and name tooltip, the Lab Hub summary and hint, "hidden for good", "not asked until 5 Dec", "Show again", "Hidden projects" all match. PlainText is set on the banner name (via `ElidedLabel`), sentence, error line, `local_note`, tile name and summary (`ui/tiles.py`), the Lab Hub verdict line, the Settings error line; tooltips go through `plain_tip` (banner error, `local_note`, Lab Hub version and verdict, `ElidedLabel`). Names that reach rich-text message boxes are validated by the registry (core). Exception: P3-2 (VERSION).
4. No-launch and Lab Hub tiles (item 4): Launch is hidden, `_launch` and `_update_button` are guarded, no state pill, no Stop (`stop_button is None`), no readiness, presence or `ps` call (a test makes those raise); Lab Hub's tile has only Land and Open in Terminal; the tile is last; Land and the badge come from the `lab_hub` hygiene row (`_apply_hygiene` keys on `card.app.project`); Check builds still has one `lab_hub` row by construction (`OWN_TILE` is in no registry group), though the test that claims it is vacuous (P2-3). The tray, menu bar and Settings count are the core's (`e7737c6`), outside this diff.
5. Layout (item 5): measured widths above; tests assert banner `minimumSizeHint().width() <= 500` and tile `<= 380` in both themes, and the Settings row at 560 px.
6. Hidden projects (item 6): Show again calls `forget` (atomic write, core), rereads, signals the Apps page (`suggestions_changed` -> `apps_tab.rescan`) and the status bar; date format `{day} {Jan..Dec}` independent of locale, tested for a one-digit day and across the year; "No hidden projects." shows only when empty; a lapsed "Not now" and a deleted folder are not listed. Issues: P2-1, P3-3, P3-4.
7. Tests (item 7): none touch the real support dir or write to the lab folder (`isolated_config` is autouse; temp lab folders; the `window` fixture only reads the real lab folder). Weak tests: P2-2, P2-3, P3-6, P3-7, P3-8. Strong ones confirmed by mutation: dropping coalescing, dropping the closed check in `_drain`, and removing `setParent(None)` each fail a test.
8. Unapproved wording (item 8) and 12.5-F: P3-5 and P2-1.

## Not verified
- A double-click on "Add to Apps": the next row is rebuilt under the pointer synchronously, and Qt turns a second press into a click on whatever is there. I could not reproduce it (QTest delivers events straight to the widget, with no hit test), so it is not a finding; Verify should try a real double-click on the Mac with three rows. If it answers two projects, the mitigation is to ignore clicks on a row built less than about 300 ms ago.
- VoiceOver, the focus ring on `QPushButton` under this stylesheet, and macOS font metrics (Design 12.1.7, 12.6): Verify's.
- Lint and type checks (no tool installed).
- The full suite: not run, as instructed.

## Summary of fixes asked for
1. P2-1: expose "dismissals unreadable" from `discovery`, show F, hide "No hidden projects." then (or the owner defers it in writing).
2. P2-2 and P2-3: make the two tests able to fail.
3. P3-1, P3-2: two one-line behaviour fixes (`apply_settings`, `setTextFormat` and `plain_tip` on the version label).
4. P3-3 to P3-8 at the author's or owner's discretion; P3-5's wording needs the owner's yes.
