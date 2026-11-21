# Code review, spec `apps-discovery`, PART 1 (core)

Reviewer: `code-reviewer` (independent of the author), read-only. Date 2026-11-21.
Range: `git diff ade8e4b..93d1b07` (4 commits: dde0687, e7737c6, 4a103a8, 93d1b07). UI files
(`ui/apps_tab.py`, banner, settings, `own_verdict.py`) are PART 2 and were not reviewed here, except
where a core function is called from them (cited as `HEAD:`).
Contract: spec `docs/specs/apps-discovery.md` §4-§7 and §13, ADR 0007 (accepted).

Process notes
- Playbook `docs/playbooks/code-reviewer.md`: `last-reviewed 2026-10-14`, `status: current` (38 days): not stale.
- `docs/foundry/app-context.md` is still the unfilled template (no Commands, no Invariants, no Architecture hot
  spots), so there is no named local check. I used the repo's own `pytest.ini` suite.
- Method: the commit was exported with `git archive 93d1b07` into the scratchpad (the working tree holds another
  session's UI commits, and `git checkout` was off limits). All probes ran there with `python -I`.

## Evidence run
- `pytest tests/test_discovery.py test_registry.py test_launcher.py test_self_update.py test_selftest_app_list.py
  test_tray.py test_wake_start.py` on the export: **455 passed, 2 failed**. The 2 failures
  (`test_the_commit_count_is_read_from_a_real_repository`, `test_this_project_reports_its_own_version`) need a
  `.git`, which the export has not; both pass in the real worktree (run read-only, `-p no:cacheprovider`).
- Scan against the real lab folder with the real shipped registry: exactly `kaila`, `overseer`, `shopfront`, as
  §13.11 predicts. No `foundry`, `toolbox`, `lab_hub`.
- Hand-made **mutation run, 95 mutations** (every `# condition:` line, the writer, the guards, the merge): **81 killed,
  14 survived**. The survivors are listed under P3-5; none is a missing detection rule.
- Every reader of `app.entry` in the whole repo at 93d1b07 (`git grep -n "\.entry\b"`, plus `lab_hub/tools`,
  `scripts`, `ui/`, `main.py`): `control.py:181,260,276` (behind the two `launchable` guards at 164 and 211),
  `state.py:126,132` (behind the guard at 123), `state.py:196` (guarded), `state.py:925-929` (guarded, and unreachable).
  No reader in `ui/`, `scripts/`, `lab_hub/tools/`, `main.py`. **Safe for `entry is None`.** The 9 shipped entries
  all pass the new `_check_text` and read as before (`test_every_shipped_entry_is_launchable...`).

## Findings

### P0
None.

### P1
None.

### P2-1. "A bad local file never fails the hub or the self-test" is true for typos, not for two odd inputs
`lab_hub/launcher/registry.py:198-228` (`_check_text`), `:237` (`parse`), `:346-366` (`_read_local`),
`lab_hub/discovery.py:486-502` (`suggestions`).
ADR 0007 decision 2 and `main.py` `_app_list_problems` promise that nothing in `apps-local.toml` can break startup
or the self-test (a failed self-test rolls an update back). Two inputs get through:
1. `project = "a\u0000b"` (a TOML escape, valid) passes `_check_text` (it checks `Cc` only for `name`).
   `registry.current()` parses it fine; then `discovery.suggestions()` calls `os.path.realpath(root / "a\x00b")` and
   raises `ValueError: embedded null byte`. `ui/apps_tab.py` `_scan` (HEAD:937) calls it with no `try`, on the GUI
   thread, at startup and on every Refresh.
   Repro: `/private/tmp/.../scratchpad/probe/nul.py` (prints `RAISES ValueError embedded null byte`).
2. A deeply nested value (`a = [[[[ ... ]]]]`, 5000 deep, well under the 256 KiB cap) makes `tomllib` raise
   `RecursionError`, which `parse` (only catches `TOMLDecodeError`) and `_read_local` (only catches `RegistryError`)
   let through. `registry.current()` raises, so the app does not start and `--selftest` crashes.
   Repro: `probe/deep.py` prints `current() raises RecursionError`.
Same family: `project = "."` is accepted (`probe/nul.py`: tile for the lab folder itself; `_clash_key(".")` overlaps
nothing). Not typo-likely, so P2 and not P1, but the guard is the whole point of `_check_text`.
Fix direction: in `_check_text` reject any `Cc` (and NUL) in `key`, `project`, `entry`, and a `project` whose
`posixpath.normpath` is `.` or empty; in `parse` catch `(tomllib.TOMLDecodeError, RecursionError)`; in `suggestions`
catch `(OSError, ValueError)` and return `()`. One test each (NUL project, deep nesting, `.`).

### P2-2. A README title decides which installed app a tile controls
`lab_hub/discovery.py:392-396` (name from the README heading), `lab_hub/launcher/state.py:48-50` (`bundle_path`
joins `name` into `/Applications/<name>.app`), `lab_hub/launcher/registry.py:305-343` (`merge_local` never
compares names).
A suggested project that has a `main.py` gets `entry = "main.py"`, so it is launchable, and its `name` comes from an
untrusted README. If that title equals an installed bundle, the new tile launches, raises and shows "Running" for
the other app. Probe (`probe/hostile.py`, README `# Safari`): the entry is added, and
`launcher.bundle_path(ExternalApp("p6","Safari","p6","main.py","x"), ...)` returns `/Applications/Safari.app` and
`can_bring_to_front` is True. Realistic case, no hostility needed: a clone, fork or copy of SONAR/Imprint in a new
folder keeps the README title "SONAR", so its tile opens the installed SONAR instead of the copy's source.
The name is shown in the banner before Add, so the owner can see it, but nothing tells them it collides.
Fix direction: in `add`/`scan`, when the project is launchable and `/Applications/<name>.app` exists, or the name
equals (case-insensitive) a registered app name, use the folder name instead; and give `merge_local` a name-clash
rule with a `local_note` line. One test with a temp `APPLICATIONS`.

### P3-1. `# C#` becomes "C"
`lab_hub/discovery.py:332` (`.rstrip("#")`). Probe: README `# C#` gives name `C`; `# F#` gives `F`. The closing
`#` run of an ATX heading must be preceded by a space. Fix: strip with `re.sub(r"\s+#+\s*$", "", text)`.

### P3-2. README text is shown raw: markdown, quotes, bullets, setext titles
`lab_hub/discovery.py:358-411` (`describe`). On the real lab folder the registered projects would read
`**Version:** \`v1.xxx\`, derived — see [Versioning](#versioning).` (Backstage) and `...with **paper money instead
of promises**.` (SONAR). Probes: a `> tagline` line is kept with its `> `; a bullet list gives `- one - two`;
`Kaila\n=====` gives name = folder and summary = `Kaila`. Not unsafe (PlainText, escaped), but §4.5 says the
sentence is "shown as found" and the banner text is the first thing the owner sees. The three projects the first run
offers (Kaila, Overseer, Shopfront HQ) read cleanly, so this is polish. Fix direction: drop `>` and list lines like
badges, strip `**`, backticks and `[text](url)` to `text`, treat a setext underline as a heading.

### P3-3. A second corrupt dismissals file overwrites the first `.bad`
`lab_hub/discovery.py:231` (`os.replace(path, ... ".bad")`). Probe: `{bad1` then `{bad2` leaves only `{bad2`. The
`.bad` exists so older answers survive; a second corruption loses them. Fix: `.bad`, `.bad.1`, ... or refuse to
rename over an existing `.bad`. Related, accepted: a crash that leaves `<name>.<pid>.tmp` makes the first later write
fail with "File exists" (the `finally` then removes it, so the next try works); the message could say "a leftover
temp file was removed, try again". No `fsync` of the folder after `os.replace` (`:154-158`): a power cut right after
Add can lose the entry, which is then offered again. Acceptable.

### P3-4. `verdict_line` says "up to date" where its row says "ahead of main" or "level, with uncommitted edits"
`lab_hub/self_update.py:206-209`. `self_status` also returns verdict `current` for "built from X, ahead of main.
Update now leaves Lab Hub alone: ..." and for the level-with-main case whose note warns about uncommitted edits; both
become the tile line "up to date". Check builds shows the note beside the verdict, the tile shows only the line, so
the tile can read more reassuring than the row. Tests (`test_self_update.py` after line 1410) cover plain current only.
Fix direction: key on the note ("ahead of") and say "ahead of main"; add the two parametrized rows.

### P3-5. Test quality (what would still pass with the code broken)
Mutation survivors, with my reading of each:
- `discovery.py:601` `_verify` equality (`after != expected`) removed: all tests pass. The hostile-README tests are
  fully carried by `toml_string`; the second layer §13.3 requires ("verify before writing") has no test. Needs a test
  that patches `toml_string` to a naive writer and expects `DiscoveryError` and an unchanged file.
- `discovery.py:586` size cap on `add` removed: untested.
- `discovery.py:287` `Cs` and `Cn` dropped from `_DROPPED`: untested (`Cs` cannot survive UTF-8 decode; `Cn` needs an
  unassigned code point such as U+0378 in `test_control_bidi_zero_width...`, `:491`).
- `discovery.py:299-311` the README `lstat` regular check, the `fstat` check and `O_NONBLOCK`: each alone is
  redundant, so removing one is invisible. A swap-after-`lstat` (the case they exist for) is not tested. Accept as
  defence in depth, or add one test with a patched `os.lstat`.
- `registry.merge_local` `keys.add(app.key)`: the "earlier local key" branch is unreachable through `parse` (a duplicate
  key already fails there), and no test calls `merge_local` directly with two equal keys.
- Equivalent or near-equivalent survivors: `suggestions` reserved-path line (scan skips `lab_hub` by name anyway),
  `add`'s `joiner` (`render_entry` begins with a newline), `state.version` and `state.status` no-launch branches (the
  fall-through gives the same answer once `bundle_path` is None), `_recorded_root_version` guard (unreachable by design).
Weak or brittle tests:
- `tests/test_discovery.py:560` `test_the_hostile_table_would_catch_a_naive_writer` exercises `tomllib` only, not
  the module; it cannot fail when `toml_string` is broken (the round-trip test at `:553` is the real one).
- `tests/test_discovery.py:460` the 5 MB test checks the size of each `os.read` call, not the total: a loop that reads
  8192 bytes until EOF would pass.
- `tests/test_launcher.py:1892` and `tests/test_selftest_app_list.py:77` assert on source text
  (`"GUI thread only" not in source`, `"_app_list_problems()" in inspect.getsource`). They break on a comment edit and
  pass on any code that has the string.
- `tests/test_tray.py:45` now wraps the old assertion in `if app.launchable`; with a registry of only no-launch apps
  it asserts nothing. The new test below it covers the real case, so keep the loop but assert the list is non-empty.
- `tests/test_registry.py` "shipped entries unchanged" pins count and `launchable`, not the field values (the older
  test keeps names). Fine for now.
- `tests/conftest.py:68` `except ImportError: return` also hides a broken `ui/own_verdict.py`: every test would then
  silently start the real verdict thread and git. Narrow it to `ModuleNotFoundError` on that module name.
- No test touches the owner's real support folder or lab folder: `isolated_config` is autouse and
  `no_real_discovery` patches `suggestions`; `test_discovery.py` builds its own temp lab. Registry module globals are
  reset by `registry.use(None)` in the fixtures of the modules that set them (`test_discovery.py:31`,
  `test_registry.py`, `test_selftest_app_list.py`, `try/finally` elsewhere); there is no global autouse reset, so a
  future test that calls `registry.reload()` and forgets `use(None)` would leak `_last_local` and `local_ok`. Suggest
  moving the reset into `conftest.py`.

### P3-6. Doc drift (Document phase can take it)
`lab_hub/apps.toml:15` still says `key, name, project, entry, summary   required`; `entry` is now optional there
too (§13.9 item 5) and the header should say what an `entry`-less block means. `README.md` and `CHANGELOG.md` are
untouched (planned for Document).

## The author's four reported deviations
1. **`scan` uses `os.path.realpath(folder)`: acceptable.** The registered set is built with `realpath` (`:501`), so the
   two sides must be compared the same way; the folder itself is already a real, non-link directory, so this only
   resolves a symlinked lab root. Probes: a symlinked project, a `.git` symlink, a `docs` symlink out and a marker
   symlink are all refused (`probe/fs.py`; killed mutations for each).
2. **`hidden()` drops entries whose folder is gone: acceptable.** The signature takes `lab_root` for this; a
   vanished folder is never scanned, so a row for it would be an undo for nothing. Residual: a folder that is only
   temporarily absent (renamed, unmounted) shows no row, and its answer stays in force. Harmless.
3. **Empty `entry = ""` is a `RegistryError`: acceptable.** Before this change `_REQUIRED` already rejected it
   ("missing: entry"), so behaviour is unchanged for apps.toml, and it stops a typo from silently becoming a no-launch
   tile. The message tells the owner to leave the key out.
4. **`parse(local=True)` wording: acceptable.** "unknown group(s): utilities (expected suites)" is accurate for the
   local file. The status-bar sentence ("Your added projects file was ignored: ... The list is as it was.") is not in
   §7; it is a §12.7 proposal (spec §14 item 3 recommends approval; I did not verify the owner gave it), so Part 2 should check the exact text and its approval.

## Checked and found sound
- **Writer (§4):** hostile README text tried through `describe` then `add` (`probe/hostile.py`): `"]]\n[[suites]]
  key="x"`, `"""`, a trailing backslash, `A`, U+2028/2029, NUL, bidi override, emoji, BOM. The file read back
  with exactly 8 tables and only the five known keys, mode `0600`, no stray temp file. `toml_string` plus the
  round-trip `tomllib` equality leave no injection path. Atomic write: temp file `O_EXCL`, `0600`, `fsync`, identity
  check, `os.replace`, `unlink` in `finally`; a patched `os.replace` failure leaves the original and no temp
  (`probe/fs.py`). A symlinked state file is refused (ELOOP). Dismissal `at` of `9999-12-31` does not overflow
  (short-circuit), a future `at` is expired.
- **README extraction (§5):** FIFO, symlinked README and a directory named `README.md` return the fallback without
  hanging; a 15 MB README reads 8192 bytes; invalid UTF-8 gives U+FFFD (kept; cosmetic); BOM and CRLF handled;
  220-character cap ends with an ellipsis on a word boundary.
- **Scan (§3):** no subprocess (module imports none; test patches the five entry points). `.git` file or symlink,
  missing marker, `.x`, `_x`, spaces, quotes, newline, 65-character names, a link to inside or outside the folder,
  case variants of a registered folder (`KAILA`, `./kaila`), a registered project nested inside, `lab_hub`: all
  excluded. The 400-entry cap counts every directory entry, files and hidden folders included (as written in §13.3),
  so a lab folder with more than 400 entries silently stops suggesting; accepted by the spec.
- **Registry merge (§2):** clash rules, case-insensitive compare, "launchable first" stable sort, last good local
  part merged against the new `apps.toml`, `local_note` never in `last_error`, `use()` resets the three globals.
  `Registry.__eq__` already sees local entries, so `reload()` is True after a local edit (`test_a_local_edit_makes_
  reload_say_the_list_changed`). Two local entries with overlapping projects are both kept (the spec compares only
  against `apps.toml` and reserved); only a hand edit can do this because `add` is guarded by `suggestions`.
- **`main._app_list_problems`:** the extracted block is the old code verbatim plus one printed `local_note`;
  `last_error` stays a problem; the local note never is (`test_selftest_app_list.py`).
- **Skips:** tray (`ui/tray.py:121`) and wake-start (`ui/main_window.py:368`) guarded and tested.
- **Thread safety of the amended `state.py` comment:** the caches (`_COUNT_CACHE`, `_COMMIT_CACHE`, `_DIRTY_CACHE`,
  `_BEHIND_CACHE`, `_ROOT_BEHIND_CACHE`) are only get/set, never iterated or deleted in code, so a second writer
  thread is safe.

## Verdict
PASS with fixes. No P0/P1. Fix P2-1 and P2-2 before Verify (both small, both with a one-line test); the P3s can be
batched or deferred by the owner.
