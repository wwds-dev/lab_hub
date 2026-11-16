# Spec: a Resolve button on each app tile that has work to land

Status: **Superseded 2026-11-16 by `land-from-tiles.md` (owner approved); do not build.** Phase: Define (`product-manager`). Drafted 2026-11-16 in `lab_hub`.
Nothing built. In-flight check (`session_start.py --inflight`, 2026-11-16): `repo-tidy` (document done 2026-11-16, not released) is the spec this extends. It owns `repo_tidy`, `CleanupDialog` and `ReviewDialog`; this spec changes none of their behaviour and builds after it is released or merged, by whichever session owns `repo-tidy`.

## 1. Problem and evidence
The owner asked (2026-11-16) why a tile with the yellow badge ("2 unpushed commits · 1 commit behind · 2 branches to land") has no button to commit, push or merge. Today:
- The badge is read-only (`ui/apps_tab.py` `refresh_hygiene`, tooltip: "Commit, push or merge it, or press Check repos").
- Acting is possible only through Check repos, then **Resolve…** in its dialog (`ui/apps_tab.py` `show_repo_report`), which works on every repo at once.
- `CleanupDialog(repos, parent)` (`ui/repo_tidy_dialogs.py:81`) already takes a list of `(name, path)`, and `tidy_repos` builds it from the whole report. A single-repo call needs no new logic.

## 2. User and success measure
User: the owner, on the Apps page.
1. A tile whose hygiene row needs attention shows **Resolve…** beside Launch. A tile with nothing to land shows none.
2. Pressing it opens the existing Resolve dialog planned for that one repo only: its preview lists actions for that repo and no other (test on a fixture lab with two dirty repos).
3. After Apply, that tile's badge and the page's report refresh on their own, as after the bulk Resolve (screenshot: badge before and after on the real lab).
4. The dialog, its guards, the preview and the Stop button are the existing ones; no second code path (a test asserts both entry points build the same plan for the same repo).
5. The button never appears for an app whose repo is not in the hygiene report, and is disabled while a bulk Resolve or Check repos is running.

## 3. Scope
- `ui/apps_tab.py`: `AppCard` gets a Resolve button; `AppsTab` handles its signal by calling `tidy_repos` with a one-row list.
- Tests with the existing fixture-repo helpers; no mocks of git.
- README and CHANGELOG/TODO.

## 4. Non-goals
- No new git operations, no per-action buttons (Commit, Push, Merge) and no change to what Resolve is allowed to do (`repo-tidy` §5 guards stay).
- No change to Check repos, Review branches or the badge text.
- No push without the dialog's preview.

## 5. Decisions for the owner
1. **One button or three.** Recommend one: **Resolve…**. Separate Commit, Push, Merge buttons would each need their own guards and would skip the preview that makes Resolve safe. Alternative: also a per-tile **Review branches…**.
2. **Where it sits.** Recommend beside Launch on the button row. Alternative: next to the badge.
3. **Tiles in other tabs** (Backup and Sync, Tools): recommend the same button wherever a tile shows the badge, so every app is treated the same.

## 6. Risks
- The dialog's long progress text is the same widget as today; the layout and scroll fixes of 2026-11-16 (`eb6e9e1`) apply.
- Two Resolve runs at once on overlapping repos: refuse while one is open (success measure 5).

## 7. Phases to run
Define (this file, **GATE**), Architect (module boundary only, none expected), Plan, Build, Review, Verify, Document. Secure skipped: no new file writes, network or untrusted input beyond `repo-tidy`'s reviewed surface; say so in the review note. Comply skipped: tier `public`, no new claims.
