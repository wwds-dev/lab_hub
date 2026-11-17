# Security review: progress windows for Land and Check builds (spec progress-windows)

Role: security-engineer (Secure phase), 2026-11-17. Read-only review of the uncommitted change in
worktree `claude/zealous-benz-97c752`: new `lab_hub/durations.py`, `lab_hub/progress.py`,
`ui/progress_window.py`, `ui/rebuild.py`; `git diff` of `lab_hub/land.py`, `ui/lander.py`,
`ui/apps_tab.py`. No source or test was changed; probes ran from the session scratchpad against
scratch directories (never the real `~/Library/Application Support/Lab Hub/`).

Playbook `docs/playbooks/security-engineer.md`: last-reviewed 2026-11-11, status current (not stale).
`docs/foundry/app-context.md` still has Stack, Security surface, Invariants and Commands unfilled
(template text); scope came from the spec (§7, §8.4-8.7) and the task. Tier: public.

**Result: P0 0, P1 0, P2 2, P3 5.** Verdict at the end.

## Threat model (this change)
- **Assets.** The installed apps in /Applications (Update now replaces them); the owner's
  session (build commands run as the owner in a login shell); Lab Hub's availability (Check builds,
  Update now, Land and its Stop control); the integrity of what the owner is told (progress,
  "cancelled", "landed").
- **Trust boundaries.**
  1. Lab Hub -> `~/Library/Application Support/Lab Hub/durations.json` -> Lab Hub (a cache any
     same-user process can write; treated as untrusted on read).
  2. git, Claude Code, pytest and build-script output (repo-controlled) -> the windows.
  3. Land worker thread -> GUI thread (`SimpleQueue`, `StepEvent` of plain values).
  4. GUI -> `QProcess` running `$SHELL -lc <command>` (commands from `launcher.build_report`,
     unchanged by this diff).
- **Entry points.** Check builds button -> `show_build_report` (`ui/apps_tab.py:743-787`) ->
  `BuildCheckWindow.ask()` -> `run_updates` (`:789-830`) -> `Rebuild` (`ui/rebuild.py`); Land /
  Land all -> `_land_planned` (`ui/apps_tab.py:988-1006`) -> `LandWindow`; `Lander._drain` ->
  `step` signal (`ui/lander.py:123-124`); `durations.load()` at window construction
  (`ui/progress_window.py:624`, `:827`); `durations.record()` after a finished step
  (`ui/progress_window.py:650`, `ui/rebuild.py:158`).
- **Out of scope / unchanged.** What Update now and Land run, their guards and confirmations
  (`git status` shows `lab_hub/launcher/`, `repo_tidy.py`, `claude_resolve.py` unchanged).

## Verified negatives (tested or grepped, not assumed)
1. **Atomic write, mode, cleanup.** `durations.record(...)` into a scratch dir left only the
   target, mode `0o600`, no `.tmp` (probe output: `record ok: True 0o600`, `tmp leftovers: []`).
   With `durations.json` pre-created as a directory, `os.replace` fails: `record` returned `False`
   and the dir held only `['durations.json']` (temp unlinked, `durations.py:129-134`).
2. **Symlink on write.** A pre-existing symlink `link.json -> target.txt`: after `record`,
   `is_symlink now: False`, `target: keep` (rename replaces the link, never writes through it).
   The temp name comes from `mkstemp` (O_EXCL, random), so a planted temp-name symlink cannot be hit.
3. **Names never become paths.** `subject("repo", "../../x\x00‮\n" + "A"*500)` ->
   `'repo:../../xAAAA…'`, length 125 (C*/Cf removed, cut to 120); only a JSON key, no file or
   directory created. `StepEvent.repo` is used only as display text and a key (`land.py:244`).
4. **Lenient load (what holds).** NaN/Infinity/-Infinity/1e999, `true`, negative, 0, over 6 h and
   string samples are dropped; a 5000-digit integer is refused by Python's int-digit limit
   (ValueError, caught); a 15,000-subject file (333,916 bytes) is over the 256 KiB cap -> empty;
   JSON keys are always strings. (Two inputs still raise: P2-1.)
5. **Plain text everywhere in the new UI.** `grep -n "QLabel("` -> one hit, `_label()`
   (`ui/progress_window.py:52-59`), which sets `Qt.TextFormat.PlainText`; every name, reason, step
   label, verdict and version goes through it. No `setHtml`, `insertHtml`, `setMarkdown`,
   `QTextEdit`, `QTextBrowser`, `RichText` or `AutoText` in the four new files (grep, empty).
   Output goes to a read-only `QPlainTextEdit` via `appendPlainText` (`:455`) with
   `setMaximumBlockCount(5000)` (`:442`); the model buffer is a `deque(maxlen=5000)`
   (`progress.py:222`). Stage chip tooltips are constants (`StageView` labels from
   `LAND_STAGES`/`BUILD_STAGES`/"Rebuilding"). This is an **improvement**: HEAD's Check builds
   `QMessageBox` used auto-detected rich text for app names, notes and commands
   (`git show HEAD:ui/apps_tab.py`, lines 944-947, no `setTextFormat`).
6. **Command path unchanged.** `Rebuild` builds the same `QProcessEnvironment` from
   `launcher.child_env()`, `MergedChannels`, and `start(os.environ.get("SHELL","/bin/zsh"),
   ["-lc", command])` as HEAD's `RebuildDialog` (HEAD `ui/apps_tab.py` ~616-650). No new
   `subprocess`, `Popen`, `os.system` or `startDetached` in the new files or the `apps_tab.py`
   additions (grep). The command list comes from `build_check_view`, a line-for-line move of HEAD's
   computation (`commands`/`by_hand`/`forward` identical, compared by grep).
7. **Verify is read-only.** `launcher.version` (`lab_hub/launcher/state.py:832`, unchanged) reads
   the bundle's stamp/plist and runs git queries in the project, the same call a tile refresh
   makes today; it does not execute the built app. Exceptions are swallowed (`rebuild.py:167-170`)
   and never change success.
8. **Clipboard unchanged.** Review step: `self.copy_commands(commands + by_hand + forward)`
   (`ui/apps_tab.py`, as HEAD); Update step: `copy_requested.emit(view.commands + view.by_hand +
   view.forward)` (`ui/progress_window.py:832-834`), the same three lists.
9. **Escape / red button during a running build** now kill it: `reject()` override
   (`ui/progress_window.py:946-950`); QDialog's close event routes through it;
   `test_escape_during_a_rebuild_kills_it_and_the_next_command_never_starts` passes.
10. **Regex cost is linear.** `build_stage(plain(s))` + `plain(s)` on 1.5-2 MB pathological lines
    (unterminated `ESC[000…`, `ESC[0` x500k, 2 M non-word chars, mixed) took 0.12-0.18 s each.
    `_CSI` uses disjoint classes; `^\W*` markers are anchored.
11. **Worker boundary.** `land()` wraps the `events` callback (`land.py:271-277`); a raising slot
    on a PySide6 signal is printed and `emit()` returns (probe: "emit returned normally"), so
    `Lander._drain` keeps draining.
12. **Dependencies.** No manifest change in this diff. `pip-audit` is not installed; the OSV
    querybatch API on the installed set of `/Users/as/Documents/lab/active/lab_hub/.venv`
    (one `site-packages`, 43 distributions incl. PySide6 6.12.0): **0 advisories**. Bundled Qt is
    not covered by OSV PyPI (playbook watch list).
13. **Tests.** `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_durations.py
    tests/test_progress.py tests/test_progress_window.py tests/test_land.py tests/test_land_ui.py
    tests/test_apps_tab.py`: all passed (213 dots, exit 0). Full suite not re-run here.

## Findings

### P2-1 A hostile or corrupt `durations.json` makes `load()` raise, which breaks Check builds and the Land window, and it never heals (OWASP A10)
- **Where.** `lab_hub/durations.py:81-82` catches only `(OSError, ValueError, UnicodeDecodeError)`;
  `lab_hub/durations.py:69` `float(value)` raises `OverflowError` for an integer >= 10**309.
  Callers: `ui/progress_window.py:827` (`BuildCheckWindow.__init__`), `:624`
  (`LandWindow.start`), `:650` and `ui/rebuild.py:158` (`record` -> `load`).
- **Evidence.**
  ```
  deep_list:            RAISED RecursionError: maximum recursion depth exceeded while decoding a JSON array
  deep_obj_in_subjects: RAISED RecursionError
  bigint_4000:          RAISED OverflowError: int too large to convert to float
  # 358-byte file {"version":1,"subjects":{"repo:a":{"merge":[1000…0 (309 zeros)]}}}
  BuildCheckWindow(...)     -> RAISED OverflowError int too large to convert to float
  LandWindow(None).start([]) -> RAISED OverflowError int too large to convert to float
  record('repo:b','merge',2.0) -> record RAISED OverflowError
  ```
- **Attack.** Any same-user process (or a disk/sync corruption, or a hand edit) writes a few
  hundred bytes to the cache. Spec §8.4 promises "Never an exception out of `durations.load()`" and
  "a broken file is replaced by the next good save"; both fail.
- **Impact.** Check builds raises before its window exists: no report, no Update now, until the
  file is deleted by hand (sticky, because `record()` raises before it can save a good file).
  Land: `_land_planned` calls `self.lander.run(plans)` first, then `_open_land_window`
  (`ui/apps_tab.py:1003-1004`); the exception escapes after landing has started, so there is no
  window and `self._update_land_controls()` (`:1006`) is skipped, which leaves the page's
  "Stop landing" button hidden for the run (read from the code; the Stop-button consequence was
  not run). Fails open on availability and on the Stop control; no code execution, no secret.
- **Fix.** In `load()`, catch `(OSError, ValueError, UnicodeDecodeError, RecursionError,
  OverflowError, TypeError, MemoryError)` (or `Exception`) around parse **and** the walk; in
  `_sample`, wrap `float(value)` in `try/except (OverflowError, ValueError)`. Add the two inputs
  above to `tests/test_durations.py` (§8.12 lists "no exception" but not these cases).

### P2-2 Cancel / Escape kills only the shell's direct child; the running build step keeps going (pre-existing, carried over)
- **Where.** `ui/rebuild.py:101-104` (`self._proc.kill()` then `waitForFinished(3000)`), identical
  to HEAD `RebuildDialog`. The row then says "Cancelled" / "The build was stopped."
  (`lab_hub/progress.py:735-738`) and the header "Cancelled. Some apps may still be out of date."
- **Evidence.** Probe with `SHELL=/bin/zsh` (the owner's shell) and the real `Rebuild` class,
  command `cd /tmp && bash -c 'python3 -c "<sleep 2; write orphan.mark>"; touch after.mark'`,
  `window.reject()` after 0.7 s:
  ```
  running before cancel: True
  running after cancel: False
  orphaned child finished its work: True | next step in script ran: False
  ```
  With `SHELL=/bin/sh` the whole script survived (`next step in script ran: True`), because that
  shell did not `exec` the last command.
- **Attack / scenario.** The owner cancels during PyInstaller, a `ditto`/`cp` into
  /Applications, or an `install_app.sh` the build script runs as a child: that process is
  reparented and finishes, possibly installing a half-checked build after the UI said it was
  stopped; a second Update now can then run concurrently with it in the same `dist/`.
- **Impact.** Integrity of what the owner is told, and of /Applications; same user, no
  privilege change. Not introduced by this change, but §8.7/§8.11 now promise "the build is
  killed".
- **Fix.** Start the command in its own process group/session (PySide6 6.12:
  `QProcess.setUnixProcessParameters` with `CreateNewSession`, or a child-process modifier calling
  `os.setsid`), and on cancel `os.killpg(pid, SIGTERM)`, wait, then `SIGKILL` the group. Until
  then, word the row as "Stop sent; a step may still finish" rather than "was stopped".

### P3-1 Closing the window before the first command starts runs every command with the window hidden
- **Where.** `ui/rebuild.py:71` defers the first start (`QTimer.singleShot(0, self._start_next)`);
  `ui/progress_window.py:946-950` only cancels `if rebuild.running`; `_start_next`
  (`ui/rebuild.py:114-121`) does not check `_cancelled` set by a close, nor visibility.
- **Evidence.** Probe: `Rebuild([sleep 1; touch early.mark, touch early2.mark], w);
  w.reject()` before the event loop turned ->
  `visible after reject: False cancelled flag: False` then
  `first command ran: True second ran: True ended: True`.
- **Reachability.** Narrow: only a close/Escape processed before the zero-timer fires (between the
  Update now click and the first loop turn of `Rebuild.exec()`). Not reproduced with real input
  events. Impact if hit equals the P1 the spec fixed (§8.7): every rebuild runs unwatched, no
  Cancel visible.
- **Fix.** In `reject()`, call `rebuild.cancel()` whenever `rebuild is not None and not
  rebuild.ended` (`cancel()` already handles "not running"); add a regression test that rejects
  before the first start.

### P3-2 `load()` follows symlinks and reads non-regular files; the size cap is stat-then-read
- **Where.** `lab_hub/durations.py:79-81` (`file.stat()` then `file.read_text()`).
- **Evidence.** `durations.json -> pipe` (a FIFO): `load()` blocked, killed after 4 s
  (`BLOCKED >4s (timeout)`). `os.stat` of a symlink to `/dev/zero` reports `st_size 0`, so the
  256 KiB cap passes and `read_text` would read without bound (not run, to avoid exhausting
  memory). A regular file can also grow between `stat` and `read`.
- **Impact.** Same-user only; freezes the GUI thread at window open (Check builds, Land).
- **Fix.** `fd = os.open(path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK)`, `os.fstat(fd)` must be
  `S_ISREG` and `<= MAX_BYTES`, then `os.read(fd, MAX_BYTES + 1)` and refuse if longer.

### P3-3 One very long output line without a newline freezes the GUI (pre-existing; no per-line cap)
- **Where.** `ui/rebuild.py:124-127` (`_partial` grows unbounded), `lab_hub/progress.py:231-233`
  (no length cap), `ui/progress_window.py:453-455` (`appendPlainText`).
- **Evidence.** Real `Rebuild` + window, offscreen:
  ```
  2000000 bytes newline=True:  run 0.77s; render to pane 0.01s; blocks=5000
  2000000 bytes newline=False: run 0.87s; render to pane 59.43s; blocks=2
  8000000 bytes newline=True:  run 6.50s; render to pane 0.00s; blocks=5000
  8000000 bytes newline=False: did not finish in >4 min (probe killed)
  ```
- **Impact.** The source is the owner's own build scripts (or a tool they call, such as a progress
  bar without newlines), so the risk is accidental, not adversarial. HEAD had no cap at all; the
  new 5000-block cap fixes the many-lines case but not the one-huge-line case.
- **Fix.** Cut each displayed line to e.g. 4 KiB with a trailing "…", and flush `_partial` as a
  line once it passes that size.

### P3-4 `plain()` leaves OSC payloads, C1 controls, DEL and bidi overrides; row labels skip it
- **Where.** `lab_hub/progress.py:41-48`; row names, reasons and step labels are not passed
  through `plain()` (only output lines, `:232`, `:703`).
- **Evidence.** `plain('ESC]8;;https://x.example ESC\click … ‮abc \x9b31m \x7f')` ->
  `']8;;https://x.example\\click]8;;\\ ‮abc \x9b31m \x7f'`.
- **Impact.** Display only (all PlainText, nothing clickable): leftover OSC text, and an RLO in a
  branch name, test line or Claude output can visually reverse the rest of a line (spoofing a
  status). No markup, no link, no execution.
- **Fix.** Before removing ESC, strip OSC (`\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)`) and other ESC
  sequences; also strip `\x7f-\x9f` and Unicode bidi controls (U+200E/F, U+202A-202E,
  U+2066-2069); apply `plain()` to repo names, reasons and step labels too.

### P3-5 "Open in Terminal" tooltip still uses rich-text auto-detection (carried over)
- **Where.** `ui/progress_window.py:800-801` (`"…project folder of " + view.folder_names`);
  same text as HEAD `ui/apps_tab.py:976`.
- **Impact.** App names come from `apps.toml` (the owner's config); a name with tags would render
  as markup in the tooltip. Spoofing only.
- **Fix.** Use the existing `plain_tip()` (`ui/apps_tab.py:49-52`) or `html.escape`.

## Answers to the five checks
1. **durations.json.** Atomic temp + `os.replace` in the same dir, 0600, temp cleanup on error,
   symlink at the target replaced not followed, temp name not attackable, key sanitising,
   names never paths: hold (negatives 1-4). Size cap before read: present but bypassable
   (P3-2). Lenient load: fails for deep nesting and huge integers (P2-1).
2. **Untrusted text in the UI.** Plain text on every QLabel and the output pane; no rich-text
   path; ANSI CSI and C0 stripped; pane bounded to 5000 blocks (negative 5). Gaps: OSC/C1/bidi
   residue (P3-4), one-huge-line freeze (P3-3), one carried-over tooltip (P3-5).
3. **Command paths.** No new shell invocation; Update now's `$SHELL -lc` with `child_env()`
   unchanged; Verify is read-only and runs no build output (negatives 6-7). Kill on Escape/close
   works for a running build (negative 9) but only for the direct child (P2-2) and not before the
   first start (P3-1).
4. **Clipboard.** Unchanged (negative 8).
5. **DoS.** Stage-marker and ANSI regexes linear (negative 10); output spam bounded by line count,
   not line length (P3-3).

## Not verified
- The Land-side consequence of P2-1 (Stop button hidden) was read from the code, not run.
- P3-1 with real keyboard/close events on a real display.
- A real `build_app.sh` cancelled mid-PyInstaller (P2-2 used a stand-in script).
- `/dev/zero` read in P3-2 (not run deliberately).
- Full test suite; `pip-audit` itself (OSV API used instead).

## Verdict
No P0 or P1. The change keeps every display path plain text (better than HEAD's Check builds box),
runs nothing new, and the cache write is sound. Recommend fixing **P2-1** before Release (small,
testable, and it is the spec's own "never raises" promise); **P2-2** is pre-existing and can be
deferred by the owner with a wording change, but the fix is small. P3s are optional hardening.
Secure does not block on its own; the owner decides on P2 deferral.
