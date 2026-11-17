# Secure: land-resolve-all (2026-11-17)

Reviewer: `security-engineer` agent, read-only. It is not the author. It probed gitleaks 8.30.1 directly
with fixture files. Scope: `lab_hub/land_resolve.py`, `lab_hub/land.py`, the `land_mode` changes in
`repo_tidy.py`, and `claude_resolve.py`'s `tools`. No new dependencies, so pip-audit was not run.

Verdict as reported: **0 P0, 2 P1, 4 P2, 5 P3.** Status of each finding is in the table at the end,
filled in after the fixes.

## Findings (as reported)
- **P1-1. gitleaks reports "no finding" for files it never scanned.**
  - With Land's flags, a secret in `photo.png` or `package-lock.json` was not found. gitleaks'
    built-in path allowlist skips both.
  - It was also not found in `backup.zip` holding a `.env`, in `*.gz`, or in `app.sqlite`.
  - A finding that cannot be matched to a file is dropped silently.
  - Fix:
    - copy each file under a neutral name;
    - fail closed on an unmatched finding;
    - quarantine binaries gitleaks cannot read;
    - add more secret names.
- **P1-2. Only untracked files are scanned, but Land commits and pushes more.**
  - Unscanned outgoing content:
    - files that are staged but not committed;
    - edits to tracked files (now also in agent worktrees);
    - unpublished branches that Land merges.
  - Spec §2.4 says "no secret is pushed".
  - Fix: scan the outgoing range with `gitleaks git` before every push, using a config Lab Hub owns,
    `--ignore-gitleaks-allow`, an empty ignore path, and cwd set to a temporary folder.
- **P2-1. TOCTOU between the scan and `git add`.** Fix: compare the staged blob with the scanned bytes.
- **P2-2. `.gitignore` handling.**
  - A file name containing a newline injects a `!pattern` line.
  - A symlinked `.gitignore` is followed outside the repo.
- **P2-3. `link_target` is not confined.** It reads the working-tree text, not git's blob, and accepts any
  target.
- **P2-4. A Claude "land" verdict publishes work that was never published.** Prompt injection in a diff can
  cause it. Mitigated by the P1-2 scan.
- **P3-1.** The gitleaks call has no cwd and no `-i`, so a `.gitleaksignore` in the current folder is read.
- **P3-2.** The push lacks `--no-follow-tags`, so `push.followTags` could publish an archive tag.
- **P3-3.** An untracked symlink is committed as its target text, which may contain a local path.
- **P3-4.** The triage diff goes to Anthropic unscanned. This is disclosed in the confirmation.
- **P3-5.** Repo hooks run on commit, switch and merge. This is the same class as existing Land. Hooks are
  not disabled, because they may be the owner's own scanner.

## Checked OK (reviewer)
- FIFOs and sockets: git does not list them.
- Sparse files: caught by the size rule.
- The repo's `.gitleaks.toml` and `GITLEAKS*` env vars cannot take effect.
- Quarantine paths come from `ls-files` and their folders are 0700.
- Logs: newlines are flattened, the file is 0600, and only rule IDs are written.
- Branch deletion uses `update-ref <old sha>`.

## Status after fixes
| Finding | Status |
|---|---|
| P1-1 | fixed: each file is copied as `<n>/f`, archives are opened, an unmatched finding fails closed, a binary that is not an image is quarantined, more secret names. Tests: `test_gitleaks_path_allowlist_cannot_skip_a_file`, `test_a_binary_the_scan_cannot_read_is_quarantined`, `test_a_finding_lab_hub_cannot_place_fails_closed` |
| P1-2 | fixed: every Land push first runs `gitleaks git` over `origin/<default>..<default>` with Lab Hub's own config, no ignore file and no allow comments, and a finding refuses the push. Test: `test_a_secret_in_a_tracked_edit_is_never_pushed` |
| P2-1 | fixed: after `git add`, each staged blob must equal the bytes scanned and be a plain file or link; otherwise the files are unstaged and nothing is committed. Test: `test_a_file_changed_after_the_scan_is_not_committed` |
| P2-2 | fixed: a name containing a line break never gets a `.gitignore` line, and a `.gitignore` that is not a regular file is refused. Tests: `test_a_name_with_a_line_break_…`, `test_a_symlinked_gitignore_…` |
| P2-3 | fixed: the link text must equal git's blob, and the target must sit under `~/Documents/lab`. Test: `test_a_link_outside_the_lab_or_edited_locally_is_not_followed` |
| P2-4 | fixed by the P1-2 scan; branches Claude chose to land are named in the result |
| P3-1 | fixed: gitleaks runs from an empty folder with `--gitleaks-ignore-path` set to it |
| P3-2 | fixed: pushes use `--no-follow-tags`. Test: `test_archive_tags_are_never_pushed_even_with_follow_tags` |
| P3-3 | accepted: the link text is a path, not a secret |
| P3-4 | accepted: disclosed in the confirmation |
| P3-5 | accepted: the same as the existing Land |
