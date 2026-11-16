# Spec: when an app runs a release clone that is behind, the Build check says to move the clone, not to re-run the installer

Status: **Built 2026-11-16 on claude/release-root-behind, not yet merged.** Define approved by the owner 2026-11-16 ("Approve"), all three recommendations in §5. Phase: Define (`product-manager`). Drafted 2026-11-16 in `lab_hub`.
Nothing built. In-flight check (`session_start.py --inflight`, 2026-11-16): `update-now-terminal` (document done, merged to `main`, not released) is the spec this builds on: it owns `run_updates` and `run_in_terminal`, and this spec changes what they are handed for one kind of app, not how they work. The others (`lab-wide-build-marker`, `land-from-tiles`, `repo-tidy`, `tile-resolve`) do not touch `build_status`.

## 1. Problem and evidence
After Update now was changed to open Terminal for Provisio (2026-11-16), the owner pressed it and the tile did not go current, for this reason (read from the code and checked on the real Mac the same day):
- Provisio's installed bundle runs a release clone, `~/Releases/provisio` (recorded in `project_root.txt`, `state.py:88`). The tile is "behind" when that clone is behind the working checkout (`_recorded_root_version`, `state.py:899`; `_build_status`, `state.py:1234`).
- The command Lab Hub offers is `cd ~/Releases/provisio && ./scripts/install_app.sh` (`build_status`, `state.py:1160-1162`). That installs from the same clone, so it rebuilds the stale build. On 2026-11-16 the clone was 11 commits behind `origin/main`; only moving it forward (`docs/RUNBOOK-release.md` §2 steps 2-5, no installer run) made the tile current.
- `update-now-terminal` made it worse: one click now opens the installer, which looks like the fix and is not. The note under the app does say "Follow ...RUNBOOK-release.md first", but the command does not do what the runbook's step 3 does.

## 2. User and success measure
User: the owner, on the Apps page.
1. For an app that runs a root other than the working checkout and whose root is behind, the Build check **names the real step**: "its release clone <root> is N commits behind; move it forward first (runbook §2), the installer will not change it" (test: fixture with a root behind its source).
2. For that app, **Update now does not open the installer** and the command list shows the clone-forward command instead, copyable: `git -C <root> fetch origin && git -C <root> merge --ff-only origin/main` (never `--force`, never a merge commit; test asserts the exact string and that no installer command is listed).
3. Lab Hub runs nothing in the release clone itself and opens no Terminal for it (see §5.1).
4. When the root is level with the source, behaviour is unchanged: the by-hand installer is offered and Update now opens Terminal as shipped in `update-now-terminal` (existing tests still pass).
5. Other apps' rows and commands are unchanged (test over the full registry fixture).
6. After the owner has moved the clone, Refresh shows the tile current (verified once by hand on the real Mac; the owner did exactly this on 2026-11-16).

## 3. Scope
- `lab_hub/launcher/state.py` `build_status`: for an app with `version.root` set and `needs_rebuild`, replace the installer command with the clone-forward command and say why in the note; keep the installer command only when the root is level.
- `ui/apps_tab.py` `show_build_report`: such a row is neither an in-app command nor a by-hand installer; it is listed under its own heading and its command is copyable. It adds no Update now by itself.
- Tests in `tests/test_launcher.py` and `tests/test_apps_tab.py`; README, TODO.

## 4. Non-goals
- No automatic fast-forward, no git operation on a release clone by Lab Hub (it is a release root: CI and legal gates come first, `docs/RUNBOOK-release.md` §2 step 1, and those are the owner's).
- No change to how "behind" is measured, to `lab-wide-build-marker`, or to any other app.
- No change to the installer's own checks or to Provisio.

## 5. Decisions for the owner
1. **Show the command or run it.** Recommend **show and copy only**, as in §4: the clone is a release root and the runbook puts a CI-passed commit and the legal check before moving it. Alternative: **Copy and open Terminal** (paste-only, as today for other commands), still no run.
2. **Which commit the command moves to.** Recommend `origin/main` as the copyable default, with the note "the runbook wants a commit that passed CI: use its sha instead if you have one". Alternative: show only the template `--ff-only <sha>` and no default.
3. **When it applies.** Recommend any app whose bundle records a root other than the working checkout (today only Provisio). Alternative: name Provisio in the code; recommend against, since the rule is about the root, not the app.

## 6. Risks
- Lab Hub cannot know that the clone is also behind `origin/main` (that needs a fetch); the Build check says "behind the source" and the command fetches first. If `origin/main` is not where the source went (an unpushed working checkout), the move changes nothing: the note says to push the source first.
- The wording must not read as an instruction to skip the runbook's gates: it names them.
- `update-now-terminal`'s tests and `show_build_report` are in the same function; this is the one place two specs overlap, so it builds after that spec is released or merged (it already is on `main`).

## 7. Phases to run
Define (this file, **GATE**), Architect (module boundary only, none expected), Plan, Build, Review (independent), Verify, Document. Secure skipped: no new file write, network or executable content (the command is displayed, not run); say so in the review note. Comply skipped: tier `public`, no new claims. Radar check skipped: no new tool.
