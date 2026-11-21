# ADR 0007: Apps found in the lab folder live in a local registry file, and a tile may have no launch command

Status: proposed, awaiting owner approval (Architect gate).
Spec: `docs/specs/apps-discovery.md` §4.3, §4.6, §13.

## Context
A tile exists only because someone typed an entry into `lab_hub/apps.toml`, a tracked file in Lab Hub's
own repository. The owner wants new projects offered automatically, a project with no launch script
(Kaila) to get a tile, and Lab Hub itself to be a tile. Answers must survive restarts. A running app
must not write a tracked file (it would dirty the repo and race with sessions that edit it), and
`entry` is required today (`registry.py:83`), so an app with nothing to launch cannot be listed.

## Decision
1. **A second registry source, `~/Library/Application Support/Lab Hub/apps-local.toml`,** same format as
   `apps.toml`, only `[[suites]]` allowed. It is read after `apps.toml` on every `reload` and merged into
   the same `Registry`: its entries come after the hand-written suites. `apps.toml` always wins a key or a
   project clash; the local entry is dropped and the reason goes to `registry.local_note`.
2. **A bad local file never empties the hub and never fails the self-test.** The last good local part is
   kept, `registry.last_error` (which `main.py:383-385` turns into a self-test failure, and a failed
   self-test rolls an update back) stays about `apps.toml` only, and the note is shown in the status bar.
3. **`entry` becomes optional.** `entry is None` is the "no launch command" kind (`ExternalApp.launchable`
   is False). Such an entry carries identity and summary only; it cannot set `url`, `service`, `args`,
   `bundle_dir`, `build` or `build_output`. It has no bundle, no running state, no menu-bar entry and no
   Check builds row. The field keeps its position and has no default, so every positional
   `ExternalApp(...)` call in code and tests is unchanged.
4. **Dismissals live in `~/Library/Application Support/Lab Hub/apps-dismissed.json`:**
   `{"<folder>": {"answer": "never"|"not_now", "at": "YYYY-MM-DD"}}`. Unreadable or malformed reads as
   empty; an unparsable `at` or one in the future counts as expired (the file can only ever cause an
   extra question, never a permanent silent hide).
5. **Both files are written atomically** (temp file in the same folder, fsync, `os.replace`), by the GUI
   thread, after the new text has been parsed back and checked. Values from a README are serialised by a
   strict basic-string escaper and the written entry is round-tripped through `tomllib`; no new
   dependency (`requirements.txt` has no TOML writer).
6. **Lab Hub's own tile is built in code** (`self_update.OWN_TILE`, an `ExternalApp` with no `entry`),
   appended last to the Apps page by `MainWindow`, never read from any file. Its key and project
   (`lab_hub`) are reserved: a registry file cannot define them.

## Consequences
- The two file formats are now a contract with the owner's disk. Changing them later needs a migration;
  this is why they are fixed here.
- `apps.toml` stays the owner's curated list. Moving a local block into it by hand is supported (the
  local copy then yields), but only a Lab Hub build that has this change can read an `entry`-less block
  there; an older installed build rejects that `apps.toml` and falls back to its bundled copy.
- Every consumer of `entry` had to be made safe for `None` (`docs/specs/apps-discovery.md` §13.2): one
  guard per module path, with tests.
- Deleting `apps-local.toml` removes the added tiles on the next Refresh and re-offers the projects;
  deleting `apps-dismissed.json` re-offers dismissed ones. Neither file is needed for Lab Hub to run.
- Not decided here: removing a tile from the UI, tiers, or registering nested repos (spec §8 Out).
