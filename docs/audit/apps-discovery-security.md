# Security review, spec `apps-discovery` (Phase 8, Secure)

Reviewer: `security-engineer`, read-only. Date 2026-11-21. Code: HEAD 95869a3 (code is byte-identical to 668eab2;
the only later commit is README/CHANGELOG). Scope: spec §4, §9, §10, §13.3, §13.5, ADR 0007, the two earlier
reviews (`apps-discovery-review-core.md`, `-ui.md`, whose P2/P3 fixes are in the tree and are not re-reported).

Process notes
- Playbook `docs/playbooks/security-engineer.md`: `status: current`, `last-reviewed: 2026-11-11` (10 days): not stale.
- `docs/foundry/app-context.md` is still the unfilled template (no Security surface, Invariants or Commands), so the
  threat model below is from the code and the spec. Lab Hub's own tile and the app are tier `public`.
- Every probe ran in a temp sandbox under the session scratchpad (`.../scratchpad/sec/`), with `config.SUPPORT_DIR`
  patched, `python -I`. The real `~/Library/Application Support/Lab Hub/` was never written (checked after: no
  `apps-*` file there) and neither was the real lab folder. Probe scripts: `p1_symlinks.py`, `p2_writer.py`,
  `p2_fifo_child.py`, `p4_exec_after_add.py`, `p4b_git_after_add.py`, `p5_ui.py`, `p6_terminal.py`, `p7_nonet.py`,
  `p8_deepjson.py`, `p8b_startup.py`, `p9_misc.py`, `p10_name_shell.py`, `p12_hostile_local.py` (all in that folder; paths
  below are relative to it, with `common.py` as the shared harness).

## Threat model

Assets
- The owner's login session: whatever Lab Hub starts runs as the owner (`launch`, Update now, the self-test probe).
- The lab folder's projects (Land and Update now act on them) and `/Applications/<name>.app` bundles (Update now
  trashes and replaces one).
- Lab Hub's state in `~/Library/Application Support/Lab Hub/` (`apps-local.toml`, `apps-dismissed.json`, config).
- Nothing secret is created or stored by this feature (see 8).

Trust boundaries
1. Lab folder contents -> Lab Hub: folder names, `.git`, `docs/foundry/app-context.md`, `README.md` (first 8 KiB),
   `main.py`. **Untrusted**: a cloned or unpacked project is attacker-chosen text, and every marker the scan looks for
   is an ordinary file, so a stranger's repo can satisfy it (a fork of a Foundry app does).
2. Support folder -> Lab Hub: the two state files. Same-user files, 0600 when Lab Hub writes them, but any process
   running as the owner can replace them. Treated as **input to validate for robustness**, and as **trusted for
   intent** (see P3-5: they can already make Lab Hub run things).
3. Lab Hub -> the operating system: `open -a Terminal <dir>` (argv list), `git` in project folders, the project's own
   `.venv/bin/python` and `main.py` (Launch, and the self-test), `/bin/zsh -c` for a build command.
4. The owner's click: Add to Apps is the one gate between "a folder exists" and "Lab Hub treats it as an app".

Entry points: scan (startup, Refresh), `describe`, banner buttons (Add / Not now / Never), Settings "Show again",
`registry.reload` (reads `apps-local.toml`), `--selftest`, the Open in Terminal button, Lab Hub's own tile (reads
nothing from outside; its verdict thread calls fixed `git` commands in Lab Hub's own checkout).

STRIDE in short: **Spoofing** a banner row or tile named like another app (P3-4); **Tampering** with the two state files
(P2-2, P2-3, P3-5), README to TOML (sound), scan-to-Add swap (P3-3); **Repudiation** n/a (no audit trail exists or is
claimed); **Information disclosure** nothing secret read or logged (8), symlinks refused (1); **Denial of service**
by a file in the Support folder (P2-2, P2-3); **Elevation of privilege** none across a user boundary, but Add widens what
Lab Hub itself runs (P2-1, P3-1, P3-2).

## Findings, ranked

### P0
None.

### P1
None.

### P2-1. The self-test runs an added project's own `.venv/bin/python` with no click, though Add says "Nothing is started"
- Where: `main.py:105-122` (`_probe_child_launches`: `for app in launcher.APPS` -> `launcher.venv_python(project)` ->
  `_probe_one_child` runs `<project>/.venv/bin/python -c ...`); reached through `launcher.APPS` = `Registry.apps`, which
  now contains every launchable local entry (`registry.py:169-170`). The Add tooltip (`ui/discovery_banner.py:37`,
  owner-approved) and README ("Nothing is started or changed in the project", "no program is run") say otherwise.
  Spec §13.2 listed `main.py:105` as safe because "no-launch entries are already excluded"; a local entry **with**
  `main.py` is launchable and was not considered.
- Attack: the owner puts a stranger's checkout in the lab folder (a PR branch of a public Foundry app, a cloned repo
  that carries `docs/foundry/app-context.md`, `main.py`, and a committed `.venv/bin/python`, which git can track).
  The banner shows only the README title and first sentence. The owner presses Add. At the next `--selftest`
  (the self-update helper runs it on every installed update; the owner can run it too) Lab Hub executes that file, as
  the owner, with Lab Hub's `child_env()`. No Launch click, nothing on screen.
- Reproduction: `p4_exec_after_add.py` (project `pr12` whose `.venv/bin/python` is a shell script that touches a marker):
  ```
  scan marker files after scan: []
  after add, local entry: pr12 main.py launchable True
  selftest probe result: [('Lab Hub', True, 'a real Qt child starts')]
  markers after selftest probe: ['PWNED_BY_VENV_PYTHON']
  ```
- Impact: code execution as the owner from an unvetted checkout, one click earlier and less visible than Launch.
  Needs an attacker-supplied repo in the lab folder plus the owner's Add.
- Fix direction: skip `app.local` entries in `_probe_child_launches` (the probe's purpose is Lab Hub's environment against
  curated apps); add a test with a planted interpreter and a marker file. Then keep the README sentence true, or say
  what Add does enable (git calls, P3-2; Launch).

### P2-2. A 60 KB `apps-dismissed.json` of nested brackets stops Lab Hub from starting (`RecursionError`)
- Where: `lab_hub/discovery.py:182-184` (`json.loads` inside `except (UnicodeDecodeError, ValueError)`; `RecursionError`
  is neither); callers with no guard: `ui/settings_tab.py:210-220` (`_refresh_hidden`, called from `SettingsTab.__init__`),
  built unguarded at `ui/main_window.py:115`; also `discovery.hidden`, `dismissed_ok`, `dismiss`, `forget`, `suggestions`
  (the last is wrapped by the page's broad `except` in `ui/apps_tab.py:_scan`, so it only goes quiet).
  The file is under the 64 KiB cap (`DISMISSED_MAX_BYTES`), so the cap does not help.
  Same family as core review P2-1 (deep TOML), fixed there for TOML only.
- Reproduction: `p8_deepjson.py`, then `p8b_startup.py` (builds the real `MainWindow` offscreen against the sandbox):
  ```
  file size 60000 cap 65536 -> within cap: True
  load_dismissed RAISES RecursionError   dismissed_ok RAISES RecursionError   hidden RAISES RecursionError
  suggestions RAISES RecursionError      dismiss RAISES RecursionError (UI catches only DiscoveryError)
  SettingsTab() RAISES RecursionError
  control : MainWindow built OK
  deepjson : MainWindow() RAISES RecursionError
  ```
- Impact: persistent failure to start with no message; recovery means knowing to delete a file in Application
  Support. Contradicts ADR 0007 decision 4 ("Unreadable or malformed reads as empty") and the Consequences line
  "Neither file is needed for Lab Hub to run". Accidental trigger is implausible; a local process or a bad merge tool can do it.
- Fix direction: in `_parse_dismissed` catch `RecursionError` with the other two (return None); test with `[` * 30000.
  Optionally make `_refresh_hidden` and `_dismiss_suggestion` catch `Exception` so one bad file never reaches `MainWindow.__init__`.

### P2-3. `apps-local.toml` as a FIFO hangs startup, Refresh and the self-test; `registry._read_local` lacks the hardening `discovery._snapshot` has
- Where: `lab_hub/launcher/registry.py:368` (`path.open("rb")`: follows symlinks, no `S_ISREG` check, blocking open).
  `discovery._snapshot` (`discovery.py:98-121`) does it right (`O_NOFOLLOW | O_NONBLOCK`, `fstat`), so the two readers of one
  file disagree. `registry.current()` runs on the GUI thread at startup and on every Refresh.
- Reproduction: `p2_fifo_child.py fifo` under a 6 s wrapper (`run_timeout.py`):
  ```
  == fifo
  TIMEOUT after 6 s: the process hung
  == symlink_dev_zero   -> reload -> False | local_ok False | note: Your added projects file was ignored ...
  == dir                -> reload -> False | local_ok False | note: ... cannot read ...
  ```
  The self-update helper's `--selftest` has a timeout (`self_update.py:506-508`) and rolls back on it, so this also breaks
  ADR 0007 decision 2 ("a bad local file never ... fails the self-test").
- Impact: availability, same preconditions and same class as P2-2. A symlink is also followed (read of any file the owner
  can read; only TOML error positions and top-level table names are echoed into `local_note`, so no content leaks).
- Fix direction: read the file with the same `os.open(O_RDONLY|O_NOFOLLOW|O_NONBLOCK)` + `fstat` + `S_ISREG` + capped read
  (reuse `discovery._snapshot` logic, or move it to a shared helper); a non-regular file becomes "(None, why)".
  Test: FIFO and symlink, with a timeout.

### P3-1. A README title becomes shell text if `build` is hand-added to the entry (latent injection)
- Where: `lab_hub/discovery.py:376-381` (`_name_ok` rejects only `/ \ < > &`, leading `.`, length), `registry.py:221`
  (`name` check: same set plus `Cc`), `lab_hub/launcher/state.py:1088`
  (`trash = f'"$HOME/.Trash/{app.name} before update $(date ...).app"'`, a double-quoted shell string with the name unescaped).
  `add` never writes `build`, but the spec and TODO point the owner at "add `build` to the entry by hand" as the way to
  make a project buildable (TODO lists a related note under core P2-2 residual).
- Reproduction: `p10_name_shell.py`: README `# Cool $(touch PWNED_BY_NAME)` is accepted as the name; after
  `build = "true"` and `build_output = ...` are appended, `registered_build_command` contains
  `... "$HOME/.Trash/Cool $(touch PWNED_BY_NAME) before update ..."` and `zsh -c` on that fragment creates the marker
  (`shell expanded the name: marker file created -> True`).
- Impact: needs the owner to edit the block and then press Update now; the visible name in the banner and the file
  shows the payload. P3, but it makes "a README line reaches `sh -c`" true, and it is one line to close.
- Fix direction: restrict `name` to a conservative set (letters, digits, space, `. _ - + ' ( )`) in both `_name_ok` and
  `_check_text`, or `shlex.quote` the trash path and build it with `$HOME` outside the quotes.

### P3-2. After Add, Lab Hub runs `git status` in an untrusted `.git` (config-driven commands such as `core.fsmonitor`)
- Where: `lab_hub/launcher/state.py:840` (`checkout_version` -> `_is_dirty` -> `dirty_checkout`, `:693-701`, `:1139`
  `git status --porcelain`), reached for every tile including a no-launch tile (`state.py:864-866`). The scan itself runs no
  git (7).
- Reproduction: `p4b_git_after_add.py` (git 2.56.1): a repo whose `.git/config` sets `core.fsmonitor` to a `touch` command;
  after Add, `version()` + `build_status()` ran `git rev-list`, `git rev-parse`, `git status --porcelain` and:
  `fsmonitor fired: True`.
- Impact: only an attacker-supplied `.git` directory carries such config (a normal `git clone` does not transfer it; an
  archive or copied folder does). The other registered apps and git_autosync's hygiene run share this exposure; what is new is
  that Add extends it to a folder the owner never vetted.
- Fix direction: run Lab Hub's read-only git calls with `-c core.fsmonitor=false` (and `GIT_OPTIONAL_LOCKS=0`), or only
  call `git status` for a project that has been Added from a folder inside the lab's own trusted set. Cheap in one place:
  a shared `git` argv prefix in `state.py`.

### P3-3. Scan-to-Add race: Add re-checks nothing, so the symlink and `.git` guards can be bypassed after the banner is drawn
- Where: `lab_hub/discovery.py:586-618` (`add`) trusts the `Suggestion` computed at scan time; `ui/apps_tab.py:_add_suggestion`
  passes it straight in; the banner stays up until the next scan (startup/Refresh).
- Reproduction: `p9_misc.py`: scan gives `kaila` (main.py), the folder is replaced by a symlink to another directory, Add:
  `Add after swap-to-symlink: ADDED kaila main.py | is_dir via link: True`. The tile then follows the link (`source_dir`
  uses `is_dir()`, which follows it) and Launch would run the target's `main.py`.
- Impact: needs write access to the lab folder, i.e. the same actor who could just run the file. Low; but the spec (§4.1,
  §13.3) says a symlinked project is never suggested, and Add is where that stops being true.
- Fix direction: factor the per-folder conditions of `scan` into one function and call it again in `add` (and recompute
  `entry` from `main.py` there). One test: swap after scan, expect `DiscoveryError`.

### P3-4. The banner hides which folder it means, and a README title can pose as another app
- Where: `ui/discovery_banner.py:79-91` (row shows lead-in, the README name, the sentence: no folder name; the accessible
  name is the title too), `registry.py:322-360` (`merge_local` has no name rule; TODO already lists "two tiles can still
  carry one name").
- Scenario: a stranger's checkout in `evil-thing/` with README `# Sentinel` is offered as "New project in your lab folder:
  Sentinel"; Add gives a second "Sentinel" tile with a Launch button for `evil-thing/main.py`. Core P2-2 stopped it from
  controlling the installed bundle; it did not stop the look-alike. Names pass through without a Unicode confusables check.
- Impact: social engineering, one step before P2-1 or a Launch click. The tile's `detail` line does show the project path.
- Fix direction: show the folder in the banner row (muted, e.g. `kaila/`), add a name-clash note in `merge_local`
  (case-insensitive against every registered name and `Lab Hub`), and fall back to the folder name when a title collides.
  Wording needs the owner (§7 approved words).

### P3-5. A hand-edited `apps-local.toml` can set fields that are not validated; the trust boundary is not written down
- What a hostile or hand-edited file can make Lab Hub do (`p12_hostile_local.py`; field checks are only on key, name,
  project, entry, see `registry.py:209-238`):
  - `project` + `entry` + `args`: Launch or the tray runs any file under the lab folder with `<venv python or python3>`
    (or, `runtime = "node"`, `/bin/zsh -lc "exec node <entry> 'arg' ..."`, args quoted: `Popen (['/bin/zsh', '-lc', "exec node .../proj/tool.py --flag '$(id)' '; rm -rf ~'"]`).
  - `build` + `build_output`: a raw shell string run by Update now (`registered_build_command` carries it verbatim).
  - `url`: `open <url>` with any scheme or path (`open_url argv: ['open', 'file:///Applications/Calculator.app']`).
  - `bundle_dir` with `..`: resolves to any `.app` and defeats the `local` guard on `/Applications/<name>.app`.
  - `service`, and `project` in the `detail` line, reach labels that are auto-text, so markup renders
    (`p5_ui.py`: `rich?=True` for `no folder at .../<b>proj</b>` and for a `service` link; no link opens, nothing is fetched,
    `openExternalLinks` is False). Cosmetic; README-derived text never gets here (all PlainText, 3).
  - `local = ...` cannot be set from the file (`unknown field(s): local`).
- Assessment: a process that can write the Support folder can already do all of this by other means (edit `~/.zshrc`, a
  login item, the app bundle), and `SECURITY.md` puts "problems that need an attacker who already controls your Mac"
  out of scope. **The boundary is acceptable**, but it is written nowhere for this file: ADR 0007 and README describe
  `apps-local.toml` as "the same format" and a source of tiles, not as a file that carries launch and build commands.
- Fix direction (docs, one sentence in ADR 0007 Consequences and README "How the list is made"): "`apps-local.toml` is
  as trusted as `apps.toml`: it can name a project script to run and a shell command to build; Lab Hub validates its shape
  to stay up, not to contain it." Optionally validate `bundle_dir` (no `..`) and set `Qt.PlainText` on the `service` and
  `detail` labels (`ui/apps_tab.py:226,284,477`, `ui/tiles.py:118`) for the stated invariant of spec §12.6.

## Checked and found sound (with evidence)

1. **Path escape and symlinks** (`p1_symlinks.py`, sandbox). Scan result with all of: symlink to outside, symlink to inside,
   symlinked `.git`, symlinked `app-context.md`, symlinked `docs`, README symlink to a secret, README FIFO, `main.py`
   symlink, 11 junk names (space, quote, newline, 65 chars, leading `-`/`.`/`_`, accent, `;`, `$(...)`, backtick):
   `names: ['fifo', 'good', 'mainlink', 'readmelink']`. The four are correct and safe: the FIFO and symlinked README fall
   back to the folder name and `A project in your lab folder.` (returns in 0.001 s, no hang), the `main.py` symlink gives
   `entry=None`, and the secret's text never appears. Case folding: registered `KAILA`, `./kaila`, `kaila/`,
   `Kaila/../kaila` each suppress the folder `kaila` (`p9_misc.py`). `NAME_OK` is ASCII, so no Unicode normalisation gap.
2. **Writer** (`p2_writer.py`, `p9_misc.py`). 11 hostile READMEs (`]]\n[[suites]]` injection, `"""`, trailing backslash, NUL, ESC,
   U+2028, U+0085, bidi override, U+FFFE, emoji, markup, a 5000-character line, a 500-character title) added; the file read
   back has exactly 11 `suites` tables and only the five known keys; mode `0600`; no temp file left; no entry with a path
   outside its folder. Seven directly hostile `Suggestion` objects (markup name, `../etc`, `../../bin/sh`, newline in name,
   lone surrogate, space in key) are refused with the file unchanged. **Verify-before-write works as a second layer**:
   with `toml_string` replaced by a naive `'"' + v + '"'`, `add` refuses (`the entry does not parse`) and the file is
   unchanged. A patched `os.replace` failure leaves the original and no `.tmp`. A stale `<name>.<pid>.tmp` makes the first
   Add fail with "File exists" and is removed, the next Add works. A `.tmp` pre-created as a symlink to a victim file is
   refused by `O_EXCL`, the link is removed and the victim is intact. Symlinked or FIFO `apps-dismissed.json` is refused
   (`Too many levels of symbolic links`, `is not a regular file`), target untouched, no hang. A corrupt dismissals file is
   set aside as `.bad`, a second one as `.bad.1` (core P3-3 fix holds). Over-cap file (64 KiB + 10) reads as unreadable.
3. **README to UI** (`p5_ui.py`). Every label that can hold README text (banner name, sentence, error line, tile name, tile
   summary, version, hygiene, `local_note`, Settings error) is `PlainText`; tooltips go through `plain_tip` (`html.escape`);
   `openExternalLinks` is False everywhere; long names are elided (58-character title: `WWWWWWWWWWWWWWWWWWWWWW…`, full text in
   the tooltip); the sentence is 215 of 220 characters at most. Control, format (bidi, zero-width) and unassigned code points
   are dropped by `describe` before anything is shown or written (`‮`, `​`, `\x1b` gone in `p2_writer.py` output).
   A README whose first line is a tag (`<a href=...>`) is treated as a tag line and skipped. `QMessageBox` text:
   `Qt.mightBeRichText` looks only at the first line (checked, `p11b.py`), and the boxes that carry a name put it after fixed
   words, with `<>&` already refused in names, so no README-derived string can start a rich-text box.
4. **Open in Terminal and Lab Hub's tile** (`p6_terminal.py`). The whole action is
   `subprocess.run(['open', '-a', 'Terminal', str(path)])` (`control.py:353-363`), an argv list with no shell and no
   AppleScript; with a project named `x"; do shell script "touch pwn" -- $(id) `id` 'q` the argv is exactly that one element
   (`shell=False`). A symlinked project opens its target directory only; a project that is a file gives no repo path (the
   button needs `is_dir`), so Terminal is never asked to open a script. Lab Hub's tile reads no outside text: its thread
   runs fixed `git` commands in its own checkout; no Launch, Stop or Quit exists on it (`OWN_TILE.entry is None`).
5. **`local_note` and `DiscoveryError`**: PlainText label with a `plain_tip` tooltip (`ui/apps_tab.py:790-800,945-950`), status
   bar (Qt paints `QStatusBar` messages as text: from Qt's source, **not tested here**), Settings and banner error lines
   PlainText. Content is path, TOML position, field names and OS `strerror`; nothing from a README except the project
   name, which is already validated. Hand-edited field names are echoed (`unknown field(s): ...`) but only as text.
6. **No network, no subprocess in the scan** (`p7_nonet.py`): `subprocess.run/Popen/check_output/call`, `os.system/popen/
   execv/posix_spawn/fork`, `socket.connect`, `create_connection`, `getaddrinfo` and `urlopen` all replaced by raisers,
   then `suggestions`, `describe`, `add`, `reload`, `dismiss`, `hidden`, `forget`, `dismissed_ok` run:
   `blocked calls attempted: []`. Grep: `lab_hub/discovery.py` imports `itertools json os stat tomllib unicodedata` and
   `config`, `registry` only; no `subprocess`, `socket`, `urllib`, `logging`, `print`, `environ`.
7. **Dependencies and packaging.** No change to `requirements.txt`, `requirements-dev.txt`, `Lab Hub.spec`, `build_app.sh`,
   `scripts/`, `THIRD_PARTY_NOTICES.md` since the spec's base commit (`git diff ade8e4b..HEAD --stat` over those paths is empty).
   New imports across the diff are stdlib (`tomllib` is already used by the registry), repo modules and PySide6 classes
   already shipped; the new modules are imported statically so PyInstaller picks them up; `apps.toml` is already in `datas`.
   Dependency audit on the **installed** set (playbook): 43 distribution names and versions read from the venv's
   `*.dist-info`, sent to `https://api.osv.dev/v1/querybatch` (package names and versions only): **0 advisories**. No
   `pip-audit` is installed; bundled Qt (PySide6 6.12.0) is not covered by OSV PyPI. `gitleaks` over `ade8e4b..HEAD`
   and the working tree: no leaks. Runtime venv is Python 3.11.15, so `tomllib` exists.
8. **Secrets and logging.** Nothing is read from the environment, Keychain or `.env`, nothing is logged
   (`main.py` prints `local_note`, a path and a TOML error, in the self-test only). State files hold folder names, dates and
   one README sentence, mode 0600 (the Support folder itself is 0755, like the rest of Lab Hub's state). A README sentence
   can contain anything the README does; it is copied into the 0600 file and shown on screen.
9. **Lab Hub as a threat to its own update.** `main.py:_app_list_problems` still fails the self-test on `last_error` (apps.toml)
   only; a garbage local file is printed, never a problem (existing test; I confirmed by reading, and P2-3 is the exception).

## Not verified
- The full test suite (QA's run), lint and types (no linter in the venv).
- `QStatusBar` rendering of markup-looking text (Qt source reading only), VoiceOver, macOS font metrics.
- `open -a Terminal` against a real Terminal (argv checked with a spy, not executed).
- A real macOS self-update run with a hostile local file (P2-1 reproduced through `main._probe_child_launches`, which is the
  function `--selftest` calls; the helper script itself was not run).
- `core.fsmonitor` behaviour on other git versions (reproduced on 2.56.1 only).
- Behaviour of Land and Ask Claude on an added project: reused unchanged, not re-reviewed here (their own security reports
  cover them: `land-from-tiles-security.md`, `claude-handoff-security.md`).

## Verdict: PASS with fixes
No P0 or P1. Fix the three P2 before Verify's screenshots and release: P2-1 (skip local entries in the self-test probe; the
Add tooltip and README promise otherwise), P2-2 (`RecursionError` in the dismissals reader) and P2-3 (FIFO and symlink in
`registry._read_local`); each is a few lines with a one-line test. The P3 items can be batched or deferred by the owner in
writing; P3-5's one-sentence trust statement belongs in ADR 0007 and the README before the next Document pass closes.

## Residual risks the owner accepts
1. **Same-user write access to the Support folder is code execution** through `args`, `build`, `url` and `entry` in
   `apps-local.toml` (P3-5). Consistent with `SECURITY.md` scope; accept, or ask for the sentence in the ADR.
2. **Add on an untrusted checkout is still "run its code" one Launch click later**, and it lets Lab Hub run `git` in it
   (P3-2) and read its README into a 0600 file. The owner's Add is the vetting step; the banner shows the title, not the
   folder (P3-4).
3. **Look-alike names**: two tiles can carry one name until the P3-4 rule exists (already on the TODO).
4. **The scan stops at 400 directory entries** (files included) and says nothing; a very large or hostile lab folder
   silences suggestions. Scan runs on the GUI thread, so a stalled network mount would stall Refresh (`ps` already has that exposure).
5. **No folder `fsync`** after `os.replace`: a power cut right after Add can lose the entry, which is offered again.
6. `.bad` copies of a damaged dismissals file keep the original file's mode and are never cleaned up.
7. Bundled Qt/PySide6 advisories are not covered by an OSV PyPI query; they are tracked by the radar's watch list.
