# Spec: a readable Land confirmation

Status: **Define approved by the owner 2026-11-17 ("Approve as recommended"): all four §5 decisions as recommended.** Design is the mockup below. Architect: §8 (no GATE). Build in progress.
In-flight check (`session_start.py --inflight`, 2026-11-17): no spec owns the confirmation shown before Land starts. `land-from-tiles` (document done) made it one confirmation and owns Land's engine; `land-resolve-all` (document done) added stops and the triage notice; `progress-windows` (document done) owns the window shown *after* confirmation; `land-fast` (document done) changed stop wording. This spec changes only how the confirmation looks; it changes nothing Land does.
Mockup: `docs/specs/land-confirm-dialog-mockup.html` (filled with the data from the owner's screenshot).

## 1. Problem and evidence
Owner, 2026-11-17, with a screenshot of Land all: "this window needs to be shown visually better. this looks like a mess now."
- `ui/apps_tab.py:1062` `confirm_land` builds one `QMessageBox` with a "?" icon. Its text is every repo's `LandPlan.sentence` (`lab_hub/land.py:131`) run together: one long comma-joined sentence per repo, with the hard stops embedded at the end ("stop at 2 things only you can clear: lab_hub: /Users/as/… — a process is running in it (node (pid 2971), node (pid 3094), gk (pid 3114) and 60 more): close that terminal or session, then Land again; …").
- Its informative text is every repo's `LandPlan.claude_notice` (`land.py:185`), one paragraph each, so the screenshot shows two cost paragraphs ("$12 in total", "$3 in total") and a triage paragraph ("$2.00 … at most"), and no single total.
- What Land will do, what it cannot do, and what it costs are not separable at a glance. The stop's place is a full path and its action is buried after a process list with pids.

## 2. User and success measure
The owner, after pressing Land on a tile or Land all, deciding whether to go. Success: at a glance they can see per repo what Land will do and what only they can clear, and the total Claude Code cost, then press Land or Cancel.

1. **One card per repo** with something to do, in plan order. Card header: repo name; a count of steps ("3 steps"); when it has stops, an amber "stops at N"; when Claude Code may be used, "Claude Code · up to $X" for that repo.
2. **Will do:** the plan as short items, one per line, sentence case, in the order of today's sentence (rescue, untracked files, quarantine, ignored links, switch, commit, merge, pull, push, delete branches, remove worktrees, the other branches and Claude Code's decision). Each item says exactly what today's sentence part says. A Claude merge item names the test command Lab Hub runs ("tests: `python3 -m unittest discover -s tests`", or "its test command" when unknown).
3. **Only you can clear:** a separate amber section under Will do, one line per stop: the place (short: "Main checkout", "Worktree <folder name>", or the branch/path for other stops), the problem in a few words, and the one action on its own line. Process lists are shortened: "63 processes running in it, including node and gk" (count plus distinct names, at most 3 names, no pids); three or fewer processes are named in full ("disclaimer, claude and zsh running in it"). Full paths and every pid go to Details and the place's tooltip. The section is labelled in words and an icon, never colour alone.
4. **One Claude Code panel** below the cards, shown when any repo may use Claude Code, always visible without scrolling. It keeps every fact today's notices disclose (spec `land-from-tiles` Secure P2, `land-resolve-all` §Preview), combined across repos:
   - the model (`claude_resolve.MODEL`);
   - **one total**: "at most $N in total" = sum of today's per-repo merge totals plus triage totals;
   - merge line: how many branches may be sent (with "N known to conflict now" when some are only possible), the cap each ($3) and its subtotal;
   - triage line: how many branches may be sent read-only (log and diff), the cap each ($0.50) and its subtotal;
   - code from these repos goes to Anthropic, as in any Claude Code session;
   - Lab Hub runs each repo's tests itself; a merge that passes them lands and is pushed without review;
   - a branch that fails or is archived is kept as a local tag `archive/<branch>/<date>`, never pushed, restorable from Review branches.
   Per-repo amounts stay on the card headers (item 1). A unit test asserts each fact above appears for a multi-repo plan.
5. **Nothing to do:** repos in the batch with nothing to land are named in one muted line ("Nothing to land in Imprint, SONAR."), not as cards.
6. **Header:** "Land 3 repos" (or "Land <name>" for one), and one sentence: "Land does everything it can, then stops at N things only you can clear. You can clear them now and press Land after, or press Land and clear them later." With no stops: "Land does all of it; nothing needs you."
7. **Footer:** "Each step is checked again just before it runs. Nothing is forced. Cancel leaves everything as it is." Buttons: Show details (left), Cancel, and a primary "Land 3 repos" / "Land" (decision 1).
8. **Details:** Show details expands an in-window, read-only, plain-text area holding today's full texts unchanged: every `sentence`, every `claude_notice` and every `detail`, plus every stop with its full path and full process list with pids. Nothing that today's dialog shows is lost.
9. **Fits the screen:** the window is about 640 px wide; the cards scroll inside it when they do not fit (at most ~70 % of the screen height); the header, Claude Code panel and buttons never scroll away.
10. **Safe text:** every name, branch, path, process name and reason is shown as plain text (as today, `land-from-tiles` Secure).
11. Tests in the `tests/test_land_ui.py` / `tests/test_apps_tab.py` patterns; full suite green with `.venv/bin/python -m pytest`; screenshot of the new dialog on the real lab as evidence.

## 3. Scope
- New `ui/land_confirm.py`: `LandConfirmDialog(plans, parent)`; `confirm_land` in `ui/apps_tab.py` builds it and returns whether Land was pressed (its signature and the tests that replace it stay as they are).
- `lab_hub/land.py`: plain-data views beside today's text, Qt-free and unit-tested: the plan as a list of item strings (today's `sentence` becomes their join, unchanged), the per-repo Claude Code cost (merge count, known-conflict count, triage count, caps, test commands), and one combined-notice function across plans. `sentence`, `claude_notice` and `detail` keep their current text (Details, the Land window and existing tests use them).
- `lab_hub/land_resolve.py`: a `Stop` keeps its `label` text but can also give its place, problem and action separately; `who_is_in` keeps the full process list (Details shows all of it) while the short form counts and names distinct commands.
- README (Land section), CHANGELOG, version bump per the app's versioning.

## 4. Non-goals
- No change to what Land does, its order, guards, caps or the stops it finds; no new "land without Claude Code" choice (decided in `land-from-tiles` decision 2).
- No "check again" button that re-plans after you close terminals (possible follow-up; today you Cancel and press Land again).
- No change to the Land progress window (`progress-windows`) or to stops found while running.
- Why the main lab_hub checkout always holds 60+ processes (Claude Code sessions run in it) and so always stops Land there is a separate question, not this spec.

## 5. Decisions for the owner
1. **Land button.** Recommend: "Land" drawn as the primary (blue) button, but Return does not press it; Escape and Cancel close. Today Cancel is the default on purpose (Land merges and pushes). Alternative: Land is the Return default.
2. **Process names.** Recommend: count plus up to 3 distinct names, pids only in Details. Alternative: keep today's first three with pids.
3. **Repos with nothing to do.** Recommend: one muted line naming them. Alternative: leave them out, as today.
4. **Claude Code panel.** Recommend: one combined panel with one total, per-repo amounts on the card headers. Alternative: the combined panel only, no per-repo amounts.

## 6. Risks
- Rewording the Claude Code disclosure could drop a fact. Mitigation: item 4 lists them; a test checks each; Details keeps today's exact notices.
- `QLabel` word-wrap inside a scroll area mis-sizes on macOS Qt at times; the Build checks long items at the real width in the screenshot.
- Splitting a stop into place/problem/action by parsing its text would be fragile; the Architect section decides the structured form (stops are built in few places: `land_resolve.prep`, `make_plan`).

## 7. Phases to run
Define (this file, **GATE**: user-visible), Design (the mockup, recorded here once approved), Architect (short section in this file; no ADR or GATE expected: no state, concurrency or boundary change, only plain-data views in `land.py`/`land_resolve.py` and a new dialog), Plan, Build, Review, Verify, Secure (light: untrusted text from git, paths and `lsof` shown in the UI must stay plain text), Document. Comply skipped: tier `public`, no new data flow or claim; the existing Claude Code disclosure is kept in full (item 4). Launch skipped: optional for `public`. Radar check at Define: not run from this session (a slash command; the owner or orchestrator runs `/radar-check land-confirm-dialog`).

## 8. Architecture
Phase: Architect (`architect` role, by the orchestrator), 2026-11-17. No GATE: no new state, thread or module boundary; no ADR.
- **Engine stays the source of the words.** `lab_hub/land.py` gets Qt-free views: `LandPlan.items` (today's sentence parts without the stop clause; `sentence` is rebuilt from them, text unchanged), `LandPlan.cost` (a frozen `ClaudeCost`: merge count, known-conflict count, triage count, test commands, totals with today's caps), `LandPlan.stop_views` (a frozen `StopView` per stop: place, problem, action, full text) and `claude_panel(plans)` (the combined disclosure as a frozen `ClaudePanel`, or `None`).
- **Stops.** `land_resolve.Stop` keeps `reason` and `label` byte for byte (the run, the tiles and the Land window read them) and gains `processes: tuple[str, ...]` (every `cmd (pid N)`), filled by `prep` from one `lsof` run (`_worktree_stop_full`; `_worktree_stop` keeps its string). Problem and action are split only at known action endings (`STOP_ACTIONS`); an unknown reason is shown whole with no action line, never mis-split.
- **Dialog.** `ui/land_confirm.py` `LandConfirmDialog(QDialog)` renders the views with plain-text labels and the app theme (`QFrame#card`, `runPill`, `QPushButton#primary`). Land is `#primary` but not the default button (`autoDefault` off on every button), so Return presses nothing; Escape rejects. `ui/apps_tab.py` `confirm_land` only builds it and returns `exec() == Accepted`.

## 9. Build
Phase: Build (`engineer` role, by the orchestrator), 2026-11-17. `ui/land_confirm.py` (new), `lab_hub/land.py` (`items`, `cost`, `stop_views`, `stop_view`, `claude_panel`; `sentence` and `claude_notice` text unchanged), `lab_hub/land_resolve.py` (`Stop.processes`, `STOP_ACTIONS`, `processes_in`; `who_is_in` and stop reasons unchanged), `ui/apps_tab.py` (`confirm_land` builds the dialog). Tests: `tests/test_land_confirm.py` (17, built from the owner's screenshot data), `tests/test_land_ui.py` (the confirmation test rewritten for the dialog). Mutation check on `land.py`: 5 planted mutations (process threshold, action split, "up to" wording, total, place) all caught; the action-split one needed an extra case, added.
Evidence: `docs/specs/land-confirm-dialog-screenshot.png` (Graphite) and `-light.png` (Paper), Land all planned read-only on the real lab, 2026-11-17 (state had moved on since the owner's screenshot: 3 repos, 3 stops, at most $10.50). Process ids and full paths are under Show details, not in these pictures.
