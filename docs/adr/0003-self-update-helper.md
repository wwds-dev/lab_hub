# ADR 0003: Lab Hub replaces its own bundle through a detached helper

Status: accepted by the owner 2026-11-17 ("Approve architecture"); amended the same day after review (staged install, checked swap, `broken` outcome).
Spec: `docs/specs/self-update.md` §9.

## Context
A running macOS app cannot safely overwrite its own bundle:
- `build_app.sh --install` deletes `/Applications/Lab Hub.app` while the process may still load files from it lazily.
- The script keeps no previous build.

The new build also has to start only after the old process has exited, because `SingleInstance` turns a second copy away. Lab Hub must never quit while a Land or a tool runs in-process.

## Decision
1. **The build and self-test run inside Lab Hub**, via the existing `Rebuild` runner, as `./build_app.sh` with no `--install`. The output is `<checkout>/dist.noindex/Lab Hub.app`.
2. **What gets installed is a staged copy.** As soon as Lab Hub's build passes, Lab Hub copies `dist.noindex/Lab Hub.app` to `~/Library/Application Support/Lab Hub/update/staged/` (`stage_build`). It does so only if the checkout is still clean on `main` and its HEAD is the commit stamped into the build, and the path contains no symlink. A later commit or build in the shared checkout cannot change what is installed. *(Amended after review P2-2 / security P2-2.)*
3. **The swap is done by a fixed bash script that is a constant in `lab_hub/self_update.py`.** It is started with `start_new_session=True` and takes only six values as positional parameters, all computed and checked in Python.
   - It waits for the old PID to exit (60 s max).
   - It copies the new bundle next to the target with `ditto`.
   - It renames the old bundle to `~/Library/Application Support/Lab Hub/update/previous/Lab Hub.app` and the new one into place.
   - It self-tests the installed copy (120 s max).
   - If the self-test fails, it rolls back.
   - It records a two-line outcome file and starts the result with `open`.
4. **Lab Hub quits only when it is idle.** It quits through `QApplication.quit()`, the menu bar Quit path, and only once `busy_reasons()` is empty: no `Lander.busy` on any page and no tool panel running. It checks this in the same GUI-thread call as the quit.
5. **Lab Hub's own build row is synthetic.** A `BuildStatus` with `restarts=True` is appended to the unscoped build report. It is never registered, so no tile and no menu bar entry exist.

## Consequences
- **There is always a known previous build to return to.** One previous build, about 300 MB, stays on disk until the next update.
- **An update that fails leaves a working Lab Hub** (the old one or a rolled-back one), except in the `broken` case above. The worst case is the old process not exiting within 60 s: nothing is replaced, and the owner keeps the running copy.
- **The script is a new process-spawn and `/Applications` write surface.**
  - Its inputs are paths, a version and numbers that Lab Hub computes, never text from a checkout's or a build's output.
  - It runs with a fixed environment (`PATH=/usr/bin:/bin:/usr/sbin:/sbin` and nothing that changes bash), `umask 077` and a lock. It refuses any path not named `Lab Hub.app`, a symlinked or identical source, and any argument that is not a number where one is expected.
  - It runs `rm -rf` only on the target, `$target.updating`, the kept previous build and the staged copy. Every removal and rename is checked, and a rename only goes onto a path that no longer exists.
  - A state it cannot repair is recorded as `broken`, naming where the previous build is, and nothing is opened. That is the one case in which no working Lab Hub is left, and the notice says so.
  - An EXIT trap writes an outcome if the script stops early.
- **Whether the relaunched window comes to the front is not guaranteed by this design.** It relies on `open` and `dock.activate()`, with a menu bar notice as the fallback. Verify on the real Mac decides.
- **`build_app.sh` is unchanged.** A manual `./build_app.sh --install` still works as before, so the self-update is an additional path, not a replacement.
- **The `Rebuild.hold` and `verify` hooks become part of the runner's contract.** Both are optional and default to today's behaviour.
