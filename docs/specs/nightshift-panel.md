# Nightshift panel

Needs: define, design, architect, build, review, verify, secure, document

23 November 2026. Phase 2 of Nightshift (Foundry, `docs/nightshift.md`, merged 23 Nov). Phase 1 writes
everything under `<foundry>/local-drafts/nightshift/`; this panel shows it and drives the CLI. The data
contract is Foundry's `docs/nightshift-audit-schema.md`, schema version 1.

## Problem
Arming a night, reading the gate, checking last night's grades and recording verdicts all happen in a
terminal today, across `run.json`, `record.json`, `track.jsonl` and `notices.jsonl`. The owner wants one
page in Lab Hub that shows tonight and the history and runs the few owner commands.

## Scope
A built-in tool **Nightshift** under Tools (tile plus page), reading `<lab root>/foundry/local-drafts/nightshift/`.
The Foundry folder is found from Lab Hub's lab root (`Settings.resolved_lab_root()`), never a hardcoded path;
it counts as present only when `tools/nightshift.py` exists there.

Sections, top to bottom:
1. **Tonight**: armed or not (`armed.json` and its `run.json`), ticked tasks, the window, and the pre-start gate:
   memory (needed, available, compressed, swap, short by, apps to close with GB), task load, per task the
   predicted band and score, reasons, fix hints, lossy-quant flag; blockers and warnings. Stop files shown when present.
2. **Tasks**: `tasks/*.toml` with id, title, type, app, estimate and approved yes/no; a tick box per task feeds
   Plan and Arm. A task file that fails to parse shows as unreadable.
3. **Runs**: newest first. Per run: state, dry run, abort `{rule, why}`, and per task status, band and score,
   predicted score, gap, retries, model, quant (flag `lossy_quant`), branch, the owner's verdict; buttons to open
   `MORNING.md`, `diff.patch`, `tests.log`, `review.md` when listed in `files` and present. A dry run that was
   cancelled shows its memory check and its `checks`.
4. **Track record** per task type: status (allowed, building, watch, daytime only), accepted of the last 10, mean gap.
5. **Notices**: newest first.

Actions: Plan (ticked tasks), Arm (ticked tasks), Disarm, Stop after this task, Stop now, Clear stop, Dry run,
and Accept / Reject (with an optional note) on a task of a finished run. Each runs
`python3 tools/nightshift.py <args>` in the Foundry folder, off the UI thread, and shows the command,
its output and exit code. Arm, Disarm, Stop now and Reject ask for confirmation first.

## Rules
- The panel never writes in the Nightshift folder; every change goes through the CLI.
- It never edits a task's `approved` flag; never runs `run`, `recheck`, or anything with `launchctl`.
  The command builder accepts only the listed subcommands and refuses everything else (tested).
- A record whose `schema_version` is missing, not 1, or that fails to parse is shown as **Unreadable** with the
  reason; no field is guessed. Unknown extra fields are ignored.
- Empty states said plainly: no Foundry folder, no state folder yet, nothing armed, no runs, no tasks.

## Out of scope (in `TODO.md`)
Scheduler, notification delivery, task spec editor, model watch, device scanner, savings tracker.

## Design
One scrolling page in Lab Hub's look (`ui/theme.py` cards, section titles, pills: `stateOk`, `stateWarn`,
`stateBad`, `hint`). Each section is a card; long lists are tables. The command bar sits at the top under
the title; a read-only output box below it shows `$ nightshift.py ...`, the output, and `exit N`. Buttons are
disabled while a command runs. Unreadable rows use the warning pill and the reason in plain words.

## Architecture
- `lab_hub/nightshift.py` (no Qt): `locate(lab_root)`, `read_state(state_dir) -> Snapshot` (frozen dataclasses;
  each run and task record is either a parsed record or `Unreadable(path, reason)`), `track_summary`, and
  `command(subcommand, ...) -> list[str]` with the allowlist. The track rule and `read_track` merge are copied
  from Foundry (`nightshift_quality.track_status`, `nightshift_audit.read_track`) with a drift test that runs
  the Foundry originals against the same fixtures when the Foundry checkout is present and skips otherwise.
  The track thresholds are read from `[track]` in `tools/nightshift.toml` when present.
- `ui/nightshift_tab.py`: the page. A `QTimer` polls every 5 s while the page is visible; each poll starts a
  one-shot reader `QThread` (skipped if the previous one is still going) that returns a `Snapshot`; the UI only
  renders. Commands run in a `CommandWorker` `QThread` with `subprocess.Popen`, no shell, cwd the Foundry folder,
  a 30-minute cap; Cancel sends SIGINT so the CLI's cleanup runs (model unloaded, server stopped), then
  kills the child after 20 s; never the thread (no `QThread.terminate()`).
- `MainWindow`: a Tools tile; `busy_reasons` names a running command; `shutdown()` stops the poll, kills a
  running child and waits for both threads.

## Acceptance
- `tests/test_nightshift_reader.py`: records built in the tests to schema version 1 (armed run with gate, a
  cancelled dry run with only memory, a finished run with task records); a refused `schema_version` (2,
  missing, a string) and a broken JSON file are Unreadable; empty and missing folders; track summary rules;
  allowlist refuses `run`, `recheck`, `launchctl`, unknown words.
- `tests/test_nightshift_tab.py`: the page renders those states; commands run against a fake CLI script and show
  output and exit code; nothing is written in the state folder by the panel.
- Drift test for the copied track rule. Full suite green; `python main.py --selftest` passes.

## Review (23 Nov 2026)
Independent read-only review: 1 P1, 2 P2, 5 P3, all fixed (`docs/audit/nightshift-panel-code-review.md`).
