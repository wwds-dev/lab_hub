# Security review: land-pick-and-time (Secure, light)

Reviewer: security-engineer (read-only subagent), 2026-11-18; saved by the orchestrator. Spec `docs/specs/land-pick-and-time.md` §7-8, ADR `docs/adr/0005-land-run-log.md`. Scope: commit 7aacfd2 plus the review-fix diff. Playbook `docs/playbooks/security-engineer.md` current (reviewed 2026-11-11). `docs/foundry/app-context.md` `## Security surface` is still a placeholder; scope came from the spec.

No P0 or P1.

## Threat model (short)
- Assets: the owner's repos and branches; Anthropic spend and data flow through the Claude Code CLI; integrity of `durations.json` and `land-runs.json`; a GUI thread that must not hang.
- Boundaries: repo names, paths, branches and reasons (git, lsof, apps.toml) are untrusted text in Qt widgets; the JSON files are a same-user-writable cache; Lab Hub -> Claude Code CLI -> Anthropic on the owner's login.
- Out of model: a same-user local attacker (can already rewrite the venv and repos).

## Findings

### P2-1 (older than this change): the Claude Code disclosure can understate run-time use
- Cost comes from the plan (`lab_hub/land.py:193-197` `LandPlan.cost`; `:360-388` `claude_panel`), but at run time later rounds re-plan with Claude (`:599-602`), a plain merge that became a conflict is re-planned as a Claude merge (`:620-624`, land-fast §3.5), and `triage()` reads the live `unlanded` (`:660-665`).
- Scenario: a repo with Claude Code available and two plain merges, nothing unlanded: no Claude pill, panel hidden if it is the only chosen repo. The first merge turns the second into a conflict; round 2 sends the conflicted files to Anthropic (up to $3), or a failed merge goes to triage (up to $0.50). With several repos, "at most $X in total" can be exceeded.
- Not caused by this change: the panel is rebuilt from `chosen()` (`ui/land_confirm.py` `_sync`), and `_land_planned` runs exactly the chosen plans by identity plus nothing-to-land plans, which `claude_panel` drops and which return before any Claude call (`land.py:765-771`). So `claude_panel(chosen) == claude_panel(picked)`.
- Fix (separate spec, owner's call): count each plain merge as a possible Claude merge and triage when `plan.claude` is set ("up to"), or show a fixed line that a merge turning into a conflict may use Claude Code, or enforce a run-time ceiling equal to the disclosure.
- Evidence: code reading; not reproduced live.

### P3-1: run-log validation lenient in harmless ways
- `"version": true` / `1.0` accepted (`True == 1`); `strptime` accepts `"2026-1-8T1:9"` and year 0001. Feeds only a muted plain-text line; counts, seconds and booleans are checked strictly. Fix (optional): `type(version) is int`.

### P3-2: temp files left by a hard crash are never cleaned
- `durations.py` `_write_json` (`mkstemp(prefix=f".{file.stem}.")`), unchanged pattern. A kill between `mkstemp` and `os.replace` leaves a 0600 `.land-runs.*.tmp` with counts only. Fix (optional): sweep stale temp files on load.

## Verified (no finding)
Probes with `.venv/bin/python` 3.11.15 against a scratch dir (`config.SUPPORT_DIR` redirected):
- Reading `land-runs.json`: symlink, FIFO (no hang), directory, >64 KiB, invalid UTF-8, 65,000-deep `[`, 13,000-deep `{`, 5,000-digit ints, NaN, `1e999`, negative/bool/string fields -> `[]` or the entry dropped, no exception. `landed > repos` clamped; 700 entries cut to 10.
- Writing: 0600 under umask 022, same-dir temp file, fsync, `os.replace`; a symlink target is replaced, not followed; a directory target returns False and leaves no temp file; out-of-range values refused.
- Stored: only `at` (minute), `repos`, `landed`, `seconds`, `stopped`. No names, paths or output.
- `durations.json`: same prefix `.durations.`, same content and mode; `tests/test_durations.py` passes.
- Plain text: with a repo named `<img src="file:///etc/hosts"><a href="x">n</a>`, every QLabel in the dialog and window is PlainText (also after toggling), tooltips go through `_plain_tip`, accessible names are raw text, "Took"/"Earlier" hold only numbers and dates.
- `_land_planned` fails closed: an exception, `[]` or any non-list non-True answer cancels; plans not offered are ignored (identity); nothing-to-land plans run only with a choice; left-out tiles reset at once.

## Not run
- Dependency audit (`pip-audit` not installed); no dependency changed, only standard library used.
- Full suite (left to the orchestrator); P2-1 not reproduced with a live Land.
