# Review: nested repos in the test worktree (spec land-from-tiles section 9)

Playbook code-reviewer.md: last-reviewed 2026-10-14, status current (not stale).
Suite: `pytest -q -p no:warnings` in the worktree: all dots, exit 0 (no summary line captured; ~3+ min).
Spec success measure e (real lab) not verified, out of scope.

## P1
1. **claude_resolve.py `_link_nested` (the `(tmp / rel / ".git").exists()` checks, todo list and link loop).**
   A half-done `submodule update --init` (timeout at SUBMODULE_TIMEOUT, SHA not fetchable, one of several
   submodules failing) leaves `<rel>/.git` (git file) but no checked-out files. The code treats ".git exists"
   as "initialised", skips the fallback link, and the tests then fail at collection against an empty tree,
   with a misleading "tests fail" verdict instead of falling back to the checkout's copy. Return code of
   `rt.git(... submodule update ...)` is also ignored. Not run against a failing clone: not verified by
   execution; derived from the code (the `.git` test is the only success signal; rc is dropped).
   Fix: after update, treat a submodule as ready only if rc==0 and the directory has content beyond `.git`
   (or `git -C <rel> rev-parse HEAD` works); otherwise remove the half-init and link from the checkout.
   Test gap: no test runs a failed/partial update.

## P2
2. **`_ignored_nested` quoted paths.** Without `-z`, git prints non-ASCII dirs as `"\303\251/"` (verified in a
   scratch repo). `_safe_rel` rejects a leading `"`, so a nested repo under such a name is silently not linked.
   Fix: `ls-files -z`, split on NUL (as `_Tmp.untracked` already does). No test for odd paths.
3. **`links[:] = new` in `_tests` happens after `_link_env` returns.** An exception in `_link_env` after a
   symlink is made (e.g. `OSError` from `read_bytes`, KeyboardInterrupt) leaves links the caller cannot
   remove; `_cleanup` gets an empty list. Worktree removal does not follow symlinks (rmtree), so the
   checkout is safe, but the "removed straight after" claim is not guaranteed. Fix: pass `links` into
   `_link_env`/`_link_nested` and append in place. No crash test exists.
4. **`_link_dir` `target.parent.mkdir(parents=True)`** creates parent dirs that stay after unlink, and if a
   parent in the merge is a tracked symlink pointing outside, the link is created through it, before
   `symlinks_outside` has run. Fix: refuse when any parent of target is a symlink; ignore empty leftover parents.
5. **Dead branch `if rel in submodules: continue`.** A tracked submodule can never appear in
   `ls-files --others --ignored`, so this skip is unreachable: mutation survives (equivalent mutant).
   Remove it or test it with a case that reaches it. Also `ls-files -- rel` should use `:(literal)` pathspec.
6. **Cost.** One `ls-files --directory` on the checkout per `_tests` call (two per Resolve) plus one
   `config -f`; `--directory` does not descend into ignored dirs, so cheap. A real `submodule update` is a
   full network clone per Resolve (up to 120 s each, and again only if not initialised); acceptable but
   not measured: not verified on the real lab.
7. **Shared git dir.** `submodule update --init` in the worktree left the main `.git/config` unchanged in my
   scratch run (verified), and `worktree remove --force` succeeded with an initialised submodule (verified).
   `_git_state` baseline is taken after `_link_env`, so a future change to config by init would not be caught.
   Move `before = _git_state(repo)` ahead of `_link_env`.

## Mutations that survive (tests)
- Submodule branch with a successful `update` is only exercised against a local file URL via `git -c
  protocol.file.allow=always` in `submodule_repo`; `_link_nested` forces `protocol.allow=never`, so in tests the
  real update fails and only the link fallback is ever exercised. The "initialised in worktree" success path is
  never run (spy test checks flags only). Mutating `--init` away or breaking success handling survives.
- Same-bytes `.gitmodules` check: only the "ext::" case is tested; mutating `==` to always true is caught only
  via the marker, but a mutation to always-false (never init) survives since the link fallback passes the same asserts.
- `rel in submodules` skip: survives (unreachable).
- `_safe_rel` rejections (`..`, absolute, `.git`, ENV_DIRS prefix, leading quote): no direct test; each can be removed.
- Second `_tests` call on a reused worktree after reset/clean/merge: no test. Links removed after a crash in
  `_link_env`: no test. `_cleanup` unlink: no test.
- Test "unlink" assertion for submodule: `not lexists(...) or is_dir()` is always true; asserts nothing.
