# Spec: Lab Hub updates itself from Check builds

Status: **Define approved by the owner 2026-11-17 ("Approve as recommended"), all four §5 recommendations. Architect approved by the owner 2026-11-17 ("Approve architecture"). Built 2026-11-17; reviewed and secured, with all P1/P2 findings fixed (§10). Second Verify found no production defect and three missing tests (N29, N2, N10); these were added and each was confirmed to catch its planted mutant (§10). Not done: the owner's real-Mac check (`docs/audit/self-update-qa.md` §6), commit, merge and release.**
**Amendment 1 (§11–§13, 2026-11-20): build from a snapshot of `main`, not the shared checkout. Define approved by the owner 2026-11-20 ("Approve as recommended"); Architect approved 2026-11-20 ("Approve architecture"). Built, reviewed, verified and secured 2026-11-20; P2-1 and the P3s fixed (§13). Not done: the owner's real-Mac check (`docs/audit/self-update-qa.md` §6, A2 and D), merge and release.**
In-flight check (`session_start.py --inflight`, 2026-11-17): `lab-wide-build-marker`, `land-already-applied`, `land-from-tiles`, `land-resolve-all`, `progress-windows`, `release-root-behind`, `repo-tidy`, `update-now-terminal` (all document done, not released) and `tile-resolve` (superseded). None of them updates Lab Hub itself. This spec adds a row and a final step to the Check builds window that `progress-windows` built and that `update-now-terminal` and `release-root-behind` feed. It changes none of their rows, buttons or commands for the other apps. Worktrees: `bold-merkle-831506` (`land-cherry-shortcut`, Land's engine) and `zealous-benz-97c752` (progress windows, already merged in `e888bbf`). Neither touches self-update.

## 1. Problem and evidence
The owner asked on 2026-11-17 for Lab Hub to update itself from the Apps tab, the same way the other apps do.
- **Lab Hub has no build row.** Check builds reports only the apps in `lab_hub/apps.toml` (`state.build_report`, `lab_hub/launcher/state.py:1296`), and Lab Hub is not one of them. So Check builds never says that Lab Hub is behind.
  Evidence: on 2026-11-17 the installed v2.172 (commit `8ea789b`) lacked the Land progress window that main gained in `e888bbf`, and nothing in the app showed it.
- **Updating today takes four manual steps:**
  1. Run `./build_app.sh --install` in a terminal.
  2. `kill` the running process. ⌘Q and Dock Quit only hide it (`_QuitGuard`, `ui/main_window.py:600`). Only the menu bar item's Quit really quits (`MainWindow.quit`, `:376`).
  3. Relaunch.
  4. Click the menu bar icon, because the relaunch from a background shell came up without a window in front.
- **The install step swaps the bundle under a running app.** `build_app.sh --install` deletes `/Applications/Lab Hub.app` and copies the new one in (`build_app.sh`, end of file) while the old copy may still be running from that folder.
  - A frozen app loads some files lazily (Qt plugins, extension modules), so the old process can fail on its next load from a bundle that is gone.
  - The script keeps no copy of the old build to fall back to.
- **A restart while work runs would kill it.** Long jobs run inside the Lab Hub process:
  - Land and Land all: one `Lander` per Apps page, and four pages have one (`ui/apps_tab.py:602`).
  - The Convert, Images, Video and Narrator tools (`MainWindow._running_panels`, `:364`).
  - Restarting Lab Hub mid-Land would end a Claude Code merge or a test run partway through.

## 2. User and success measure
User: the owner, on the Apps page.
1. **Lab Hub has its own row.** Check builds shows a row for Lab Hub (this app):
   - The installed build, for example `v2.172+g8ea789b`.
   - A verdict worded like the other rows: up to date, or "N commits older than its source".
   - The verdict uses the same `Version` comparison as every frozen app: the stamp in the bundle against the working checkout. Covered by tests on a fixture bundle and a fixture repo.
2. **Update now covers Lab Hub, and does it last.** When Lab Hub is behind, Update now includes it.
   - The other apps rebuild first, unchanged.
   - Then `build_app.sh` builds Lab Hub, including its self-test, in the same window.
   - If any earlier rebuild failed or was cancelled, Lab Hub is not rebuilt (as `update-now-terminal` §2.5 does for Terminal).
3. **Lab Hub restarts on its own, in front.** Lab Hub quits only after its new build has passed the self-test. A detached helper then:
   - waits for the old process to exit;
   - moves the old bundle aside;
   - installs the new one;
   - runs `--selftest` on the installed copy;
   - starts it.
   The new Lab Hub opens with its window in front and shows the new version in the title (screenshot before and after, on the real Mac).
   No terminal, no `kill`, no menu bar click.
4. **Running work is never killed.** Update now does not start a Lab Hub rebuild while a Land is planning or running on any page, or a tool is running. Instead the window names what is running, for example: "Land is running on 3 repos. Lab Hub will update when it finishes."
   The same check runs again at the moment of restart, and Lab Hub never quits while one of these is running. §5.2 sets which of the two behaviours applies.
   Tests with a stub `Lander` and stub panels assert: no build, no quit, no helper started while busy.
5. **A failed update leaves the old Lab Hub working.**
   - If the build or its self-test fails, Lab Hub does not quit, the error is shown, and the installed app is untouched.
   - If the install or the installed copy's self-test fails, the helper puts the old bundle back and starts it. The next start says: "The update to vX did not install; you are on vY. See <log>."
   - Tests cover the helper on fixture bundles in a temporary folder: success, a failed self-test (rolled back), and an old process that never exits (nothing replaced).
6. **One previous build is kept.** The replaced bundle is kept as the single previous build, and the last update's log is kept as well. Both live under `~/Library/Application Support/Lab Hub/`. A later update replaces the kept copy.
7. **From source, there is nothing to update.** When Lab Hub runs from source (`python main.py`), its row says "runs the checkout directly" and offers no update, as other source apps do. The same applies when the running copy is not `/Applications/Lab Hub.app`.

## 3. Scope
- **`lab_hub/launcher/state.py`:** a `BuildStatus` row for Lab Hub itself, built from the running bundle (`sys.executable`'s `.app`) and the checkout. The checkout is `version.PROJECT_ROOT` for a source run, or the lab folder's `lab_hub` checkout for a frozen one; Architect decides which.
- **New `lab_hub/self_update.py` (Qt-free):**
  - the busy check's inputs;
  - the helper's fixed script text;
  - starting the helper fully detached (`start_new_session`, arguments passed as positional parameters, never pasted into the script);
  - reading the last update's outcome on start.
- **`ui/apps_tab.py`, `ui/progress_window.py`, `lab_hub/progress.py`:**
  - the Lab Hub row;
  - Update now orders Lab Hub last;
  - the busy refusal or wait;
  - the "Restarting Lab Hub…" end state.
- **`ui/main_window.py`:** a quit path for the update that skips the tool prompt only when nothing is running (it asked already), and a one-line notice on the first start after an update.
- **`build_app.sh`:** left as it is. The update runs it without `--install`, so the build and self-test are the script's own, and the install is the helper's. Architect may instead move the install into the script behind a flag.
- **Tests:**
  - `tests/test_self_update.py` (the helper on fixture bundles in `tmp_path`: a fake `.app` whose executable is a stub script, a fake PID);
  - additions to `tests/test_apps_tab.py`;
  - nothing is ever run against the real `/Applications`.
- **Docs:** README (Check builds, Update now, Running and building), CHANGELOG, TODO.

## 4. Non-goals
- No Lab Hub tile on the Apps page. The Launch, Stop and Open in Terminal buttons would all mean "this window". See §5.1.
- No download or network update. The build comes from the local checkout, as every other app's does.
- No Land, merge, push or `git pull` as part of the update. It builds what the checkout holds (see §5.3).
- No change to how other apps rebuild, to `build_app.sh`'s build or self-test, or to ⌘Q and Dock Quit hiding the window.
- No automatic update check or auto-restart. The owner presses Update now.

## 5. Decisions for the owner
1. **Where the control lives.**
   - **Recommended:** a "Lab Hub (this app)" row in Check builds, always last, so the existing Update now covers it like any other app. You see it where you already look.
   - Alternative A: an **Update Lab Hub** button next to Check builds and Land all, shown only when Lab Hub is behind.
   - Alternative B: a Lab Hub tile. Not recommended: a tile's Launch and Stop make no sense for the window you are in.
2. **When a Land or a tool is running.**
   - **Recommended:** check both before the build and at the restart.
     - Before the build, the Lab Hub row reads "Will update after Land finishes". Update now still rebuilds the other apps, then waits for Land and Lab Hub's build, with a Cancel.
     - At the restart, if something started meanwhile, it waits for that too.
   - Alternative: refuse outright with the reason and let you press Update now again later. That is simpler, but it means coming back.
3. **What it builds from.**
   - **Recommended:** only a checkout that is clean and on `main`. Otherwise the row says why and Update now skips Lab Hub, for example: "the checkout has uncommitted changes, maybe another session's work; Land them first".
   - The reason: several sessions share this checkout (AGENTS.md), and an update would install their half-done edits into the app that runs Land. The self-test catches a crash, not a wrong behaviour.
   - Alternative: build whatever the checkout holds, as the other apps' rows do. Their verdict "uncommitted" counts as a reason to rebuild.
4. **How the old bundle is replaced.**
   - **Recommended:** the build and self-test run inside Lab Hub without `--install`. A detached helper does the swap only after the old process has exited, keeps the previous build and rolls back on failure (§2.3, §2.5).
   - Alternative: run `build_app.sh --install` while Lab Hub runs, then quit. That is today's manual path, with the swap-under-a-running-app risk in §1 and no rollback.

## 6. Risks
- **The helper writes into `/Applications` and starts a process.** That makes it a file write and process spawn surface, so the Secure phase is required. The helper is a fixed script in the code. Its only inputs are four paths and a PID, which Lab Hub computes itself. It never takes text from a checkout's output or from the build report's commands.
- **The new window may not come to the front.** macOS may not bring a relaunched app to the front: that is how the owner's manual relaunch ended on 2026-11-17. `open` without `-g` normally activates, and the new copy calls `dock.activate()` on a normal start, but this is **not verified** for an app started by a process whose parent has exited.
  Fallback: the menu bar item posts "Lab Hub updated to vX. Click to open." Check on the real Mac in Verify.
- **The old copy must be gone before the new one starts.** `SingleInstance` (`ui/single_instance.py`) turns a second launch away and wakes the old copy instead. So the helper starts the new copy only after the old PID is gone. If the old copy has not exited after 60 s, the helper replaces nothing and logs why.
- **Restarting ends things Lab Hub started.** Apps that Lab Hub started in the background, such as the sync companions, must survive the restart (they are their own processes). This is to be confirmed in Architect against `launcher.start_in_background`.
- **The build takes minutes.** Lab Hub stays usable while the build runs: the window is modal for Update now as today (`progress-windows` §5.1). This is unchanged.

## 7. Phases to run
1. Define: this file, **GATE**.
2. Design: the row and the end state, in the existing Check builds window; no new window.
3. Architect: **GATE**. It covers process lifetime and a write to `/Applications`, and needs an ADR for the helper and the rollback.
4. Plan.
5. Build.
6. Review.
7. Verify: includes the real-Mac update and the front-window check.
8. Secure: required (file writes, process spawn, packaging).
9. Document.

Skipped phases:
- Comply: tier `public`, no new claims, no new data.
- Launch: optional for `public`, and nothing is announced.
- Release: the owner's call once Verify passes. The first self-update is itself the release smoke test.

## 8. Design (ux-designer, 2026-11-17)
This change adds no new window. It uses the existing Check builds window (`progress-windows`) like this:
- **The Lab Hub row** is always the last row. It is headed "Lab Hub (this app)" and uses the same verdict words as the other rows. When the update cannot run, it says why in one line:
  - "runs from source, so there is nothing to update";
  - "this copy is not the one in /Applications";
  - "the checkout has uncommitted changes, maybe another session's work: Land them first";
  - "the checkout is on <branch>, not main".
- **While Update now waits before Lab Hub's build,** the Lab Hub row reads "Waiting: <what is running>". The window's live line says the same. Cancel stays available.
- **After Lab Hub's build passes,** the end line reads "Built and tested v2.180. Lab Hub restarts to install it when you close this window." The Close button reads **Close and restart**.
- **On the first start after an update,** the status bar shows the outcome for 30 s and the menu bar item posts the same text:
  - "Updated to v2.180."
  - Or: "The update to v2.180 did not install; you are on v2.172. Log: <path>."

## 9. Architecture (architect, 2026-11-17)
ADR: `docs/adr/0003-self-update-helper.md`, which needs the owner's Architect gate.

### 9.1 Modules and boundaries
- **`lab_hub/self_update.py` is new and Qt-free.** It holds:
  - `SELF`, an `ExternalApp(key="lab_hub", name="Lab Hub", project="lab_hub", entry="main.py", …)`. It is never added to the registry, so no tile and no menu bar entry appear.
  - `running_bundle()`: the `.app` the current process runs from, or None when running from source.
  - `self_status(lab_root) -> BuildStatus`. This is `build_status(SELF, …)` narrowed by §5.3 and §2.7. Its command is `cd <checkout> && ./build_app.sh` with **no** `--install`.
  - `checkout_blocker(project) -> str | None`: the clean-and-on-`main` check.
  - `HELPER_SCRIPT` and `start_helper(...)`.
  - `read_outcome()`.
- **`lab_hub/launcher/state.py`:** `BuildStatus` gains `restarts: bool = False`, which is true only on Lab Hub's own row. The field has a default, so every existing caller is unchanged.
- **`lab_hub/progress.py`, `build_check_view`:** the unscoped report (the launchpad's) appends `self_status`, and the row's command goes last in `view.commands`. A scoped report never includes it. The view gains `restarts: bool`.
- **`ui/rebuild.py`, `Rebuild`:** two optional hooks, both defaulting to today's behaviour.
  - `hold(command) -> str | None` is asked before each command starts. A reason means "wait": the window says it, and the hook is asked again every 2 s. Cancel during a wait ends the run as cancelled, the same path as Cancel before a command starts.
  - `verify` for the restarting row returns "installs on restart" instead of reading `/Applications`, which still holds the old build.
- **`ui/apps_tab.py`, `AppsTab`:** a `busy_reasons: Callable[[], list[str]]` is injected by `MainWindow`. By default it reports only the tab's own `Lander`. `run_updates` passes `hold` for the restarting command. That `hold` returns the busy reasons; when there are none, it returns `checkout_blocker` again (the checkout may have changed while waiting). After a successful run with `restarts`, it emits `restart_requested`.
- **`ui/main_window.py`:**
  - `busy_reasons()` collects every page's `Lander.busy` (all four Apps pages) and `_running_panels()`.
  - `restart_for_update()` re-checks `busy_reasons()`. If anything is busy, it polls every 2 s with a status bar line. *Built 2026-11-17 without a cancel or a menu bar notice for this wait: it can only happen if a job started between the build and Close, which the modal window prevents. Quitting Lab Hub drops the pending restart.* Once nothing is busy, it calls `start_helper(...)`, sets `_quitting`, and calls `QApplication.quit()`. That is the menu bar Quit path, so `_QuitGuard` is not involved, and `aboutToQuit` still runs `Lander.shutdown` and `MainWindow.shutdown`.
  - On start, `read_outcome()` drives the notice in §8.

### 9.2 The helper: a process outliving its parent
- **How it starts:** `subprocess.Popen(["/bin/bash", "-c", HELPER_SCRIPT, "lab-hub-update", pid, src, target, backup, log, outcome], start_new_session=True, stdin=DEVNULL, close_fds=True, cwd="/", env=child_env())`, with stdout and stderr going to the log.
  - The script text is a constant in the code. The six values are positional parameters (`$1`..`$6`), never interpolated into the text.
  - No file is written to disk to run it.
  - `bash` 3.2 (macOS's) is enough.
- **The paths are computed and checked in Python before the start.** If any check fails, nothing starts and the error is shown:
  - `target` equals `running_bundle()` and is `/Applications/Lab Hub.app`.
  - `src` is `<checkout>/dist.noindex/Lab Hub.app` and has an executable.
  - `backup`, `log` and `outcome` are under `SUPPORT_DIR/update/`.
  - `pid` is `os.getpid()`.
- **Steps, with the outcome file written at every exit:**
  1. Poll `kill -0 $pid` every 0.25 s for up to 60 s. If the old process is still alive, write `not_replaced`, replace nothing, start nothing (the old copy is still running) and exit.
  2. `ditto "$src" "$target.updating"`. This copies onto the same volume as `/Applications`, so step 3's renames are atomic on APFS. On failure, remove the partial copy, write `not_replaced`, `open "$target"` and exit.
  3. `rm -rf "$backup"`; `mv "$target" "$backup"`; `mv "$target.updating" "$target"`. If the second `mv` fails, move the backup back.
  4. Run `"$target/Contents/MacOS/Lab Hub" --selftest`, killed after 120 s (a background job plus a wait loop, since macOS has no `timeout`). On failure, remove the new bundle, move the backup back, and write `rolled_back`.
  5. On success, write `ok`, `touch "$target"` (the Dock icon cache, as `build_app.sh` does) and remove `"$src"`.
  6. `open "$target"`. This is a foreground launch with no `--background` flag, so `run()` takes the normal-start branch: `show_in_dock`, `showMaximized`, `dock.activate()`.
- **The helper refuses by name.** It exits before step 1 when `basename "$target"` is not `Lab Hub.app`, or when `$target.updating` or `$backup` would be `/` or empty. Every `rm -rf` runs only on those derived paths.
- **The outcome file** has two plain-text lines: a token (`ok`, `rolled_back` or `not_replaced`) and a sentence. The new process reads it leniently: anything unreadable means "no notice". It then renames the file to `outcome.seen`, so the notice shows once.

### 9.3 State, threads, concurrency
- **No new thread.** The build is the existing `QProcess` in `Rebuild`. Waiting is a 2 s `QTimer` on the GUI thread. The helper is a separate process with its own session.
- **The race between the busy check and the quit is closed by modality and the event loop.** The Check builds window is modal for Update now, so no new Land can start from the UI. The busy check and `QApplication.quit()` run in the same GUI-thread call, with no event processed between them.
  - A Land that is already running keeps running. Its `Lander` timer still drains under the modal loop, and `busy` goes False only when it has finished.
  - The menu bar item's tool shortcuts can launch other apps, but they do not start in-process jobs.
- **Apps Lab Hub started survive the restart.** They are started with `start_new_session=True` (`lab_hub/launcher/control.py:286`), so the old Lab Hub exiting does not end them. The new Lab Hub finds them in the process table as today.
- **The single-instance guard and the helper agree on order.** The helper starts the new copy only after the old PID is gone, so `SingleInstance.acquire()` in the new copy wins the socket.

### 9.4 Rejected
- **`build_app.sh --install` and then quit:** this replaces the bundle under a running process, with no rollback (§1).
- **A Python helper:** a frozen app has no Python to spare, and `/usr/bin/python3` may be missing without the Command Line Tools.
- **A `.command` file in Terminal:** the owner wants no Terminal, and the restart has to work without a click.
- **Moving the old bundle to the Trash:** a rollback needs a known path, and Finder Trash moves need Apple Events or `NSFileManager` from the dying process.
- **Building while a Land runs and holding only the restart:** a Land can be merging in this very checkout, so building at that moment could package half a merge (§5.3's reason).

### 9.5 Tests (Build)
- **`tests/test_self_update.py` runs the real `HELPER_SCRIPT` with `bash`** against fixture bundles in `tmp_path`. Each fixture `.app` has a stub executable whose `--selftest` exits 0 or 1. The `/Applications` check is made injectable for tests only, through a module-level constant the tests patch, never through an argument. Cases:
  - success;
  - the self-test fails and the update is rolled back;
  - the old PID never exits (a `sleep` child), so nothing is replaced;
  - the `ditto` source is missing;
  - the basename is wrong, so it refuses;
  - the outcome file is read once.
- **`self_status`** is tested on fixture repos: clean on main, dirty, on a branch, running from source, and a frozen copy in another place.
- **`build_check_view`:** the Lab Hub row is last and appears only when unscoped.
- **`Rebuild` hooks:** `hold` waits and then proceeds, Cancel during a wait, and `verify` is skipped for the restarting row.
- **`MainWindow.busy_reasons` and `restart_for_update`** use stub Landers and panels, and `start_helper` and `QApplication.quit` are patched: no helper starts and no quit happens while busy, and both happen once idle.
- **Not testable in CI:** the real `/Applications` swap and the window coming to the front. Verify does those on the real Mac.

## 10. Review and fixes (2026-11-17)
Reports:
- `docs/audit/self-update-code-review.md` (P1-1, P2-1 to P2-3, P3 1–9);
- `docs/audit/self-update-security.md` (P2-1, P2-2, P3-1 to P3-6);
- `docs/audit/self-update-qa.md` (FAIL: missing tests and 10 surviving mutants).

**What changed:**
- **Every remove and rename in the helper is checked** (review P1-1, security P2-1).
  - A rename only goes onto a path that is free.
  - A previous build that cannot be cleared means nothing is replaced.
  - A failed restore is recorded as `broken`, naming where the previous build is, and nothing is opened.
  - An EXIT trap writes an outcome if the script stops early.
  - A lock turns away a second helper.
  - An old Lab Hub that quits after the 60 s wait is opened again.
- **A staged install** (review P2-2, security P2-2). Right after Lab Hub's build passes, `stage_build` copies the bundle to `update/staged/`. It refuses a symlinked path, a checkout that is no longer clean on main, or a build whose stamped commit is not HEAD. The helper installs only that copy and refuses a symlinked source, or a source equal to the target.
- **A refused Lab Hub is skipped, not failed** (review P2-1).
  - `Rebuild` has a `Skipped` result: the other rebuilds count and by-hand installers still open.
  - The end line says "Lab Hub itself was not rebuilt; its row says why", and there is no restart.
- **A fixed environment for the helper** (security P3-1, P3-4). `PATH=/usr/bin:/bin:/usr/sbin:/sbin`, `HOME`, `USER`, `LOGNAME`, `LANG` and `TMPDIR` only.
  - `ditto` and `open` are absolute paths.
  - The timeouts are module constants, passed as numbers and checked as digits. The `LAB_HUB_UPDATE_*` variables are gone.
- **Files** (security P3-2). The log is 0600 with `O_NOFOLLOW`, the folder is 0700, and the script runs under `umask 077`. `read_outcome` reads at most 4 KB from a regular file only.
- **The waiting row** (review P3 1–2).
  - It reads "Waiting", with no estimate.
  - Every poll counts as activity, so no "No output for 1:00".
  - Cancel clears the waiting reason.
- **Wording** (review P3 3–5, QA drift).
  - git failures are no longer called "detached HEAD".
  - The failure notice names the version it tried to install.
  - A source run reads "runs the checkout directly".
  - The review step says "Will update after this finishes: …" while something is busy.
- **Tests** (review P2-3, P3 7–8; QA gaps 1–8). `tests/test_self_update.py` went from 31 to 62 tests, adding:
  - the restart emit (passed, failed, skipped);
  - the all-pages wiring and the signal reaching the window;
  - a stub `Lander`;
  - the verify skip;
  - a self-test that hangs;
  - no previous build;
  - unremovable folders (both P1-1 scenarios);
  - the late quit, the lock, and wrong names, symlinks and numbers;
  - the fixed environment;
  - staging;
  - a row computed from a real stamp and checkout.
  The restart tests patch the helper and the message box, so a regression cannot open a modal and hang the suite.

**Not changed:**
- The checkout's `build/` and `dist.noindex/` are no longer removed by an update (`--install` removed them). Both are build output and are replaced by the next build.
- No cancel for the post-build restart wait (§9.1 note).

**After the second Verify (2026-11-17).** QA's second pass (`docs/audit/self-update-qa.md`, "Second Verify") found no production defect but three tests missing: N29 (P1), N2 (P2) and N10 (P2). The engineer added:
- a test that `run_updates` hands `Rebuild` the hold, and that the hold waits while a Land runs (N29);
- a test that an `.updating` folder that cannot be cleared means nothing is replaced (N2);
- two EXIT-trap tests. An early stop before the swap now reads `not_replaced` "stopped before anything was replaced"; during the swap it reads `broken`, naming the previous build (N10 and the P3 wording).

**Also:** `isolated_config` now points `self_update.UPDATE_DIR` at the test's scratch folder.

**Mutation check:** each of the three mutants was planted alone and then restored (checked with `cmp`). Each fails its tests: N2 fails 1, N10 fails 2 and N29 fails 3. `tests/test_self_update.py` passes 65 tests.

**Deferred for the owner:** the P3 survivors N3, N14, N23, N26, N28 and N31 (QA report). Each is a branch for a failure that a test can only reach by faking `mv` or `ditto`.

## 11. Amendment 1: build from a snapshot, not the shared checkout (Define, 2026-11-20)

Status: **Define approved by the owner 2026-11-20 ("Approve as recommended").** Owner of this amendment:
session `intelligent-wright-6029ac`. The in-flight list shows `self-update` itself (document done,
not released); this amendment is that spec's next change, asked for by the owner's session after
the real-Mac run below. No other in-flight spec changes `lab_hub/self_update.py`.

### 11.1 Problem and evidence
Update now builds Lab Hub in the shared checkout (`/Users/as/Documents/lab/active/lab_hub`) and
stages the result only if that checkout is still clean, on `main` and at the commit the build was
stamped with (§5.3; `checkout_blocker` and `stage_build`, `lab_hub/self_update.py:112`, `:214`).
Several sessions edit and commit there all day, and the window between the start of Lab Hub's build
and **Close and restart** is 10–20 minutes. In the owner's real-Mac check (QA report, "Owner's
manual check"), part D never reached the install in three attempts over two days:
- 2026-11-18: Update now held Lab Hub because another spec's edits appeared mid-run, and they
  stayed uncommitted overnight.
- 2026-11-19 23:17: the build passed, then a Foundry rollout committed `9f13596`; Close and
  restart refused: "the new build is from 596251f, but the checkout is now at 9f13596".
- 23:22: on the rerun, two `docs/foundry/*.jsonl` logs changed three minutes in.

The refusals were correct (nothing half-done was installed), but self-update can only succeed when
no other session touches the checkout, which in practice is never.

### 11.2 Success measures
1. **Builds from a snapshot at a recorded commit.** When the Lab Hub row is offered, Lab Hub
   records the full SHA of `main` in the shared checkout. Update now makes a private copy of the
   repository at exactly that commit, outside the shared checkout, and runs `build_app.sh` (with
   its self-test) there. Test: a fixture repo with a fake `build_app.sh`; the build sees the
   recorded commit's files and none of the checkout's uncommitted edits.
2. **The shared checkout cannot block or contaminate it.** Uncommitted edits, new commits on
   `main`, or a branch switch in the shared checkout, at any time after the row was offered, change
   neither whether Lab Hub builds nor what source is built and staged. (The Python environment,
   `.venv`, is still the checkout's: §11.4.) Tests: the checkout is dirtied, and
   separately moved forward a commit, (a) before the build starts and (b) after the build but
   before staging; in every case the bundle stamped with the recorded commit is staged.
3. **Close and restart installs what was built.** Staging checks the built bundle's stamp against
   the recorded commit and the snapshot's own `HEAD`, never the shared checkout. A mismatch still
   refuses ("Lab Hub was not restarted"), with the commits named.
4. **Uncommitted work is not a reason to update Lab Hub.** Lab Hub's row says "behind" only when
   the recorded `main` commit differs from the installed build's commit. When the checkout only has
   uncommitted edits, the row is up to date and its note says the edits are not in any build until
   they are committed to `main`. When the installed build has commits `main` does not (built by hand
   from a branch), Update now never offers `main`, which would be older: ahead of `main` the row is
   up to date, diverged it is held, and both notes say why (review P2-1, 2026-11-20). (The other
   apps' rows are unchanged.)
5. **Nothing is left behind or shown elsewhere.** The snapshot lives under
   `~/Library/Application Support/Lab Hub/update/`, is removed after staging, and is replaced by
   the next Update now. It is not a `git worktree` of the shared repository, so it never appears in
   Land, Tidy or `session_start.py --inflight` lists. Test: after staging the folder is gone and
   `git worktree list` on the fixture repo is unchanged.
6. **The rest of self-update is unchanged:** the waits for Land and tools, the helper, rollback,
   outcome notice and the previous build (§2.3–§2.7). The existing 65 tests still pass.

### 11.3 Scope
In: `lab_hub/self_update.py` (row, build command, staging), the hold in `ui/apps_tab.py`
(`_hold_for`, `_restart_on`), tests, this spec, `docs/audit/self-update-qa.md` §6, CHANGELOG.
Out: `build_app.sh` stays as it is (the snapshot runs the copy at the recorded commit); the
helper script; the other apps' rows.

### 11.4 Non-goals
- Building commits that are not on `main` (a branch someone checked out in the shared checkout).
- Isolating the Python environment: the snapshot uses the shared checkout's `.venv`, as the
  build always has. A session changing `.venv` mid-build is not addressed.

### 11.5 Decisions for the owner
1. **Which commit is built.**
   - **Recommended:** the tip of `main` at the moment Check builds shows the row, recorded and
     shown in the row ("builds `<sha7>`"). If `main` moves while Update now waits for a Land, Lab
     Hub still builds the recorded commit; the next Check builds offers the rest. What you reviewed
     is what is installed.
   - Alternative: the tip of `main` when Lab Hub's build actually starts (after any wait). Newer,
     but not what the row showed.
2. **The shared checkout's branch.**
   - **Recommended:** build `main` whatever the shared checkout has checked out; the row is offered
     whenever `refs/heads/main` exists. The checkout's state no longer matters to the build.
   - Alternative: keep today's rule that the checkout must be on `main` for the row to be offered.
3. **What kind of snapshot.**
   - **Recommended:** a private `git clone` of the shared repository (about 10 MB of history,
     hard-linked), checked out detached at the recorded commit, with a link to the checkout's
     `.venv`. It is invisible to Land, Tidy and the in-flight check, and no other session's
     `git worktree remove` or `prune` can touch it.
   - Alternative: a temporary `git worktree add --detach`. Cheaper, but it is registered in the
     shared repository, so it shows up in Land and Tidy lists for 10–20 minutes and could be
     removed by them mid-build.

### 11.6 Owner's decision
Approved by the owner 2026-11-20 ("Approve as recommended"): all three §11.5 recommendations.

## 12. Amendment 1: architecture (architect, 2026-11-20)
ADR: `docs/adr/0006-self-update-snapshot-build.md` (supersedes decision 2 of ADR 0003). It changes
state (a new folder) and the build's boundary, so it needs the owner's Architect gate.

### 12.1 Modules and boundaries
All in `lab_hub/self_update.py` unless named; Qt-free as before.
- **`snapshot()`** returns `UPDATE_DIR / "snapshot" / "lab_hub"`, computed from `UPDATE_DIR` at
  each call so tests that patch `UPDATE_DIR` move it too: a private clone. Its build output is
  `…/lab_hub/dist.noindex/Lab Hub.app`.
- **`main_commit(project) -> str | None`:** `git rev-parse --verify --quiet refs/heads/main^{commit}`,
  the full 40-hex SHA. Replaces `checkout_blocker` and `head_commit`; nothing reads the shared
  checkout's branch or status any more.
- **`build_command(project, commit) -> str`:** one fixed `&&` chain, every value `shlex.quote`d,
  `commit` checked to be 40 lowercase hex first:
  `[ ! -L <update> ] && [ ! -L <update>/snapshot ] && /bin/mkdir -p <update>/snapshot && /bin/chmod 700 <update> <update>/snapshot`
  `&& /bin/rm -rf <snap> && git -c core.hooksPath=/dev/null clone --template= --quiet --no-checkout -- <project> <snap>`
  `&& git -C <snap> -c core.hooksPath=/dev/null -c advice.detachedHead=false checkout --quiet --detach <commit>`
  `&& /bin/ln -s <project>/.venv <snap>/.venv && cd <snap> && ./build_app.sh`.
  `git clone` of a local path hard-links the objects (about 10 MB of history, a second or two) and
  does not copy the shared repository's hooks or config. The command is shown in the live output
  and copied by Copy commands, as today.
- **`planned_commit(command, project) -> str | None`:** the commit in a command, accepted only if
  `build_command(project, commit)` rebuilds the very same string. This is how `_restart_on` learns
  the recorded commit from the `restarts` command it already has; no new state is passed around.
- **`self_status`:** the row is offered when the copy runs from `/Applications`, `main` resolves
  and `build_app.sh` exists at that commit (`git cat-file -e <commit>:build_app.sh`). Its verdict for
  Lab Hub is taken from the installed stamp against `main_commit`:
  - stamp is a prefix of the `main` commit: `current`. If `build_status` said `uncommitted`, the note
    says those edits are in no build until they are committed to `main` (§11.2.4).
  - otherwise `behind`, with the `build_status` note when the checkout is on `main`, or "main is at
    `<sha7>`" when it is not. The note ends "Update now builds `<sha7>`."
  - stamp unknown: as today (no command).
- **`stage_build(commit)`** (was `stage_build(project)`): checks the snapshot path has no symlink,
  the executable exists, `git -C <snap> rev-parse HEAD` equals `commit`, and the bundle's stamp is a
  prefix of `commit`; then `ditto`s to `staged/` as today and removes the snapshot. It never touches
  the shared checkout. On a refusal the snapshot is left for the log and replaced by the next build.
- **`ui/apps_tab.py`:** `_hold_for` keeps the busy wait and drops the checkout re-check (only "its
  checkout is gone" still skips). `_restart_on(restarts)` calls
  `stage_build(planned_commit(restarts, project))`, refusing with "the build command is not one Lab
  Hub made" if that is None.
- **Unchanged:** `build_app.sh`, `HELPER_SCRIPT`, `helper_paths`, `start_helper`, outcomes,
  `main_window.restart_for_update`, the other apps' rows.

### 12.2 State and concurrency
- **One new folder,** `update/snapshot/`; the command sets it and `update/` to 0700. Only Update now writes it; it is
  cleared at the start of each build and after staging. Two Update nows cannot overlap: the Check
  builds window is modal and `Rebuild` runs one command at a time.
- **The shared checkout is read twice and never written:** at the row (`rev-parse`, `cat-file`) and by
  `git clone` (reads objects and refs). Concurrent commits there are harmless: the clone reads
  immutable objects for a SHA already recorded, and a ref moving mid-clone does not change that SHA.
- **`.venv` is shared** (§11.4): `uv pip install -q pyinstaller` in `build_app.sh` still writes it,
  as every Lab Hub build always has.
- **Space in the path:** the snapshot sits under `Application Support/Lab Hub/`, two spaces.
  `build_app.sh` quotes its paths and PyInstaller accepts them; Verify confirms with one real build
  (without `--install`) in such a path.

### 12.3 Rejected
- **`git worktree add --detach`:** registered in the shared repository, so Land and Tidy list it and
  can remove it mid-build (§11.5.3).
- **`git archive | tar`:** no `.git`, so `stamp_version.py` (`rev-list --count`) cannot stamp it.
- **Shallow clone:** `rev-list --count` would give the wrong build number.
- **Snapshot at build start instead of at the row:** owner chose the reviewed commit (§11.5.1).

### 12.4 Tests (Build)
In `tests/test_self_update.py`, on fixture repos with a fake `build_app.sh` that writes a fake
bundle stamped from its own `git rev-parse`, running the real `build_command` with `bash`:
- the snapshot builds the recorded commit; uncommitted edits in the checkout are not in it;
- the checkout dirtied, and separately moved one commit forward, before the build and after it: the
  recorded commit is staged in all four cases (§11.2.2, §11.2.3);
- a stamp that does not match the recorded commit, a snapshot `HEAD` that does not, and a symlinked
  snapshot path: refused;
- after staging the snapshot is gone and `git worktree list` is unchanged (§11.2.5);
- `planned_commit` accepts only a command `build_command` made (changed path, short SHA, extra text);
- `self_status`: dirty checkout level with `main` is `current` with the note; on another branch it
  still builds `main`; `main` missing gives no command.
In `tests/test_apps_tab.py`: the hold no longer skips Lab Hub for a dirty checkout; `_restart_on`
stages from the recorded commit after the checkout moved.

## 13. Amendment 1: review, verify and secure (2026-11-20)
- **Review** (`docs/audit/self-update-snapshot-code-review.md`): no P0/P1. P2-1 (a build ahead of
  `main` would be offered a downgrade) fixed, with §11.2.4 amended; P3-1 to P3-5 fixed; P3-6 fixed
  except the `.venv` link showing as untracked in the snapshot, which is harmless while the stamp
  records no dirty flag.
- **Secure** (`docs/audit/self-update-snapshot-security.md`): no P0/P1/P2. P3-1 (`rm -rf` redirected
  by a symlinked `update/` or `update/snapshot/`) fixed: the command refuses symlinked parents before
  `mkdir` and `rm`, and staging re-checks before removing the snapshot; tested. P3-2 (git older than
  the 2026-11-10 security release, not reachable from this path) is the owner's: `brew upgrade git`.
  P3-3 (the spec claimed more isolation than `.venv` gives; `update/` was 0755) fixed in §11.2.2,
  §12.2 and the command.
- **Verify** (`docs/audit/self-update-qa.md`, "Verify of amendment 1"): 15 mutants planted one at a
  time, all killed; full suite green; one real PyInstaller build in a snapshot under a path with
  spaces passed its self-test and staged.
- **Bootstrap:** the installed Lab Hub still runs the old Update now, which needs a quiet checkout
  to install this version. Install this one by hand (`./build_app.sh --install` after quitting Lab
  Hub) or run Update now at a quiet moment; from then on the snapshot build applies.
