# Lab Hub — TODO

> **Testing first (owner, 2026-11-20).** `P0` now means: needed before the owner can test this app on his own Mac, or a security must. Everything else waits until after testing, and no new feature or redesign row starts unless the owner asks for it. These protect the other apps' checkouts while they are being tested.

> **Legend** — priority `P0` critical · `P1` high · `P2` normal · `P3` low
> categories `security` `bug` `feature` `performance` `design` `docs` `testing` `infra` `research`
> owner `@me` (needs you — accounts, keys, money, judgement) · `@ai` (Claude can do this)

---

## v2 — complete (2026-09-14)

- [x] `P1` `feature` `@ai` **Ask Claude… in Check builds and the Land window (2026-11-18).**
  - Spec `docs/specs/claude-handoff.md`: Define "Approve, use defaults", Architect "Approve architecture", fixes "Fix all as proposed" and "Fix as proposed". ADR `docs/adr/0004-claude-handoff-terminal-session.md`.
  - Why: the owner relayed every "Needs you" / "Not rebuilt" / Land stop row to Claude by hand, across several sessions.
  - What it does: one Claude Code session per repo, in Terminal, after a confirmation with the cost. Manual permission mode, inline ask/deny rules, seven limits.
  - Code: `lab_hub/handoff.py`, `ui/handoff_dialog.py` (new); `ui/progress_window.py`, `ui/apps_tab.py`, `ui/main_window.py`, `ui/lander.py`, `lab_hub/land.py`.
  - Reviews:
    - `docs/audit/claude-handoff-code-review.md` (1 P1, 7 P2, fixed);
    - `docs/audit/claude-handoff-qa.md` (13 mutants, fixed);
    - `docs/audit/claude-handoff-security.md` (1 P2, P3s, fixed).
- [ ] `P1` `testing` `@me` **Real-Mac check of Ask Claude.** Follow `docs/audit/claude-handoff-qa.md` §2.7:
  - `git push` asks;
  - `legal_gate.py sign` is refused;
  - a Provisio row ends clean;
  - record the session's cost with `model_use.py --purpose eval`.

  It needs a Lab Hub build with branch `claude/resolve-button-5dc32f`, so it comes after merge and Update now.
- [x] `P1` `feature` `@ai` **Lab Hub updates itself from Check builds (2026-11-17).**
  - Spec `docs/specs/self-update.md`; Define "Approve as recommended", Architect "Approve architecture". ADR `docs/adr/0003-self-update-helper.md`.
  - Why: the installed v2.172 lacked the Land progress window, and updating meant a terminal, `kill` and a menu bar click.
  - A "Lab Hub (this app)" row comes last in the launchpad's Check builds. Update now builds Lab Hub last, waiting for any Land or tool and skipping Lab Hub unless the checkout is clean on `main`.
  - The build that passed is staged out of the checkout. After Close and restart, a detached helper installs it (checked swap, previous build kept, self-test, rollback or `broken`) and opens Lab Hub, which reports the outcome once.
  - Code: `lab_hub/self_update.py` (new), `ui/rebuild.py` (`hold`, `Skipped`), `ui/apps_tab.py`, `ui/main_window.py`, `lab_hub/progress.py`, `ui/progress_window.py`.
  - Reviews: `docs/audit/self-update-code-review.md` (1 P1, 3 P2, fixed), `docs/audit/self-update-security.md` (2 P2, fixed), `docs/audit/self-update-qa.md`.
  - Not done: the owner's real-Mac check (QA report §6: the swap, the window in front, a forced rollback), commit, merge and release. The first self-update has to come from a build that already has this feature: build and install it by hand once with `./build_app.sh --install` while Lab Hub is not running.
- [ ] `P2` `testing` `@me` **Real-Mac check of Land's folder-link stop text.**
  - Session "Mac check: Land's folder-link stop text" is waiting for you to confirm Sonnet, low effort (about 5–15 min).
  - It follows the self-update and `land-folder-link-guard` work.
- [ ] `P3` `testing` `@me` **Self-update: the last unchecked A2 case** (`docs/audit/self-update-qa.md` §6 A2, third item).
  - The case: with only uncommitted edits in the checkout, Lab Hub's row reads up to date and says the edits are in no build.
  - It was not run on 2026-11-20 because `main` had moved.
  - The next routine Update now also installs `9bf3cdc` (the failed staged build is removed after a rollback).
  - Otherwise the self-update Mac check passed on 2026-11-20 (A, A2, B, C, D).
- [ ] `P3` `infra` `@me` **Provisio's release clone is 30 commits behind.**
  - Check builds shows Provisio as "Needs you".
  - Move `/Users/as/Releases/provisio` forward per its `docs/RUNBOOK-release.md`: CI, legal check, dependencies and selftest.
  - Only needed before the next Provisio release.
- [x] `P1` `feature` `@ai` **Land leaves nothing open (2026-11-17).**
  - Spec `docs/specs/land-resolve-all.md`, approved by the owner: "Approve, use defaults". ADR `docs/adr/0001-land-quarantine-and-archive-tags.md`.
  - Why: Land all landed 2 of 6 repos and left 25 branches "for your decision". The owner said: "all open items always have to be resolved".
  - Untracked files are scanned with gitleaks and committed. Secret-like names, binaries the scan cannot read, files over 10 MB and files with a finding move to `~/Documents/lab/.quarantine/` and into `.gitignore`.
  - A checkout on a side branch is committed and switched back to the default branch. A detached HEAD holding work is put on a rescue branch.
  - A git symlink checked out as a file (`shopfront/website`) is followed and restored.
  - Branches that still cannot land go to Claude Code read-only ($0.50 cap) for a land-or-archive verdict. An archived branch becomes a local tag `archive/<branch>/<date>`, never pushed, with Restore in Review branches.
  - Every Land push is preceded by a gitleaks scan of the outgoing commits. "Landed" means nothing is left open.
  - Code: `lab_hub/land_resolve.py` (new), `land.py`, and a `land_mode` flag in `repo_tidy.py`.
  - Reviews: `docs/audit/land-resolve-all-review.md` (2 P1, 7 P2, all fixed), `docs/audit/land-resolve-all-security.md` (2 P1, 4 P2 fixed), `docs/audit/land-resolve-all-verify.md`.
  - Not done: owner approval of the Architect section, owner commit, merge and rebuild, and a real Land all on the lab. On the dry run, Backstage stops because two live Claude Code sessions are working in its checkout.
- [x] `P1` `bug` `@ai` **Land no longer sends already-applied branches to Claude (2026-11-17).** Spec `docs/specs/land-already-applied.md` (owner: "Approve as recommended"). Evidence: Sentinel's `fixes/audit-tier2-2026-10-12`, 19 commits already in main as rebased copies, cost $1.15 and 147 turns for an empty merge commit. `repo_tidy.applied_copies` (`git cherry` all `-`, no merge commits) makes such a branch landed: its branch and clean worktree are deleted, no Claude run, no merge; the preview says "matched by patch" and counts differing files. Tests with real git in `tests/test_repo_tidy.py`. Independent review (0 P0/P1, P2s fixed) and mutation check: `docs/audit/land-already-applied-review.md`. Not done: owner merge, rebuild, a real Land on Sentinel.
- [x] `P1` `bug` `@ai` **A stale release clone is moved forward, not reinstalled (2026-11-16).** Spec `docs/specs/release-root-behind.md` (owner: "Approve", all three recommendations). Found while trying Update now on Provisio: its installer rebuilds from `~/Releases/provisio`, so on a clone 11 commits behind it changed nothing; only the runbook's fast-forward made the tile current. Now an app whose bundle records a release clone that is behind gets no installer and no Update now: the report names the problem, lists `git -C <clone> fetch origin && git -C <clone> merge --ff-only origin/main` to copy (nothing is run, no Terminal opened), and points at the runbook's CI, legal, dependency and selftest steps. Review `docs/audit/release-root-behind-review.md` (0 P0, 1 P1 and 6 P2, all fixed or accepted). 679 tests pass, including one end-to-end with real git that runs the shown command and sees the tile go current. Lab Hub not rebuilt. Not verified: a fresh stale-clone run on the real Mac.
- [x] `P2` `feature` `@ai` **Update now covers apps whose installer needs a terminal (2026-11-16).** Spec `docs/specs/update-now-terminal.md` (owner: "Approve", all three recommendations). Provisio alone being behind left no Update now. Now, after the in-app rebuilds succeed, it opens one Terminal window per by-hand installer, started from a one-line `.command` file (0700, `~/Library/Application Support/Lab Hub/terminal-runs/`, created `O_EXCL|O_NOFOLLOW`, removes itself); the owner still types `install` there; Lab Hub types nothing and needs no Apple Events grant. A bad command is refused before any rebuild; a Terminal that will not open is shown, not swallowed. Review `docs/audit/update-now-terminal-review.md` (0 P0, 2 P1 fixed) and security `docs/audit/update-now-terminal-security.md` (0 P0/P1; P2 `-t 0` substring routing is repo-controlled, left as is). 670 tests pass, 13 planted mutants caught. Lab Hub rebuilt and installed (build 156). **Verified by the owner on the real Mac 2026-11-16:** Update now opened Terminal with the installer. Not checked: that the Provisio install itself completed and its tile then read current.
- [x] `P1` `bug` `@ai` **Land's test limit is per repo, and a bare `python3` is no longer the system 3.9 (2026-11-16).** Spec `docs/specs/land-from-tiles.md` §10 (owner: "fix the timeout and the python lookup order"). `- Test timeout: N min` under `## Commands` (1 to 180); the test PATH lists Homebrew and `/usr/local` first. Open: add the line to Imprint's app-context (its runs took 29 of the 30 minutes).
- [x] `P1` `bug` `@ai` **Land's test run sees SONAR's and Sentinel's nested repos (2026-11-16).** Spec `docs/specs/land-from-tiles.md` §9 (owner: "approve section 9"). SONAR's gitignored `sonar/macro`/`sonar/playmaker` are copied into the temporary worktree (without `.git`) and Sentinel's `agents/bug_spray` submodule is initialised or copied, for the test run only; this was why Land on SONAR stopped with `ImportError: cannot import name 'macro'`. Independent review and security review done. Open: a real Land on SONAR and Sentinel (owner); Imprint's 35-minute suite still exceeds the 30-minute test limit (decision: left as is).
- [x] `P1` `feature` `@ai` **Land: one button per tile replaces Check repos, Resolve and its tick-boxes (2026-11-16).** Spec `docs/specs/land-from-tiles.md` (owner: "approve as recommended"; it superseded `tile-resolve.md`, closed unbuilt). A tile with work to land shows **Land**; one confirmation in one sentence, progress and the outcome on the tile ("Landed" or "Not landed: <reason>"), **Land all (N)** on the launchpad, "N branches need your decision — review" opens Review for that repo. The badge now wraps under the version and a dialog's scrolling no longer swipes the pages behind it (`eb6e9e1`). Engine unchanged (`repo_tidy`); new `lab_hub/land.py`, `ui/lander.py`; tests `test_land.py`, `test_land_ui.py`. Open: the branch suffix on checkout tiles (build-marker spec decision 2).
- [x] `P1` `feature` `@ai` **Resolve wastes nothing on branches it cannot land (2026-11-16).** Spec `docs/specs/repo-tidy.md` §12 (owner: "Build fixes 1–4"), after the first real run landed 1 of 11 for about $3.90. Temporary worktrees under `~/Library/Caches/LabHub/resolve` (no spaces); the default branch's tests run first, and a branch stops with no Claude call unless they pass (a pass is reused for the same tip); `DELETE: <path>` for modify/delete conflicts, literal and limited to conflicted files one side deleted; tile badge counts items; Review branches shows the last Resolve reason. Code review `docs/audit/resolve-wasteless-code-review.md` (0 P0/P1, 4 P2 fixed). 19 mutations caught. Not done: owner merge/push/rebuild; pytest missing in imprint's and backstage's `.venv`; sentinel's test command says `python`; sonar's tests need the ignored `sonar/macro` repo.
- [x] `P1` `feature` `@ai` **Resolve lands conflicting branches with Claude Code (2026-11-16).** Spec `docs/specs/repo-tidy.md` §11 (owner: "Approve as recommended": Sonnet, $3 cap per branch, fix round allowed). `lab_hub/claude_resolve.py`: Lab Hub merges in a temporary worktree under its support folder, Claude Code runs headless with file tools only (`--restricted --safe-mode --strict-mcp-config`, no shell/web/MCP/hooks/CLAUDE.md) on the conflicted files, Lab Hub checks nothing else changed (ignored files and `.git` included), commits, runs the repo's tests itself (allowlisted env, git config/hooks fingerprint), one fix round that may not touch tests, then fast-forwards and pushes only if both tips are unchanged. Confirmation, streamed progress with cost/turns, Stop. Code review (`docs/audit/resolve-with-claude-code-review.md`: 1 P0, 2 P1) and Secure (`docs/audit/resolve-with-claude-security.md`: 2 P1) fixed; security P1-2 narrowed, `sandbox-exec` for tests left as owner decision A6. 54 tests with a stub CLI; guard mutations caught (see audit). Real CLI end to end on a toy repo: landed a correct two-parent merge (haiku, <$0.01). Dry run 2026-11-16: 12 branches in 7 repos would go to Claude. Not done: owner merge/push, Lab Hub rebuild, a real Resolve on the lab.

- [x] `P1` `feature` `@ai` **Resolve merges branches that merge cleanly; tiles fit; no more build-rewrite loop (2026-11-16).** Spec `docs/specs/repo-tidy.md` §10. Merge only with no conflicts, main on its default branch, clean and not behind origin, and the branch's worktree finished (clean, unused, no agent use in 24 h); then its worktree and branch go and main is pushed; a failed merge is aborted. Version and badge on their own tile line (the third column had been pushed off the window). Update now restores tracked files its build rewrote (SYNDUSTRYX `release-manifest.json`), which had made Resolve commit them and the tile read 1 behind. 9 new merge tests, 9 guard mutations caught. Dry run 2026-11-16: 3 merges; SYNDUSTRYX's 10 clean branches wait while its checkout is on `claude/bundle-backup-prune`; 12 conflicting branches need a person.
- [x] `P1` `bug` `@ai` **SYNDUSTRYX updated; its tile now knows what was installed (2026-11-16).** The build crashed swiftc on a stale module cache from the project's old Codex path (`build/swift-cache-syndustryx`, moved aside as `.stale-<date>`); rebuilt with CPython 3.12.16 from `~/Runtimes` and installed through Lab Hub's own command. Its plist stays pinned at 0.6.53 and it stamps no commit, so Update now now records the commit, the pre-build dirty flag, a fingerprint of the checkout after the build, and the installed executable's SHA-256 in `~/Library/Application Support/Lab Hub/installs/<key>.json`; the tile counts behind from that commit, and files the build itself rewrites (`release-manifest.json`) do not read as uncommitted. A replaced bundle no longer matches its record, and nothing is claimed. Tests in `tests/test_launcher.py`. Left in SYNDUSTRYX: `release-manifest.json` rewritten by its build (0.6.54), uncommitted.
- [x] `P1` `feature` `@ai` **Check repos: Clean up… becomes Resolve… and commits open work (2026-11-15).** Spec `docs/specs/repo-tidy.md` §9 (owner: "Yes, build it"). Commits tracked changes only (`git add -u`), in main checkouts and in linked worktrees not in use or recently used by an agent; skips detached HEADs, paused operations and conflicts; untracked files are listed, never added. A push follows when the default branch was otherwise level or only ahead. 10 new tests, 9 guard mutations caught. Read-only dry run on the lab: 7 commits, 1 push, 67 branch deletions, 5 worktree removals proposed. Not run for real.
- [x] `P2` `feature` `@ai` **Check builds: SYNDUSTRYX gets Update now; no-command apps get Open in Terminal (2026-11-15).** Owner's choice: run its build anyway. `apps.toml` `build`/`build_output` fields: Update now runs `python3 build_desktop.py`, then moves the installed bundle to the Trash (dated) and copies `dist/SYNDUSTRYX.app` in. This skips SYNDUSTRYX's own update preflight and signing checks (`desktop/BUILDING.md`, ADR 0001 D4), and the build fails until a Python 3.12.16+ runtime is supplied. An app with no command at all names its build guide and offers Open in Terminal. Tests in `tests/test_launcher.py`, `tests/test_apps_tab.py`. Not run for real.
- [x] `P1` `feature` `@ai` **Check repos: Clean up and Review branches (2026-11-15).** Spec `docs/specs/repo-tidy.md` (Define/Architect approved 2026-11-15, A1 code in Lab Hub, A2 skip recent agent worktrees). `lab_hub/repo_tidy.py`, `ui/repo_tidy_dialogs.py`; 42 tests on real temp repos; 23 guard mutations all caught. Review (`docs/audit/repo-tidy-code-reviewer.md`) and Secure (`docs/audit/repo-tidy-security-engineer.md`): one P1 each, the same one (worktree removal deleted ignored files such as `.env`), fixed with all P2s and P3s. Dry run on the real lab (read-only, 2026-11-15): 66 branch deletions and 5 worktree removals proposed; Imprint/Sonar/Sentinel worktrees with ignored data left alone. Not done: commit/merge (owner), Lab Hub rebuild, a real Apply by the owner.
- [x] `P1` `bug` `@ai` **Update now no longer runs installers that cannot work there (2026-11-14).** Provisio's `install_app.sh` refuses the main checkout and any shell without a terminal, so Update now failed on it and stopped the whole run. `build_status` now installs a launcher bundle from the root it records (the release clone) and marks an installer that checks `-t 0` as by hand: the build check lists it under "Run yourself, in a terminal" (pointing at the project's `docs/RUNBOOK-release.md`) and copies it, and Update now skips it. A behind app with no known build script (SYNDUSTRYX builds with `build_desktop.py`) is named under "No rebuild command" instead of silently dropped. Tests in `tests/test_launcher.py` and `tests/test_apps_tab.py`; three planted mutations all caught. Not verified in the running app; Lab Hub not rebuilt.
- [x] `P1` `feature` `@ai` **Repo hygiene in the launchpad** (2026-11-13): "N to land" badge per app and a **Check repos** button, read from git_autosync's `hygiene.json`. `tests/test_hygiene.py`.
- [x] `P1` `feature` `@ai` **Every tile shows its real build and how far behind it is (2026-11-13).** Spec `docs/specs/lab-wide-build-marker.md`. Tile text is `v<major>.<build>+g<sha7>[-dirty]` for every origin; a launcher bundle is read at the root it records (Provisio: the release clone) and gets `· N behind` against the working checkout; `build_status` reports it `behind`. `stamp_version.py` requires a commit. Review fixes 2026-11-13: an unreadable recorded root is unknown and names the root (tile and build report), `behind_unknown` gives `unknown` in the report, shallow clones show `unknown` for the count, `behind` is cached on HEAD, and a stamp's unknown commit is never compared by count. Lab Monitor (measure 5) done 2026-11-13 in the lab repo: `build_marker.py`, parity test `_Admin/tests/test_build_marker_parity.py` (run with `LAB_HUB_SRC`). Not done: branch suffix on checkout tiles (spec decision 2) not built, owner has not answered. `tests/test_build_marker.py`.
- [x] `P1` `bug` `@ai` **Narrator converter knows OpenAI retires `gpt-4o-mini-tts` on 2027-01-06 (2026-10-19).** The vendored converter (copy of Imprint's) gained a `retires` date on the OpenAI route and `default_tts_provider()`: until that day the default stays OpenAI, which the Narrator tab uses; from it the default is Gemini, which this app's Python does not support (no google-genai), so the tab will say the route cannot run — decide before the date whether to add google-genai here or point the tab at an explicit route. Imprint's `test_converter_drift.py` passes against it. `tests/test_narrator_tab.py`.
- [x] `P0` `bug` `@ai` **A running Sentinel reported as *Did not start*, twice.** The
  first time it was `running_markers()` matching the bundle alone, when Sentinel's stub
  execs the project's python and exits. The second (2026-10-07) reached the identical
  tile through the other half: `ExternalApp.project` is a directory name baked into the
  build, the checkout was renamed `sentinel_fork` → `sentinel`, and the installed v2.049
  was left with no checkout marker and only the bundle again — which also blanked the
  version label and the build report. Three changes, because one of them would only
  have postponed it: `source_dir()` falls back to the checkout the bundle records in
  `Contents/Resources/project_root.txt` (the configured lab folder still wins, so
  Settings keeps deciding); `launch_is_observable()` stops the card claiming failure
  when nothing durable was there to watch — it says *Started* and admits it cannot tell;
  and `--selftest` fails the build when a registered `project` is gone while the
  bundle's record points somewhere that works, so the next rename is caught at build
  time rather than on a tile. `tests/test_launcher.py`, `tests/test_apps_tab.py`.
- [x] `P1` `feature` `@ai` **Health check per app, before the button is pressed** —
  `launcher.readiness()` answers "would this start at all", where `status()` only
  answered "where from". Catches a checkout with no `.venv` and no `python3` on PATH,
  and a bundle that is still a directory but has lost its executable; either disables
  Launch and says why on the tile. The executable is read from `CFBundleExecutable`
  rather than assumed to match the app's name — Sentinel is an applet wrapper
  whose binary is `applet`, and assuming would have called a working app broken.
  `tests/test_launcher.py`, `tests/test_apps_tab.py`.
- [x] `P1` `bug` `@ai` **A child that dies at startup no longer looks like one that
  worked.** A source run was already death-watched and reports its exit code and
  captured output. The gap was the installed bundle: started through `open`, it is not
  our child, so there is no code to read. The tile now says *Starting…* and waits for
  the process to appear; if it has not within `LAUNCH_CONFIRM_SECONDS` it says *Did not
  start* and the status bar names where the output went — the `log show` predicate for a
  bundle, the captured temp file for a source run. Reported once, not on every poll.
  `tests/test_apps_tab.py`.
- [x] `P2` `feature` `@me` Decide whether Lab Hub should start at login (LaunchAgent) or stay manual — decided yes: `lab_hub/login_item.py` installs a LaunchAgent, toggled from the Settings tab, and on login it also starts Backup Control Center and git_autosync if they're not already running.
- [x] `P2` `testing` `@ai` **`--selftest` probes every registered app**, not one
  sibling sample: a real `QApplication` under each app's own venv, with the scrubbed
  child environment. The env is shared but the Qt build on the other side of it is each
  project's own, so each venv is its own answer. Judgement call worth knowing about: it
  probes each app's *interpreter* rather than running the app — launching six GUI apps
  on every build would not survive being run, and the crash it guards against happens
  inside `QApplication()` before any app reaches its own code. No checkout or no venv is
  reported as skipped, never as a pass.
- [x] `P3` `design` `@ai` Apps tab: group by category rather than one flat list, now that there are twelve projects — addressed by splitting into three tabs (Apps / Backup & Sync / Tools) instead of grouping within one tab; the Apps tab itself is back down to 5 items (`PRIMARY_APPS`).
- [x] `P1` `bug` `@ai` **Red button did nothing on a blank window** (2026-10-19). After a long run (since 05:13, through sleep and two displays) Qt believed the window hidden while macOS still drew it, blank; `hide()` on an already-hidden widget is a no-op, so closing never reached AppKit. `_hide_now` now also sends `orderOut:` to the NSWindow (`dock.order_out`, cocoa platform only — offscreen winIds are not NSViews and segfault). Root trigger not reproduced; the stuck state was, and is the regression in `tests/test_window_lifecycle.py`.
- [ ] `P3` `debt` `@ai` `backstage_tab` in `ui/main_window.py` is now an empty, unreachable page since Backstage became a suite (31dbb9d). Remove it, or drop `[[tools_only]]` support if nothing else will use it.
- [x] `P1` `bug` `@ai` Red button quit instead of hiding — and the fix for that re-showed the window in the same breath as closing it. Both shipped, with `tests/test_window_lifecycle.py` as the regression.
- [x] `P2` `infra` `@ai` Config written to `~/Library/Application Support/Lab Hub/`, never inside the bundle
- [x] `P2` `feature` `@ai` **Narrator Library** — a second sub-tab browsing the generated ebook catalogue (`ebook_catalog.csv` from Codex's `outputs/`), with per-row Read/Queue checkboxes persisted to `narrator_library_state.json`, a Narrated-books filter (matched against existing audio files, not tracked separately), and one click to load a book into Convert. `ui/narrator_library.py`, `tests/test_narrator_tab.py`.
- [x] `P1` `bug` `@ai` **Dock icon shown only while a window is open** — done, and
  verified in the packaged app across all four states (login start, app launched from
  the menu bar, window opened, window closed). Three pieces were needed: `LSUIElement`
  in the bundle (LaunchServices pins the type from `Info.plist`, so the runtime switch
  alone is ignored once packaged), the policy switch in `ui/dock.py`, and — the piece
  that was missing — `dock.activate()`, because promoting out of `Accessory` gives a
  Dock icon but does not make the app frontmost, so the window was created and left
  sitting behind everything. That looked like "no window", which is why this was
  reverted once as impossible. `--selftest` prints the true reading via
  `dock.current_policy()`; use that. The note here used to blame `lsappinfo` for
  that wrong turn, which was unfair — its `ApplicationType` does track the live
  policy (`Foreground` with the window up, `UIElement` once hidden, against one
  running pid). It could only ever show a switch that was actually happening, and
  back then it was not. `tests/test_window_lifecycle.py`.
- [x] `P1` `design` `@ai` **Quitting from the Dock hides Lab Hub instead.** The Dock
  icon only exists while a window does, so Quit there — and ⌘Q — means "off my
  screen", not "shut it down"; both used to take the menu bar item with them. macOS
  sends these through `applicationShouldTerminate:`, which Qt delivers as a
  `QEvent.Quit` to the application object; `_QuitGuard` answers with `event.ignore()`.
  Returning `True` alone does not refuse it: a `QEvent` starts out accepted and
  filtering one leaves that flag set, which macOS reads as consent. The menu bar's own
  **Quit Lab Hub** is the single real exit and bypasses the event entirely; a test runs
  a real event loop with a failsafe timer to prove it, because the failure mode here is
  an app that cannot be quit. Verified against the installed bundle: the quit Apple
  Event came back `-128` (cancelled), the pid survived and its type went
  `Foreground` → `UIElement`. `tests/test_window_lifecycle.py`.
- [x] `P1` `bug` `@ai` **Apps tab pointed at a renamed project** — the tile called
  `create_and_publish` no longer resolved (renamed to `imprint`), but
  `Create & Publish.app` was still installed, so the card read *Installed* and
  silently launched a stale build. Worse than a dead tile.
- [x] `P2` `design` `@ai` **Umbrella apps only — agents are not separately launchable.**
  Tunnel and Bug Spray live inside Sentinel (`sentinel/agents/`), the video
  pipeline inside Imprint, macro and Playmaker inside SONAR. Lab Hub lists the three
  umbrella apps and nothing below them, in the Apps tab and the menu bar alike. The
  nested-companion rows tried in between are gone: they still offered a second door to
  a feature that belongs to its parent app. `/Applications/VPN Agent.app` is still
  installed and **stale** (built Aug 17; the source has commits through Sep 9). It is
  not orphaned — `build_app.sh` and the spec moved along with the source to
  `sentinel/agents/vpn_agent`, so it rebuilds from there. Not deleted: VPN Agent
  is essential to Sentinel and is being worked on elsewhere.
  `tests/test_tab_groups.py`, `tests/test_tray.py`.
- [x] `P3` `design` `@ai` Menu bar lists **top-level apps only** — companions were
  appearing there as peers, making a six-item menu nine items long. `MENU_BAR_APPS`,
  `tests/test_tray.py`.
- [x] `P3` `bug` `@ai` Tab read "Backup_Sync" — Qt treats `&` in a tab label as a
  mnemonic marker. Renamed to "Backup and Sync", with a test forbidding `&` in labels.
- [x] `P0` `bug` `@ai` **Lab Hub aborted whenever its menu bar menu opened.** SIGABRT,
  and not this app's fault: Qt's cocoa plugin asks the current event for its `clickCount`
  when a menu begins tracking, and on **macOS 27** that raises for a non-mouse event
  instead of answering zero. The Objective-C exception unwinds through C++ frames that
  catch nothing, into `terminate()`. Proven not to be ours: SONAR produced a byte-identical
  stack on the same day the machine moved to 27, and PySide6 6.11.2 is the newest release
  there is. Reproduced directly — building any non-mouse `NSEvent` and asking it for
  `clickCount` aborts the interpreter. `ui/appkit_guard.py` swizzles that one selector to
  answer 0 for the event types that have no click count and to call through for the ten
  that do; `--selftest` fails the build if it does not install. Remove it when Qt ships a
  fixed plugin. `tests/test_appkit_guard.py` runs against the real runtime.
- [x] `P2` `design` `@ai` **"Engine · running" meant nothing to the reader.** It is now
  "Background engine", and the tooltip says what it actually is: a process that goes on
  collecting and settling data with no window, running whether or not the app is open, and
  which Launch neither starts nor stops.
- [x] `P2` `feature` `@ai` **Copy and open Terminal** beside Copy commands — the clipboard
  plus a window to paste into. Not typed in for you: driving Terminal needs an Apple Events
  grant, and a window that runs a command the instant it opens is the wrong shape for
  something that replaces an installed app.
- [x] `P2` `bug` `@ai` **The rebuild command it printed would not have installed.** The
  first cut of the build report printed `cd <project> && ./build_app.sh` for everything,
  but the scripts disagree silently: `sonar`, `unblock_tracker`, `lab_hub` and Sentinel
  only copy into `/Applications` when passed `--install`, while `backup_manager`,
  `git_autosync` and Imprint install by default. Running the flagless version against
  SONAR would have cost several minutes and left v2.104 installed. `install_command()`
  reads the flag from the script itself — a table here would be a second place to be
  wrong — and **Copy commands** puts the line on the clipboard. `tests/test_launcher.py`.
- [x] `P2` `feature` `@ai` **Check builds** — one button on the launchpad, reporting for
  every registered app whether what Launch would open is the newest thing available. Adds
  the case the tile's counter cannot see: a checkout with **uncommitted** changes, where
  the commit count still matches the build because it only moves on commit. Names the
  build script for anything out of date. A launcher bundle is never out of date and being
  dirty does not change that — it runs the source, so the edits are what opens.
  `tests/test_launcher.py`, `tests/test_apps_tab.py`.
- [x] `P2` `feature` `@ai` **Tiles say which build they would open, and whether it is
  stale.** `launcher.version()` follows the launch path: a frozen bundle answers with the
  `_build_info.json` stamped inside it, a launcher bundle (Sentinel, Imprint) with the
  checkout it runs, and an unstamped frozen bundle answers nothing — the checkout's number
  there would describe code that is not what opens. A frozen bundle behind its checkout
  shows `· N behind`, which is the question the number exists for: committing to a project
  does not rebuild it, and SONAR was five commits ahead of its installed app when this was
  written. The commit count is cached on `HEAD`'s mtime so the poll can re-read it without
  a subprocess per app per tick. `tests/test_launcher.py`, `tests/test_apps_tab.py`.
- [x] `P1` `bug` `@ai` **SONAR's headless agent made its tile read *Running* forever.**
  Fallout from the fix below: once the checkout's entry script became a marker, SONAR's
  launchd agent — `main.py --headless`, running around the clock — matched it, so the tile
  claimed the app was open even when it had been properly quit, and offered to raise a
  window that did not exist. Command lines carrying a `NO_WINDOW_FLAGS` flag are now
  skipped, and matching is per line rather than across the whole `ps` snapshot so one
  process's flag cannot discount another's. `--background` is deliberately excluded from
  that list: it is the whole app with its window hidden, which is how Lab Hub starts
  Backup Control Center and git_autosync, and calling those stopped would offer a Launch
  button that starts a second copy. Verified live, before and after, against the real
  agent. Note the *reported* symptom was not this: SONAR's close button hides to the menu
  bar, so the app genuinely was still running at the time. `tests/test_launcher.py`.
- [x] `P0` `bug` `@ai` **A running Sentinel showed as *Did not start*, and stayed that
  way.** Two faults, reported together. `running_marker()` matched the installed bundle's
  `Contents/MacOS` and nothing else, but Sentinel's bundle is a one-shot C stub
  (`SentinelLauncher`) that execs the project's python and exits — so moments after a good
  launch the only thing in the process table is `<project>/main.py`, and the tile called a
  visibly running app dead. `running_markers()` now returns bundle *and* entry script and
  matches either, which is also what survives the next change of launcher: this bundle has
  been a PyInstaller build, an applet and a C stub inside one month. Second fault: *Did not
  start* never cleared, because it only cleared on seeing the app run — so it outlived the
  app being opened and closed by hand. It is a notice about one launch, not a property of
  the app, so it expires after `FAILURE_NOTICE_SECONDS` and **Re-check** now clears it
  outright. Verified against the real `ps` table with Sentinel up.
  `tests/test_launcher.py`, `tests/test_apps_tab.py`.
- [x] `P1` `bug` `@ai` **Raising a launcher-bundle app did nothing.** Sentinel's
  `/Applications/Sentinel.app` is a compiled AppleScript applet that starts the real GUI
  as a separate process, so macOS registers two apps: the applet, which owns no window,
  and the python process, which does. `open -a` reaches the applet — busy inside
  `do shell script` and deaf to the reopen event — so *Bring to front* silently did
  nothing. `is_launcher_bundle()` spots one (its executable is `applet` rather than the
  app's name) and re-runs the entry script instead, letting the app's own
  single-instance guard hand off, raise the running copy and exit 0. A non-zero exit is
  reported with the tail of its output rather than swallowed.
- [x] `P2` `bug` `@ai` **A rebuild is required after a launched app is renamed.** Sentinel
  Fork became Sentinel on 2026-09-12 and its installer removed the legacy bundle by
  design; the Lab Hub installed twenty-one minutes earlier still had the old name
  compiled in, so the tile read *Source only* and looked like a fault in Sentinel.
  Rebuilding fixed it. Second occurrence of this shape (`Create & Publish` → `Imprint`
  was the first) — see SUGGESTIONS #11 for the structural fix.


- [x] `P2` `infra` `@ai` **Versioned `v<MAJOR>.<BUILD>`, shown in the app.** The arc
  lives in `VERSION`; the build is `git rev-list --count HEAD`, so it cannot be forgotten.
  `lab_hub/version.py` reads live git from a checkout and a `_build_info.json` stamped by
  `scripts/stamp_version.py` from a frozen bundle, and says `v2.???` rather than guessing
  when it has neither. Shown in the window title and on the Settings tab, and read by Lab Hub's tile so you can see which
  build its Launch button would open. Lab-wide scheme, same two inputs as the Lab Project
  Monitor.

## Build marker — follow-ups (2026-11-13)

- [ ] `P2` `infra` `@me` Push Hub `main` (merge `b6b7460`, 4 commits ahead of `origin/main`) and remove branch `claude/build-marker-tiles-1a353e` with its worktree `.claude/worktrees/priceless-chaum-7679b1`.
- [ ] `P3` `docs` `@ai` Lab root `AGENTS.md`: list `build_marker.py` among the root scripts (Monitor side of the marker, commit `40aa92a`).
- [ ] `P3` `feature` `@me` Spec decision 2: branch suffix ` (<branch>)` on checkout tiles. Unanswered; not built.

## Narrator converter — open (2026-09-30)

What the review of df9c356 found. The fix (1dc265b, wwds-dev/lab_hub#1) and its port to
Imprint are merged; still open are three pre-existing faults noticed on the way, one
decision, one check that needs the real machine, and the tidying that would let the two
copies be one.

- [x] `P1` `infra` `@me` **wwds-dev/lab_hub#1 merged** (2026-10-05) — the converter fixes and
  the corrected drift guard, merged in the same minute as Imprint's port so neither drift
  test was left failing. https://github.com/wwds-dev/lab_hub/pull/1
- [x] `P1` `infra` `@ai` **The port of 1dc265b is in Imprint** (2026-10-05, wwds-dev/imprint#1).
  Each copy keeps its own `OUTPUT_ROOT`, `DEFAULT_FORMAT`, `ON_SETTINGS_CHANGE` and CLI
  docstring path (the `LOCAL` list); Imprint's own drift test got the same fix, its converter
  tests follow the two signature changes (`text_to_audio()` takes `chapters` and no `text`;
  `write_chapter_metadata()` a title and no `total_chunks`), and Sourcery's one finding there
  — the audiobook panel and Reading Compass contract still refusing AZW3 — went in with it.
  With both mains checked out side by side, both drift tests pass. The standalone Audiobook
  Studio was retired into Imprint on 2026-09-30 and its repository archived, so
  wwds-dev/audiobook_studio#1, the same port for that copy, was closed unmerged (2026-10-06).
- [x] `P1` `bug` `@ai` **A chunk cut off mid-stream is no longer stitched into the finished
  book** (2026-10-05). Stop in the Narrator tab terminates the worker; if
  `response.stream_to_file` was half way through `chunk_57.mp3`, the bytes already streamed
  sat under the chunk's final name, `sync_manifest_with_files` trusted any non-empty file,
  and the next run merged a mid-sentence cut into a book it then reported as finished.
  Nothing said so — the same shape as the stale-chunk bug the drift guard exists for. The
  stream now goes to `chunk_57.mp3.part` and is renamed only once complete, so a cut leaves
  nothing a resume can mistake for done; a resume, cleanup and the stale-chunk sweep remove
  partials. A manifest from before this change is trusted only where it recorded a chunk as
  done, since a chunk it never recorded may be the one a stop cut short (at most the few
  finished since the last manifest save are redone). Pinned in Imprint's
  `tests/test_narrator_converter.py`; both copies.
- [ ] `P2` `feature` `@me` **Decide whether the Narrator tab should offer M4B.** The converter
  makes chaptered M4B behind `--format m4b`; the tab never passes `--format`, so Lab Hub is
  MP3-only by choice (df9c356). If yes: a format picker in `ui/narrator_tab.py`, `_validate`
  checking `ffprobe` as well as `ffmpeg`, the README's Narrator section saying so, and the
  argv covered in `tests/test_narrator_tab.py`. If no, nothing to do.
- [ ] `P3` `testing` `@me` **Check the chapter marks on one real M4B.** The review could not
  run ffmpeg. The marks are the summed `ffprobe` durations of the MP3 chunks, which is what
  the concat demuxer places each file by too; the one way they could drift is TTS chunks
  carrying LAME gapless tags, which trim audio the duration does not count. Narrate one short
  book to M4B and open it in Apple Books: the last chapter should start where its text does.
- [x] `P3` `bug` `@ai` **MOBI and AZW3 no longer leave `<stem>.converted.epub` beside the
  audiobook** (2026-10-06). `convert_mobi_to_epub` wrote into `book_out_dir`, which nothing
  cleared; it now writes into `temp_dir`, which `wipe_book_state` and `cleanup_after_success`
  already clear (the latter sweeps the EPUB by name too). Pinned in Imprint's
  `tests/test_narrator_converter.py`; both copies.
- [x] `P3` `bug` `@ai` **Inside the frozen app, the converter's subprocesses get the launch
  environment back** (2026-10-06). They inherited PyInstaller's: `DYLD_*` pointing at the
  bundle's libraries, and Finder's bare `PATH` without Homebrew, so a MOBI, or the merge
  itself, could fail in the bundle for a tool that is installed. `converter.py` now carries
  the same logic as `lab_hub/tools/convert/calibre.py` (it is vendored and cannot import
  `lab_hub.*`): `subprocess_env()` restores the linker variables from `*_ORIG` or drops them
  when frozen and adds `/opt/homebrew/bin` and `/usr/local/bin` to `PATH`; `find_tool()`
  looks on that `PATH` first and then in Calibre's app bundle under `/Applications` and
  `~/Applications`; and one `run_checked(cmd, what)` replaced the three copies of
  run-a-subprocess-and-raise, so ebook-convert, ffprobe and ffmpeg all run with that
  environment and fail with the same error shape. The Narrator tab's own ffmpeg check in
  `_validate` looks on the same `PATH`, since it gated the converter behind the same bare
  one. Pinned in Imprint's `tests/test_narrator_converter.py`; both copies.
- [ ] `P3` `design` `@ai` **The resume policy as an argument, not a per-copy constant.**
  `ON_SETTINGS_CHANGE` is the one line of real code the drift test has to be taught to look
  away from, and the `REFUSE` branch ships dead in both copies now that Audiobook Studio, the
  one copy that refused, is retired. An `--on-settings-change {rebuild,refuse}` flag (default
  `refuse`; the Narrator tab passes `rebuild`) makes both files identical. Cost: Imprint's
  front-end must pass it too, and a `refuse` default changes what a plain CLI run does in
  both copies, which is why the frozen-app port (2026-10-06) went without it. Decide the
  default first; with `rebuild` as the default nothing changes for anyone and the flag is
  only an addition.
- [ ] `P3` `testing` `@ai` **The drift guard is itself a vendored copy, and guards one pair.**
  `SELF` is hand-set and `LOCAL` hand-kept, so copied into Imprint there are two of it that
  can drift. Derive `SELF` from `__file__`, and turn `_normalised` and the compare into
  a table of `(mine, theirs, local)` so the other vendored pair the docstring names —
  `lab_hub/tools/convert/{calibre,formats,jobs,runner}.py` against `toolbox/convert_epub` —
  is guarded the same way. Those four headers say "keep the two in step"; nothing checks.
- [ ] `P3` `feature` `@ai` **A format switch could remux instead of re-narrating.** M4B is an
  AAC re-encode of the same MP3 chunks, so an existing `Book.mp3` could become `Book.m4b` for
  no TTS spend — if the chunk durations survived `cleanup_after_success` (keep
  `chapters.ffmeta`, or the durations in a retained manifest). Today the run warns and
  narrates the book again.
- [x] `P3` `bug` `@ai` **Two conversions of the same book at once no longer corrupt each
  other** (2026-10-06). Nothing locked a book's output folder: two runs shared
  `manifest.json` and the chunk names, so each could publish or delete the other's work (the
  CLI and the tab, or two tabs, on the same book). `narrator.lock` beside the manifest now
  holds the pid of the run that owns the folder, created with `O_EXCL` so of two runs
  starting together only one wins; a second run is refused before it reads the text, with
  the lock's path in the message. A lock whose pid is gone was left by Stop in the tab or a
  crash and is taken over; one that holds no pid is left for a human, since it cannot be told
  from one a run is still writing. Raised by Sourcery on wwds-dev/imprint#2. Pinned in
  Imprint's `tests/test_narrator_converter.py`; both copies.
- [x] `P3` `infra` `@ai` **Four pre-existing lint warnings in `converter.py`** (2026-10-06) —
  two f-strings without placeholders (`F541`), one long line (`E501`) and one missing blank
  line before `def convert` (`E302`), left alone in 1dc265b so the review diff stayed
  minimal. Fixed with the frozen-app port; `flake8 --max-line-length=120` is clean on both
  copies.

## Theme overhaul — open (2026-10-12)

- [x] `P1` `design` `@ai` **Graphite (dark) and Paper (light) themes, with a switch.**
  Dark mode is Graphite (borderless cards, sidebar, one mint accent); light mode is
  Paper (warm off-white, hairlines, no accent colour, black pill buttons). Mockups
  agreed 2026-10-12. Add a Settings switch — System / Light / Dark — that applies live
  and persists in the config; System stays the default. Done 2026-10-12: palettes,
  stylesheet and painted glyphs in `ui/theme.py`; `theme.apply` re-themes at runtime and
  follows macOS while on System; `Settings.theme`; `tests/test_theme.py`.
- [x] `P1` `design` `@ai` **Sidebar navigation** replacing the top tab row and the
  Tools sub-tab row; one primary action per view; quieter tiles (one status pill,
  secondary actions in a menu); a spacing and type scale kept only in `ui/theme.py`.
  Done 2026-10-12: `ui/sidebar.py` drives two `QStackedWidget`s (Tools pages fold out
  under Tools), Refresh in its footer; swipe and refresh-on-show unchanged. Tiles are
  quieted by stylesheet only — one status pill/dot, a tile's Launch/Open as a quiet
  button, its other actions as text — so the filled primary is the one per view.
  Not done: secondary actions moved into a menu (left for the shared tile base).
- [x] `P1` `infra` `@ai` **Structure.** Split `lab_hub/launcher.py` (registry / status /
  launch); app list in a data file or auto-scanned, so Refresh finds new apps without a
  rebuild; one shared tile base for `AppCard` and `LinkCard`; a single `Refreshable`
  interface so `MainWindow.refresh_all` stops enumerating tabs. Done 2026-10-12:
  `lab_hub/launcher/` (`registry` / `state` / `control`), `lab_hub/apps.toml` re-read on
  Refresh, `ui/tiles.py` (`Tile`, `TilePage`, `Refreshable`); per-tab Re-check removed.

## v3 — later

- [x] `P3` `testing` `@ai` **Code-level readiness audit (promises vs code).** Check every promise in the
  README and `docs/foundry/app-context.md` against the code (launcher, Land, self-update, narrator
  converter); classify each Delivered / Narrower / Stub; findings to `docs/audit/` and this file. Own
  chat, Opus high, ~30–60 min. Requested 2026-11-18 after the lab-wide doc sweep.
  - Done 2026-11-18: `docs/audit/2026-11-18-readiness-audit.md` (1 Blocker, 3 High, 9 Medium, 8 Low). New items below under "Readiness audit 2026-11-18".


- [x] `P0` `bug` `@ai` **Land: stop a branch that already contains a folder link (follow-up to `land-update-gaps`, 2026-11-17).** Landed 2026-11-20 (spec `docs/specs/land-folder-link-guard.md`; Define and Architect approved by the owner, "Approve and land" also covers the widening to plain files). Every merge, Claude merge, prep switch and pull is checked before the main checkout moves; tests `tests/test_land_folder_link_guard.py`; reviews `docs/audit/land-folder-link-guard-code-review.md`, `-security.md`. Full suite green offscreen. Not done: Lab Hub rebuild, a real Land on the Mac.
  - Audit 2026-11-18 (B1): release blocker. Also cover `claude_resolve.py:1289` (`merge --ff-only`) and prep's `git switch` (`land_resolve.py:705`), not only `repo_tidy.apply`'s merge (`:919-924`).
  - Why: Land no longer commits a `.venv` symlink itself (6d04df6). But a link an agent committed on its own branch (`git add -A`, with only `.venv/` in `.gitignore`) still lands. Updating the main checkout then replaces the real, ignored `.venv` with the link, which is the SONAR data loss of 17 Nov.
  - Idea: an outgoing check next to `outgoing_findings` in `lab_hub/land_resolve.py`. It stops a branch whose diff adds a symlink (mode 120000) where the target checkout has a real folder, or a name the default branch ignores as a folder. Reuse `never_commit_link` / `ignored_as_folder`.
  - Start: Define a new spec (owner gate). Context: `docs/specs/land-update-gaps.md` §10.1, `docs/audit/land-update-gaps-code-review.md` P2-2. Suggested setup: Opus, high, about 60–90 min.

- [ ] `P2` `security` `@ai` **Land: the Claude Code cost notice can understate what a run sends (2026-11-18).**
  - Source: security review P2-1, `docs/audit/land-pick-and-time-security.md`. Older than `land-pick-and-time`; not caused by it.
  - Why: the confirmation's cost comes from the plan (`lab_hub/land.py:193-197` `LandPlan.cost`, `:360-388` `claude_panel`). At run time, a plain merge that turns into a conflict is re-planned as a Claude merge (`:599-602`, `:620-624`), and `triage()` reads the live `unlanded` (`:660-665`). A repo with Claude available and only plain merges shows no Claude pill and no panel, yet can send conflicted files (up to $3) or a branch's log and diff (up to $0.50) to Anthropic, and "at most $X in total" can be exceeded.
  - Options (owner picks at Define): count every plain merge as a possible Claude merge and triage when `plan.claude` is set ("up to"); or show a fixed line that a merge turning into a conflict may use Claude Code; or enforce a run-time ceiling equal to the disclosed total.
  - Start: Define a new spec (owner gate). Suggested setup: Opus, medium, about 30–60 min.

- [ ] `P2` `bug` `@ai` **Land window: some step times are never saved, so it stays on "Estimating…" (2026-11-18).**
  - Found while defining `land-pick-and-time` (gap in `progress-windows`).
  - Why: `lab_hub/durations.py:43-46` `KINDS` lists only the seven `repo_tidy.Action` kinds and the build stages. Land's prep and archive steps (`rescue`, `untracked`, `switch`, `archive`; mapped to stages in `lab_hub/progress.py:104-105`) are refused by `record()` and dropped by `load()`. Every run with a prep step therefore has a step with no history, and the time left reads "Estimating…" throughout (owner's build-199 screenshot, "0:05 elapsed · Estimating…").
  - Fix: add the four kinds to `LAND_KINDS`, with a test that a finished `untracked` step is recorded and estimated next time; check that `progress-windows` §8.4's whitelist text still holds.
  - Start: a small change in `progress-windows` (no new spec expected). Suggested setup: Sonnet, medium, about 15–25 min.

- [ ] `P3` `security` `@me` **Decide: remove the real-lab Land confirmation screenshots from git history (2026-11-17).**
  - Why: commits `4072f72` and `b2c0ab5` added `docs/specs/land-confirm-dialog-screenshot*.png` taken on the real lab, showing repo names and local process names (`gk`, `node`, `zsh`, `claude`) and counts. No paths or usernames are shown. `d87d2f2` replaced them with demo data, but the old images stay in the public repo's history (security review P2-1, `docs/audit/land-confirm-dialog-security.md`).
  - Decision (owner): accept the exposure, or rewrite `main` (for example `git filter-repo --path docs/specs/land-confirm-dialog-screenshot.png --path docs/specs/land-confirm-dialog-screenshot-light.png --invert-paths`, then re-add the demo PNGs and force-push). A rewrite changes every commit hash after `4072f72`: every clone, worktree and open branch has to be re-synced. Do it while no other session is working in `lab_hub`.
  - If rewriting: Sonnet, medium, about 20–30 min, with every other lab_hub session stopped first.

- [x] `P1` `feature` `@ai` **Provisio and SYNDUSTRYX on the Apps tab; new Websites and
  Dashboards tabs** (2026-10-07). Provisio is a *web app* tile: Launch starts its local
  server through a login shell with the absolute entry path, `ui/web_open.py` opens
  `localhost:5173` once it answers, *Running* means the address answers, **Open in
  browser** replaces Bring to front, and **Stop** ends a server Lab Hub can recognise
  (process group, so `workerd` goes too). Headroom stays inside it — no tile. SYNDUSTRYX
  (the Antfarm workstation, working name) is linked in as `active/syndustryx`; its bundle is
  found in `dist/` (`bundle_dir`, state *Built*) and its checkout is never run
  (`runs_from_source=False` — `server.py` would take the Monitor's port). **Websites**
  (altmerch.store, bookadatewithme.com) checks each site with a non-blocking `HEAD`;
  **Dashboards** is the lab's `dashboard_catalog.json`, re-read when it changes. Both carry
  Re-check, on-screen-only polling, swipe, Settings refresh and a menu bar submenu.
  `--selftest` fails a build with no TLS backend. `tests/test_launcher.py`,
  `test_apps_tab.py`, `test_sites.py`, `test_dashboards.py`, `test_links_tab.py`,
  `test_tray.py`, `test_tab_groups.py`. *The Provisio half was superseded the same day:
  see the next item.*
- [x] `P1` `feature` `@ai` **Provisio's tile launches its native app** (2026-10-07).
  Provisio became `/Applications/Provisio.app`, a window with its own server and a
  Demo/Real workspace switch (`provisio/docs/DESKTOP.md`). The tile launches it like
  Imprint's and must not start the browser-mode server: vinext allows one dev server per
  checkout. The web-app support stays, unused. `--selftest` now probes Provisio's venv
  ("a real Qt child starts").
- [x] `P1` `infra` `@ai` **Rebuild and reinstall Lab Hub** with the new Provisio tile.
  Done 2026-10-07 17:58: the installed bundle is v2.075, stamped from `ff8a26b`, which
  includes the tile change (`ee33ea7`); its `--selftest` probes Provisio as a Qt app,
  which only the new tile does. Checked 2026-10-09.
- [x] `P2` `design` `@ai` **Tools as tiles** (2026-10-07). The Tools tab opens on *All
  tools*: built-in tools as tiles with their state (*Running*, *Needs Calibre*, *Built
  in*) and an Open that moves the tab strip; Unblock Tracker and Backstage as the Apps
  tab's own `AppCard`. Same grid, Re-check and poll as the other tile pages.
  `ui/tools_tab.py`, `tests/test_tools_tab.py`.
- [x] `P3` `docs` `@ai` **Dashboards catalog trimmed** (2026-10-07): the Antfarm
  workstation concept (file moved to the Trash) and Provisio · Protection Studio, the
  hosted copy of the app now on the Apps tab. The hosted deployment itself was left
  alone — see the next item.
- [ ] `P3` `infra` `@me` **Decide whether to keep Provisio's hosted copy** on ChatGPT
  Sites (`provisio-protection-studio…chatgpt.site`, private). It only ever shows the demo
  workspace, and the native app's real workspace never touches it (`provisio/docs/
  DESKTOP.md`), so deleting it does not break the app. It is also the only copy reachable
  away from this Mac. Deleting it is done in ChatGPT and cannot be undone. Keep
  `.openai/hosting.json` either way: Provisio's Vite config imports it, so the build
  fails without it.
- [x] `P2` `feature` `@ai` **SYNDUSTRYX identity applied end to end (2026-10-10).**
  Owner selected the name; active source, executable/icon/bundle, deployment defaults,
  `active/syndustryx` link and compiled Lab Hub registration now match. Preserve
  old records/credentials through explicit migration readers and path compatibility.
- [ ] `P2` `bug` `@me` **bookadatewithme.com answers 404.** Netlify serves the domain with
  no site deployed behind it (checked 2026-10-07); the Websites tile reports it as *Error
  404*. Redeploy from `~/Documents/lab/websites/bookadatewithme` or point the domain elsewhere.

- [x] `P2` `feature` `@ai` **Trackpad swipes change tab** (`ui/swipe.py`). macOS sends a
  two-finger page swipe as a horizontal scroll (`QEvent.Wheel`) and a three-finger one as
  `QEvent.NativeGesture`; both are handled, because which one an app sees is a System
  Settings choice. Note the macOS default gives the three-finger horizontal swipe to
  *Swipe between full-screen apps*, so the window server eats it and no app ever sees it —
  two fingers is what works out of the box. Innermost tabs move first, so a swipe inside
  Tools moves between the tools and only falls out to the window's tabs when they run out;
  no wrap-around; a sideways-scrolling table (the Narrator library) keeps the gesture for
  itself. One gesture is one tab, momentum included. `tests/test_swipe.py`, mutation-tested.


- [x] `P2` `design` `@ai` **Tools dropped from the sidebar; the overview is the way in.**
  The sidebar no longer lists each tool under Tools: clicking Tools opens *All tools* and its
  tiles open each tool, and clicking Tools again returns to the overview. Supersedes the
  "fold out under Tools" wiring in the theme-overhaul and Tools-as-tiles items above.
  `ui/main_window.py`, `ui/tools_tab.py`, `tests/test_sidebar.py`, `tests/test_tools_tab.py`,
  `tests/test_tab_groups.py`.
- [x] `P2` `feature` `@ai` **A vertical two-finger swipe changes page too.** The pages run
  down the sidebar, so a swipe up moves to the next page as scrolling would; a page that can
  scroll vertically keeps the gesture and scrolls, mirroring the sideways-table rule.
  `ui/swipe.py`, `tests/test_swipe.py`.
- [x] `P2` `design` `@ai` **Tiles on a page are levelled to the tallest, buttons pinned to the
  card's bottom edge.** A grid only levels within a row, so `TilePage.equalise()` re-levels
  across rows on resize and after each refresh's layout change. `ui/tiles.py`.
- [x] `P2` `bug` `@ai` **The selected sidebar icon no longer vanishes.** Nav icons are
  registered for Active and Selected modes as well as Normal (Qt's generated pixmap for a
  missing mode is tinted with the highlight, invisible on the dark sidebar), and `theme.apply`
  sets the chosen palette before the repaint that asks for the icon colours. `ui/theme.py`.

- [ ] `P2` `feature` `@ai` Read each project's `TODO.md` and show an open-item count next to its launch button
- [ ] `P2` `feature` `@me` Decide whether Ebook Converter deserves a tile — its job is
  already the embedded Convert Textfiles tab, so a launch button would be a second door to
  the same thing. Left off for now.
- [x] `P3` `infra` `@me` **Stale bundles pruned** (2026-09-12, by hand): `Sentinel AI.app`
  (project archived), `Create & Publish.app` (renamed to Imprint), `vidforge.app`
  (Imprint imports the same pipeline as its Video mode) and `VPN Agent.app` (stale, and
  a second door to an agent that belongs inside Sentinel). None was referenced by a
  LaunchAgent, and no source was touched: VPN Agent rebuilds from
  `sentinel/agents/vpn_agent/build_app.sh`, vidforge from its own repo, and
  Sentinel AI is archived but fully pushed to GitHub.
- [ ] `P3` `feature` `@ai` Global search across every project's docs from the hub
- [ ] `P3` `feature` `@ai` Per-app last-launched timestamp and crash count
- [x] `P2` `design` `@ai` Load the app registry from a file rather than compiling it into
  the bundle, so renaming a launched app does not need a Lab Hub rebuild to stop the tile
  reading *Source only*. SUGGESTIONS #11. Shipped 2026-10-12 as `lab_hub/apps.toml`, read
  from the checkout and re-read on Refresh (fe23a21).
- [x] `P2` `bug` `@ai` **The Check builds report dialog could not be dismissed.** A
  `QMessageBox` whose only buttons are `ActionRole` (Copy commands / Copy and open
  Terminal) has nothing to map the red close button or Escape onto, so both were dead
  ends. Added an explicit `Close` button (`RejectRole`, also the escape/default button).
  `tests/test_apps_tab.py::test_build_check_dialog_can_be_dismissed`.
- [x] `P1` `testing` `@ai` (2026-11-18 audit: they pass; they now assert the suite placement) Update the tests that still pin Backstage as Tools-only: `test_registry.py` (suites list, `tools_only == ["backstage"]`), `test_tab_groups.py`, `test_tray.py`, `test_tools_tab.py`. 31dbb9d moved it to `suites`; by reading, these now fail (suite not run 2026-10-19).
- [ ] `P2` `feature` `@me` Confirm Backstage on the Apps tab and in the menu bar is wanted: 31dbb9d reverses the 2026-09-27 choice to keep it Tools-only.
- [ ] `P3` `design` `@ai` Remove the leftover Backstage page from the Tools stack (`MainWindow.backstage_tab`, now empty) and the stale Backstage mentions in `ui/tools_tab.py` hint/docstring and `ui/apps_tab.py:584`.
- [ ] `P2` `bug` `@ai` WWDS Websites tile: a `file://` URL has no HTTP status, so `classify()` reports *Unreachable*; show *Local file* / *File missing* instead, and drop the hard-coded `/Users/as` path.
- [ ] `P2` `infra` `@me` Review and commit the uncommitted `dock.order_out` ghost-window fix on branch `fix/close-ghost-window` (`ui/dock.py`, `ui/main_window.py`, `tests/test_window_lifecycle.py`).
- [ ] `P3` `infra` `@ai` Rebuild and reinstall Lab Hub: the bundle is stamped from bbf1077 (v2.094), and `sites.py` (WWDS) is compiled in, unlike `apps.toml`.
- [ ] `P2` `docs` `@ai` Fill `docs/foundry/app-context.md` (still the Foundry skeleton) from the README; the owner signs off the Invariants.
- [ ] `P3` `infra` `@ai` Run `/harden lab_hub` to wire CI, ruff ratchet, gitleaks and dependabot from `docs/foundry/tooling/`; branch protection and the git hook stay with the owner.

## Readiness audit 2026-11-18 — open

From `docs/audit/2026-11-18-readiness-audit.md`. Items already in this file (folder-link Land stop, WWDS `file://` tile, app-context skeleton, `/harden`, Backstage decision, old screenshots) are not repeated.

- [x] `P0` `bug` `@ai` **Land: don't commit another live session's edits (audit H1).**
  - Why: "a process inside" is only an `lsof` cwd inside the tree (`land_resolve.py:487-530`); a session working from `~/Documents/lab` or a lab-root worktree is invisible, so prep commits its half-done files (`land_resolve.py:645-650`, `repo_tidy.py:927-932`) and Land pushes them. `cc56bb6`/`9e669a1` here are Land's own "commit open work" commits.
  - Idea: busy when files changed in the last N minutes or a `claude` process's folder is an ancestor; list the files to be committed in the confirm dialog. Start with Define (owner gate).
  - Status 2026-11-20: Define draft written, `docs/specs/land-live-session-guard.md` on branch `claude/land-live-session-guard` (pushed). It waits for the owner's Define gate (four decisions; recommended: 15 minutes quiet time, main checkout included, no override, no exception list in slice 1). Build has not started.
  - **Done 2026-11-20 (slice 1; owner: "Approve as recommended"):** Land and Resolve leave a checkout or worktree alone while a changed or new file in it was modified in the last 15 minutes, the main checkout included (`repo_tidy.settling`, spec `docs/specs/land-live-session-guard.md`). 29 tests, full suite green, 20 of 23 mutants killed (3 equivalent), independent review with no P0/P1 (spec §10). Not built or installed: the installed Lab Hub gets it with the next Update now.
- [ ] `P2` `bug` `@ai` **Land's quiet-time rule reads only a file's modification time** (review P2-3, spec land-live-session-guard §8): `cp -p`, `rsync -t`, `tar x` or a move from outside the repo keep the old time, so such a fresh file is not seen as fresh. Compare the inode change time as well, and decide what to do about stops after `chmod`.
- [ ] `P3` `feature` `@ai` **Land live-session guard, slice 2** (after `land-pick-and-time` ships): list the files Land will commit in the confirmation, a per-repo "Land anyway", and a per-repo list of paths the rule ignores if a repo turns out to be stopped every time by a file that rewrites itself.
- [ ] `P1` `security` `@me` **Decide: real-lab images and `/Users/as` paths in the public repo (audit H2).**
  - `docs/audit/progress-windows-real-builds.png` (`1272be9`, shows `/Users/as/Releases/...` and every app version) and `progress-windows-real-land.png` (private repo names); `/Users/as` in README, TODO and five audit/spec docs.
  - Make `wwds-dev/lab_hub` private (then tier `internal`), or remove them and decide on a history rewrite together with the older screenshot item.
- [ ] `P2` `bug` `@ai` **Apply the 24-hour recent-use rule to every linked worktree, not only `.claude/worktrees/` (audit M1).** `repo_tidy.py:40, 437-445`; lab-root `worktrees/` session trees can be removed or archived while their session idles.
- [ ] `P2` `docs` `@ai` **Say what "up to date" means on the Lab Hub row (audit M3).** It is level with the local checkout, never origin (`self_update.py:154-188`); add the note, or warn when `@{u}` is ahead without fetching.
- [ ] `P2` `bug` `@ai` **Make `build_app.sh --install` safe (audit M4).** `rm -rf` then `cp -R` with no rollback or running check (`build_app.sh:79-83`); refuse while Lab Hub runs, or reuse the self-update helper.
- [ ] `P2` `testing` `@ai` **Add an `appkit_guard.py` drift test (audit M5).** Lab rule requires one per repo; compare code with docstrings stripped, like `tests/test_converter_drift.py`.
- [ ] `P2` `bug` `@ai` **Video job: let Stop end ffmpeg so quit cannot abort the app (audit M6, unconfirmed).** `subprocess.run` in `lab_hub/tools/video.py:132` outlives `JobWorker.wait(15000)`; register the process as `calibre.py:157-175` does. Do not raise the wait.
- [ ] `P2` `performance` `@ai` **Move the Check builds report off the UI thread (audit M7).** `show_build_report` runs `worktree_tree` (`git add -A` + `write-tree`, 60 s timeouts) per dirty checkout synchronously (`ui/apps_tab.py:771-779`).
- [ ] `P3` `bug` `@ai` **Land hardening (audit L1-L3).** Merge/switch in the main checkout under `NETWORK_TIMEOUT`, not the 30 s `GIT_TIMEOUT` (`repo_tidy.py:42, 919`); `REGENERABLE` to match top-level names only (`repo_tidy.py:215-238`); say in the Review-branches dialog that it overrides the recent-use guard (`:1040-1044`).
- [ ] `P3` `bug` `@ai` **Scrub `QTWEBENGINE*` in `child_env` (audit L4).** `lab_hub/launcher/control.py:43-70`.
- [ ] `P3` `infra` `@me` **Decide: bundle ID `com.netrunner3000.labhub` (audit L6).** `build_app.sh:14` names the retired identity; changing it resets TCC/LaunchServices.
- [ ] `P3` `docs` `@ai` **Refresh stale docs (audit M2, L7, L8).** `lab-wide-build-marker.md` and `release-root-behind.md` statuses; README:869-872 "expected to fail" Backstage note; app-context's "no `LICENSE`" evidence; the duplicate Backstage-leftover items in this file; delete tracked `_to_delete/`.

## Land network preflight — follow-ups (2026-11-21)
- [ ] `P3` `design` `@me` Offline, a repo whose only work is local cleanup (delete landed branches, quarantine an untracked file) is now stopped by the preflight, as a merge is. Decide: stop it too (as built), or skip the check when the plan has no merge or push. Spec `land-network-preflight` §3, review P3-3.
- [ ] `P3` `design` `@ai` Every `ls-remote` failure gets "cannot reach origin (no network?)", so a dead or renamed `origin` blocks Land with no override. Tell a missing remote apart from a network drop, or point to the Land log. Review P3-4.

## apps-discovery — review follow-ups (2026-11-21)

From `docs/audit/apps-discovery-review-core.md` and `-ui.md`; the P2s and the listed P3s were fixed (see `git log`). Left, none blocking:

- [ ] `P3` `bug` `@ai` README titles: `# C#` reads as "C" (`discovery._heading` `rstrip("#")`); markdown, quotes and bullets are shown raw in the summary (core P3-1, P3-2).
- [ ] `P3` `bug` `@ai` Two tiles can still carry one name (`merge_local` has no name rule); a hand-written local entry with a `build` command and an installed app's name would trash that app on Update now (core P2-2, residual; `add` never writes `build`).
- [ ] `P3` `design` `@me` Wording the owner has not approved or that overlaps: " · behind" with no count, and the behind fact said twice on Lab Hub's tile; "A newer build is ready to install" for a held row; Lab Hub's tile has no name tooltip (UI P3-5).
- [ ] `P3` `bug` `@ai` Show again: put the folder name in the row's tooltip (two READMEs with one heading look identical) and say so when a rescan will not suggest it (UI P3-4).
- [ ] `P3` `testing` `@ai` No test for `aboutToQuit.connect(self._own_verdict.shutdown)`; a double-click on "Add to Apps" is Verify's to try on the Mac (UI P3-6, Not verified).
## Land blocker actions (2026-11-21)
- [x] `P1` `feature` `@ai` **Every Land stop says what clears it: Ask Claude…, Try again or Close it… (2026-11-21).**
  - Spec `docs/specs/land-blocker-actions.md` (owner: "Approve defaults"). Build note `docs/audit/land-blocker-actions-build.md`.
  - Why: "'merge by hand' is a real blocker, since I don't know which prompt would resolve that".
  - Code: `lab_hub/land_resolve.py` (`STOP_ACTIONS`, `clearing`, `close_processes`), `land.py`, `claude_resolve.py`, `handoff.py` (`blocker_goals`), `progress.py`, `ui/progress_window.py`, `ui/lander.py`, `ui/apps_tab.py`; tests `tests/test_land_blocker_actions.py`.
  - Not done: owner merge and rebuild; one owner-watched Ask Claude run on syndustryx's `.claude/settings.json` conflict (spec §2.2), ending in "Landed" or a different, named stop.
- [ ] `P3` `bug` `@ai` "land it by hand (Review branches → Open in Terminal)" is still the skip reason when Claude Code is missing or a repo has no test command (`repo_tidy._claude_blocker`). Not a Land stop; Ask Claude… cannot help without Claude Code either.
- [ ] `P3` `test` `@ai` The §2.1 check scans only for banned words: a raw git or gitleaks error passed through `plain_reason` ends in no clearing sentence and relies on the Ask Claude… footer (QA `docs/audit/land-blocker-actions-verify.md` P3-8).
- [ ] `P3` `process` `@owner` `app-context.md` `## Commands` and `## Test bar` are still placeholders, and the venv has no coverage, `pytest-timeout` or `pytest-randomly`: branch coverage, random order and timeouts are not verified (QA P3-9).
- [ ] `P3` `test` `@ai` `test_land_resolve.py::test_a_file_that_appears_after_the_preview_is_not_committed_and_land_says_not_landed` fails with a long pytest temp path: the reason is cut at 180 characters before "untracked" (QA P3-10; pre-existing, commit `3cd5dd7`).

## Out of scope, deliberately

Lab Hub does not replace the projects it launches. Each keeps its own repo, README, venv and build script. Changing what Sentinel AI does still means changing Sentinel AI.
