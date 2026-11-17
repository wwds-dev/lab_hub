# ADR 0001: Land resolves open items by quarantine and archive tags

Date: 2026-11-17. Status: accepted with spec `land-resolve-all` (owner approved Define 2026-11-17).

## Context
Land left untracked files and unlanded branches "for the owner". The owner wants every open item resolved
(spec `land-resolve-all` §1). The repos are public, so an untracked file can carry a secret, and a deleted
branch can hold work nobody else has.

## Decision
1. **Untracked files** are split three ways, in `lab_hub/land_resolve.py`:
   - Secret-like names and files over 10 MB go to quarantine without a scan.
   - Every other file is copied into an empty temporary folder and scanned there with gitleaks
     (`gitleaks dir --redact`). The repo's own `.gitleaks*` config and ignore files never apply.
   - A file with a finding goes to quarantine. A clean file is committed by its exact path.

   Quarantine is `~/Documents/lab/.quarantine/<repo>/<date>/<path>` (folders 0700). The path is
   appended to the repo's `.gitignore`. Nothing is deleted.
2. **Unlanded branches** get one Claude Code verdict each, `land` or `archive`. The run is read-only:
   tools `Read,Grep,Glob`, in a temporary folder holding only the branch's diff and log.
   - `land` uses the existing merge path (`repo_tidy.apply`, which hands conflicts to `claude_resolve`).
   - `archive`, or a land that fails, writes the log line first. Then it creates the local annotated
     tag `archive/<branch>/<date>` at the tip and deletes the branch with `update-ref <old sha>`, so
     a moved branch is never deleted. Tags are never pushed. Review branches lists them and offers
     Restore (`git branch <name> <tag>^{commit}`).
3. **Orchestration** stays in `lab_hub/land.py`. `land()` runs the prep steps, then repeats plan
   and apply for up to 3 rounds (a branch committed in round 1 merges in round 2), then triage, then
   one more round for the push. `repo_tidy` gains a `land_mode` flag that relaxes two Resolve-only
   rules:
   - the 24-hour agent rule for commits and merges
   - the "process inside" rule for merges (a merge reads commits only)

   Removal guards are unchanged.

## Consequences
- Bulk Resolve (Check repos → Resolve…) keeps the old, stricter rules; only Land uses `land_mode`.
- A gitleaks miss is a residual risk the owner accepted (spec §7).
- `refs/tags/archive/*` grows over time; a later tidy may prune old ones (not in scope).
