# ADR 0005: a small Land run log beside the step history

Status: accepted by the owner 2026-11-18 ("Approve architecture").
Spec: `docs/specs/land-pick-and-time.md` §8.3 (decision 3: show the last three Land runs).

## Context
The owner wants to read how long Land all took and compare it with earlier runs. `durations.json` (ADR 0002) keeps only the last 5 samples per repo and step kind, with no dates and no run totals, so a run's total cannot be rebuilt from it. `durations.save()` writes only `version` and `subjects`, so a new key inside that file would be dropped by the next step record.

## Decision
1. **Its own file:** `~/Library/Application Support/Lab Hub/land-runs.json`, `{"version": 1, "runs": [...]}`, newest last, at most 10 entries of `at` (local time to the minute), `repos`, `landed`, `seconds`, `stopped`. No repo names, paths or output.
2. **Same safeguards as `durations.json`,** in the same module: read without following a symlink and only a regular file of at most 64 KiB; lenient load (anything wrong reads as no runs, never an exception; bad entries are dropped); atomic write through a same-directory temp file, `fsync` and `os.replace` (the existing save body becomes a shared `_write_json`).
3. **One writer, one write per run:** the GUI thread, in `LandWindow.finish`. Read once when a Land window starts.
4. **A cache, not a record.** Deleting the file only hides the "Earlier" line until the next Land.

## Alternatives considered
- **A `runs` key in `durations.json`.** Would need `save()`/`record()` to carry it through every step write; one mistake loses it. Rejected.
- **Rebuild totals from `repo-tidy.log`.** Its lines are text for people; parsing them for timing is fragile. Rejected.
- **No history (decision 3 alternative).** The owner chose the line.

## Consequences
- A second small file under Application Support; Secure checks the write like ADR 0002's.
- The first comparison is with the next Land; the 92-minute run of 2026-11-17 is not in any record this can read.
