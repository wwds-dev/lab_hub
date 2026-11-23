# Nightshift panel: code review

23 November 2026. Independent read-only review (`code-reviewer` agent, not the author) of the
uncommitted Build of spec `nightshift-panel`. The reviewer ran the new tests (81 passed), Foundry's
`write_task` into a scratch folder against the reader, Foundry's `validate_task`/`validate_run` on the
fixtures, and Foundry's `verdict` argparse on the argv the panel builds.

| # | Sev | Finding | Fix |
|---|---|---|---|
| 1 | P1 | `diff.patch`, `tests.log` and `review.md` buttons never enabled for real records: Foundry lists files under their stem (`"diff": "diff.patch"`); the fixture listed them by full name and hid it. | Fixed: files keyed by the resolved file name; fixture lists by stem as Foundry does; drift test runs Foundry's `write_task` and reads the record back. |
| 2 | P2 | Accept enabled on failed, skipped and aborted tasks and on unfinished runs; accepting a failed task overrides Nightshift's `reject` in the track rule. | Fixed: Accept/Reject only for a `done` task of a `finished` or `aborted`, non-dry run; tested. |
| 3 | P2 | Cancel, the 30-minute cap and shutdown SIGKILLed the CLI, so its `finally` (unload model, stop server) never ran. | Fixed: SIGINT first, SIGKILL after 20 s (5 s on quit); tested with a CLI that cleans up on KeyboardInterrupt. |
| 4 | P3 | Track hint text wrong ("fewer than 10 is Building") and ignored `[track]`. | Fixed: text built from the thresholds in use. |
| 5 | P3 | UI thread stat'ed the disk (`resolved_lab_root`, `locate`, `shutil.which`) on selection changes and polls. | Fixed: Foundry folder found on the reader thread and cached from the snapshot; python found on the command thread. |
| 6 | P3 | `shutdown()` waited without a limit. | Fixed: 15 s, like the other panels. |
| 7 | P3 | A running night showed "Nothing armed" (Foundry removes `armed.json` at start). | Fixed: the newest run in state `running` is shown as running now; tested. |
| 8 | P3 | Dry runs counted toward the 30-run cap. | Fixed: 30 real runs plus up to 10 dry runs; tested. |

Checked and fine (reviewer): verdict argv incl. notes starting with `-`; allowlist refuses `run`,
`recheck`, `status`, `launchctl`; no hardcoded `/Users` paths, no `terminate()`; record `files` cannot
leave the task folder; unknown, missing, string and bool `schema_version` and broken JSON are Unreadable;
copied track rule matches Foundry; thread lifetime via `_LIVE`.
