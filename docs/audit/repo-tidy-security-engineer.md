# Security review: repo-tidy (2026-11-15)

Reviewer: `security-engineer` subagent, read-only; experiments in scratch temp repos only. 28 tests passed. No new dependencies (no audit run).

Threat model: at stake are unlanded commits, files inside worktrees, and remote default branches. Trust boundaries: `hygiene.json` (written by another tool) and repo state (refs, worktree paths, `.git/config`, hooks) that agent sessions also write.

No P0. One P1.

## P1
- **Worktree removal deletes gitignored files** (`is_clean` hides ignored files; `git worktree remove` deletes them). Confirmed with `.env`. In lab_hub, `/docs/legal` and `.env` are gitignored, so legal drafts or keys in an old agent worktree would be lost through a default-ticked action. Fix: block when `git ls-files -o -i --exclude-standard --directory` is non-empty outside a regenerable allowlist; list them in the Review confirmation.

## P2
- `lsof` guard fails open (returns `()` on failure); and one `busy` snapshot is used for a whole Apply run. Fix: fail closed; fresh snapshot before each removal.
- Restore after `branch -D` only lasts until gc (~2 weeks); spec §7 is wrong. Fix: keep a backup ref before deleting, or state the limit.

## P3
- Check-then-delete gap: use `git update-ref -d refs/heads/<b> <planned-sha>`.
- `worktree list --porcelain` parsed without `-z`: a path containing a newline can spoof another entry.
- Git environment not cleaned: inherited `GIT_DIR`, `GIT_WORK_TREE`, `GIT_INDEX_FILE`, `GIT_CONFIG_*` would redirect actions.
- Credential prompts not fully shut off (`GIT_ASKPASS`/`SSH_ASKPASS`, no `GCM_INTERACTIVE=never`, no `ssh -oBatchMode=yes`).
- Sync guards inconsistent: fetch/push to `origin` but compare with `@{upstream}`; `default_branch` trusts local `origin/HEAD`. No force, so the risk is an unexpected publish, not loss.
- Repo paths from `hygiene.json` not validated; preview shows only the JSON name.
- Log file: default umask, raw multi-line stderr (remote `remote:` lines can forge log lines). Fix: 0600 and escape newlines.
- Review actions block the UI thread (git and lsof up to 30 s).
- `refname:short` can become `heads/x` when a tag `x` exists; use `%(refname:lstrip=2)`.

## Checked and fine
No shell; branch args after `--` or as full `refs/heads/`; no force push, explicit refspec; git refuses to remove the main checkout; `GIT_TERMINAL_PROMPT=0` and timeouts; PATH lookup puts SIP-protected `/usr/bin`, `/usr/sbin` first; hooks and config run only code the same user controls.
