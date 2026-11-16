# Security review: land-from-tiles (Secure phase)

Reviewer: security-engineer (read-only). Playbook `docs/playbooks/security-engineer.md`: last-reviewed 2026-11-11, status current (not stale).
Scope: `git diff`, `lab_hub/land.py`, `ui/lander.py`, `ui/apps_tab.py`, against `git show HEAD:ui/repo_tidy_dialogs.py` (`CleanupDialog`). `lab_hub/repo_tidy.py` and `claude_resolve.py` unchanged (git status).
Tests run: `tests/test_land.py tests/test_land_ui.py` pass (30). Dependency audit: not run (no manifest change in the diff).

## Verdict
No P0, no P1. Nothing new is reachable in terms of git actions: the same `repo_tidy.plan_repo` produces the actions and `repo_tidy.apply` re-checks every guard. Three P2 reductions of what the owner sees or is protected from, and three P3 notes.

## Threat model (short)
- Assets: the lab repos' history and their `origin` remotes (push, merge, deletes), source code sent to Anthropic, the owner's Claude spend.
- Trust boundaries: `git_autosync/hygiene.json` (written by autosync, read by `hygiene.load`, hygiene.py:118) to paths and names; repo content (branch names, `docs/foundry/app-context.md` test command, hooks) to git and test execution; git/pytest/Claude output to the UI.
- Entry points: the Land button (apps_tab.py:~1048), Land all (~1055), `Lander.plan/run` (lander.py:50-62).

## Answers to the five questions
1. Confirmation before any push or Claude run: yes. `Lander.run` is called only from `_land_planned` (apps_tab.py:1079-1088), which returns without running when any plan has actions and `confirm_land` is not "Land". Cancel is the default and escape button (1073-1074). Land all lists one sentence per repo with actions (1066-1067). Plans with no actions skip the dialog but `land.land` does nothing for them beyond a read-only `unlanded` (land.py:236-241). Mixed case (some repos with actions) confirms all of them at once; repos without actions run as no-ops. `plan.claude` is set only when `availability()` finds Claude, and only `claude_merge` actions use it.
2. Stale plan: `land.land` calls `repo_tidy.apply(action, log, busy, now, claude=..., stop=...)` (land.py:251) and does nothing else to git; `apply` calls `check` first (repo_tidy.py:828-ish), which re-checks branch tip sha, default branch, clean tree, no paused op, busy dirs, fresh fetch before a push, and the test command string. Nothing in land.py bypasses it. The window between plan and run is only the time the confirm dialog is open, shorter than the old Apply window. Verified by reading; the guards themselves are not re-tested here.
3. Crafted `hygiene.json`: `make_plan` requires absolute path plus `.git` (land.py:181), identical to the old `repo_tidy.plan` (repo_tidy.py:665). So a report can point Land at any git checkout on the machine, inside the lab or not; nothing stops it. Not new (old Resolve used the same rows), and the file is in the owner's own `git_autosync/` directory, so writing it already needs the owner's privileges. See P2-3.
4. Rich text: no `Qt.PlainText` is set anywhere in ui/ for the new labels (grep). See P2-1.
5. Claim registry: `_ACTIVE` guarded by `_LOCK`, claim/release in `try/finally` (land.py:233-269), keyed by resolved path. Sound. See P3-2 for what it does not cover.
6. Remote and branch: push is `git push origin refs/heads/X:refs/heads/X` (repo_tidy.py, apply), X is the default branch found at plan time, no `--force`, remote fixed to `origin`, and `sync_blocker` requires the upstream to be `origin/<default>`. Pull is `--ff-only origin`. Nothing pushes another remote or branch. Edge: `check` uses the current default but pushes `action.target` from plan time; if `origin/HEAD` changed between plan and run, a plan-time branch could be pushed. Pre-existing in repo_tidy, mismatch only possible when the checkout is on the new default and tracks origin/new, so the push target is not checked out: git would push the old branch ref if it still exists locally. Not verified by running.

## Findings

### P2-1 Git, pytest and Claude output is rendered as auto-detected rich text
- ui/apps_tab.py:162 (`self.outcome = QLabel()`, default `Qt.AutoText`), :341 (progress line), :350-351 (`result.line` and tooltip), :1067 (`box.setText` with report `name`), :882 and :1114 (summary).
- Evidence: `result.line` ends with `plain_reason(message)` of git stderr or test output (land.py:35-59, collapses to one line, so the first-line rich-text test always applies). `QtGui.Qt.mightBeRichText("Not landed: failed <b>x</b>")` returns True; same for `&lt;`. Tooltips also auto-detect. `git check-ref-format --branch '<b>x</b>'` accepts it, so a branch name, or a failing test line, can carry tags.
- Attack: a repo with a hostile branch name or test output makes the tile or dialog show spoofed text (e.g. a fake "Landed"), or `<img src=file:...>` loads a local image. QLabel does not run scripts and `openExternalLinks` is off, so impact is spoofing and odd rendering only.
- Fix: `setTextFormat(Qt.PlainText)` on `outcome`, `hygiene`; `box.setTextFormat(Qt.PlainText)` on the three QMessageBoxes; or `html.escape` the strings. Tooltips: wrap or use a plain-text widget.

### P2-2 The single confirmation shows less than the old Claude confirmation
- ui/apps_tab.py:1061-1077 and lab_hub/land.py:148-162 versus old `confirm_claude` (HEAD:ui/repo_tidy_dialogs.py:163-186).
- Old: separate dialog, total cost `${n*cap}`, and "Apply without them" to land the rest without Claude, plus per-action untick. New: the cap is stated per branch only, no total, no way to take the clean merges and push but not Claude (Cancel loses everything), and the test command that Lab Hub will run appears only in the collapsed Details (`Action.reason`, repo_tidy.py "tests (...): cmd"). A merge that passes tests is pushed without review.
- The spec (docs/specs/land-from-tiles.md:16, "No checkbox wall") accepted one confirmation, so this is a design reduction, not a bypass. The disclosure text is the same.
- Fix (cheap): add the total to `claude_notice`; put the test command and the repo path into the main text; consider a second button "Land without Claude" that filters out `claude_merge` actions (the filter exists in the old dialog).

### P2-3 A crafted report can aim Land at any git checkout, and name and path are not shown together
- lab_hub/land.py:181; hygiene.py:126 (`Path(raw["path"])`); ui/apps_tab.py:1048-1056 (name and path both taken from the row).
- Attack: a `hygiene.json` entry with name "sonar" and path of some other clone. The confirmation shows only the name (`LandPlan.sentence`), so the owner cannot see the path. Land then commits, merges and pushes that repo's `origin`, and runs the repo's `app-context.md` test command and Claude on it. Hooks and `core.fsmonitor` of a hostile checkout run via git.
- Precondition: write access to `~/.../git_autosync/hygiene.json` (same user), so this is defence in depth and equal to the old Resolve. Not new.
- Fix: in `make_plan`, require `path.resolve()` to be inside the lab root (`settings.resolved_lab_root()`), and show the path in Details.

### P3 notes
1. `Lander._drain` clears `_thread` before emitting `planned` (lander.py:114-119), so `busy` is False while the confirmation is open and Land all and the card buttons are re-enabled behind it (apps_tab.py `_update_land_controls`). Only the dialog's window modality prevents a second click; the claim in `land.land` still stops same-repo concurrency. Fix: hold a "confirming" flag.
2. The claim covers Land only, not ReviewDialog deletes, `git_autosync` runs, or a Terminal. The guards in `check` are the real protection there.
3. `_card_for` matches tiles by report `name` (apps_tab.py `_card_for`); duplicate names show an outcome on the wrong tile. Cosmetic.

## Not verified
Running Land against a fixture with a hostile branch name; the origin/HEAD change edge case in item 6; any live Claude run; pip-audit.
