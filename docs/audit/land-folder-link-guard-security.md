# Security review: land-folder-link-guard

Phase: Secure (8), read-only, 2026-11-18, by the `security-engineer` agent. Saved by the owning session from the agent's report.
Scope: commit 585e3b3 and spec `docs/specs/land-folder-link-guard.md`. Git 2.56.0, macOS APFS (case- and normalisation-insensitive).
**Playbook:** `docs/playbooks/security-engineer.md`, `last-reviewed: 2026-11-11`, `status: current`; not stale.

## Verdict
No P0. One P1 needs an owner decision: the SONAR data loss can still happen through a path this guard does not check. Two P2, five P3. For the link cases it was built for, the guard holds: the case-variant, Unicode-normalisation and `..` attacks are caught (see "Verified safe").

## Threat model
- **Assets:** untracked and ignored data in each repo's main checkout (`.venv/`, `node_modules/`, local config); what is on the default branch and gets pushed (public repos); the owner's files outside the repo; Land being available.
- **Trust boundaries:** branch content written by unreviewed agents (paths, modes, link text, `.gitignore` files, branch names); what origin brings in through the pull (anyone who can push controls it); the main checkout's filesystem, which Land reads but other processes can change.
- **Entry points (moves of the main checkout):** plain merge (`repo_tidy.py:953`), Claude merge fast-forward (`claude_resolve.py:1295`), prep's switch (`land_resolve.py:824`), pull, now fetch + check + `merge --ff-only` (`repo_tidy.py:975-983`); preview checks (`repo_tidy.py:584`, `847`, `686`).

## Findings

### P1-1. A regular file (not a link) at `.venv` still replaces the ignored real `.venv/` folder
- **Where:** `land_resolve.py:379-401`. `incoming_links` keeps only mode `120000`, and the real-folder check in `link_problem` runs only for those entries.
- **Reproduced** (`scratchpad/sec/r2`):
  - The repo has `.gitignore` = `.venv/` and a real `.venv/bin/python`.
  - In a worktree, an agent writes `.venv` as a text file. `git add -A` adds it without `-f`, because `.venv/` only matches folders.
  - `merge_link_stop` returns `''`. `git merge --no-ff` exits 0, and `.venv` is now an 11-byte file.
- **Scenario:** a tool writes a `.venv` file in the agent worktree (pipenv's `.venv`-file convention), or a link is materialised as a text file (`core.symlinks=false`, the case `repair_link` exists for).
- **Impact:** the same loss as SONAR, through the same unforced `git add -A`. Spec §4/§5.1 A justify "links only" by saying a file needs `git add -f`. That holds for a file over an ignored *file*, not over an ignored *folder*. §2.1 "cannot recur" does not hold for this variant.
- **Fix:** check added or type-changed blobs (`100644`, `100755`) too, for §3.2.1 (real folder) and §3.2.2 (ignored as a folder). Keep §3.2.3 (link text) for `120000`. File over an ignored file (option B) can stay out.
- **Gitlink:** a gitlink (`160000`) at `.venv` keeps the folder ("unable to rmdir"), so it is not a loss path with default config. `submodule.recurse=true` was not verified.

### P2-1. The outside-the-repo check is lexical; chained links bypass it
- **Where:** `land_resolve.py:439-441`. `posixpath.normpath` treats `l/..` as `.` even when `l` is a link.
- **Reproduced** (`r1`): `x/l2 -> ..` plus `l1 -> x/l2/..` both pass. After the merge, `l1` resolves to the repo's parent folder. Deeper nesting reaches any path. The bypass also works through a link the checkout already tracks.
- **Impact:** decision §5.2 A is bypassed. A landed link can lead to sibling repos or `~/.ssh`, and tools that write through links can write outside the repo.
- **Fix:** resolve the text against the result tree and the checkout, link by link, with a hop limit.

### P2-2. A branch with many links makes Land very slow
- **Where:** `land_resolve.py:458`. Each link gets its own `.gitignore` mirror plus 1-3 git calls.
- **Measured** (`r5`): 500 links took 78.8 s for one `merge_link_stop`. The check runs in every planning round and in `check()`.
- **Fix:** batch it (one `cat-file --batch`, one `check-ignore --stdin` against one mirror), or cap the count.

### P3-1. Time of check and time of use differ
- **Merge:** `check()` confirms `tip == action.sha`, but the link check reads `refs/heads/<branch>`, and `apply` then merges `action.sha`.
- **Pull:** the check and the merge each read `refs/remotes/origin/X` by name.
- **Switch:** the check and the switch each read `refs/heads/<default>` by name.
- **Fix:** check exact OIDs and move to the same OID.
- **Status:** read only, not run. An attacker who can win the race already has a shell.

### P3-2. Non-UTF-8 bytes in a path or in link text raise `UnicodeDecodeError`
- **Where:** `rt.git` uses `text=True`.
- **Impact:** fails closed, but one branch blocks the whole repo in `make_plan`. In the run path it is not caught, so `land()` breaks its "never raises" contract.
- **Fix:** read `diff-tree` and `cat-file` as bytes and decode with `surrogateescape`.

### P3-3. A link into `.git` passes
- **Reproduced** (`r7`): `scripts -> .git/hooks` passes. A later write of `scripts/pre-commit` installs a live hook.
- **Fix:** stop when the resolved target is inside `.git`.

### P3-4. `_shown` lets Unicode formatting characters through
- **What gets through:** C1 controls, bidi overrides, zero-width characters and U+2028/2029. They reach the stop text.
- **Fix:** replace characters in categories Cc, Cf, Zl and Zp.

### P3-5. The ignore check reads the checkout's `.gitignore`, not the incoming one
- A branch that adds both the `.venv/` rule and the `.venv` link passes §3.2.2 when the checkout has no folder yet.
- **Fix (optional):** also check the result tree's `.gitignore` files.

## Verified safe
- **Case variants:** `.VENV` against `.venv/` stops, both with and without the folder (`core.ignorecase` applies in the mirror).
- **Unicode normalisation:** an NFD name against an NFC folder stops.
- **A `..` tree entry:** stops, and git itself refuses the merge.
- **Argument injection:** refs are fully qualified, pathspecs are `:(literal)` after `--`, and OIDs are validated.
- **Fail-closed paths:** every git error and odd output shape becomes a stop, as does `OSError`.
- **Pull rewrite:** it fetches the same thing with the same trust, and `--ff-only` is kept.
- **Claude fast-forward:** it checks and moves between the same OIDs.

## Dependencies and secrets
- **Dependencies:** none added. OSV on the installed set (43 packages) returned 0 advisories. `pip-audit` is not installed.
- **Secrets:** `gitleaks git --redact` on 585e3b3 found no leaks.

## Not verified
- How the Qt UI renders the stop text.
- `submodule.recurse=true`.
- The races in P3-1 (only read).

## Disposition (owning session)
See the end of `docs/specs/land-folder-link-guard.md`, §9.
