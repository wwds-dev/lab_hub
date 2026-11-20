# ADR 0006: Lab Hub builds its update from a private snapshot of `main`

Status: proposed 2026-11-20, waiting for the owner's Architect gate.
Spec: `docs/specs/self-update.md` §11–§12. Supersedes decision 2 of ADR 0003 (staging only while
the shared checkout is clean, on `main` and at the built commit).

## Context
Update now built Lab Hub in the shared checkout and staged the result only if that checkout was
still clean and unmoved. Other sessions edit and commit there all day; over three real-Mac attempts
on 2026-11-18/19 the 10–20 minute build window was never quiet, so the update never installed
(`docs/audit/self-update-qa.md`, owner's manual check).

## Decision
1. When Check builds offers Lab Hub's row, it records the full SHA of `refs/heads/main`.
2. Update now's command clones the shared repository into `~/Library/Application Support/Lab Hub/update/snapshot/lab_hub`
   (a local, hard-linked clone, not a worktree), checks out that SHA detached with hooks off, links
   the checkout's `.venv`, and runs `build_app.sh` there.
3. Staging accepts the bundle only if the snapshot's `HEAD` and the bundle's stamp both match the
   recorded SHA, then removes the snapshot. The shared checkout is not consulted.
4. The recorded SHA travels inside the command string; `planned_commit` recovers it only when the
   command is exactly one `build_command` makes.

## Consequences
- Other sessions' uncommitted edits, commits or branch switches can neither block nor enter the
  update. Uncommitted edits are never installed; Lab Hub's row no longer calls them a reason to
  rebuild.
- What is installed is the commit the owner saw in the row, even if `main` has moved since.
- About 10 MB of hard links plus the build output (a few hundred MB) exist under `update/` during an
  update; removed after staging.
- The build still shares `.venv` with the checkout.
- New surface: one `git clone` and `checkout` of a local path with quoted, checked values; the
  snapshot carries none of the shared repository's hooks or config.
