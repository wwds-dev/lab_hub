# Security review: Update now opens Terminal installers (spec update-now-terminal)

Role: security-engineer (Secure phase). Read-only review of the uncommitted diff
(`git diff -- lab_hub ui`, 2026-11-16). No code was changed. Playbook
`docs/playbooks/security-engineer.md`: last-reviewed 2026-11-11, status current (not stale).
`docs/foundry/app-context.md` is still the empty template (Security surface, Invariants, Stack
unfilled); scope was taken from the task and the spec. Tier: public.

Result: P0 0, P1 0, P2 2, P3 5.

## Threat model (this change)
- Assets: the owner's login session and files (the installer runs as the owner, in a login shell);
  /Applications bundles; `~/Library/Application Support/Lab Hub/` contents.
- Trust boundaries: (a) Lab Hub process -> `.command` file on disk -> Terminal.app (LaunchServices);
  (b) Lab Hub -> project checkout / release clone (repo content is untrusted-ish but is already
  executed by the existing Update now); (c) the stub bundle's `project_root.txt` (state.py:96-101)
  decides which directory is `cd`'d into (writable only by whoever can write /Applications bundles).
- Entry points: `show_build_report` -> `run_updates(commands, by_hand)` (ui/apps_tab.py:909, 982,
  1005-1006) -> `launcher.run_in_terminal` (control.py:362). Command strings come from
  `install_command` (state.py:993-1016): `cd <shlex.quote(project)> && ./<name>[ --install]`.
- What an attacker-controlled repo can influence in that string: which of the three fixed script names
  exists (`BUILD_SCRIPTS`, state.py:979), whether ` --install` is appended (substring in the script,
  state.py:1011), and whether the app is routed to Terminal at all (substring `-t 0`, state.py:1031).
  It cannot add shell syntax: `relative` is one of three constants and is the only unquoted piece.
  It does control what the script itself does, which is already true of Update now and Copy commands.

## Verified negatives (tested, not assumed)
- Injection through the project path: a directory named with `'`, `$(touch ...)`, backticks, `;`,
  `"` and `!`, quoted with `shlex.quote` into a zsh script, ran only the intended script; no side
  effect file was created. Newline in the path is refused by the guard (control.py:378-380),
  fail-closed (ValueError; see P3-3).
- Pre-created symlink at the fixed name `install-1.command` pointing at another file: not followed.
  `glob("*.command")` + `unlink` (control.py:390-391) removes the link itself first; the target kept
  its content. A symlink not ending in `.command` is ignored and cannot be hit because the fixed
  names are `install-N.command`.
- Final mode is 0700 even with `umask 000` (control.py:402).
- `~/Library` is `drwx------` and `Application Support` is `drwx------+` on this Mac, so another
  local user cannot reach `terminal-runs`; the symlink/race findings below need the same account,
  which already owns the session.
- `open -a Terminal <abs path>`: argument list, no shell, path starts with `/`, so no option or
  shell injection at the launch step (control.py:403-404).

## Findings

### P2-1 Terminal routing and the "you confirm there" assurance are repo-controlled, not enforced
state.py:1031 (`"-t 0" in text`), state.py:1163, ui/apps_tab.py:915-921.
Scenario: a checkout or release clone (or a repo update pulled by Land/Resolve) whose
`scripts/install_app.sh` contains the text `-t 0` (a comment is enough) is classified `by_hand`, and
Update now now starts it in a real Terminal in one click. The dialog tells the owner "You confirm
there (Provisio's asks you to type install)", but nothing checks that this script asks anything.
Impact: no new code-execution primitive (the same script would already run under Update now through
RebuildDialog, and the owner could paste it from Copy commands), but the new path runs it with a tty,
a login shell (`#!/bin/zsh -l`, control.py:397), no Cancel, no captured output in Lab Hub, and a
prompt the script can imitate. The script content is read at report time and executed later, so what
was previewed is only the command line, not the script.
Fix: keep the dialog wording honest ("runs this app's installer in Terminal; Lab Hub cannot see what it
asks"); show the script path and its git state (clean/dirty, commit) in the dialog; restrict
by-hand routing to scripts that are tracked and unmodified (`git status --porcelain -- <script>`
empty), or require an explicit per-app opt-in. Not blocking, because the trust in repo scripts is
the existing design.

### P2-2 `open` failure is ignored and success is announced (A10)
control.py:403-404 (`check=False`, return code and stderr discarded); ui/apps_tab.py:1006-1011.
Scenario: Terminal missing, LaunchServices error, or the file removed/unreadable. The status bar
still says "Opened Terminal for 1 installer". Related race: `open` returns before Terminal reads the
file; a second Update now click unlinks and rewrites `install-N.command` (control.py:390-401) in
that window, so the first window can run the newer content or find nothing.
Impact: owner believes an installer started; no secret leak. Integrity risk is self-inflicted.
Fix: check `returncode`, raise or report a failure naming the file; make the file name unique per
run (timestamp or `tempfile.mkstemp(dir=..., suffix=".command")`) and prune old ones by age instead
of unlinking everything at the start.

### P3-1 File and directory created with default mode, then chmod
control.py:387-388 (`mkdir` then `chmod(0o700)`), control.py:394-402 (`write_text` then `chmod`).
The file exists for a moment as 0666 & ~umask and non-executable; the directory as 0777 & ~umask.
Not exploitable here (parent directories are 0700, file is not executable until the chmod), but the
spec asked for "mode 0700 at creation". `chmod` on a symlinked `terminal-runs` also follows it
(verified: a symlinked directory was chmod'ed to 0700 and filled with the file).
Fix: `directory.mkdir(mode=0o700, ...)`, refuse if `directory.is_symlink()`, create the file with
`os.open(path, O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW, 0o700)` and write through the descriptor.

### P3-2 Same-user race between unlink and create
control.py:390-401. A process of the same user could plant a file or symlink at `install-N.command`
between the unlink and the write. Needs the same account, which already has everything the file
could give. Resolved by the `O_EXCL|O_NOFOLLOW` fix in P3-1.

### P3-3 Uncaught exceptions leave a silent, half-done Update now
control.py:378-380 raises ValueError for a path with a line break; a directory named `*.command` in
the folder makes `unlink` raise PermissionError (verified); neither is caught at
ui/apps_tab.py:1006. By then the in-app rebuilds have already run and replaced apps. PySide6 prints
the traceback and carries on, so the owner sees nothing happen.
Fix: validate `by_hand` commands before starting any rebuild, and catch `ValueError`/`OSError`
around `run_in_terminal` with a message box.

### P3-4 Non-UTF-8 encoding of the script text
control.py:394 `write_text` uses the locale encoding (`US-ASCII` under `LC_ALL=C`, verified with
`locale.getpreferredencoding()`); a non-ASCII project path would raise after the file was created
(empty, 0644, not chmod'ed) and abort the rest. Not verified for a GUI launch.
Fix: `encoding="utf-8"` (done by the `os.open` rewrite as well).

### P3-5 Executable `.command` files stay after the run
They remain in `terminal-runs` until the next Update now and can be double-clicked from Finder to
re-run an old install command. Low impact, mode 0700 in a private folder.
Fix: have the script end with `rm -- "$0"` (or prune on app start), and make
`run_in_terminal(directory=...)` refuse a directory other than the default or a fresh temp dir,
since it globs and unlinks `*.command` in whatever is passed (control.py:390).

## Not verified
- How Terminal.app invokes a `.command` file (own shell vs shebang) and whether macOS warns about it;
  the spec lists this as unverified (spec §6). Not run on the real Mac.
- No dependency change in this diff, so no `pip-audit` was run.
