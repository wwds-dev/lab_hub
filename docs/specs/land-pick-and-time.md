# Spec: pick the repos to land, and see how long Land took

Status: **Define approved by the owner 2026-11-18 ("Approve as recommended"): all four §5 decisions as recommended.** Design is the mockup below. Architect: §8, approved by the owner 2026-11-18 ("Approve architecture"), including the end title "Land finished · N repos". Built; Review, Verify and Secure in `docs/audit/land-pick-and-time-*.md`.
In-flight check (`session_start.py --inflight`, 2026-11-18): no spec owns choosing repos in the confirmation or the Land window's end state. `land-confirm-dialog` (released in build 199) owns the confirmation's look; this spec adds a choice to it. `progress-windows` (document done) owns the Land window; this spec changes only its finished state and lets finished rows open. `land-fast` and `land-from-tiles` own what Land does; nothing here changes that. Another session ("Land: let Claude edit .claude/ files; test main once") is changing `lab_hub/land.py`; this spec needs no change to `land.py`'s engine.
Mockup: `docs/specs/land-pick-and-time-mockup.html` (filled with the data from the owner's build-199 screenshots).

## 1. Problem and evidence
Owner, 2026-11-18, with two screenshots of build 199: "a) this window should have uncheck option to exclude from the landing task b) window that shows the land time".
- **(a)** The Land confirmation (`ui/land_confirm.py` `LandConfirmDialog`) lists every repo Land all found, one card each (screenshot: sonar, lab_hub, sentinel, kaila and two more). The only choices are Land all of them or Cancel. To leave one repo out today you cancel and press Land on each other tile one by one.
- **(b)** The Land window (`ui/progress_window.py` `LandWindow`) shows "0:05 elapsed · Estimating…" while running, but when Land finishes the time line is hidden (`Header.draw`: `self.times.setVisible(snap.started and snap.live)`), so the total time is gone. Only a repo that landed cleanly keeps a time ("Landed · 2:14", `progress.py` `LandModel.on_repo_done`); a repo that ends "Needs you" shows no time, and a finished repo's step times cannot be opened. The owner wants to read off how long Land all took: the last slow run took 92 min and `land-fast` was built to cut that.
- `progress.fmt_clock` has no hours: a 92-minute run would read "92:00".

## 2. User and success measure
The owner, pressing Land all (or Land on one tile), choosing what to land, and afterwards wanting to know how long it took.

**(a) Pick the repos**
1. Every repo card in the confirmation has a checkbox at the left of its header, on by default, labelled for screen readers "Land <repo>". Clicking the card header or pressing Space on the box toggles it.
2. An unchecked card folds to its header line, dimmed, with a muted "Left out" pill in place of the step and stop pills. Checking it again opens it as before.
3. Everything that sums or counts follows the checked repos only, at once: the title ("Land 5 repos", "Land sonar" for one), the sentence under it (the stop count), the Claude Code panel (its lines and its one total; the panel disappears if no checked repo can use Claude Code), the Details text, and the primary button ("Land 5 repos", "Land" for one).
4. With nothing checked: the title says "Nothing chosen", the sentence says "Tick a repo to land it.", the Claude Code panel is hidden and the Land button is disabled. Cancel still works.
5. Only the checked repos run. Unchecked repos are not planned again, not touched, and their tiles go back to their normal state at once, as after Cancel. The Land window has a row only for the checked repos.
6. Single-repo Land (one card) shows no checkbox: Land and Cancel are the whole choice.
7. Every Land starts with every card checked (decision 2). Return still presses nothing; Escape still cancels (`land-confirm-dialog` decision 1).

**(b) See how long it took**
8. When Land finishes, the Land window's header keeps the time: "Took 14:22 · 13:55 to 14:09" (start and end clock times), in place of "elapsed · left". The title becomes "Landed 6 repos" / "Landed sonar" (or "Land stopped" when the owner pressed Stop landing). Times of an hour or more read "1:32:05", while running too.
9. Every repo that started shows its own time in its status pill, whatever the outcome: "Landed · 2:14", "Needs you · 0:41", "Stopped · 1:03". "Nothing to land" and "Not reached" show no time.
10. After the end, each finished row opens on click (a ▸ before the name) into its step list with each step's time, using today's step list ("Commit · 0s", "Merge feature-x (Claude Code) · 8:12"). Rows start folded; the running row still opens by itself while Land runs.
11. **Earlier runs (decision 3).** Under the header, one muted line with the last three finished Lands: "Earlier: 17 Nov 16:20 · 6 repos · 1:32:05 · 17 Nov 09:10 · 1 repo · 0:41". Shown only when there is at least one earlier run. The 92-minute run of 2026-11-17 was not recorded anywhere this line can read (`durations.json` keeps only the last 5 samples per step kind, with no dates or run totals), so the first comparison starts with the next Land.
12. Tests in the `tests/test_land_ui.py` / `tests/test_apps_tab.py` / `tests/test_progress.py` patterns; full suite green with `.venv/bin/python -m pytest`; offscreen screenshots of the dialog with one repo unchecked and of a finished Land window as evidence.

## 3. Scope
- `ui/land_confirm.py`: a checkbox per card (not for a single card), folding, live recount of title, sentence, Claude Code panel, Details and the Land button; `LandConfirmDialog.chosen()` returns the checked plans.
- `ui/apps_tab.py`: `confirm_land(plans)` returns the plans to land (an empty list for Cancel). `_land_planned` runs only those, resets the other tiles, opens the window for those. Tests that replace `confirm_land` with `lambda plans: True` keep working (True means all).
- `lab_hub/progress.py`: `fmt_clock` with hours; a finished snapshot carries "Took …" and start/end clock times; per-row time for every started row; finished rows keep their step list for opening; title at the end.
- `ui/progress_window.py`: header shows the end time line; finished rows open and fold on click.
- If decision 3 is yes: a short run log (date, repo count, total seconds, landed count; last 10 kept), written once when a Land finishes, read by the window. Where it lives is Architect's call (a new key in `durations.json` or its own file beside it).
- README (Land section), CHANGELOG, version bump.

## 4. Non-goals
- No change to what Land does, its order, guards or caps, or to planning (`lab_hub/land.py`).
- No per-step checkboxes inside a card (`land-from-tiles` dropped the 28-checkbox preview on purpose).
- No remembering which repos were left out last time (decision 2).
- No backfill of earlier runs from `repo-tidy.log`.
- The step kinds `rescue`, `untracked`, `switch` and `archive` are not in `durations.KINDS`, so their times are never recorded and a run with prep steps says "Estimating…" throughout (as in the screenshot). That is a `progress-windows` gap, a separate fix, not this spec.

## 5. Decisions for the owner
1. **A repo whose card has only stops** (nothing Land can do until you clear it). Recommend: checked like every other card; it costs nothing, and its "Needs you" row in the Land window is where Ask Claude picks it up. Alternative: start it unchecked, so Land all runs only repos with work to do.
2. **Remember left-out repos?** Recommend: no; every Land starts all checked, so a repo is never silently skipped. Alternative: remember until Lab Hub quits.
3. **Earlier runs line** (item 11). Recommend: yes, the last three finished Lands under the header; it needs one small new history (Architect GATE, as new persistent state). Alternative: only this run's time, no new state.
4. **Unchecked card.** Recommend: fold to its header, dimmed, "Left out". Alternative: keep it open, only dimmed (longer list).

## 6. Risks
- The Claude Code disclosure must cover exactly the repos that run. Mitigation: the panel and Details are rebuilt from `chosen()` on every toggle, and the run receives `chosen()`; a test unchecks the repo with Claude Code and asserts the panel is gone and `lander.run` got the other plans only.
- Tests that replace `confirm_land` return a bool; the new return type must accept both. Mitigation: `_land_planned` treats `True` as all plans, `False` as none.
- `apps_tab.py` and `progress_window.py` may also be edited by the `.claude/`-files session; Build reads the current tree first and stages by name.

## 7. Phases to run
Define (this file, **GATE**: user-visible), Design (the mockup, recorded here once approved), Architect (short section here; **GATE** only if decision 3 is yes: new persistent state), Plan, Build, Review, Verify, Secure (light: the run log is a file write under Application Support; repo names stay plain text), Document. Comply skipped: tier `public`, no new data flow or claim; the Claude Code disclosure is kept and now matches the chosen repos. Launch skipped: optional for `public`. Radar check at Define: not run from this session (a slash command; the owner or orchestrator runs `/radar-check land-pick-and-time`).

## 8. Architecture
Phase: Architect (`architect` role, by the orchestrator), 2026-11-18. **GATE: new persistent state (the Land run log, decision 3).** ADR: `docs/adr/0005-land-run-log.md`. No thread or module boundary changes. `lab_hub/land.py` is not touched.

### 8.1 Choosing repos (spec items 1-7)
- `ui/land_confirm.py`: `RepoCard` gets a `QCheckBox` (accessible name "Land <repo>") only when the dialog has two or more cards; clicking the header row toggles it. `toggled` folds the card (its body widgets hidden, header dimmed via a `out` property, "Left out" pill shown) and calls `LandConfirmDialog._sync()`.
- `_sync()` recomputes from `chosen()` (checked plans, plan order): title and sentence via the existing `headline()`, the Claude Code box (old one removed, a new `ClaudeBox(land.claude_panel(chosen))` inserted at the same place, or none), `details_text(chosen)`, the Land button text, and `setEnabled(bool(chosen))`. With none chosen, `headline([])` is extended to give "Nothing chosen" / "Tick a repo to land it." when the dialog has cards (today's "Nothing to land." stays for a dialog with none). The engine functions are reused unchanged, so the disclosure for the chosen set is exactly what a dialog built from that set alone shows; a test compares the two.
- `ui/apps_tab.py`: `confirm_land(plans)` returns `dialog.chosen()` on Land, `[]` on Cancel. `_land_planned` normalises the answer: `True` -> all plans, falsy -> cancel, a list -> those plans (by identity). It runs `chosen + [p for p in plans if p.nothing]` in plan order: repos with nothing to land are not cards and keep today's "Nothing to land" row in Land all's window. Tiles of the left-out repos get `set_landing(None)` and leave `_landing_cards` at once.

### 8.2 Times in the Land window (items 8-10)
- `progress.fmt_clock`: `h:mm:ss` from 3600 s (`1:00:00`); below an hour unchanged. The existing case `(3600, "60:00")` in `tests/test_progress.py` becomes `"1:00:00"` (the spec changes this behaviour; noted, not a weakened test).
- `RunModel` keeps `started_wall = wall()` at construction and `ended_wall` in `finish()`. `Snapshot` gains `took` ("Took 14:22 · 13:55 to 14:09", empty while live), `earlier` (item 11) and the end title.
- `Header.draw`: while live as today; finished, the times label shows `snap.took` instead of being hidden. `LandModel.snapshot` title when finished: "Land finished · 5 repos" ("Land finished · sonar" for one, "Land stopped" when any result has `stopped`). **Wording note:** the approved spec said "Landed 6 repos"; that would sit above today's outcome line "Landed 4 of 5 repos." and contradict it when a repo needs you, so Architect proposes "Land finished · N repos". The owner approves this at this gate.
- `RowView` gains `took: str` (a row whose first step started: `fmt_clock(ended - started)`, else ""). `RowView.status` stays the bare word ("Landed", "Needs you", "Stopped"): `handoff.qualifies` matches it exactly (`lab_hub/handoff.py:35`) and the Ask Claude prompt quotes it. The pill shows `status · took`. Today's landed status "Landed · m:ss" becomes `status="Landed"`, `took="m:ss"`, so the pill text is unchanged for landed rows; existing tests that assert a bare "Needs you" pill for a row whose steps ran get the time appended. A stopped result gets `status="Stopped"`, tone muted; `handoff_rows` already skips stopped results.
- Opening finished rows: `RowView` gains `openable` (finished and has units) and finished rows carry their full step list (`_steps_all`: every unit, its outcome and `fmt_took`, no "earlier steps" folding). The window keeps `_open: set[str]` of row names; `Row` gets a small flat `QToolButton` (▸/▾, accessible name "Show steps of <repo>") before the name, visible only when `openable` and not live. While live, only the running row opens, as today. `_open` is cleared by `start()`.

### 8.3 Earlier runs (item 11; ADR 0005)
- One file `~/Library/Application Support/Lab Hub/land-runs.json`: `{"version": 1, "runs": [{"at": "2026-11-18T14:09", "repos": 5, "landed": 4, "seconds": 862.1, "stopped": false}]}`, newest last, the last 10 kept. Not inside `durations.json`: `durations.save()` writes only `version` and `subjects`, so any other key would be lost on the next step record.
- In `lab_hub/durations.py` beside the step history, sharing its safeguards: `_read` (no symlink, no FIFO, size cap 64 KiB), the atomic temp-file-and-replace write (the save body is extracted into `_write_json(file, obj)` and `save()` calls it; behaviour unchanged), lenient `load_runs()` (anything wrong -> `[]`, never raises; each entry validated: `at` parses as ISO minutes, `repos`/`landed` ints 0..500, `seconds` a valid sample, `stopped` bool), `record_run(...) -> bool`. `runs_path()` follows `config.SUPPORT_DIR` at call time, so the autouse test fixture isolates it.
- Written once per finished Land that had a window, on the GUI thread in `LandWindow.finish`, after the model's `finish()`: `at` = `ended_wall` to the minute, `repos` = rows that are not "Nothing to land", `landed` = results with state `landed`, `seconds` = elapsed. No repo names or paths are stored.
- Read once in `LandWindow.start()` (before this run is recorded): the last three entries, newest first, as one muted line "Earlier: 17 Nov 16:20 · 6 repos · 1:32:05 · …" (" · stopped" after a stopped run). Hidden when the log is empty.

### 8.4 Tests (Build writes them first or alongside)
- `tests/test_land_confirm.py`: checkbox only with 2+ cards; unchecking folds and dims; title, sentence, button text follow; the Claude Code box disappears when the one Claude repo is unchecked and its total drops when one of two is; `details_text` covers only the chosen; none chosen -> "Nothing chosen" and Land disabled; Return still presses nothing; the chosen-set panel equals a dialog built from that set.
- `tests/test_land_ui.py` / `tests/test_apps_tab.py`: `confirm_land` returning a subset runs only those plans (plus nothing-to-land ones), resets the other tiles, the window has rows for the run only; `True` still means all; Cancel unchanged.
- `tests/test_progress.py`: `fmt_clock` hours; `took`/span with fake clock and wall; per-row `took` for landed, needs-you and stopped rows, none for nothing/not-reached; status words unchanged for `handoff.qualifies`; end titles; full step list for a finished row.
- `tests/test_durations.py`: run log round trip, keeps 10, hostile/oversized/symlink/FIFO/wrong-type entries -> `[]` or the entry dropped, `save()` still unchanged.
- `tests/test_progress_window.py`: finished header shows "Took …"; the ▸ button opens a finished row's steps; the earlier line appears with a seeded log and not without.
- Mutation check on the new `progress.py` and `durations.py` logic; full suite with `.venv/bin/python -m pytest`; offscreen screenshots (dialog with one repo unchecked, finished window) as evidence.

### 8.5 Risks
- Another session is editing Land code; Build re-reads `ui/apps_tab.py`, `ui/progress_window.py` and `lab_hub/progress.py` before each edit and stages by name.
- Rebuilding the Claude Code box on toggle must not leave the old widget visible; a test checks only one box exists after several toggles.

## 9. Build
Phase: Build (`engineer` role, by the orchestrator), 2026-11-18. Files: `lab_hub/durations.py` (run log, `_read(limit)`, shared `_write_json`), `lab_hub/progress.py` (`fmt_clock` hours, `took_line`, `earlier_line`, `MONTHS`, `RowView.took`/`openable`, `Row.time_text`, end titles, stopped rows), `ui/progress_window.py` (finished header time, "Earlier" line, row opener, run recorded once per Land that ran a repo), `ui/land_confirm.py` (tick boxes, folding, `chosen()`, `_sync`, `_refit`), `ui/apps_tab.py` (`confirm_land` returns plans; `_land_planned` runs the choice). README, CHANGELOG. Version: `v<MAJOR>.<BUILD>` moves with the commit count.
Existing tests changed to the approved behaviour, not loosened: `fmt_clock(3600)` reads `1:00:00`; the single-Land title reads "Land finished · repo"; `confirm_land` returns `[]`/`[plan]`; a "Needs you" pill carries its time; the pill list counts visible pills (the hidden "Left out" pill).
**Wording for the owner:** the "Earlier" line uses commas inside a run and " · " between runs ("Earlier: 17 Nov 16:20, 6 repos, 1:32:05 · 17 Nov 09:10, 1 repo, 0:41"); with " · " everywhere, as §2 item 11 had it, three runs read as one chain. Review P3-1.
Evidence: `docs/audit/land-pick-and-time-confirm.png` (one repo unticked, fixture data from the owner's screenshot) and `docs/audit/land-pick-and-time-window.png` (finished window with a run in the log and one row opened), rendered offscreen with a temporary support dir. Not verified: on a real display and a real Land all (the owner's next Land all gives the real "after" time).
