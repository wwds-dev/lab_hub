# Code review: claude-handoff (commit 69aa809)

Reviewer: `code-reviewer` agent, read-only, not the author. Date: 2026-11-17.
Against: `docs/specs/claude-handoff.md`, ADR 0004, AGENTS.md. Playbook `docs/playbooks/code-reviewer.md` is current (last reviewed 2026-10-14).

Tests run by the reviewer: `tests/test_handoff.py tests/test_handoff_ui.py`, 37 passed. The full suite was run by the author: two runs, exit 0.

## P1
**P1-1. Permission rules do not hold limits 1 and 3 when the repo's own settings allow broad Bash commands.** (`lab_hub/handoff.py` SETTINGS; spec §4.2; ADR 0004 §3)
- **Evidence.** Several repos' `.claude/settings.local.json` allow broad inline Python:
  - `imprint` and `sentinel`: `Bash(python3 -c ' *)`, `Bash(python -c ' *)`, `Bash(.venv/bin/pip install *)`;
  - `sonar`: `Bash(python3 -c ' *)`.
- **Failure.** A session in imprint can run any of these without asking:
  - `python3 -c '…subprocess.run(["git","push"])'`, which avoids `Bash(git push:*)`;
  - a runpy call of `legal_gate.py` with `sign` in argv, which avoids `Bash(*legal_gate.py sign*)`;
  - `open("docs/legal/signoff.jsonl","a")`, which avoids the Edit/Write deny rules, since those cover only the Edit and Write tools.
- **Author's check, 2026-11-17.**
  - `claude --help` (2.1.304) lists `--setting-sources <user,project,local>`.
  - Every lab repo's checked-in `.claude/settings.json` holds hooks only, with no Bash allow rules. The broad rules are all in `settings.local.json`.
  - So `--setting-sources user,project` would drop them and keep the Foundry hooks.

## P2
**P2-1. A Land the owner stopped is offered, ticked, and the prompt asks the session to land it.**
- Where: `lab_hub/progress.py:458-465`, `ui/lander.py:99-100`.
- A stopped repo is `LandResult(..., "not_landed", "it was stopped")`. That renders as Needs you and qualifies.
- The test `tests/test_handoff.py:43` assumes stopped repos show "Not reached"; they don't.

**P2-2. The Check builds button can stay disabled after Land ends.**
- The busy state is set once, when the window is built (`ui/apps_tab.py:797`), and `_update_land_controls` refreshes only `land_window`.
- A Land started on another page does not disable an open Land window here. The click-time re-check still catches it.

**P2-3. The "Opened…" and "Copied the prompt…" lines are invisible at Review.** The output pane is hidden until `begin_update` (`ui/progress_window.py:859, 975`). Spec §9 wants a visible line.

**P2-4. The prompt for the spec's main example (Provisio `forward`) contradicts limit 4.**
- The release clone is outside the checkout, so limit 4 ("Never another repo's") and the CLI's cwd restriction both forbid running the row's own command.
- Needs an owner decision: amend limit 4 to allow the folder named by the row's own command, opened with `--add-dir`.

**P2-5. The prompt omits owner decision 5.** Archived branches are information only, with no Restore without the owner's yes.

**P2-6. The 24 h clean-up can delete a still-open session's `settings.json`.**
- `_prune` keys on the folder's mtime.
- Should skip folders that still hold a `*.command` file, with a longer hard cap.

**P2-7. Test gaps.**
- launch failure mid-way;
- "no folder" for every row;
- Copy prompt through `confirm_handoff`;
- `qualifies` against real `BuildModel` snapshots for no_command, held and unknown rows;
- a Land stop-row prompt snapshot (spec §2.5).

## P3
- **P3-1.** The tooltip counts distinct paths, including `None`, not repos.
- **P3-2.** `find_claude()` runs `claude --version` before the wait cursor is set.
- **P3-3.** The dialog differs from §9: repo name not bold, folder not elided in the middle, and `&` in a repo name becomes a keyboard shortcut.
- **P3-4.**
  - Grouping by `--show-toplevel` sends an app folder that is not its own repo to the lab-root repo, and `context` then lists nested repos' processes.
  - A worktree path resolves to the worktree, not the main checkout.
- **P3-5.** `handoff_paths` is keyed by `item.name`, while rows are keyed by `plain(item.name)`.
- **P3-6.** The archived count is lost for a Needs-you Land row that also archived branches.
- **P3-7.** No Refresh after the confirmation (spec §3).

## Not verified (belongs to Verify and Secure on the real Mac)
- The CLI accepts `--permission-mode manual`, `-n`, and the `*`-patterned Bash rules.
- `ask` in `--settings` overrides a project allow rule.
- How the CLI behaves when its `--settings` file is deleted.

## Checked and sound
- Shell quoting of `command_line`: real zsh run with a hostile repo name.
- `_new_folder` and `_write` (O_EXCL, O_NOFOLLOW); refusal of a linked base folder.
- `rmtree` resists symlink attacks on Python 3.11.15.
- Alignment of `zip(report, view.items)`.
- Routing through `self.sender()`; dialog lifetime.
- lsof failure reaches the prompt.
- `claude` shows by that name in `lsof -F c`.

## Status
All findings fixed 2026-11-18 on `claude/resolve-button-5dc32f`. The owner approved the limit changes: "Fix all as proposed".
- **P1-1.**
  - `--setting-sources user,project`;
  - deny rules for `*legal_gate*sign*`, `*record_approval*` and `*signoff.jsonl*`;
  - spec §4.2 reworded: indirect commands are held by `manual` mode only.
- **P2-1.**
  - `LandResult.stopped` is set by the Lander for repos skipped or cut short by Stop;
  - `LandWindow.handoff_rows` leaves them out.
- **P2-2.**
  - `refresh_handoff_buttons` covers the open Check builds window as well as the Land window;
  - `MainWindow.land_state_changed` refreshes every page.
- **P2-3.** `show_handoff_note` writes a footer line, visible at any step, and the output line.
- **P2-4.**
  - Limit 4 amended;
  - a row command's `cd` folder outside the repo is passed with `--add-dir` and named in the prompt.
- **P2-5.** `ARCHIVED_NOTE` is added to the prompt when a row is archived.
- **P2-6.** `_prune` keeps folders with a live `.command` file for up to 30 days.
- **P2-7.** Tests added:
  - launch failure;
  - no folder;
  - Copy prompt through the page;
  - real `BuildModel` rows;
  - Land stop-row prompt;
  - stopped repos;
  - button refresh;
  - `--add-dir`;
  - worktree grouping;
  - nested repos;
  - live clean-up.
- **P3-1 to P3-7.**
  - P3-1: tooltip counts rows;
  - P3-2: `find_claude` runs under the wait cursor;
  - P3-3: bold name, elided folder, no mnemonic;
  - P3-4: grouping by main checkout; nested repos left out of the context;
  - P3-5: `plain` keys;
  - P3-6: archived count appended to a Needs-you row;
  - P3-7: Refresh after a session opens.

The real-Mac checks listed under "Not verified" remain for Verify and Secure.
