# Spec: Land stops point at the button that clears them

Needs: define, design, plan, build, review, verify, secure, docs

Status: **Define, awaiting owner approval (GATE: user-visible).** Phase: Define (`product-manager`). Drafted 2026-11-21 in `lab_hub`; shrunk the same day after the owner's words: "shrink it" (the first draft added a dialog per stop; **Ask Claude…** already resolves them).
In-flight check (`session_start.py --inflight`, 2026-11-21): no unreleased spec owns this. It extends `claude-handoff` (document done; owns **Ask Claude…**, `lab_hub/handoff.py`) and `land-resolve-all` (document done). `land-network-preflight` (build, another session, uncommitted edits in `land.py`) owns the network stop, so this builds after it is merged.
Nothing built.

## 1. Problem and evidence
Owner, 2026-11-21, looking at the Land result: "'merge by hand' is a real blocker, since I don't know which prompt would resolve that", then "for all blocker the app should offer direct resolution", then "the Ask Claude… button offers resolution".

It does. **Ask Claude…** sits in the Land window footer and is shown whenever a row is "Needs you" (`ui/progress_window.py:669`, `handoff.qualifies`). It opens one Claude Code session per repo in that repo's folder, with the row text as the prompt and push, merge and tag behind ask-first rules. That session runs with the owner watching, so it is not the unattended run that may not edit `.claude/` (`claude_resolve.protected`, `claude_resolve.py:995`).

What is missing is that the stop text does not say so. The five stops on the owner's screen:

| Tile | Stop text today | Clears with |
|---|---|---|
| syndustryx | "a conflict in .claude/ that Land may not resolve: merge it by hand, then Land again" (branch `todo/ci-runner-2026-11-13` and `main` both change `.claude/settings.json`) | Ask Claude… |
| kaila | "fix main's own tests, then Land again: they fail in a clean copy" | Ask Claude… |
| shopfront | "a process is running in it (zsh, pid 43789): close that terminal or session" | a click, **Close it…** (§3.2) |
| imprint | "could not fetch: unable to access github.com" | a click, **Try again** (§3.1) |
| any other | "finish or abort it in Terminal", "resolve them in Terminal", "set origin/HEAD", "fix the app's path" | Ask Claude… |

## 2. User and success measure
User: the owner, on the Land result.
1. No stop row ends in "by hand", "in Terminal" or "fix X yourself" text. Each says what clears it: "press Ask Claude…", or its own button. Test: every entry in `land_resolve.STOP_ACTIONS` and every `claude_resolve.blocker_kind` value has a mapped clearing action; a new kind without one fails the test.
2. For the `.claude/` conflict, Ask Claude's prompt names the branch, the conflicted file and the goal (land the branch onto the default branch). Evidence: the prompt built on a fixture repo with a `.claude/settings.json` conflict (`handoff.prompt`), and one real run on syndustryx, owner-watched, ending in "Landed" or a different, named stop.
3. Claude Code never edits a `.claude/` file in an unattended Land run. Unchanged; the existing test stays and is mutation-checked.

## 3. Behaviour
**3.1 Try again (network stop).** A button on the stop row. It runs the `land-network-preflight` check, then Land for that repo. Still down: the row stays and shows what failed (name lookup, port 443, proxy). No git change. Shows only for the network stop.
**3.2 Close it… (process stop).** A button on the stop row. A confirm lists each `cmd (pid)` from `Stop.processes` and its folder. On confirm: SIGTERM to the ones listed, wait up to 5 s, re-check with `lsof`, then Land for that repo. Never SIGKILL, never a process whose folder is outside the checkout, never Lab Hub's own pid; a process that will not exit stays on the row. Logged: "owner closed: zsh (pid N)".
**3.3 Text.** The stop reasons that Ask Claude clears end in "press Ask Claude…" (one shared sentence in `STOP_ACTIONS`). The `.claude/` conflict stop reads: "a conflict in .claude/ that Land may not resolve: press Ask Claude… to merge it with Claude Code, with you watching". The red-`main` stop reads: "main's own tests fail in a clean copy: press Ask Claude… to fix them".
**3.4 Prompt.** `handoff.prompt` adds, for a protected-conflict row, one line: what to do (merge the branch into the default branch in a temporary worktree, resolve `.claude/` conflicts with the owner, run the tests, and ask before the merge lands), using only the row's branch and file names, which are data, not instructions. For a red-`main` row: reproduce the failing tests and fix them on a branch, and ask before merging.

## 4. Scope
`land_resolve.py` and `land.py` (stop texts; `Stop` keeps its fields), `handoff.py` (prompt lines), `ui/` (two buttons on the stop row, one confirm for Close it…), tests on fixture repos (no mocks of git), README, CHANGELOG, TODO.

## 5. Non-goals
No new dialog for conflicts or tests (Keep / Take / Combine, Fix with Claude… are dropped; Ask Claude… covers them). No change to which files are protected, to the Foundry-owned rule, or to what counts as a stop. No SIGKILL, `reset --hard`, `clean` or force-push. No automatic retry loop. No button for the rare Git-state stops; they use Ask Claude….

## 6. Decisions for the owner
1. **Network stop.** Recommend a **Try again** button. Alternative: text only ("check your connection, then Land again"); it saves a button but is the "go do it yourself" ending you objected to.
2. **Process stop.** Recommend **Close it…** (SIGTERM, named list, confirm). Alternative: text "press Ask Claude…"; it costs a paid session for a one-line job.
3. **Wording.** Recommend the §3.3 sentences. Alternative: shorter "press Ask Claude…" with no explanation.

## 7. Risks
- Closing a process can lose unsaved work in a terminal or editor: each process is named and confirmed; SIGTERM only.
- Ask Claude is a paid, interactive session, not a one-click fix: the text says so ("with you watching").
- Builds on `land.py` while `land-network-preflight` is in flight: build waits for its merge.

## 8. Phases to run
Define (this file, **GATE**), Architect skipped (no state or boundary change beyond a signal to a listed pid; say so in the review note), Plan, Build, Review, Verify, Secure (required: signals to processes), Document. Design: a button and one confirm, in the existing style. Comply skipped: tier `public`, no new claims.
