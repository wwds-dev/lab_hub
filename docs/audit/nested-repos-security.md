# Security review: nested repos in `_link_env` (spec land-from-tiles §9)

Scope: uncommitted diff of `lab_hub/claude_resolve.py` and `tests/test_claude_resolve_nested.py`
(branch `claude/nested-repos-tests`). Playbook `security-engineer.md` last-reviewed 2026-11-11, status current.
Tests: `pytest tests/test_claude_resolve_nested.py tests/test_claude_resolve.py` all pass (run, no failures).
Read-only review; nothing network-facing was run (not verified: any real https/ssh submodule fetch).

Threat model. Assets: the main checkout (its `.git` config/hooks, nested repos, `.venv`), the owner's
account, the default branch ref that gets pushed. Boundary: the merge result plus Claude's edits are
untrusted; the tests run that code as the owner's user with an allowlisted env (`test_env`, no secrets)
and NO filesystem sandbox. So "tests cannot write X" is only a tripwire (`_git_state`), never a barrier.
Entry points: `_link_env` -> `_link_nested` (reads `.gitmodules`, `git ls-files --ignored`, runs
`git submodule update`), `_unlink`, `_cleanup`.

## P0
None found.

## P1

### P1-1 Nested repos' own `.git` is writable through the symlink and outside the tripwire
`claude_resolve.py:775-779` (`_link_dir` / `links.append`), `:791-811` (`_git_state`), `:908`.
`_link_dir` links the whole nested repo, including its `.git` directory. `_git_state` fingerprints only
the main repo's `config`, `hooks`, `info`. A test run (branch code) can write
`nested/.git/hooks/*` or `nested/.git/config` (`core.fsmonitor`, `core.hooksPath`, `alias.*`,
`core.sshCommand`), which run the next time the owner or Lab Hub runs git in that nested repo, and the
change is not detected, so the land goes ahead. The code's own comment (`_git_state` docstring) names this
exact risk for the main repo. This is a regression: before, only `.venv`, `venv`, `node_modules` were
linked and none is a git dir. Whether Lab Hub itself runs git inside nested repos: not verified.
Same applies to a nested `.git` that is a file (gitdir elsewhere) or a submodule inside a nested repo:
everything under the link is writable and unfingerprinted.
Fix: extend `_git_state` to also hash `<nested>/.git/{config,hooks,info}` (resolving a `.git` file) for
every linked nested repo (and `.git/modules/*` for linked submodules), taken after `_link_env`; or link
the nested repo read-only (copy / `git worktree`-style checkout without `.git`) when the tests only need to import it.

## P2

### P2-1 Baseline for `_git_state` is taken after `_link_env`; submodule init permanently edits shared config
`claude_resolve.py:903-914`. `submodule update --init` in the worktree adds `submodule.<name>.url` and
`.active` to the main repo's shared `.git/config`. Reproduced with git 2.56 (scratch repo, file transport
allowed only for the experiment): config 296/384 bytes -> 543 bytes after one run, not rolled back by
`worktree remove`. The baseline is taken after the write, so the first run is not flagged and later runs
are stable. The values come from the checkout's own `.gitmodules` (byte-identical, see below), so I rate
the addition acceptable but undocumented: it is a lasting side effect on the main repo. Fix: document it,
or snapshot before `_link_env` and restore, or init with `-c submodule.<name>.url=...` only. Note the same
snapshot ordering means the tripwire cannot see anything `submodule update` itself wrote.

### P2-2 Recursive submodules and the pinned commit are not constrained by the `.gitmodules` byte compare
`:751-762`. The byte compare covers only the top-level file. The gitlink SHA comes from the merge
(attacker-influenced), and `--recursive` reads each submodule's own `.gitmodules` at that SHA, so URLs
are fetched that nobody compared. Requires the SHA to exist upstream (Claude has file tools only and
cannot create commits there), so reach is limited to content an upstream owner already published.
Also `protocol.git.allow=always` allows unauthenticated, tamperable `git://`; the code that then runs in
tests could be swapped by a network attacker. Fix: drop `--recursive` unless the nested `.gitmodules` is
also unchanged, allow only https/ssh, and verify the gitlink SHA equals the checkout's own HEAD of the submodule.

### P2-3 `_safe_rel` edge cases
`:714-718`. Verified by running it: `_safe_rel(".")` and `"./"` raise `IndexError` (caught by the generic
handler in `resolve`, so fail-closed, a denial of landing from a crafted `.gitmodules` path `.`). `.GIT/x`
and `a/.git` return True (git itself rejects these as submodule paths and `ls-files` never yields them, so
exploitability not shown; on case-insensitive macOS compare `parts[0].lower()`). Quoted names (leading `"`)
are rejected, and absolute and `..` paths are rejected, ENV_DIRS first components rejected: verified. Fix: guard empty `parts`,
compare case-insensitively, reject any component equal to `.git`.

### P2-4 When `.gitmodules` differs, the merge chooses which checkout directory is linked
`:764-770`. Paths come from the merge's `.gitmodules`; a path that has `.git` in the checkout is linked
from the checkout (writable, see P1-1). It cannot name a path outside the repo (`..`, absolute refused)
but `repo/<rel>` is resolved through any symlink in the checkout (`is_symlink` is only checked for the final
component in `_ignored_nested`, not in this branch, and not for parent components). Fix: require
`rel` to be in `_ignored_nested(repo)` or a gitlink of the checkout's own `HEAD`, and `resolve()` the source inside `repo`.

### P2-5 `_link_dir` creates parents through the worktree
`:742`. `target.parent.mkdir(parents=True)` and `symlink_to` would follow a tracked symlink parent and
create a link outside the worktree. Mitigated: `symlinks_outside` (`:950`) fails the merge when a tracked
symlink points outside, before Claude and before the post-fix test runs (base run on the default branch is
the owner's own tree). Not exercised by a test; not verified end to end.

### P2-6 Timeout and stop
`:57`, `:759-763`. `SUBMODULE_TIMEOUT=120` is per `git` call and is run in each `_tests` call (up to base,
merge, each fix round); `stop` is not consulted, so Stop waits up to 120 s. `subprocess.run` kills only
git, so `ssh`/`git-remote-https` children can outlive it (not verified). Exit code of the update is ignored
(by design, falls back to link; a half-populated directory then gives "already exists", fail-closed).

## What I checked and found sound
- Hooks: `core.hooksPath=/dev/null` is passed with `-c`, which git forwards to submodule child processes.
- `ext::`/`file`: `protocol.allow=never` default plus explicit `protocol.ext.allow=never`; reproduced that a
  `file` URL is refused ("transport 'file' not allowed") and the code then falls back to linking.
- `submodule.<name>.update=!cmd`: git ignores `!cmd` from `.gitmodules`; the shared `.git/config` is the
  owner's and is covered by the tripwire (except the ordering in P2-1).
- Differing `.gitmodules`: `same` is False so no `submodule update` call is made, hence nothing is fetched
  (unit test `test_a_changed_gitmodules_never_reaches_the_network` covers it; I read it, the suite passes).
  When it is the same, `update --init` always clones from the checkout's URL, i.e. it does use the network by design.
- Tracked or already existing path: `:772-775` refuses it, `_link_dir` uses `lexists`, tests cover both.
- Test env: allowlist, no tokens or SSH agent (`test_env`, `:512`).
- `_cleanup`: `_unlink` only unlinks symlinks; the submodule initialised in the worktree lives under the
  worktree's own gitdir (`.git/worktrees/<n>/modules`), and `git worktree remove --force` succeeded on a
  worktree with an initialised submodule (reproduced). A left-over symlink: git's remover and
  `shutil.rmtree` use lstat and do not follow symlinks (known behaviour; I did not run the left-over-symlink case: not verified).
  Both stay guarded by the `root` containment check.
