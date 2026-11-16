# Security review: test run time limit and program lookup (land-from-tiles §10)

- Date: 2026-11-16. Role: security-engineer (read-only; this file is the only thing written).
- Reviewed: uncommitted `git diff lab_hub/claude_resolve.py` and new `tests/test_claude_resolve_env.py`
  on branch `claude/test-timeout-python`; spec `docs/specs/land-from-tiles.md` §10.
- Playbook `docs/playbooks/security-engineer.md`: `status: current`, `last-reviewed: 2026-11-11` (5 days; not stale).
- `docs/foundry/app-context.md`: Product, Stack, Commands, Security surface and Invariants are still
  template placeholders (lines 7, 23, 26-30, 39, 45). Scope was therefore taken from the brief and the code.

## Verdict
No P0. No P1. Three P2 and three P3 findings. Neither change gives a test run a capability it did not
already have; the findings are about the strength of the "tests passed" gate and about how long a run can last.

## Threat model (short)
- Assets: the default branch and its push (only "tests passed" stands between a merge and a push); the
  owner's Claude login (used by `claude_env`); the main checkout's `.git` config/hooks and its `.venv`/`node_modules`;
  everything under `HOME` readable by the user.
- Trust boundaries: (1) branch code and merged code run as tests versus Lab Hub's own process and git calls;
  (2) the main checkout's `app-context.md` (already-landed content, decides command and now the limit) versus
  the merge in the temporary worktree; (3) user-writable program folders (`/opt/homebrew/bin`, `~/.local/bin`)
  versus SIP-protected ones (`/usr/bin`, `/bin`).
- Entry points touched by this change: `_commands_line`/`test_timeout` (text from the checkout's app-context),
  `test_env` (PATH), `run_tests` (`shutil.which(exe, path=env["PATH"])`, `claude_resolve.py:588`).
- Baseline that frames every finding: the test run is not sandboxed. `_stream` is a plain `Popen` as the
  owner (`claude_resolve.py:250-252`) with `HOME` kept (`:75`). `test_env` withholds environment variables, not file access.

## STRIDE on the change
| | PATH reorder (`TEST_PATH`) | Test timeout line |
|---|---|---|
| Spoofing | P2-1: a file planted in `/opt/homebrew/bin` now also stands in for `python3` | none found |
| Tampering | same; no new write access | limit comes from the checkout, not the merge (see "Checked, no finding") |
| Repudiation | P2-1: the log shows the bare name, not the resolved path (`:592`) | P2-3: the limit is not in the preview or the log |
| Information disclosure | none: allowlist unchanged (`:547-550`) | none |
| Denial of service | none | P2-2: per command and per run, not per Land |
| Elevation of privilege | none: same user, no new boundary crossed | none |

## Findings

### P2-1 A bare `python3` now resolves from a user-writable folder; the run does not record which program it used
- Where: `lab_hub/claude_resolve.py:48` (`TEST_PATH`), `:550`, `:588-592`.
- Evidence (this machine): `/opt/homebrew/bin` is `drwxrwxr-x as:admin`; `/usr/local/bin` is `drwxr-xr-x root:wheel`
  (but `/usr/local/bin/python3` is `-rwxrwxr-x root:admin` and the owner is in `admin`). Resolution old PATH versus new,
  for every name in `_RUNNERS`: only `python3` changes (`/usr/bin/python3` to `/opt/homebrew/bin/python3`).
  `node`, `npm`, `npx`, `uv`, `uvx` resolved to `/opt/homebrew/bin` before and after; `make`, `swift`, `ruby`,
  `bundle`, `rake` stay in `/usr/bin`. Names now shadowed for the tests' own child processes: `git`, `git-receive-pack`,
  `git-shell`, `git-upload-archive`, `git-upload-pack`, `openssl`, `pip3`, `python3`, `rsync` (9).
- Scenario: branch A's tests (run by Land, as the owner) replace `/opt/homebrew/bin/python3` with a script that exits 0.
  Every later Land whose command is a bare `python3 ...`, in any repo, then "passes" and is pushed untested. Before
  this change that particular command ran the SIP-protected `/usr/bin/python3`.
- Why P2 and not P1: it is not an escalation. The attacker already runs code as the owner; the same persistence already
  existed for `node`/`npm`/`npx`/`uv` (Homebrew only), for `.venv/bin/python` (`:580`, the checkout's own writable venv),
  for the user site-packages the system `python3` loads, and for `~/.local/bin/claude` (`:99`). `lab_hub/hygiene.py:21`
  already looks `python3` up Homebrew-first. Lab Hub's own git calls are not reached: `_git_exe` uses
  `repo_tidy._SEARCH_PATH` with `/usr/bin` first (`repo_tidy.py:42,55`), unchanged.
- Fix: print and log the resolved path (`found`, and its `os.path.realpath`) instead of the bare words at `:592`, so a
  changed interpreter is visible in the Land log. Optional: refuse a resolved program that is group- or world-writable
  by anyone other than the owner. Spec §10 should state plainly that the lookup trusts user-writable folders.

### P2-2 The limit is per command and per test run; one branch can hold Land for 9 hours or more
- Where: `claude_resolve.py:44` (`MAX_TEST_TIMEOUT = 180 * 60`), `:593` (applied to each command), `_tests` called
  at `:1032`, `:1088`, `:1122` (default branch, merge, after the fix round).
- Evidence: probe with `- Run tests:` naming three commands and `- Test timeout: 180 min` gives 3 commands, limit
  10800 s each. Worst case per branch = 3 runs x N commands x 180 min: 9 h with one command, 27 h with three
  (was 1.5 h and 4.5 h). The comment at `:42-43` ("a typo cannot hold Land for a day") holds per command only.
- Impact: availability, and a six times longer window in which branch code runs with the checkout's `.venv` and
  `node_modules` linked in (`:716-739`). Stop still kills the group (`:211-215`); not verified end to end.
- Fix: a total budget per Land or per branch (for example the limit applied to the whole `run_tests` call), or a lower
  cap (Imprint, the only evidence in §10, needs 60). Correct the comment either way.

### P2-3 The limit is invisible in the preview and outside the "changed since the preview" check
- Where: `repo_tidy.py:549-550` (preview text is `cmd.display` and the note), `:765-766` and `:847-848`
  (`cmd.display != action.detail`); `TestCommand.display` does not include `timeout` (`claude_resolve.py:416-418`).
  `_BASE_PASSED` key likewise (`:1027`).
- Scenario: a landed change (or an uncommitted edit in the main checkout) sets `- Test timeout: 180 min`; the next
  Land runs up to six times longer with nothing shown to the owner and nothing in `repo-tidy.log`.
- Impact: low (bounded by the cap; no code runs that would not run anyway). Combined with P2-2 it is the realistic
  way to a very long unattended run.
- Fix: show a non-default limit in the preview line and the `CLAUDE landed` log line, and compare it in the stale check.

### P3-1 Section detection ignores code fences and repeated sections
- Where: `claude_resolve.py:428-433`.
- Evidence (probe): a `## Commands` heading inside a fenced code block under another section is accepted
  (`- Test timeout: 170 min` there returns 10200); a second `## Commands` section later in the file also counts.
  `### Commands`, ` ## Commands` and `## Commands (all)` are correctly ignored; "Test timeouts" and a mention in
  prose on the Run tests line are ignored. Same behaviour as before for `Run tests`; not new, now reused.
- Impact: negligible; the value stays within 1 to 180 minutes and the file is the checkout's own.

### P3-2 Value parsing accepts more than the spec says
- Where: `claude_resolve.py:444`.
- Evidence (probe): `0090 min` gives 5400; Arabic-Indic digits give 10200 (`\d` is Unicode); `60 minimum` would match
  on the `min` prefix (by reading, not run). All still within the cap. Rejected as intended: `181`, `0`, `99999`,
  `01800`, `1.5`, `-5`, `3 h`, `soon`; a malformed first line is not rescued by a valid second one (fails to default).
- Fix (optional): `[0-9]{1,3}` and `min\b|minutes?\b`.

### P3-3 Test gaps
- `tests/test_claude_resolve_env.py` has no test that the limit comes from the checkout when the merge's app-context
  says otherwise (spec §10 point 1 claims it). It holds by construction today; a test would keep it.
- `:89-91` is skipped on a machine without Homebrew Python, and `:77` only asserts absolute entries, not that the
  folders are the fixed list (an equality assert on `TEST_PATH` plus `~/.local/bin` would pin it).

## Checked, no finding
- ReDoS in `_commands_line` and `test_timeout`: none. `label` goes through `re.escape` and both callers pass
  literals (`:438`, `:444`). The patterns have no nested or overlapping unbounded quantifiers that backtrack badly:
  a line with five 200,000-space runs and a near-miss ending took 0.004 s; 5,000 near-miss lines of 2,000 spaces took 0.028 s.
- Limit read from the merge instead of the checkout: no. `test_command(repo)` is called with the repo path before the
  temporary worktree exists (`repo_tidy.py:847`, worktree made at `claude_resolve.py:957-959`) and `run_tests` only uses
  `cmd.limit` (`:593`); a branch cannot raise the limit for its own Land. Verified by reading the code, not by an
  end-to-end run. Not verified: that `repo` is always the main checkout and that it has the default branch checked out.
- Environment allowlist: unchanged. `test_env()` here returns only `CI, GIT_TERMINAL_PROMPT, HOME, LC_CTYPE, LOGNAME,
  PATH, QT_QPA_PLATFORM, SHELL, TMPDIR, USER`; PATH is `/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:~/.local/bin`,
  all absolute, nothing from the caller's PATH or the repo. `/sbin` is new on the list (system folder, no concern).
  `_BANNED_VARS` still stops a Run tests line from setting `PATH` (`:72`).
- Lab Hub's own git: `repo_tidy._SEARCH_PATH` and `_git_exe` untouched by the diff; `_git_state` (`:890-909`) still guards
  config, hooks and info around every test run.
- Error path (OWASP A10): unreadable or missing app-context returns "" and the default limit (`:423-426`); out-of-range
  values fall back to the default, never to "no limit". The timeout message leaks nothing.

## Pre-existing, outside this diff (context only, verified by reading, not exploited)
- `find_claude` prefers `~/.local/bin/claude` (`claude_resolve.py:99`), a user-writable path a test run could replace;
  that program is then run with the owner's Claude login. Same class as P2-1, larger asset.
- `repo_tidy._env()` (`repo_tidy.py:61-69`) passes Lab Hub's inherited PATH to git, so programs git itself starts
  (`ssh` from `GIT_SSH_COMMAND`, credential helpers, filters) are resolved through whatever PATH Lab Hub was launched with.
- A child that calls `setsid` leaves the process group and survives the `killpg` in `_stream`.

## Dependencies
- The diff adds no dependency and touches no manifest.
- `pip-audit` is not installed (`pip-audit not found`; `No module named pip_audit`). Per the playbook the installed set
  of `/Users/as/Documents/lab/active/lab_hub/.venv` (one `site-packages`, 43 distributions) was sent to the OSV
  querybatch API on 2026-11-16: 0 packages with advisories. Bundled Qt is not covered by OSV PyPI. No `npm audit` run
  (no Node lockfile looked for; not verified).

## Commands run
- `QT_QPA_PLATFORM=offscreen /Users/as/Documents/lab/active/lab_hub/.venv/bin/python -m pytest -q -p no:warnings tests/test_claude_resolve_env.py tests/test_claude_resolve.py`
  in the worktree, twice: all passed (71 dots on the progress line, no failure or error; the run printed no summary count).
- A probe script outside the repo (parser edge cases, timings, old/new resolution, shadowed names); `ls -ldO` on the
  program folders; the OSV query above.

## Not verified
- No file was written to `/opt/homebrew/bin` or `~/.local/bin`; the planting scenario rests on the folder modes and the
  lookup order, not on a live exploit.
- No end-to-end Land (real Claude, real push), no run past a real timeout, no Stop during a long run.
- Intel Macs (`/usr/local/bin` user-writable under Homebrew there) and the frozen app's inherited PATH.
- The full test suite and the other modes; mutation checks (QA's phase).
