# Spec: every Land blocker gets a direct Resolve action

Status: **Define, awaiting owner approval (GATE: user-visible).** Phase: Define (`product-manager`). Drafted 2026-11-21 in `lab_hub`; widened the same day after the owner's words: "for all blocker the app should offer direct resolution".
In-flight check (`session_start.py --inflight`, 2026-11-21): no unreleased spec owns this. `land-resolve-all` and `land-from-tiles` (both document done) own the Land code this extends; `land-network-preflight` (build, another session, uncommitted edits in `land.py`) owns the network stop, so this builds after it is merged. `tile-resolve` is superseded. Replaces the earlier draft `land-protected-conflict` (same day, renamed).
Nothing built.

## 1. Problem and evidence
Owner, 2026-11-21, looking at a Land result: "'merge by hand' is a real blocker, since I don't know which prompt would resolve that", then "for all blocker the app should offer direct resolution". Today every hard stop is a yellow line of text that tells the owner to go and do something elsewhere. Five stops on the same screen:

| Tile | Stop text (today) | Why Land stops | Code |
|---|---|---|---|
| imprint | could not fetch: unable to reach github.com | network down; Land cannot sync | `land.py` (see `land-network-preflight`) |
| kaila | fix main's own tests, then Land again: they fail in a clean copy | no branch may land onto a red `main` | `land.py:686`, `claude_resolve.base_fail_reason` |
| syndustryx | a conflict in .claude/ that Land may not resolve: merge it by hand | an unattended Claude may not edit `.claude/` (`claude_resolve.protected`, `:995`); real case: branch `todo/ci-runner-2026-11-13` and `main` both change `.claude/settings.json` | `claude_resolve.py:969` |
| shopfront | a process is running in it (zsh, pid 43789): close that terminal or session | a live process has its folder inside the checkout | `land_resolve.py:825` |
| any | finish or abort it in Terminal / resolve them in Terminal / set origin/HEAD / fix the app's path / folder link | merge, rebase or cherry-pick in progress; unmerged files; no default branch; path gone; link over a folder | `land_resolve.STOP_ACTIONS` |

Each is a dead end: no button, no command, no prompt to give. Land is right to stop in each case; it is wrong to leave the owner alone with it.

## 2. User and success measure
User: the owner, on the Land result (Apps page, Backup and Sync).
1. Every stop row has a **Resolve…** button. No stop ends in "go do it yourself" text without one. A stop kind with no direct action is a bug against this spec, not an exception (test: every `STOP_ACTIONS` entry and every `blocker_kind` value maps to an action; a new kind without one fails the test).
2. The button opens one dialog that says, in plain words, what is wrong, what the action will do, and what stays untouched, with the exact diff, process or command where there is one. Nothing runs until the owner presses its confirm button.
3. After a successful action Land re-runs for that repo on its own and the row clears or shows its next, different stop. Evidence: fixture repo per kind goes from stop to "Landed" after one click; screenshot of the real lab's five stops above.
4. Claude Code never edits a `.claude/` file in any mode. Only the owner's click does. Tested; mutation-checked.
5. Every owner click and its effect is written to the Land log ("owner chose: ...").
6. The words "merge it by hand" and "close that terminal" are gone from the rows; they name the button.

## 3. Actions per stop kind
| Stop | Button | What it does (after the owner confirms) |
|---|---|---|
| Network down | **Try again** | Runs the `land-network-preflight` check, then Land. If still down, the row stays and shows what failed (DNS, port 443, proxy). No git change. |
| `main`'s own tests fail | **Fix with Claude…** | Claude Code, in a temporary worktree of `main` (as `claude_resolve` already does), fixes the failing tests within the usual budget. The dialog then shows the diff and the test result; **Apply** commits it to `main`, **Discard** drops it. If tests are still red, nothing is applied. Alternative button: **Waive for this Land** (owner-only, logged): land the waiting branches onto a red `main`; see decision 2. |
| `.claude/` conflict | **Choose…** | Per conflicted file: **Keep main's** (preselected), **Take the branch's**, or for JSON such as `settings.json` **Combine** (arrays such as `permissions.allow/deny` and `hooks` are the union; a key both sides changed to different values is listed and the owner picks the side). Lines that add a permission or a hook are marked "widens what Claude Code may do". No Claude run. The choice is bound to the branch and `main` SHAs shown; if either moved, the dialog asks again. Land's temporary-worktree merge takes the choice the way `_take_default` takes Foundry's copies, then continues as for any Claude merge. Rename-into-`.claude/`, delete-versus-edit and binary files: Keep or Take only. |
| Process running in the checkout | **Close it…** | Shows each `cmd (pid)` and its folder, then sends SIGTERM to the chosen ones, waits, re-checks with `lsof`; never SIGKILL, never a process outside the checkout, never the Lab Hub itself or a terminal tab the Lab Hub owns without naming it. If one will not exit, the row says which. Alternative: **Wait and retry** (re-checks every 10 s, up to 5 min). |
| Merge, rebase, cherry-pick or bisect in progress | **Abort it…** | Shows `git status` and the operation, runs `git <op> --abort` after confirm. Never a reset or a clean. |
| Unmerged files in the checkout | **Open in editor** | Lists the files and opens them in the editor named in app-context (or Finder); the row re-checks on focus. Land does not guess a resolution of the owner's own working files. |
| No default branch (`origin/HEAD`) | **Set it** | Offers the branches `main`/`master` found on the remote; runs `git remote set-head origin <branch>` after confirm. |
| App path gone | **Pick the folder…** | A folder picker that rewrites the app's path in the Lab Hub config after confirm. |
| Folder link over a folder | **Repair the link** | The existing repair from `land-folder-link-guard`, behind a confirm and a preview, only when the file text equals the blob in git. |

## 4. Scope
`land_resolve.py` and `land.py` (a `Stop` carries a `kind` and the data its action needs; one registry maps kind to action), `claude_resolve.py` (accept owner choices for protected files; a fix-tests run on `main`), `ui/` (the button on each stop row and tile, one `StopDialog` with per-kind content), tests on fixture repos (no mocks of git), README, CHANGELOG, TODO.

## 5. Non-goals
No Claude edit of `.claude/` files. No change to which files are protected, to the Foundry-owned rule, or to what counts as a stop. No SIGKILL, no `reset --hard`, no `clean`, no force-push. No bulk "resolve everything" button in this change. The network stop gets no automatic retry loop.

## 6. Decisions for the owner
1. **Scope of the first build.** Recommend all kinds in one spec, built in two slices: slice 1 = the three on your screen plus the process stop (network, red `main`, `.claude/` conflict, process); slice 2 = the rare Git-state stops. Alternative: all at once.
2. **Red `main`.** Recommend **Fix with Claude…** only. Alternative: add **Waive for this Land**; it lets a branch land onto failing tests, so I advise against it.
3. **`.claude/` conflict.** Recommend per-file Keep / Take / Combine, Keep preselected. Alternative: one **Keep main's** button; simpler, but it silently drops a branch's settings change.
4. **Process stop.** Recommend **Close it…** with SIGTERM and a named list. Alternative: **Wait and retry** only.
5. **Where the button sits.** Recommend on every stop row and on the tile that shows it.

## 7. Risks
- Closing a process can lose unsaved work in a terminal or editor: the dialog names each process and its folder; SIGTERM only.
- A `settings.json` merge can widen permissions: owner-only, Keep preselected, widening lines marked, logged.
- Fix-with-Claude on `main` can make a wrong fix: the owner sees the diff and the green run before Apply; failing tests apply nothing.
- Builds on `land.py` while `land-network-preflight` is in flight: build waits for its merge.

## 8. Phases to run
Define (this file, **GATE**), Design (`StopDialog`, one pattern for all kinds), Architect (kind-to-action registry; state: SHA binding; ADR if the registry changes the `Stop` shape across modules), Plan, Build, Review, Verify, Secure (required: signals to processes, writes to a security-relevant file, git aborts), Document. Comply skipped: tier `public`, no new claims.
