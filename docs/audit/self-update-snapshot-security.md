# Secure: self-update amendment 1, snapshot build (security-engineer, 2026-11-20)

Read-only review of `git diff c29f0d2..HEAD -- lab_hub/self_update.py ui/apps_tab.py` (commit
`ae2d84e`), against spec `docs/specs/self-update.md` §11–§12, ADR 0006 and the earlier review
`docs/audit/self-update-security.md`. No code was changed.

- **Playbook:** `docs/playbooks/security-engineer.md` is `status: current`, last reviewed 2026-11-11
  (9 days old), so it is not stale.
- **App context:** `docs/foundry/app-context.md` still has template placeholders in Security surface,
  Stack and Invariants. Scope came from the brief, the spec and the ADR.

## Verdict

**No P0, P1 or P2. Three P3 items.**

The amendment narrows what the update trusts:
- **Before:** the shared working tree, gated by `checkout_blocker` at build start and again at
  staging, with an edit-and-revert window in between.
- **Now:** committed `main` at a 40-hex SHA that Lab Hub recorded.

Nothing new reaches the detached helper. Its arguments, environment and script are unchanged; it
still gets only `update/staged/Lab Hub.app`. The only change is that this bundle is now copied from
the snapshot instead of the checkout's `dist.noindex`.

The new trusted inputs were all trusted already:
- the owner's global git config;
- `git` on the login-shell `PATH`;
- `~/Library/Application Support/Lab Hub/`, which is owner-only.

Secure may pass once the owner has read the P3 items. None blocks.

## Threat model

### Assets
- `/Applications/Lab Hub.app`, which runs Land.
- The integrity of the staged bundle: it should be built from the commit shown in the row.
- The shared checkout `lab_hub/`, including its `.venv` and `.git`.
- The owner's home folder, which is at risk from any `rm -rf`.

### Trust boundaries
1. Lab Hub → `$SHELL -lc <command>` (`ui/rebuild.py:228`). The child gets `child_env()` and the
   login profile.
2. The command → the shared checkout. It is read by `git clone` and through the `.venv` symlink.
3. The command → `update/snapshot/lab_hub`, which Lab Hub owns.
4. The snapshot → `stage_build` → `update/staged`.
5. `update/staged` → the helper → `/Applications`. This boundary is unchanged.

### Who can write what
- Every agent session runs as the owner (same uid) and can write to the shared checkout, its
  `.git/`, `.venv` and `refs/heads/main`. Land merges to `main`.
- `~/Library` and `~/Library/Application Support` are 0700 (checked on this Mac). Only the owner's
  uid can write under the support folder.
- Within one uid there is no privilege boundary. The findings below cover robustness against
  mistakes and against confused automation, not against an attacker who already runs code as the
  owner.

### Entry points that changed
- `main_commit` (`self_update.py:116-121`)
- `build_command` (`:129-145`)
- `planned_commit` (`:148-157`)
- `self_status`: `rev-list` and `cat-file` (`:212-221`)
- `stage_build` (`:252-289`)
- `_restart_on` and `_hold_for` (`ui/apps_tab.py:910-923`, `:1047-1066`)

## Findings

### P3-1: `rm -rf` on the snapshot follows a symlink in the folders above it

**Where:**
- `lab_hub/self_update.py:140`: `/bin/rm -rf <snap>` at the head of the build command, with no
  check at all.
- `lab_hub/self_update.py:288`: `rm -rf <snap>` in `stage_build`. The only check before it is
  `_no_symlinks(src)` at `:260`, run before a `ditto` that can take up to 600 s.

**Scenario:**
1. `update/` or `update/snapshot/` becomes a symlink. Lab Hub never creates one, so this would be a
   same-uid process or a confused agent, for example `snapshot -> ~/Documents/lab/active`.
2. The next Update now runs `rm -rf .../snapshot/lab_hub`. That resolves through the link and
   deletes `~/Documents/lab/active/lab_hub`, which is the shared checkout.
3. The command then clones into the same redirected path.

`rm` refuses only a symlink in the final path component, not one in a folder above it. I reproduced
this in a scratch folder: a `victim/lab_hub` reached through `update/snapshot -> ../victim` was
deleted.

**Impact:** loss of an arbitrary `<dir>/lab_hub` that the owner can write to, including any
uncommitted work in it. The likelihood is low: it needs a same-uid write into the owner-only support
folder, which already means full compromise.

**Fix (hardening):**
- Refuse in the chain itself, just before the removal:
  `[ ! -L <update> ] && [ ! -L <update>/snapshot ] && /bin/rm -rf <snap> && ...`
  Alternatively, check `_no_symlinks(snapshot().parent)` in the `hold` hook the moment before the
  command starts. The in-chain test is tighter.
- In `stage_build`, repeat the `_no_symlinks` check on `snap` right before line 288.
- Add a test with a symlinked `update/snapshot`.

### P3-2: the `git` on this Mac is below the 2026-11-10 security release

**Where:**
- The build chain calls a bare `git` (`self_update.py:141-143`). On the login `PATH` that resolves
  to `/opt/homebrew/bin/git` 2.56.0.
- `_git()` in Python finds `git` on the bundle's `PATH`. `/usr/bin/git` is Apple Git 2.54.0.

**Status:** fixed versions are 2.56.1 and 2.54.1 (see the sources below). The flaw that runs code
(CVE-2026-111760) needs `clone --recurse-submodules` from a malicious repository. This chain does
not recurse, and its source is the owner's own repository. The secondary sources I found describe
none of the other five as reachable through a local, non-recursive clone or checkout. I did not
check this against Git's own release notes.

**Impact:** not exploitable through this path today. Git is now a step in every Lab Hub update, so
it is worth keeping current.

**Fix:** `brew upgrade git`. Apple Git follows Xcode Command Line Tools updates.

### P3-3: the spec claims more isolation than the build has

1. **The shared `.venv` still reaches every build.** Spec §11.2.2 says the shared checkout "cannot
   ... contaminate" the build. But the snapshot's `.venv` is a symlink to the shared `.venv`
   (`self_update.py:144`). `build_app.sh:17-18` activates it, and runs
   `uv pip install -q pyinstaller` into it. So a package another session has changed, downgraded or
   added there without committing is bundled with the commit's own code.

   I checked that `site-packages` has no `.pth` or editable install that points at the checkout. Only
   `_virtualenv.pth` and `distutils-precedence.pth` are present, so the checkout's uncommitted
   `lab_hub/` or `ui/` source is not picked up this way.

   §11.4 lists this as a non-goal and ADR 0006 notes it, so this is not new trust. The fix is
   wording: user-facing text (README, CHANGELOG, row note) should not say the installed build is
   exactly the reviewed commit without the words "and the checkout's `.venv`".

   Optional hardening: before PyInstaller runs, check the venv against the snapshot's
   `requirements.txt`, for example by comparing the output of `uv pip sync --dry-run`.

2. **§12.2 says `update/snapshot/` is "mode 0700 like `update/`".**
   - `update/` is 0755 on this Mac.
   - `mkdir -p -m 700` sets the mode only on the last folder. I checked this in the scratch run:
     `snapshot/` was 0700 and `snapshot/lab_hub` was 0755.
   - There is no exposure, because `~/Library` is 0700. Correct the sentence or create `update/`
     with 0700.

## What I checked and found sound

### Command injection
- The SHA is `fullmatch`ed against `[0-9a-f]{40}` (`:61`, `:137`, `:257`) before it is put into the
  command unquoted at `:143`.
- Every path is `shlex.quote`d. `--` comes before the clone's source path.
- `planned_commit` returns a SHA only when the command is byte-identical to the one `build_command`
  makes for the current project (`:155`). A changed lab root at restart therefore fails closed.
- A full 40-hex name always resolves as an object ID, even if a ref has the same name. Staging also
  re-checks `HEAD == commit` (`:264-268`).
- `installed`, used in `rev-list --count <installed>..<commit>` (`:214`), comes from
  `_stamped_commit`. That is checked against `[0-9a-f]{7,40}` (`launcher/state.py:436`, `:525-528`),
  so it cannot be read as a git option such as `--output=`.

### Git hooks and config during the clone and checkout
I ran the exact chain with Homebrew git 2.56.0 against a source repository that had three
executable hooks (`post-checkout`, `reference-transaction`, `post-index-change`), `core.fsmonitor`
set to a command, and a `.gitattributes` smudge filter defined in its own `.git/config`. None of
them ran:
- The clone's `.git/config` holds only `core`, `remote.origin` and `branch.main`.
- Its `hooks/` folder has only template `*.sample` files.
- `HEAD` equals the SHA.

The only config that applies is global and system config. On this Mac that has no `core.hooksPath`,
`init.templateDir` or `core.fsmonitor`. It does have `filter.lfs.*`, which runs only for paths the
committed `.gitattributes` marks as LFS; this repository tracks no `.gitattributes` or `.lfsconfig`.

Filters, `.gitattributes` and `.lfsconfig` from the committed tree are no more trusted than
`build_app.sh` at that same commit, which runs anyway.

Side benefit: the build's own git calls (`stamp_version.py`) no longer read the shared checkout's
`.git/config`, which any session can write to.

### The `.venv` symlink and removal
- `rm -rf` of the snapshot removes the `.venv` link, not its target. Reproduced: the target's
  `bin/python` survived.
- Removing the hard-linked objects leaves the source intact: `git fsck` on the source was clean
  afterwards.
- If a committed `.venv` entry existed, `ln -s` would put the link inside it. Committed content is
  trusted anyway, and `.venv/` is git-ignored.

### TOCTOU and concurrency
- Nothing else uses the snapshot, so swapping the bundle between the build and staging needs a
  deliberate same-uid write. Under the old design, other sessions wrote to `dist.noindex` as part of
  normal work, so this is strictly better.
- The Check builds window is `ApplicationModal` (`ui/progress_window.py:926`), so two Update nows
  cannot overlap and race on `rm -rf <snap>`.
- Tests point `UPDATE_DIR` at a temporary folder through an autouse fixture
  (`tests/conftest.py:37-50`), so a test run cannot delete a real snapshot.

### Data and other paths
- The snapshot holds only tracked files. The untracked `.env` with the Narrator keys is never
  cloned, so no secret lands in the support folder or the bundle. The snapshot is removed after a
  successful stage.
- If Lab Hub's row fails, its new command text goes to Ask Claude. `handoff.command_dir`
  (`lab_hub/handoff.py:152`) returns None for a command that starts with `/bin/rm`, so no new
  `--add-dir` is granted.

### Error handling (OWASP A10)
Every refusal in `stage_build` raises `ValueError`, and `_restart_on` turns it into "not installed;
this copy keeps running". Nothing is installed on any error path, and no secrets appear in messages.

One small exception: the cleanup `rm` at `:288` can time out (`TimeoutExpired`) after a good stage.
That reports "not installed" when staging actually worked. It still fails closed.

### Dependencies
- The diff changes no manifest.
- `pip-audit` is not installed. I sent the 43 installed packages in `lab_hub/.venv` (read from
  `*.dist-info`, including PySide6 6.12.0, pillow 13.0.0, pypdf 7.0.0, pyinstaller 6.22.3, urllib3
  2.8.0 and certifi 2026.10.23) to the OSV `querybatch` API on 2026-11-20: **0 advisories**.
- Git is covered in P3-2.

### Not verified
- A real end-to-end Update now from the support folder (the path has two spaces).
- The real `/Applications` swap.
- Git's primary advisory text.

## Sources
- [Help Net Security: Git fixes six vulnerabilities, including code execution during recursive clones](https://www.helpnetsecurity.com/?p=390990)
- [SmartScope: Git 2.56.1, 6 vulnerabilities fixed](https://smartscope.blog/en/blog/git-2-56-1-6-vulnerabilities-fixed-across-2026/)
- [The Hacker News: Git patches flaw](https://thehackernews.com/2026/11/git-patches-flaw-that-lets-malicious.html)
- [oss-security announcement, 2026-11-11](https://www.openwall.com/lists/oss-security/2026/11/11/10)

## Fixes after this review (orchestrator, 2026-11-20)
- **P3-1 fixed:** `build_command` now starts `[ ! -L <update> ] && [ ! -L <update>/snapshot ] &&`
  before `mkdir` and `rm -rf`, and `stage_build` re-checks the snapshot path for symlinks right
  before removing it. Test `test_a_symlinked_snapshot_folder_stops_the_build_before_removing_anything`;
  mutant M1 (guard removed) is killed by it.
- **P3-2 open, owner's:** `brew upgrade git`.
- **P3-3 fixed:** spec §11.2.2 now says `.venv` is still the checkout's; the command `chmod 700`s
  `update/` and `update/snapshot/` (asserted in a test). Also, following the code review, `git clone`
  now runs with `-c core.hooksPath=/dev/null --template=`, so no global or template hook runs.
