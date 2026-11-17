# Spec: progress windows for Land and Check builds

Status: **Define approved by the owner 2026-11-17 ("Approve as recommended"): all four §5 decisions as recommended.** Phase: Define (`product-manager`), 2026-11-17. Design is the mockup below; next is Architect (GATE).
Nothing built. In-flight check (`session_start.py --inflight`, 2026-11-17): no spec owns a progress window. `land-from-tiles` (document done, not released) owns Land's engine and tile UI; this spec reuses its `Lander` signals and changes none of its behaviour. `update-now-terminal` and `release-root-behind` (document done, not released) own the Check builds report and `RebuildDialog`; this spec replaces their presentation, not what they run.
Mockup: `docs/specs/progress-windows-mockup.html` (the owner chose "take best of both" of two variants per window, 2026-11-17).

## 1. Problem and evidence
Owner, 2026-11-17: "when landing is processing i need to see a window where the processing is shown", and the Check builds window "needs to be updated and made visually improved. the user should have the chance to understand what is happening", plus "some type of progression bar and moving dots so the user can see the window is not crashed but working and how long estimated it is taking to finish".
- **Land / Land all** shows progress only as one line per tile (`ui/apps_tab.py:1212` `_land_progress` -> `card.set_landing`). The owner's screenshot (2026-11-17) shows four tiles reading "Landing..." with no step, no count, no time and no sign of life. A Claude Code merge plus tests can take minutes.
- **Check builds** opens a `QMessageBox` with a text dump (`ui/apps_tab.py:863` `show_build_report`: `[ok]`/`[OLD]`/`[??]` lines and raw commands). **Update now** then opens `RebuildDialog` (`ui/apps_tab.py:574`): one status line ("Rebuilding 1 of N… this takes a few minutes"), a raw log and Cancel. No per-app state, no stage, no progress bar, no time estimate.
- Nothing records how long a land step or a rebuild took, so no estimate is possible today.

## 2. User and success measure
The owner, on the Apps page, starting Land, Land all, Check builds or Update now, and wanting to know at a glance what is happening, that it is alive, and when it will finish.
1. **Land window.** Land and Land all open one window (non-modal; closing it hides it and landing goes on, the tiles still show their line). It shows: overall progress bar and percent (steps done of steps planned), elapsed time, time left and a "done around HH:MM" clock once an estimate exists, counts (landed, running, waiting, needs you), one row per repo with a stage track (commit, merge and test, push, tidy), the running repo expanded into its step list with the running step's own timer, a reason line under any repo that did not land, a collapsed live output, Hide and Stop landing.
2. **Check builds window.** Check builds opens one window that replaces the message box and `RebuildDialog`: a step header (Check, Review, Update, Done), one row per app with its verdict in words (up to date, older than source and why, needs Terminal, cannot check), the same overall bar, percent, elapsed, time left and counts, the app being rebuilt expanded into its stages (build, package, install, verify) with time left for that app, apps that are up to date collapsed into one line, a collapsed live output, and the existing buttons (Update now, Copy commands, Copy and open Terminal, Open in Terminal, Cancel, Close) with their current behaviour.
3. **Alive signal.** While work runs, both windows show animated dots, a spinner on the running row, and "Last activity Ns ago", which counts up from the last output line. When no output has arrived for 60 s, that text turns amber and reads "No output for 1:00. Still running." It never claims something froze.
4. **Estimate.** Time left comes from recorded durations of past runs (per repo per step kind for Land, per app per stage for builds). With no history, the window shows elapsed time and "Estimating…" instead of a guess. Shown as minutes above 60 s, seconds below; never negative (an overrun shows "Taking longer than usual").
5. **Ends clearly.** At the end, each window says the outcome in one line (Land all keeps today's "Landed N of M repos" content, now in the window instead of a separate box) and leaves the rows for reading.
6. Tests: the window models (progress percent, counts, estimate, stale-output state) are unit-tested with fake clocks and fixture events; the UI is tested with the existing `test_land_ui.py` and `test_apps_tab.py` patterns. Screenshot of both windows on the real lab as evidence.

## 3. Scope
- New `ui/progress_window.py`: one shared widget set (header with bar, dots, times and counts; row with stage track; expandable step list; output pane), used by both windows.
- `ui/apps_tab.py`: Land and Land all open the Land window and feed it from the existing `Lander` signals; `show_build_report` and `RebuildDialog` replaced by the Check builds window, keeping every current command path and button.
- `lab_hub/land.py`: progress events carry structure (repo, step index, step kind, start/end, outcome) besides today's text line. Tile lines keep their text.
- Build stages: a stage is recognised from the build output by known lines (`pyinstaller`, `codesign`, the install copy, the version check); an app whose output matches none shows one "Rebuilding" stage instead of four. Build scripts are not edited by this spec.
- New duration history file `~/Library/Application Support/Lab Hub/durations.json`: per repo or app, per step kind, the last 5 durations; the estimate is their median. Written after each finished step; a broken or missing file means "Estimating…", never a crash.
- README, CHANGELOG.

## 4. Non-goals
- No change to what Land or Update now does, its guards, its confirmation, the Claude Code cost cap or the order of steps.
- No editing of other apps' `build_app.sh` to print stage markers (possible follow-up per app).
- No notification centre or Dock badge.
- No new tile layout; tiles keep their one-line progress and outcome.

## 5. Decisions for the owner
1. **Window style.** Recommend non-modal for Land (it runs for minutes; you keep using Lab Hub) and modal for Check builds' Update now, as today (it replaces installed apps). Alternative: both non-modal.
2. **Estimate source.** Recommend the median of the last 5 recorded durations, shown only once one exists. Alternative: a fixed guess per step kind from day one (shows a number sooner, often wrong).
3. **Build stages.** Recommend recognising stages from output lines, falling back to one stage. Alternative: one stage only (simpler, less informative).
4. **Land all summary.** Recommend the end state of the Land window replaces the separate "Land all" message box.

## 6. Risks
- Output-line stage recognition breaks silently if a build script's output changes; the fallback keeps it truthful (one stage) but less detailed.
- The estimate is wrong on the first runs after a big change (for example a new Claude merge); "Taking longer than usual" keeps it honest.
- The Land window and the tiles both listen to the same signals; the window must not slow the worker thread (UI updates are throttled to at most 10 per second).

## 7. Phases to run
Define (this file, **GATE**: user-visible), Design (the mockup above, recorded in this spec once approved), Architect (**GATE** expected: new persistent state `durations.json` and structured progress events across the worker boundary), Plan, Build, Review, Verify, Document. Secure: required (a file write under Application Support; output from git, Claude and build tools shown in the UI must stay plain text, as `land-from-tiles` Secure required). Comply skipped: tier `public`, no new claims or data flows. Launch skipped: optional for `public`, nothing to announce.

## 8. Architecture
Phase: Architect (`architect`), 2026-11-17. **GATE: new persistent state (`durations.json`), a new event contract across the Land worker boundary, and a changed module boundary in `ui/apps_tab.py` (the Check builds box and `RebuildDialog` go). The owner approves before Plan.** ADR: `docs/adr/0002-progress-events-and-duration-history.md`. Radar check before Architect: not run from this session (a slash command; the owner or orchestrator runs `/radar-check progress-windows`). `docs/foundry/app-context.md` has no hot spots or invariants filled in, so the hot spots below come from the code.

### 8.1 Approach in one paragraph
The engine says *what* happens in structured form; the GUI decides *how it looks*. `lab_hub/land.py` emits a frozen `StepEvent` at the start and end of every planned action, beside today's text lines (unchanged, so tiles are unchanged). `ui/lander.py` carries it over the existing queue-and-drain boundary as one new signal. Build progress needs no thread: the rebuild already runs in a `QProcess` on the GUI thread, and its output lines are mapped to stages by a pure function. Both windows feed one Qt-free model (`lab_hub/progress.py`) that knows percent, counts, times and estimates against an injected clock; thin widgets (`ui/progress_window.py`) render a snapshot of it at most 10 times a second. Finished-step durations go to `durations.json` through one small Qt-free module (`lab_hub/durations.py`), written on the GUI thread only.

### 8.2 Modules and files
| File | Change | Qt? |
|---|---|---|
| `lab_hub/land.py` | add `StepEvent`, `step_outcome()`, `land(..., events=None, clock=time.monotonic)` | no |
| `ui/lander.py` | add `step = Signal(object)`; `_run` passes `events=`; `_drain` emits `("step", e)`; `Lander(clock=...)` kwarg | yes |
| `lab_hub/durations.py` (new) | load, `record()`, `estimate()`, atomic save, key sanitising | no |
| `lab_hub/progress.py` (new) | `RunModel` and its `Snapshot`; formatting; `land_stage(kind)`; `build_stage(line)`; `build_check_view(report, scoped)` | no |
| `ui/progress_window.py` (new) | `Header`, `Row`, `StepList`, `OutputPane`; `LandWindow`; `BuildCheckWindow` | yes |
| `ui/rebuild.py` (new) | `Rebuild`: the QProcess runner taken out of `RebuildDialog` (`ui/apps_tab.py:574-700`), no widgets of its own | yes |
| `ui/apps_tab.py` | `show_build_report` (`:863-997`) builds the view and drives `BuildCheckWindow`; `run_updates` (`:999-1048`) uses `Rebuild`; `RebuildDialog` (`:574`) removed; Land slots (`:1196-1239`) also feed `LandWindow` | yes |
| `tests/test_progress.py`, `tests/test_durations.py`, `tests/test_progress_window.py` (new); `tests/test_land.py`, `tests/test_land_ui.py`, `tests/test_apps_tab.py` (extended / seams renamed) | | |

The model sits in `lab_hub/` rather than in `ui/progress_window.py` so it is importable and testable without Qt, matching the existing engine/UI split (`lab_hub/land.py` vs `ui/lander.py`). `ui/progress_window.py` holds only widgets.

### 8.3 Structured Land events (spec §3, item 1 of the brief)
```python
@dataclass(frozen=True)
class StepEvent:                 # lab_hub/land.py
    repo: str                    # LandPlan.name: display data, never used as a path
    index: int                   # 0-based position in plan.actions
    count: int                   # len(plan.actions)
    kind: str                    # Action.kind as planned (repo_tidy.py:476)
    phase: str                   # "start" | "end"
    at: float                    # clock() when emitted, seconds, monotonic
    started: float = 0.0         # end only: the matching start's `at`
    outcome: str = ""            # end only: "done" | "failed" | "skipped"
    label: str = ""              # Action.label, same text as the progress line
```
- **Where emitted.** Inside the loop at `land.py:250-263`: a `start` before `repo_tidy.apply`, an `end` after it, with `outcome = step_outcome(ok, message)`: `ok` -> `done`; a message starting `skipped` (guard re-check or stop, `repo_tidy.py:876-882`) -> `skipped`; anything else -> `failed`. `say()` calls are untouched, so tile lines, their order and wording stay exactly as today. No event for `plan.nothing` or a failed `claim` (`land.py:239-247`); `repo_done` covers those.
- **Never raises.** `land()` promises never to raise (`land.py:236`); the `events` callback is wrapped so an exception in it is ignored. Default `events=None` means today's behaviour bit for bit; `test_land.py` and every `repo_tidy.apply` fake (`test_land_ui.py:120,165,191`) keep working because events wrap `apply`, they do not live in it.
- **Clock.** `clock` defaults to `time.monotonic`; `Lander(clock=...)` passes it through. Tests inject a counter. Durations are `end.at - end.started`, both from the same process clock, so no pairing is needed on the GUI side.
- **Crossing the thread boundary.** The worker is a `threading.Thread`, not a QThread (`lander.py:81`). The worker only ever does `SimpleQueue.put(("step", event))` (non-blocking, unbounded), on the same queue as `("progress", name, line)`, so text and structured events stay in one FIFO order. The GUI thread drains it every 100 ms (`lander.py:33-36,109-128`) and emits the new `step` signal beside `progress`. `StepEvent` is frozen and holds only `str`/`int`/`float`, so handing the object across is safe under the GIL build the playbook assumes.
- **Steps planned up front.** `_land_planned` already holds the full plan list before `lander.run(plans)` (`apps_tab.py:1209`). `LandWindow.start(plans)` seeds the model with `sum(len(p.actions))` units and each repo's planned kinds, so the percent denominator is fixed before the first step. `StepEvent.count` is a cross-check only. A repo stopped or skipped before it starts (`lander.py:99-100`, `land.py:239`) gets its remaining units marked `skipped` when `repo_done` arrives, so the bar never stalls short of the end.
- **Stage track for Land** (commit, merge and test, push, tidy): `land_stage(kind)` maps `commit`->commit; `merge`, `claude_merge`->merge and test; `push`, `pull`->push (sync with origin); `delete_branch`, `remove_worktree`->tidy. The plan interleaves tidy steps with merges and puts push last (`repo_tidy.py:593-656`), so the Land track is **per-stage aggregate state** (not needed / waiting / running / done / failed), never a moving cursor.
- **Unchanged (`land-from-tiles`).** Guards, step order, the one confirmation (`confirm_land`, `apps_tab.py:1177`), the Claude disclosure and cost cap (`land.py:152-168`), Stop (`lander.py:64`), the claim (`land.py:78`), and the tile lines. The window adds a second Stop button wired to the same `self.lander.stop`.

### 8.4 Duration history: `~/Library/Application Support/Lab Hub/durations.json`
```json
{"version": 1,
 "subjects": {"repo:SONAR": {"merge": [2.1, 1.9], "claude_merge": [151.0, 93.4]},
              "app:sonar":  {"build": [61.2], "package": [22.0], "install": [4.1], "rebuild": [88.0]}}}
```
- **Keys.** Subject = `"repo:" + LandPlan.name` or `"app:" + ExternalApp.key`. Names are data, never paths: there is one file and the names are JSON object keys only. Sanitised by `durations.subject()`: Unicode category C* (control, format) removed, whitespace collapsed, cut to 120 characters. Kinds are a whitelist: the seven `Action.kind` values plus `build`, `package`, `install`, `verify`, `rebuild`; anything else is dropped on load and refused on record.
- **Values.** Last 5 per (subject, kind), newest last; each a finite float with `0 < s <= 21600` (6 h). Estimate = `statistics.median` of what is there; no samples -> `None` -> "Estimating…".
- **When written.** Only after a step ends with outcome `done` (Land) or a stage/command that finished with exit code 0 (builds). Failed, skipped, stopped and cancelled steps are not recorded: they end at arbitrary points (a guard, a rejected push, a kill) and would drag the median down.
- **How written.** `record()` = load, update, save, all on the GUI thread (from slots of `Lander.step` and `Rebuild`'s QProcess signals). Re-reading before each write means two `AppsTab` instances (each owns a `Lander`, `apps_tab.py:734`) never lose each other's samples; the GUI thread serialises them and `ui/single_instance.py` keeps a second Lab Hub process away. Save = `tempfile.mkstemp(dir=<same dir>, prefix=".durations.", suffix=".tmp")` (mode 0600 by construction), write, `flush` + `os.fsync`, `os.replace` onto `durations.json`; the temp file is unlinked on any error. The directory is created with `mkdir(parents=True, exist_ok=True)` and its mode is not changed (other files live there). Writes are a few KiB, at most one per finished step (tens per run): no worker thread is justified.
- **Size bounds.** At most 200 subjects; a recorded subject moves to the end and the oldest are dropped past 200. A file larger than 256 KiB (checked with `stat` before reading) is treated as empty.
- **Lenient load.** Missing file, unreadable file, invalid JSON, wrong `version`, wrong types at any level, oversized file: all yield an empty history and the window says "Estimating…". Never an exception out of `durations.load()`; a save that fails with `OSError` returns `False` and the run goes on. A broken file is replaced by the next good save (it is a cache, not a record).
- **Injectable path.** `durations.path()` returns `config.SUPPORT_DIR / "durations.json"` at call time, so the autouse `isolated_config` fixture (`tests/conftest.py:38-47`) already redirects it; every function also takes `path=` for direct tests.

### 8.5 Build stages from output
- **Pure function.** `progress.build_stage(line: str) -> str | None` returns `build`, `package`, `install` or `None`. Markers taken from the real scripts in the lab (2026-11-17), case-sensitive, not depending on the `▸`/`✓` glyphs:
  - `build`: `INFO: PyInstaller:`, `with PyInstaller` (PyInstaller's own log, merged into stdout by `MergedChannels`, `apps_tab.py:621-623`; `imprint/scripts/build_app.sh:45`, `sentinel/scripts/build_app.sh:54`).
  - `package`: `INFO: Building BUNDLE`, `INFO: Build complete!`, `^\W*Built: ` (`lab_hub/build_app.sh:67`, `backstage/build_app.sh:50`, `imprint/scripts/build_app.sh:56`), `^Sealed \(ad hoc\):` (`sonar/build_app.sh:103`), `Self-testing the build` (`lab_hub/build_app.sh:63`), `Running self-test` (`sonar/build_app.sh:112`).
  - `install`: `^\W*Installing to ` (`imprint/scripts/build_app.sh:60`), `^\W*Installed: ` (`lab_hub/build_app.sh:73`, `backup_manager/build_app.sh:24`, `git_autosync/build_app.sh:39`), `hecking the new build first` (`sonar/scripts/install_app.sh:77-79`).
  - `codesign` prints nothing in these scripts (`lab_hub/build_app.sh:57` sends it to `/dev/null`), so it is not a marker. The commands are not echoed (`$SHELL -lc`, `apps_tab.py:650`), so the command text is not a marker either.
- **Order and monotonic advance.** Track order build -> package -> install -> verify, as approved in the mockup. A self-test runs *before* install in every script that has one (`lab_hub/build_app.sh:63-73`, `sonar/build_app.sh:112` then `install_app.sh`), so self-test lines count as `package`. A marker for a stage at or before the current one is ignored; a jump (build -> install) marks the skipped stage "not seen" and its time belongs to the stage before.
- **Verify** is not an output line: it is Lab Hub's own read of that app's installed version, `launcher.version(app, lab_root)` (the call `AppCard.refresh_version` makes, `apps_tab.py:267`), right after the command exits 0. Read-only, on the GUI thread, the same cost one tile refresh has today. The row then says which version is installed. It does not change success: success stays "every command exited 0" (`apps_tab.py:631-635`). See open question 2.
- **Fallback.** A command that ends with no marker matched shows one "Rebuilding" stage for the whole run (and for later runs while that app has no stage history). A row starts as four stages if the app has stage history or as soon as the first marker arrives; otherwise it shows "Rebuilding".
- **Line framing.** `Rebuild` decodes with `codecs.getincrementaldecoder("utf-8")(errors="replace")` (today: per-chunk `decode`, `apps_tab.py:653`, which can split a multi-byte glyph), splits on `\n` and `\r`, keeps the partial last line until the next chunk or exit, and feeds whole lines to `build_stage`.
- **Where stage durations are recorded.** In `Rebuild`'s finished slot, only on exit 0: each stage that was entered and then left (by the next marker or by exit) records `now - entered`, timestamped with the injected clock when the line was read on the GUI thread (at most one event-loop turn late). The whole command always records `rebuild`. `verify` records its read time. The time-left estimate for builds uses `rebuild` per app (one robust number); stage medians are shown on the stage chips only. A failed or cancelled command records nothing.

### 8.6 Shared model and widgets (`lab_hub/progress.py`, `ui/progress_window.py`)
- **Model, Qt-free.** `RunModel(rows, history, clock=time.monotonic, wall=datetime.now)`: rows of units with state waiting/running/done/failed/skipped and their times; `on_start`, `on_end`, `on_output(subject, line)`, `on_row_done`, `finish(line)`. `snapshot()` returns a frozen `Snapshot` the widgets render:
  - `percent` = done units / planned units, floored, capped at 99 until `finish`; for builds one unit per in-app command, with the running command's stage fraction added (stages done / stage count, 1 for "Rebuilding").
  - `counts`: Land landed / running / waiting / needs you (`not_landed`, or `remaining > 0`, `land.py:206`); builds up to date / rebuilding / needs Terminal / cannot check / needs you (forward or no command).
  - `elapsed` from run start; `left` = sum of medians of waiting units + `max(0, median(running) - running elapsed)`, or `None` ("Estimating…") if any unit still to run has no history; per row the same over that row only.
  - `done_around` = `wall() + left` as `HH:MM`, only when `left` is not `None`.
  - `overrun` when the running unit's elapsed exceeds its median: the row and header say "Taking longer than usual"; `left` never goes negative.
  - `stale`: seconds since the last output line or event; at 60 s or more, "No output for 1:00. Still running." (amber); below, "Last activity Ns ago".
  - Formatting: `fmt_clock(s)` -> `m:ss`; `fmt_left(s)` -> `~N min` (rounded up) above 60 s, `~N s` at or below.
- **Widgets, thin.** `Header` (title, `QProgressBar`, dots, elapsed/left/done-around, counts, last-activity line), `Row` (name, stage track of 4 chips or 1, status text, reason line), `StepList` (the running row's steps with the running step's own timer, and a "Then: …" line), `OutputPane` (collapsed by default). `LandWindow` (non-modal `QWidget` window; close = hide; Hide and Stop landing) and `BuildCheckWindow` (`QDialog`, application-modal; step header Check, Review, Update, Done).
- **Plain text only.** Every label showing a repo or app name, a reason, a verdict note, a step label or tool output is `Qt.TextFormat.PlainText`; output goes into a read-only `QPlainTextEdit` via `appendPlainText` (never `QTextEdit`, never `setHtml`, never `QLabel` auto-format). Output from git, Claude Code and build scripts is untrusted text, as `land-from-tiles` Secure required (pinned today by `test_land_ui.py:363`). ANSI CSI sequences and C0 controls except tab are stripped before display; the pane keeps the last 5000 blocks (`setMaximumBlockCount`).

### 8.7 Check builds: replacing the box and `RebuildDialog` without changing any path
`progress.build_check_view(report, scoped)` takes the computation out of `show_build_report` unchanged (`apps_tab.py:872-943`: headline, the per-row lines, `commands`, `by_hand`, `forward`, `no_command`, `folders`, and the informative text). It returns a frozen view with the same strings, so the asserts on headline and informative text keep their meaning. `BuildCheckWindow` shows it as rows and offers exactly the buttons the box offered, under the same conditions:

| Button | Shown when (today) | Does (today, kept) | In the window |
|---|---|---|---|
| Update now | `commands or by_hand` (`:956-959`), default button | `run_updates(commands, by_hand)` (`:996-997`) | Review step; does not close; window moves to Update step |
| Copy commands | `commands or by_hand or forward` (`:961-962`) | `copy_commands(commands + by_hand + forward)` (`:986-987`) | Review step; closes the window, as the box did; also on the Update step (copies, does not close) |
| Copy and open Terminal | `commands or by_hand` (`:965-968`) | copy, then `open_terminal(lab_root)` (`:988-992`) | Review step; closes |
| Open in Terminal | `folders` non-empty (`:971-977`) | `open_terminal(folder)` for each (`:993-995`) | Review step; closes; same tooltip |
| Close | always, Escape button (`:981-983`) | nothing | Review and Done steps; Escape and the red button close |
| Cancel | during a rebuild (`RebuildDialog`, `:609-610,674-682`) | kills the running build; turns into Close | Update step; same |

Control flow stays linear and synchronous, as today: `show_build_report` calls `window.ask()` (shows the window, runs a local `QEventLoop` until a Review button or close, returns its label or `None`) and dispatches exactly as `:985-997` do. For Update now, `run_updates(commands, by_hand, window=window)` runs its preflight unchanged (`check_terminal_commands`, `:1013-1018`), then `Rebuild(commands, window).exec()`, which drives the window's Update step and returns, like `RebuildDialog.exec()` did, when the run has ended **and** the owner pressed Close. Then `recheck()`, the Terminal handoff for `by_hand`, and the one `launched` message, in today's order (`:1022-1048`). Only one local event loop runs at a time (ask's loop ends before Rebuild's starts), the same depth as the `QMessageBox.exec()` it replaces.

`Rebuild` keeps `RebuildDialog`'s contract: `Rebuild(commands, parent)`, `.exec()`, `.succeeded`, one command after another through `$SHELL -lc` with `launcher.child_env()` and merged channels, a failure stops the run, Cancel and closing kill the running build. It also **overrides `reject()`**: today Escape on `RebuildDialog` calls `reject()`, which hides the dialog without a `closeEvent` (checked on PySide6 6.12.0 in a scratch script: `reject()` sent no `closeEvent`), so `closeEvent`'s kill (`apps_tab.py:693-700`) does not run, `exec()` returns, and the build keeps going unwatched and `_finished` starts the next command. That is an existing defect (P1); `BuildCheckWindow` routes `reject`, `closeEvent` and the Close button through one path that kills a running build first.

Tests that pin these paths, all in `tests/test_apps_tab.py`; their assertions are kept and only the seam they patch changes (`QMessageBox.exec` -> `BuildCheckWindow.ask`, `apps_tab.RebuildDialog` -> `apps_tab.Rebuild`):
`test_a_tools_only_tab_checks_its_own_build` (:508), `test_a_scoped_check_never_speaks_for_every_app` (:546), `test_the_update_button_shows_only_when_something_is_behind` (:618), `test_a_by_hand_install_gets_update_now_and_is_named_in_the_text` (:700), `test_update_now_opens_terminal_for_a_by_hand_app_and_runs_no_dialog` (:722), `test_update_now_runs_the_in_app_rebuilds_then_opens_terminal` (:765), `test_a_failed_in_app_rebuild_opens_no_terminal` (:791), `test_a_release_clone_behind_is_listed_to_move_and_gets_no_update_now` (:818), `test_copy_commands_includes_the_forward_command_and_nothing_runs_it` (:835), `test_update_now_with_a_forward_row_runs_only_the_in_app_rebuilds` (:856), `test_two_by_hand_apps_get_two_separate_windows` (:877), `test_a_bad_terminal_command_stops_everything_before_any_rebuild` (:894), `test_a_terminal_that_will_not_open_is_shown_not_swallowed` (:920), `test_nothing_behind_means_no_update_now_and_no_terminal` (:944), `test_an_app_with_no_command_gets_open_in_terminal` (:957), `test_the_rebuild_dialog_runs_the_commands_in_order` (:995), `test_a_failed_rebuild_stops_the_run` (:1009), `test_build_check_dialog_can_be_dismissed` (:1023, becomes: the window has Close, and Escape closes it), `test_copying_the_commands_puts_them_on_the_clipboard` (:587, unchanged).

**Land all summary.** `show_land_summary(results)` (`apps_tab.py:1229`) keeps its name and its content ("Landed N of M repos.", one `name: line` per repo not landed) but writes the `LandWindow` end state instead of opening a box. `test_land_all_lands_every_repo_and_carries_on_past_a_failure` (`test_land_ui.py:152`) replaces that method and keeps passing. `_land_finished` (`:1222`) also calls `LandWindow.finish(results)` for a single-repo Land.

### 8.8 Throttling and the alive signal
- Events update the model immediately (O(1), no widget calls). A model change sets a dirty flag and starts a single-shot 100 ms render `QTimer` if it is not already pending: at most 10 renders a second, each rendering the latest `snapshot()`. Output lines are buffered in the model and appended to the pane once per render.
- A 500 ms tick `QTimer` advances the dots and marks the model dirty so elapsed, last-activity and the stale text move without events. Both timers run only while the window is visible and the run is live; hidden, the model still updates and nothing renders.
- **The worker is never blocked.** Its only contact with the GUI is `SimpleQueue.put` (`lander.py:102-106`): no lock shared with the GUI, no blocking queue bound, no signal emitted from the worker, no wait on a GUI result. Window cost lands on the GUI thread's drain, which already runs at 10 Hz (`lander.py:35`). The build side has no worker: `QProcess` delivers output on the GUI thread, and its pipe buffers while a render runs.

### 8.9 Threads in words
1. Land worker (`threading.Thread "lab-hub-land"`, `lander.py:81`): `land.land()` -> `repo_tidy.apply()` (blocking git, Claude Code, tests) -> `say(line)` and `events(StepEvent)` -> `SimpleQueue.put`. It never touches Qt or `durations.json`.
2. GUI thread, every 100 ms: `Lander._drain` -> `progress` (tiles, `_land_progress` unchanged; window output), `step` (window model; on `end`/`done`, `durations.record`), `repo_done` (tile outcome; window reason line), `finished` (tiles reset; window end state).
3. GUI thread, `QProcess` signals: `Rebuild` reads chunks -> lines -> `build_stage` -> model; on exit 0, the verify read and `durations.record`, then the next command.
4. GUI thread, render and tick timers -> `snapshot()` -> widgets.
`durations.json` is touched only by the GUI thread. Land (non-modal) can run while the modal Check builds window runs a rebuild; its drain timer keeps firing inside the modal loop, and both write through the same thread.

### 8.10 Alternatives rejected
- **Parse Land's text lines for structure.** Fragile against any wording change in `repo_tidy` and `claude_resolve`; the engine knows the step index and kind already.
- **A QThread with queued signals for Land.** The queue-and-drain pattern exists and is tested (`lander.py`, `repo_tidy_dialogs._Background`); adding a second mechanism buys nothing.
- **Stage events written by each build script.** Out of scope (spec §4); the fallback stage keeps the window truthful without them.
- **SQLite or one file per subject for history.** Five floats per key; one small JSON file with an atomic replace is enough, and per-subject files would turn repo names into paths.
- **Keep `QMessageBox` and add a progress dialog on top.** Two modal windows in sequence is today's problem; the spec asks for one window.
- **Write durations from the worker thread.** Would need a lock shared with the GUI writer and makes the worker's I/O longer; GUI-thread writes are a few KiB.

### 8.11 Failure modes and migration
- No existing state is migrated: `durations.json` is new; on first run every window says "Estimating…" until a step of that kind has finished once. Deleting the file resets estimates; nothing else reads it.
- Broken or hostile `durations.json`: ignored (8.4); a 6 h cap per sample and the 5-sample median stop one bad value from dominating.
- A build whose output changes: markers stop matching -> one "Rebuilding" stage; estimate still from `rebuild`.
- A `claude_merge` that merges cleanly at run time takes the plain merge path (`repo_tidy.py:884-891`) and records a short sample under `claude_merge`; the median of 5 absorbs an occasional one.
- Window closed or hidden mid-Land: landing goes on (non-modal, close = hide); tiles keep their line. Window closed or Escape mid-rebuild: the build is killed, as `RebuildDialog.closeEvent` intended.
- Quit mid-Land: unchanged (`Lander.shutdown`, `lander.py:69-76`); a step that never ended records nothing.

### 8.12 Test plan sketch
- `tests/test_durations.py`: round trip; median of 1..5; 6th sample drops the oldest; missing, empty, invalid JSON, `version: 2`, list instead of object, string samples, NaN/negative/over-cap, 300 KiB file -> empty history, no exception; subject sanitising (control characters, 500-char name, `../x`) stays a key and creates no other file; 201st subject evicts the oldest; save leaves no `.tmp` behind and the file is mode 0600; `OSError` on save returns `False`; path follows `config.SUPPORT_DIR`.
- `tests/test_progress.py` (fake clock, fixture event sequences): percent, counts and stage aggregation for a 2-repo plan with a failure and a stop; estimate `None` until every remaining unit has history; `left` never negative and `overrun` set past the median; `done_around` with a fake wall clock; stale text at 59 s vs 60 s; `fmt_left(60)` -> `~60 s`, `fmt_left(61)` -> `~2 min`; `build_stage` on real lines copied from each script listed in 8.5 plus negatives (`INFO: Building EXE`, `Built-in`, a line with `<b>`); monotonic advance ignores a late `build` line; no-marker run -> single stage; `build_check_view` headlines and text equal today's for the fixtures used in `test_apps_tab.py`.
- `tests/test_land.py`: `land()` with a recording `events` and counter clock emits start/end pairs in plan order with correct `index`, `count`, `kind`, outcomes `done`/`failed`/`skipped`; an `events` callback that raises changes neither the result nor the progress lines; `events=None` gives identical progress lines to today.
- `tests/test_land_ui.py`: all existing tests pass unchanged; new: the window opens after confirmation, rows and percent follow a real two-repo Land, Hide keeps landing, its Stop calls `lander.stop`, `durations.json` in the tmp support dir has samples afterwards, an output line `<b>x</b>` shows literally.
- `tests/test_apps_tab.py`: the 19 tests in 8.7 with seams renamed and assertions kept; new: Escape during a rebuild kills it and the next command never starts (regression for the `reject()` defect); stage chips advance on a fake command printing the lab_hub markers; verify row shows the read version.
- Mutation-check: `step_outcome`, `build_stage`, the median/eviction code and the `left`/`overrun`/`stale` thresholds.
- Full suite: `python -m pytest` (README: offscreen). app-context lists no other modes.

### 8.13 Risks
- The two local event loops in Check builds (`ask`, then `Rebuild.exec`) re-enter the GUI while a slot is on the stack, as `QMessageBox.exec()` does today; a second Check builds click is impossible because the window is application-modal.
- Verify adds one `launcher.version()` read per rebuilt app on the GUI thread; if it proves slow on a large repo, it can move behind the end-of-run `recheck()` (see open question 2).
- Estimates are per repo per kind, so a repo's first `claude_merge` shows "Estimating…" for the whole run (approved decision 2: no guess before one exists).
- Changing the patch seams in 19 tests is mechanical but large; Review should diff assertions, not just names, to confirm nothing was weakened.

### 8.14 Open questions for the owner
1. **Getting a hidden Land window back.** The spec says closing it hides it; nothing says how to reopen it. Recommend a "Show progress" button beside "Stop landing" on the page (`apps_tab.py:813-820`), visible while a Land runs. Alternative: clicking a tile's "Landing…" line.
2. **What Verify means.** Recommend Lab Hub's own installed-version read per app right after its command exits 0 (8.5), informational only. Alternative: drop Verify and show three stages (build, package, install).
3. **Copy commands closes the window** on the Review step, as the box did today. Recommend keeping that for parity; say if it should stay open instead.

### 8.15 Build notes
Phase: Build (`engineer`), 2026-11-17. Tasks 1-6 of §9. Not committed (the owner has not asked).

**Files.** New: `lab_hub/durations.py`, `lab_hub/progress.py`, `ui/progress_window.py`, `ui/rebuild.py`, `tests/test_durations.py`, `tests/test_progress.py`, `tests/test_progress_window.py`. Changed: `lab_hub/land.py` (`StepEvent`, `step_outcome`, `land(events=, clock=)`), `ui/lander.py` (`step` signal, `Lander(clock=)`), `ui/apps_tab.py` (`RebuildDialog` removed; `show_build_report`/`run_updates` drive `BuildCheckWindow` and `Rebuild`; Land slots feed `LandWindow`; "Show progress" button; `show_land_summary` writes the window's end state), `ui/theme.py` (one "progress windows" block of rules, palette colours only), `tests/test_land.py`, `tests/test_land_ui.py` (new tests appended; the 24 existing ones unchanged and passing), `tests/test_apps_tab.py`.

**Tests.** Before: 728 collected, suite exit 0. After: 842 collected, 841 passed, 1 skipped (`test_converter_drift.py:85`: Imprint not checked out beside this worktree, environmental) (+32 durations, +50 model, +10 widgets, +11 `test_land.py`, +5 `test_land_ui.py`, +6 `test_apps_tab.py`). The 19 tests of §8.7: only `QMessageBox.exec` -> `BuildCheckWindow.ask` and `apps_tab.RebuildDialog` -> `apps_tab.Rebuild` changed (and the matching import line); no assertion removed or loosened. `BuildCheckWindow` keeps the box's `text()`, `informativeText()` and `buttons()` so the existing fakes read it unchanged. The two runner tests (`test_the_rebuild_dialog_runs_the_commands_in_order`, `test_a_failed_rebuild_stops_the_run`) build a window plus `Rebuild` instead of `RebuildDialog` and read `cancel_button`/`output_text()` instead of `_button`/`_log`; assertions kept. `test_build_check_dialog_can_be_dismissed` now checks the window (Close, the red button and Escape). Escape regression: `test_escape_during_a_rebuild_kills_it_and_the_next_command_never_starts`; the same scenario against HEAD's `RebuildDialog` (scratch script) left the build running and ran the next command.

**Deviations from §8, with reasons.**
1. `RunModel` is a base class with `LandModel` and `BuildModel` subclasses rather than one class: the two windows' rows differ (units vs. a command with stages); the base keeps times, estimate, stale text, output buffer and formatting shared.
2. `BuildCheckWindow` exposes `choice` beside `ask()`'s return value; `show_build_report` reads `window.choice` after `ask()` (as it read `box.clickedButton()` after `exec()`), so the test fakes can keep returning nothing and clicking a button.
3. The window talks back to the page through signals (`LandWindow.stop_requested`, `BuildCheckWindow.copy_requested`), not stored callbacks: a closure over the page kept on its own child window freed the page during the window's deferred delete and crashed the suite (reproduced in a scratch script).
4. One live-output pane per window, under the rows, rather than inside the running row as drawn: moving one `QPlainTextEdit` between rows at every render is fragile, and it keeps the last 5000 lines in one place. Repo names prefix Land output lines unless the line already starts with them; step labels in the expanded row drop the leading "repo: ".
5. No "Show full log" button (mockup) and no shimmer on the bar: neither is in §2 or §8.7; Live output is the full log. The dots and the row spinner are painted widgets moved by the 500 ms tick, which renders through the same 100 ms single-shot timer as events (so at most 10 renders a second, ticks included).
6. A single-tile Land with nothing to do (no confirmation is asked) opens no window, as before; Land all always opens it, so its "Landed N of M repos." summary is never lost. Land all re-shows a hidden window at the end, since its end state replaces the box that always appeared.
7. Update now with only Terminal installers closes the window before Terminal opens (nothing to watch in-app).
8. Waiting stage chips use the palette's `field_border` (Paper's `field` is white on a near-white window and was invisible in the render).

**Evidence.** Offscreen PNGs of both windows (mid-run with and without history, finished; Check builds at Review, Update and Done; Paper and Graphite) were compared with the mockup; layout gaps fixed (overlapping count labels, invisible waiting chips, Land window unpainted in Graphite, step header order). Not verified: on a real display, on the real lab, a real `build_app.sh` run (the success measure's screenshot is task 8), mutation check (task 7), and any linter (none is configured; `py_compile` and an AST unused-import pass found nothing new).

**Fixes after Review/Verify/Secure** (engineer, 2026-11-17; reports in `docs/audit/progress-windows-{review,qa,security}.md`). Finding -> fix -> test (`tests/…`). Each test failed on the code before the fix, except the QA mutant-killing tests, which pin behaviour that was already right.
- Review P1-1 -> `Rebuild` handles `errorOccurred(FailedToStart)` (run ends failed, row "It could not start", `exec()` returns); `cancel()` with nothing running ends the run; `BuildCheckWindow.done()` (reached by Escape, the red button, Close and the caller) cancels any rebuild not yet ended -> `test_apps_tab::test_a_command_that_cannot_start_ends_the_run_as_failed`, `::test_escape_after_a_command_could_not_start_returns`, `::test_escape_before_the_first_command_starts_runs_nothing` (also Secure P3-1).
- Review P2-1 -> Cancel calls `rebuild.cancel()` only; the window stays at Done, button Close, rows and outcome readable -> `test_apps_tab::test_cancel_during_a_rebuild_stops_it_and_leaves_the_window_at_done`.
- Review P2-2 -> `AppsTab._land_window_owns_run` / `_run_window()`: only the window opened for the running Land is fed, finished and offered by Show progress -> `test_land_ui::test_a_later_land_that_opens_no_window_leaves_the_finished_one_alone`.
- Review P2-3 / Secure P2-1, P3-2 -> `durations.load()` catches anything (deep nesting, huge ints); `_sample` drops ints too big for a float; reads via `os.open(O_NOFOLLOW|O_NONBLOCK)` + `fstat` `S_ISREG` + bounded read -> `test_durations::test_a_hostile_file_is_no_history_and_the_next_save_replaces_it[*]`, `::test_a_huge_integer_sample_is_dropped_not_raised`, `::test_a_fifo_at_the_path_is_not_read_and_does_not_hang`, `::test_a_symlink_or_a_directory_at_the_path_is_not_read`.
- Review P2-4 / Secure P2-2 -> each command starts in its own session (`QProcess.setUnixProcessParameters(CreateNewSession)`; PySide6 6.12 has no `setChildProcessModifier`); cancel sends SIGTERM to the group, waits up to 2 s, then SIGKILL. Command path unchanged (`$SHELL -lc`, `child_env()`, merged channels) -> `test_apps_tab::test_cancel_stops_what_the_build_started_not_only_the_shell`.
- QA P1 (finding 1) -> Escape and close tests bound `exec()` by a watchdog and assert it returns within 5 s -> `test_apps_tab::test_escape_during_a_rebuild_kills_it_and_the_next_command_never_starts`, `::test_the_close_button_during_a_rebuild_kills_it_too` (assertions added, none removed).
- QA P2 (findings 3-8) -> tests only: `test_progress_window::test_renders_are_throttled_to_ten_a_second` (adds >= 3 renders during a ~2 ms-per-line flood; a debounce gives 0), `::test_the_tick_moves_the_dots_and_the_clocks_with_no_events`, `::test_only_a_finished_land_step_is_recorded`, `::test_the_check_builds_step_header_and_end_lines`; `test_apps_tab::test_a_failed_build_records_no_durations` (cancelled: in the P2-1 test); end lines added to `::test_the_rebuild_dialog_runs_the_commands_in_order` and `::test_a_failed_rebuild_stops_the_run`; `test_progress::test_a_running_step_with_no_history_says_estimating` (LF4), `::test_done_around_adds_the_time_left_to_the_wall_clock` (LF5).
- QA P3 survivors -> `test_progress::test_at_exactly_the_median_it_is_not_yet_taking_longer` (LF2), `::test_overrun_is_said_even_when_a_later_step_has_no_history` (LF6), `::test_a_stage_with_a_failed_step_and_a_running_one_is_running` (LS1), `::test_a_long_step_list_folds_earlier_steps_and_the_rest` (">5 earlier", "and N more", `partial`); `test_durations::test_load_keeps_only_the_last_five_samples_of_a_hand_edited_file` (DU4), `::test_load_of_a_hand_edited_file_keeps_the_newest_two_hundred` (DU8), `::test_record_writes_at_most_two_hundred_subjects` (DU7); `test_apps_tab::test_a_version_read_that_raises_does_not_end_the_run` (QA 13). ESC2/ESC3/ESC4 are killed by the Escape/Cancel tests above. `Dots.advance()` (dead code, QA 14) removed. Not covered: "Not reached" (QA 11).
- Review P3-1 -> the cancel in `done()` above -> `test_apps_tab::test_done_stops_a_running_rebuild`.
- Review P3-2 -> `run_updates` deletes a window it created -> `test_apps_tab::test_update_now_without_a_window_deletes_the_one_it_made`.
- Review P3-3 -> the tick starts only once the snapshot is `started` -> `test_progress_window::test_nothing_ticks_at_review`.
- Review P3-4 -> renamed to `test_apps_tab::test_update_now_hands_its_open_window_to_the_rebuild`; assertions added (same window, not closed before the hand-off, the in-app command run); Copy-closes stays in `test_progress_window::test_review_button_answers_and_copy_closes_update_stays`.
- Review P3-5 -> `land.step_outcome("not landed — stopped")` is `skipped` -> `test_land::test_step_outcome[False-not landed — stopped-skipped]`.
- Secure P3-4 -> `progress.plain()` also strips OSC/DCS/APC strings, other ESC sequences, DEL, C1 and bidi controls; applied to row names, reasons, step labels, outcome and details -> `test_progress::test_plain_strips_osc_c1_del_and_bidi_controls`, `::test_names_reasons_labels_and_the_outcome_are_cleaned_for_display`.
- Secure P3-3 -> output lines are cut at `progress.LINE_MAX` (4000) with "…"; `Rebuild` hands newline-free output on in 4000-character pieces -> `test_progress::test_a_very_long_output_line_is_cut`, `test_apps_tab::test_one_long_line_with_no_newline_is_shown_in_pieces_without_freezing`.
- Secure P3-5 -> the Open in Terminal tooltip is escaped (`<qt>` + `html.escape`) -> `test_progress_window::test_the_open_in_terminal_tooltip_is_plain_text`.

Mutation check of the fixes (scratch copy, one mutant at a time, as QA's method): 32 mutants of the new and fixed lines, including QA's TH2, TH4, TH5, REC1, ESC3, ESC4, DU4, DU7, DU8, LF2, LF4, LF5, LF6, LS1: all killed. Full suite after the fixes: 878 passed, 1 skipped (`test_converter_drift.py:85`, environmental), 300.9 s, offscreen. Changed from §8.7's wording: no `reject()` override any more; `done()`, which `reject()` reaches, does the cancel (a separate one in `reject()` was an equivalent mutant).

**After the re-review and real-lab render (orchestrator, 2026-11-17).** Re-review P3-A: SIGKILL only to a group still alive after the grace (`ui/rebuild.py` `_stop_group`). P3-B: documented in the `ui/rebuild.py` module docstring. Window title "Build check" -> "Check builds". The real-lab render showed repos with nothing planned as "Waiting · ~0 s": they now say "Nothing to land" from the start and are not counted as waiting (`LandModel.__init__`, test `test_a_repo_with_nothing_planned_says_so_from_the_start_and_is_not_waiting`); a long verdict no longer stretches the status pill (aligned top). README: two stale lines (test time, empty docs folders).
**Real-lab evidence (§2.6).** Rendered offscreen from the real lab, read-only (real `launcher.build_report`, real `land.make_plan` with Claude off, a temporary support dir so the real `durations.json` is untouched): `docs/audit/progress-windows-real-builds.png` (Check builds, Review step: 3 of 9 behind) and `docs/audit/progress-windows-real-land.png` (Land all, 7 repos, start state). Not taken: a Land mid-run or a rebuild mid-run on the real lab, since both change repos or installed apps; the mid-run states are shown with fixture data and covered by tests.

## 9. Plan
Phase: Plan (orchestrator), 2026-11-17, after the owner approved Architect ("Approve as recommended", all three §8.14 questions as recommended). The app has no backlog file (app-context leaves it unfilled), so the tasks live here. Milestone and estimate (2.5 h agent time) in `docs/foundry/plan.toml`.

| # | Task | Priority | Category | Owner |
|---|---|---|---|---|
| 1 | `lab_hub/durations.py` and `tests/test_durations.py` (§8.4) | P1 | feature | engineer |
| 2 | `StepEvent` in `lab_hub/land.py`, `Lander.step` in `ui/lander.py`, tests in `test_land.py` (§8.3) | P1 | feature | engineer |
| 3 | `lab_hub/progress.py` model, formatting, `land_stage`, `build_stage`, `build_check_view`; `tests/test_progress.py` (§8.5, §8.6) | P1 | feature | engineer |
| 4 | `ui/progress_window.py` widgets, render/tick throttle (§8.6, §8.8) | P1 | feature | engineer |
| 5 | `ui/rebuild.py` out of `RebuildDialog`, Escape kills the build (§8.7) | P1 | bug + refactor | engineer |
| 6 | `ui/apps_tab.py`: Land window, "Show progress", Land all summary, Check builds window; 19 tests re-seamed (§8.7) | P1 | feature | engineer |
| 7 | Review, Verify (mutation check), Secure | P1 | quality | code-reviewer, qa-engineer, security-engineer |
| 8 | README, CHANGELOG, version bump; screenshot of both windows on the real lab | P2 | docs | tech-writer |

Status 2026-11-17: tasks 1-6 built, not committed (§8.15); 7: Review, Verify and Secure ran and their findings are fixed (§8.15, "Fixes after Review/Verify/Secure"), re-Review and re-Verify open; 8 open.
