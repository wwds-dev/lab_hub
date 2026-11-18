# Lab Hub: code-level readiness audit (2026-11-18)

Promises in the README, `docs/foundry/app-context.md`, `docs/specs/` and the UI, checked against
the code. Foundry phase: Verify (7), as an audit; nothing in the code was changed. Read-only:
no Land, checkout, self-update, build or launch was run.

**Scope note.** Audited at committed `HEAD` (`7aacfd2`). Another session had uncommitted edits in
`lab_hub/progress.py`, `ui/apps_tab.py`, `ui/land_confirm.py` and `ui/progress_window.py`; those
were read with `git show HEAD:<path>`. Line numbers below are `HEAD` lines.

## Verdict

Not ready to call safe. **Data-loss risks first:**

1. **Blocker:** Land can still replace a real, ignored folder (`.venv`, `data/`) with a symlink a
   branch committed: the 17 Nov SONAR loss path is open (B1).
2. **High:** Land commits and pushes another session's half-finished edits when that session's
   current folder is outside the worktree (H1).
3. **Medium:** worktrees under the lab root's `worktrees/` lack the 24-hour recent-use guard, so a
   live session's clean, landed worktree can be removed (M1).

Most of the rest holds: no force push, ff-only pull, push only after a fresh fetch and a
gitleaks scan, no `git stash`, no `--force` worktree removal of a real tree, branch deletes keep a
backup ref, the Claude resolve runs file tools only in a temporary worktree, the launcher env
scrub meets the lab rule, no `QThread.terminate()`, and the tray is behind `appkit_guard`.

## Findings

### Blocker

**B1. A committed folder symlink still replaces a real folder on Land.**
- Promise: README (Apps → Land) and `docs/specs/land-update-gaps.md` §2.1 say no directory
  symlink is ever committed by Land; `land-resolve-all` says Land leaves nothing open and loses
  nothing. Both specs admit (§4 non-goal, §10.1) that a link already committed on a branch merges.
- Code: `repo_tidy.apply` runs `git merge --no-ff` in the main checkout
  (`lab_hub/repo_tidy.py:919-924`); `merge_target_blocker` (`repo_tidy.py:303-323`) checks branch,
  paused op, conflicts, tracked cleanliness and behind-origin only. Same gap in the Claude path's
  final `merge --ff-only` (`lab_hub/claude_resolve.py:1289`; its `_link_env` check at `:749-753`
  covers only `.venv`/`venv`/`node_modules`) and in prep's `git switch <default>`
  (`lab_hub/land_resolve.py:705`). Git overwrites ignored files by default, so the ignored real
  folder is lost; Land then pushes. The only guard, `never_commit_link`
  (`land_resolve.py:309-329`, tested in `tests/test_land_update_gaps.py:81`), covers untracked
  links Land itself would commit.
- Fix: before any merge, ff-merge or switch in the main checkout, list mode-120000 paths in
  `git diff --raw <default>..<branch>` and stop when the checkout has a real directory there or
  `ignored_as_folder` says yes. Test: branch commits `.venv -> x`, checkout holds an ignored
  `.venv/` with a file. Already tracked as the TODO "Land: stop a branch that already contains a
  folder link"; this audit raises it to a release blocker.

### High

**H1. Land commits and pushes another live session's edits.**
- Promise: README (Land, ~line 352) and `land-resolve-all` §4.5: Land commits in agent worktrees,
  "not one with a process inside".
- Code: "process inside" = an `lsof -d cwd` process whose current folder is in that tree
  (`land_resolve.in_own_tree`, `land_resolve.py:487-506`; `_worktree_stop_full` `:513-530`). A
  session whose folder is `~/Documents/lab` or a lab-root session worktree and that edits
  `active/<repo>` is invisible. Prep then commits with `add --update` / scanned `add --`
  (`land_resolve.py:645-650`, `repo_tidy.py:927-932`) and Land pushes (`repo_tidy.py:957`), with
  no tests on plain merges.
- Evidence in this repo: `cc56bb6` and `9e669a1` ("Lab Hub: commit open work, …") are Land's own
  commit message (`repo_tidy.py:931`), not git_autosync's, which refutes the lead that autosync is
  sweeping this repo. `7aacfd2` ("lab_hub: checkpoint 2026-11-18") swept another session's
  in-flight files (`durations.py`, `progress.py`, tests, spec, ADR); its source is unconfirmed
  (no such message in `git_autosync`).
- Fix: also treat a tree as busy when files changed in the last N minutes or a `claude` process's
  folder is an ancestor of the tree; at minimum list the files to be committed in the confirm
  dialog.

**H2. Real-lab images and private paths in the public repo.**
- `gh repo view` reports PUBLIC. `docs/audit/progress-windows-real-builds.png` (`1272be9`) shows
  `/Users/as/Releases/provisio/...` and every app's version; `progress-windows-real-land.png` names
  private repos (autopilot, syndustryx, shopfront/website, backstage). This is in addition to the
  `land-confirm-dialog-screenshot*.png` history already in TODO. `/Users/as` also appears in
  `lab_hub/sites.py:48`, README, TODO and five audit/spec docs. `_to_delete/lab_hub_index.lock.stale.*`
  is a tracked junk file.
- Fix (owner): make the repo private, or remove the images and paths (and decide on a history
  rewrite); delete `_to_delete/`.

**H3. The WWDS Websites tile always reports Unreachable.**
- Promise: Websites tab states Online / Error / Unreachable from a live check.
- Code: `SiteChecker.check` sends `QNetworkAccessManager.head()` to every site, including
  `file:///Users/as/Documents/lab/websites/webwealth/index.html` (`lab_hub/sites.py:48`,
  `ui/links_tab.py:173-182`); a file reply has no HTTP status, so `classify` returns Unreachable
  (`ui/links_tab.py:189-196`, `lab_hub/sites.py:96-101`). No test covers a `file://` check
  (`tests/test_sites.py:65-67` checks only the URL shape). Confirmed by reading; not run.
- Fix: for `file://`, skip the request and show Local file / File missing from `is_file()`; build
  the path from the lab root. Already a TODO; this confirms it.

### Medium

**M1. 24-hour recent-use guard covers only `.claude/worktrees/`.** README (~352) promises an agent
worktree used in the last 24 h is never removed. `recent_agent_worktree` checks only
`<repo>/.claude/worktrees/` (`repo_tidy.py:40, 437-445`). A session worktree under the lab root's
`worktrees/` is protected only by the cwd check, so a clean, landed one can be removed
(`repo_tidy.py:936`) and its branch archived and HEAD detached (`land_resolve.py:935-946`).
Mitigated: removal refuses dirty trees and non-regenerable ignored files (`repo_tidy.py:448-470`),
never uses `--force`. Fix: apply the rule to every linked worktree.

**M2. Backstage placement contradicts the lab rule; `backstage_tab` is dead; the test lead is
stale.** Lab `AGENTS.md` says Backstage launches from the Tools tab only; `lab_hub/apps.toml:76-81`
puts it in `[[suites]]` (Apps tile, menu bar, Check builds) since `31dbb9d`. `MainWindow.backstage_tab`
(`ui/main_window.py:105-111`, stacked at `:176`, in `_app_pages` at `:392`) shows the empty
`TOOLS_ONLY_APPS` and nothing navigates to it. **Lead refuted:** the four test files no longer pin
Backstage as Tools-only; `tests/test_tab_groups.py:41-47` now asserts the suite placement, so
README:869-872 ("expected to fail") is stale. Fix: owner decides rule vs code; then remove
`backstage_tab`, the hint in `ui/tools_tab.py:92`, and correct README or the lab `AGENTS.md`.

**M3. "Up to date" means level with the local checkout, not origin.** The Lab Hub row compares the
bundle stamp with the checkout HEAD (`lab_hub/self_update.py:154-188`); self-update runs no fetch
(by spec §4) and refuses detached/non-main/dirty (`:112-132`, `:223`), but a local `main` behind
`origin/main` builds and reports current. Fix: say "level with the local checkout" in the row, or
warn when `@{u}` is ahead (no fetch).

**M4. `build_app.sh --install` is not atomic.** The Update-now helper swaps safely
(`self_update.py:253-405`: ditto, `mv` onto free paths, self-test, rollback), but
`build_app.sh:79-83` does `rm -rf "/Applications/Lab Hub.app"` then `cp -R`, with no rollback and
no running-app check, and TODO tells the owner to use it once by hand. Fix: refuse while Lab Hub
runs, or call the helper.

**M5. No drift test for `appkit_guard.py`.** Lab rule: a drift test in each repo for copied code.
`tests/test_appkit_guard.py` tests behaviour only; the copies matched by AST today. The converter
drift test exists (`tests/test_converter_drift.py`) but skips silently when `imprint` is absent.
`app_launcher.c` is not in this repo (not applicable). Fix: add a converter-style drift test.

**M6. Quit during a long video conversion can abort the app (unconfirmed, not run).**
`MainWindow.shutdown` → `wait_for_stop` → `JobWorker.wait(15000)` ignoring the result
(`ui/main_window.py:477-484`, `ui/widgets.py:154-157`); ffmpeg runs in an uninterruptible
`subprocess.run` (`lab_hub/tools/video.py:132`). Fix: register the process so `stop()` can end it,
as `lab_hub/tools/calibre.py:157-175` does; do not raise the wait.

**M7. Git subprocesses on the UI thread.** `show_build_report` builds the report synchronously
(`ui/apps_tab.py:771-779`), including `worktree_tree` (`git add -A` + `write-tree` in a temp index,
60 s timeouts, `lab_hub/launcher/state.py:469-487`) per dirty checkout; the 2 s self-update hold
re-runs `checkout_blocker` on the GUI thread. No network on the UI thread. Fix: move the report to
the worker pattern.

**M8. `docs/foundry/app-context.md` is still the skeleton.** Product, Stack, Commands, Docs,
Hot spots, Security surface, Test bar and Invariants are placeholders; its Distribution evidence
("no `LICENSE`") is stale (a `LICENSE` exists). Already a TODO.

**M9. No CI, lint or secret scanning in the repo.** No `.github/workflows`, no ruff config, no
`.gitleaks.toml`, no hook; Foundry templates under `docs/foundry/tooling/` are not installed.
`lab_hub` is in the effective `autosync_repos.txt`, so the autosync gitleaks gate is the only scan.
Already a TODO (`/harden lab_hub`).

### Low

- **L1.** Merge and switch in the main checkout run under the 30 s `GIT_TIMEOUT`
  (`repo_tidy.py:42, 919`); a large checkout could be killed mid-merge. Use `NETWORK_TIMEOUT`.
- **L2.** `REGENERABLE` matches any path component (`repo_tidy.py:215-238`), so ignored
  `data/build/...` counts as regenerable and does not block worktree removal. Match top-level only.
- **L3.** Review-branches' manual removal drops the recent-agent blocker after a warning
  (`repo_tidy.py:1040-1044`). Deliberate and confirmed; keep, but say so in the dialog.
- **L4.** `child_env` (`lab_hub/launcher/control.py:43-70`) meets the Qt-scrub rule but not
  `QTWEBENGINE*`/`QTWEBENGINEPROCESS_PATH`, though Lab Hub bundles QtWebEngine.
- **L5.** The source fallback runs `<project>/.venv/bin/python main.py`
  (`control.py:175-179, 261-286`) when no bundle exists; within the letter of the rule (not a
  live launcher), but those children show as "Python".
- **L6.** `build_app.sh:14` `BUNDLE_ID="com.netrunner3000.labhub"` names the retired identity;
  changing it resets TCC/LaunchServices, so the owner decides.
- **L7.** Stale spec statuses: `lab-wide-build-marker.md` ("awaiting the owner's gate"; decision 2
  never built), `release-root-behind.md` ("not yet merged"; code on main).
- **L8.** Duplicate open TODOs for the Backstage leftovers (TODO.md lines ~105 and ~493).

## Promise status

| Promise | Where | Status |
|---|---|---|
| Land never commits a folder symlink | README Land; `land-update-gaps` §2.1 | Delivered (untracked links) |
| Land loses nothing | `land-resolve-all` | Narrower (B1) |
| Not in a tree with a process inside | README ~352; `land-resolve-all` §4.5 | Narrower (H1) |
| Recent agent worktree never removed | README ~352 | Narrower (M1) |
| Secrets quarantined, never pushed | `land-resolve-all` §2.4 | Delivered |
| Push only default branch, no force, after fresh fetch | Land specs | Delivered |
| Resolve: temp worktree, file tools, $ cap, ff-only after tests | `claude_resolve`, app-context | Delivered; CLI flag validity unverifiable without a run |
| Ask Claude: manual mode, push asks, sign-off denied | `claude-handoff` | Delivered by reading; real-Mac check still open |
| Self-update: checked swap, self-test, rollback | `self-update` | Delivered (helper); `--install` path not (M4) |
| "Up to date" | Check builds row | Narrower (M3) |
| Websites: live status | Websites tab | Narrower: wrong for `file://` (H3) |
| Launcher scrubs Qt env | lab rule | Delivered (L4 gap) |
| Live launcher never execs `.venv/bin/python` | lab rule | Delivered; fallback noted (L5) |
| `appkit_guard` on tray | lab rule | Delivered |
| No `QThread.terminate()`; shutdown names every QThread | lab rule | Delivered; M6 unconfirmed |
| Copies guarded by drift tests | lab rule | Narrower (M5) |
| Backstage Tools-only | lab `AGENTS.md` | Contradicted by code (M2) |
| app-context filled | Foundry | Stub (M8) |

## Test suite

Run once, offscreen, with the repo's `.venv` (`pytest -q -rfE`), while other lab test runs were going:

- **Working tree** (committed code plus the other session's uncommitted edits): 1,243 passed, 0 failed.
- **Committed `HEAD`** (`git archive` copy outside the repo, no `.git`): all passed except
  `tests/test_launcher.py::test_the_commit_count_is_read_from_a_real_repository` and
  `::test_this_project_reports_its_own_version`. Both read the checkout's own git history, which the
  export does not have; they pass in the real checkout, so they are an artifact of the method, not
  a defect.
- The lead "four test files still pin Backstage as Tools-only and fail" is refuted: they pass and now
  assert the suite placement (see M2).
- No failure came from the other session's uncommitted files. A DeprecationWarning from
  `tests/test_convert_drop.py:75` (deprecated `QDragEnterEvent` constructor) is the only noise.
