# Secure: self-update (security-engineer, 2026-11-17)

Read-only review of the uncommitted `self-update` change. The reviewer's harness did not allow writing files, so the orchestrator saved its report here unchanged in substance. Playbook `docs/playbooks/security-engineer.md` is current (last reviewed 2026-11-11). `app-context.md` still has template placeholders in Security surface, Stack and Invariants, so scope came from the brief, the spec and ADR 0003.

## Summary

**No P0 or P1.** The change crosses no privilege boundary:
- the helper runs as the owner and asks for no extra rights;
- there is no network surface;
- the only inputs are the owner's checkout and `~/Library/Application Support/Lab Hub/` (`~/Library` is 0700).

**2 P2 findings, both reproduced** against the real `HELPER_SCRIPT` with fixture bundles. In each, a failed update can leave no working Lab Hub while the outcome says otherwise.

**6 P3 items** for hardening.

## Threat model

- **Assets:**
  - the installed `/Applications/Lab Hub.app`, which runs Land;
  - the kept previous build;
  - the integrity of what gets installed: it should be a clean build from `main` that passed its self-test;
  - the owner's environment, which may hold Narrator API keys.
- **Trust boundaries:**
  - Lab Hub → the detached `/bin/bash` helper;
  - the helper → `/Applications`;
  - the helper → the checkout's `dist.noindex/`, which is shared with other sessions;
  - the helper → the new build's `--selftest`;
  - the outcome file → the UI and tray.
- **Entry points:**
  - Update now: `self_status` → `Rebuild` → `hold`;
  - Close and restart: `restart_for_update` → `helper_paths` → `start_helper`;
  - the helper's six arguments and its environment;
  - `read_outcome` at startup.
- **Baseline:** anyone who can write to the checkout can already run code as the owner through `./build_app.sh --install`. The helper adds nothing to that. `checkout_blocker` guards against another session's half-done work; it is not a security control.

## P2-1: Rollback and cleanup ignore `rm`/`mv` failures

**Where:** `lab_hub/self_update.py`, the unchecked `rm -rf "$staged"`, `rm -rf "$backup"`, `[ "$had_old" = 1 ] && mv "$backup" "$target"`, and the rollback's `rm -rf "$target"; mv "$backup" "$target"`.

**Scenario (reproduced):**
1. The new build fails its installed self-test.
2. `rm -rf "$target"` cannot remove everything. The fixture used a read-only folder; in real use, the Finder `.DS_Store` race that `build_app.sh` already retries for would do the same.
3. `mv "$backup" "$target"` then moves the old build *into* the leftover directory, as `Lab Hub.app/Lab Hub.app`.
4. The outcome says "the previous build is back", and `open` launches a folder that is not an app.

The same nesting happens if `rm -rf "$backup"` failed before an update.

**Impact:** no working Lab Hub, and the notice says the opposite. This disproves the ADR's claim that a failed update "leaves a working Lab Hub".

**Fix:**
- Check every `rm -rf` and `mv`.
- Require that the destination does not exist before each `mv`.
- Retry `rm -rf` once.
- On a failed restore, write a distinct token (`broken`) whose message names where the previous build is, and do not `open`.
- Add tests.

## P2-2: The helper installs whatever is at `dist.noindex/Lab Hub.app` when Close is pressed

`src` is not checked against symlinks, and `rm -rf "$src"` is not validated.

**Where:**
- `helper_paths` checks `src` only with `is_file()` on the executable, which follows symlinks, and never compares it with `target`;
- the bash side has only an `-x` check, then `rm -rf "$src"`;
- `restart_for_update` does not check the checkout again;
- `checkout_blocker` runs only before the build.

**Scenario A (realistic):** the window waits for "Close and restart" as long as it stays open. Meanwhile, another session sharing the checkout commits or runs `./build_app.sh`. The helper then installs a different or half-written bundle. That is exactly what spec §5.3 is meant to prevent.

**Scenario B (reproduced):** `dist.noindex` is a symlink to the Applications folder.
1. `helper_paths` accepts it.
2. The helper copies the installed app over itself.
3. `rm -rf "$src"` then deletes the freshly installed app through the symlink.
4. The outcome says `ok`, but `/Applications` has no Lab Hub.

**Impact:** a build that was never checked gets installed, or nothing is installed while the notice says "updated". There is no privilege gain.

**Fix:**
- When Lab Hub's build succeeds, copy it into `UPDATE_DIR/staged/Lab Hub.app`, which Lab Hub owns outside the checkout, and record its build commit.
- At restart, run `checkout_blocker` again, require HEAD to equal that commit, and pass the staged path.
- In Python, require no symlinks in `src`, `src != target`, and the name `Lab Hub.app`.
- Check the same in bash.
- Add tests.

## P3-1: The helper inherits Lab Hub's whole environment

`child_env()` passes everything to `bash -c`. Reproduced with bash 3.2.57:
- `BASH_ENV` is sourced;
- an exported `BASH_FUNC_ditto%%` replaces `ditto`;
- `LAB_HUB_UPDATE_WAIT_S='PATH[$(…)0]'` runs a command substitution inside `$((…))`;
- a non-numeric value makes `set -u` exit 127 with no outcome written and nothing reopened.

`open`, `ditto` and the rest are looked up on the inherited `PATH`. Narrator keys loaded into `os.environ` reach the helper and the self-test. Only something already running as the owner can set any of this.

**Fix:**
- Give the helper a minimal environment: `PATH=/usr/bin:/bin:/usr/sbin:/sbin`, `HOME`, `USER`, `LANG`, `TMPDIR`.
- Clamp the timeouts to digits, or make them module constants.
- `claude_resolve.py` already strips `BASH_ENV`, so this follows existing practice.

## P3-2: Log and outcome file modes, symlinks and reading

- Both files get the default umask (about 0644) and both follow symlinks.
- `read_outcome` reads the whole file, so a FIFO there would block the GUI at startup.
- Contents are paths and versions, not secrets. A process running as the owner could fake the outcome.

**Fix:**
- Create the log with `O_NOFOLLOW` and mode 0600, and the folder with 0700.
- Add `umask 077` in the script.
- In `read_outcome`, require `is_file()` and read at most about 4 KB.

## P3-3: Gaps where no app ends up running

- If the old process quits after the 60 s wait, the helper has already exited without `open`, so no Lab Hub runs.
- If the helper is killed between the two `mv` calls, `/Applications` has no Lab Hub.
- If the home folder is on another volume, `mv "$target" "$backup"` is a slow copy, not a rename.
- There is no lock against two helpers running together.
- An early bash error writes no outcome.

**Fix:**
- Add a `mkdir` lock.
- Add an EXIT `trap` that writes an outcome if none was written.
- Name the recovery path `update/previous/Lab Hub.app` in the notice.

## P3-4: Test-only knobs ship in production

The `LAB_HUB_UPDATE_*` variables are a test seam that the shipped app honours. Spec §9.5 allows only a patched module constant. Covered by the P3-1 fix.

## P3-5: Spec and ADR overstate the code

The ADR and spec §9.2 claim three things the code does not do:
- "`rm -rf` only on paths derived from the target and the support folder" (`rm -rf "$src"` runs on a checkout path);
- "leaves a working Lab Hub" (disproved by P2-1);
- "outcome file written at every exit" (not true for early errors).

## P3-6: Missing tests

- a symlinked `dist.noindex`, and `src` equal to `target`;
- a failed `rm` or `mv` during rollback;
- non-numeric timeouts;
- an old process that exits late;
- two helpers running together.

## Checked and sound

- **Injection:** the script is a constant, its six values are positional, every expansion is quoted, there is no `eval`, and `Popen` gets a list with no shell. `build_command` uses `shlex.quote`.
- **Target:** a fixed path that must equal the resolved running bundle. `rm -rf` on a symlinked final path removes only the link.
- **Restart:** it fires only after the rebuild succeeded.
- **Login item:** it has `RunAtLoad` only and no `KeepAlive`, so launchd will not relaunch the old copy while the helper waits.
- **Dependencies:** no manifest change. `pip-audit` was not installed, so the reviewer used the OSV querybatch API on the 43 packages in the venv: 0 advisories (2026-11-17).

The real `/Applications` swap was not run; **not verified**.

## Resolution

Fixed on 2026-11-17 by the engineer (spec §10):
- **P2-1:** every removal and rename is checked, and a failed restore is recorded as `broken`.
- **P2-2:** the install uses a staged copy with no symlinks, checked against HEAD.
- **P3-1 and P3-4:** the helper gets a fixed environment, with absolute `ditto` and `open` and numbers that are checked.
- **P3-2:** the log is 0600 and `O_NOFOLLOW`, the folder 0700, the script runs under `umask 077`, and the outcome read is bounded to a regular file.
- **P3-3:** lock, EXIT trap, and a reopen after a late quit.
- **P3-5:** the ADR was corrected.
- **P3-6:** tests were added.

Still not fixed: if the helper is killed between the two `mv` calls, it leaves no app, and the EXIT trap does not run on SIGKILL. The previous build stays in `update/previous/`, and the README names it as the way to recover.
