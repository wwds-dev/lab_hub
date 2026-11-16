# Spec: Update now also covers apps whose installer needs a terminal (Provisio)

Status: **Built 2026-11-16, not committed; not yet run on the real Mac.** Define approved by the owner 2026-11-16 ("Approve"), all three recommendations in §5. Phase: Define (`product-manager`). Drafted 2026-11-16 in `lab_hub`.
Nothing built. In-flight check (`session_start.py --inflight`, 2026-11-16): `lab-wide-build-marker`, `land-from-tiles`, `repo-tidy` (all document done, not released) and `tile-resolve` (superseded). None of them changes the Build check dialog or `build_status`; this spec touches `ui/apps_tab.py` `show_build_report` and `lab_hub/launcher/{control,state}.py` only.

## 1. Problem and evidence
The owner asked (2026-11-16) why the Build check shows no **Update now** for Provisio. Cause, from the code:
- Provisio's `scripts/install_app.sh:65` refuses to run when stdin is not a terminal, because it asks the owner to type `install`.
- Since 2026-11-14 `needs_terminal` (`lab_hub/launcher/state.py:1019`) marks such an app `by_hand`, and `BuildStatus.runs_in_app` is false for it (`state.py:1142`), so `show_build_report` (`ui/apps_tab.py:~915`) lists it under "Run yourself, in a terminal" and offers no Update now. With Provisio the only app behind, the button disappears.
- The owner must today press **Copy and open Terminal**, paste and run it.

## 2. User and success measure
User: the owner, on the Apps page.
1. When any app is behind, the Build check offers **Update now**, including when the only app behind needs a terminal.
2. Update now first runs the apps it can run itself (unchanged `RebuildDialog`), then opens one Terminal window per by-hand app with that app's install command already started. A test on a stub launcher asserts: one window per by-hand app, none for in-app apps, none when nothing is behind.
3. The owner still confirms in Terminal: Provisio's `install` prompt is untouched. The dialog text says so before the click ("Provisio's installer will open in Terminal and ask you to type install").
4. Nothing is typed into Terminal by Lab Hub and no Apple Events permission is needed (see §5.1).
5. If an in-app rebuild fails or is cancelled, the Terminal windows are not opened (a failed run stops, as today).
6. After the Terminal installer finishes, **Refresh** shows the tile current (screenshot: tile before and after on the real lab). Lab Hub does not wait for or watch the Terminal window.

## 3. Scope
- `lab_hub/launcher/control.py`: a function that writes a one-line `.command` file for a given command and opens it with `open -a Terminal <file>`.
- `ui/apps_tab.py` `show_build_report`: Update now shown when `commands or by_hand`; `run_updates` hands the by-hand commands over after the in-app run.
- Dialog wording for the Terminal handoff.
- Tests in `tests/test_launcher.py` and `tests/test_apps_tab.py` (stub the `open` call, never Terminal); README, CHANGELOG, TODO.

## 4. Non-goals
- No change to Provisio's installer, its `install` confirmation, or its refusal rules.
- No automation of Terminal (no typing, no AppleScript, no `-t 0` workaround such as a pseudo-terminal that fakes the answer).
- No waiting on, monitoring or re-checking after the Terminal window; Refresh does that.
- No change to Copy commands, Copy and open Terminal, or the no-command case.

## 5. Decisions for the owner
1. **How the window runs the command.** `control.py:349` says the current design opens Terminal at a folder and pastes nothing, on purpose: driving Terminal needs an Apple Events grant, and "a window that runs something the moment it opens is the wrong shape for a command that replaces an installed app". Recommend a **`.command` file**: `open -a Terminal` on it runs it in a real terminal, with no Apple Events grant (I was wrong in chat to expect a permission prompt; that applies to AppleScript, not this). The window shows the command and Provisio's installer prints what it will install and waits for you to type `install`, so the "read it first" safeguard is kept by the installer, not by pasting. Alternative: keep paste-only and add nothing (today's behaviour).
2. **What the file may contain.** Recommend exactly `cd <project> && ./scripts/install_app.sh` (the same string the report already shows), nothing else, written with mode `0700` to a Lab Hub folder under Application Support, one file per run, deleted on the next run. The command comes from the app registry and a script path Lab Hub already resolved, never from a page or an app's output.
3. **One window or several.** Recommend one window per by-hand app, so each installer's prompt is its own. Today only Provisio is by-hand.

## 6. Risks
- A `.command` file is a written, executable script: path and quoting must come from `shlex.quote` (as `install_command` does), and the file is never built from text read out of a checkout other than the already-resolved script path. Needs the Secure phase (file write, executable content).
- macOS may quarantine or warn about a `.command` file created by an app; a file Lab Hub writes itself is not quarantined, but this is **not verified** until run on the real Mac.
- A Terminal window left open after a failed install gives no signal back to Lab Hub; the tile simply stays "behind" until the next Refresh (success measure 6).

## 7. Phases to run
Define (this file, **GATE**), Architect (module boundary only, none expected), Plan, Build, Review (independent), Secure (required: executable file write), Verify, Document. Comply skipped: tier `public`, no new claims. Radar check skipped: no new tool or dependency.
