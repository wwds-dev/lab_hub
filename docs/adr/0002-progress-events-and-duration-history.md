# ADR 0002: Structured progress events and a duration history file

Status: proposed (architect, 2026-11-17); awaits the owner's Architect gate for spec `progress-windows`.
Spec: `docs/specs/progress-windows.md` §8.

## Context
Land and Check builds report progress only as free text: `Lander.progress(str, str)` (`ui/lander.py:27`) carries one line per step, and the rebuild shows raw `QProcess` output (`ui/apps_tab.py:652-660`). The approved progress windows need a percent with a fixed denominator, per-step and per-stage state, and a time-left estimate from past runs. Text lines cannot give a reliable step index or kind, and nothing records how long a step took.

Two choices here are hard to reverse once other code and the owner's machine depend on them:
1. The shape of what crosses the Land worker boundary. The Land worker is a `threading.Thread` that talks to the GUI only through a `queue.SimpleQueue` drained every 100 ms (`ui/lander.py:33-36,81,109-128`). Anything added becomes a contract between `lab_hub/land.py` and every UI that listens.
2. A new persistent file under `~/Library/Application Support/Lab Hub/`. Its format lives on after any version of the code that wrote it.

## Decision
1. **`land.StepEvent`, a frozen dataclass of plain values** (`repo`, `index`, `count`, `kind`, `phase` start/end, `at`, `started`, `outcome` done/failed/skipped, `label`), emitted by `land.land()` around each `repo_tidy.apply` through a new optional `events` callback, with timestamps from an injectable monotonic `clock`. Text lines stay exactly as they are. The worker puts events on the same `SimpleQueue` as the text lines; the GUI drain emits them as one new `Lander.step` signal. The worker never emits Qt signals, never takes a lock the GUI holds, and never waits on the GUI. The percent denominator comes from the plans the GUI already holds before `run()`.
2. **`durations.json`, version 1**: `{"version": 1, "subjects": {"repo:<name>" | "app:<key>": {<kind>: [<= 5 floats]}}}`. Estimate = median. Recorded only for steps that finished successfully. Written only on the GUI thread by load-update-save with a same-directory temp file (`mkstemp`, mode 0600), `fsync`, and `os.replace`. Loaded leniently: missing, broken, oversized (> 256 KiB), wrong-version or wrong-typed content means "no history", never an exception. Names are sanitised JSON keys, never path parts. Bounded at 200 subjects, 5 samples, 6 h per sample, whitelisted kinds.
3. **Build stages are inferred, not reported**: a pure `build_stage(line)` maps known output markers to build/package/install, advancing monotonically, with a single "Rebuilding" stage as the fallback. Build scripts in other repos are not changed.

## Consequences
- Any future UI on Land (a menu bar item, a notification) can use `Lander.step` without parsing text. Changing `StepEvent` fields later means changing every listener; adding a field with a default does not.
- `land()` keeps its "never raises" contract: a failing `events` callback is ignored. `events=None` is today's behaviour, so `land()`'s existing callers and tests are unaffected.
- The history is a cache: deleting or corrupting it costs only estimates ("Estimating…" until the next successful step). A future format bumps `version`; version 1 readers treat it as empty and the next save rewrites it as version 1, so a downgrade loses history but never crashes. A reader that wants to keep newer files must not save over them; that is the cost of keeping v1 simple.
- GUI-thread writes cost one small file write per finished step. If that ever shows in a profile, batching writes per repo is a local change inside `lab_hub/durations.py`.
- Stage inference breaks quietly when a build script's output changes; the fallback keeps the window truthful but less detailed. Printing explicit stage markers from the scripts is a possible follow-up per app.
- Secure phase must review the new file write (location, mode, atomicity, bounds) and the plain-text rendering of tool output in the new widgets.
