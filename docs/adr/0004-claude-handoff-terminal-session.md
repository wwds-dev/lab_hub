# ADR 0004: Ask Claude opens `claude` in Terminal, one session per repo, with per-session permission rules

Status: accepted by the owner 2026-11-17 ("Approve architecture"); amended 2026-11-18 after review (setting sources, more deny rules, `--add-dir`), approved by the owner ("Fix all as proposed"); amended again 2026-11-18 after Verify and Secure (inline rules, folder checks, fenced rows, limit 7), approved by the owner ("Fix as proposed").
Spec: `docs/specs/claude-handoff.md` §10.

## Context
Check builds and Land end with rows that only a person or a Claude Code session can clear. The owner chose (Define, 2026-11-17, "Approve, use defaults"):
- a Terminal session;
- Claude Code's default permission mode (`manual` in 2.1.304);
- no model forced on the session;
- one session per repo.

The hard limits in spec §4.2 must hold even if the session ignores its prompt. The prompt carries text that comes from repos: branch names, file names, reasons that quote git.

## Decision
1. **Route.** Lab Hub hands one composed line to `launcher.control.run_in_terminal`, the existing `.command` route.
   - That route needs no Apple Events grant and types nothing into a window.
   - It was reviewed in `update-now-terminal`.
   - Each launch gets its own folder under `SUPPORT_DIR/claude-handoff/`, so a launch never removes another launch's files.
2. **Repo text never becomes shell syntax.**
   - The task goes in `prompt.md` and the limits in `limits.md`. Both reach `claude` only as `"$(cat -- <file>)"` arguments.
   - Every other value in the line goes through `shlex.quote`: paths, the `claude` path and the session name.
   - The line passes `check_terminal_commands` (one line, no NUL).
3. **The limits are enforced three ways.**
   - **As text:** the limits are appended to the system prompt (`--append-system-prompt`) and repeated in the task.
   - **Every change asks:** the session runs in `--permission-mode manual`. Read-only commands and reads inside the working folders run without asking.
   - **Only user and project settings** (`--setting-sources user,project`). A repo's `settings.local.json` can allow `python3 -c '…'`, which would run around every rule below; every lab repo's checked-in `settings.json` holds hooks only (checked 2026-11-17), so the Foundry hooks still run.
   - **Per-session rules, inline** (`--settings '<json>'`, amended 2026-11-18 from a file, security P3-3):
     - `ask` rules for push, merge, tag and install, so an allow rule in the owner's own settings cannot let them run without asking;
     - `deny` rules for the sign-off and approval commands, any command naming `signoff.jsonl`, and the Edit and Write tools on it, which no answer in the session can override.
   - **What the rules cannot hold.** A command that reaches git or a sign-off file indirectly (a script, inline Python) matches no rule. `manual` mode still asks the owner before it runs.
4b. **A folder outside the repo, only from Lab Hub's own command.** When a row's command starts with `cd <folder>` or `git -C <folder>` (Provisio's release clone), that folder is added with `--add-dir`, named in the prompt and shown in the confirmation. It is refused when it is `/`, the home folder, the lab root, the repo or above it, or another registered app's checkout (security P2-1).
4. **One session per resolved git top level**, started with `cd -- <repo>`. Apps that share a repo share its session. Nothing is ever started in the lab root on behalf of several repos.
5. **No tracking.**
   - Lab Hub keeps no record of a session it started and never reads one back.
   - "Already running" is found fresh on each click from one `lsof` cwd listing. That is a process named `claude` whose folder is inside the checkout or one of its worktrees.
   - Reuse means Lab Hub copies the prompt to the clipboard; it cannot reach into a running session.

## Alternatives considered
- **The Claude desktop app's Code tab.** No documented way was found for another app to start a desktop session with a folder and a starting prompt. Driving the app would need Apple Events or accessibility control, which this app has avoided so far. Revisit if the desktop app gains a URL scheme for it.
- **`claude -p` run by Lab Hub, like merge resolution.** It is non-interactive, so the owner could not answer "may I push?" in it. The owner-only items need a conversation.
- **Typing into an existing session for reuse.** That needs Apple Events and risks typing into the wrong window.

## Consequences
- **Cost.** Each opened session is a paid, uncapped interactive session. The confirmation says so, and only ticked repos open.
- **New launch surface.** There is a new process launch and new support-folder writes. **Secure is required.** It must check:
  - the quoting test with a hostile repo name;
  - folder creation with no-follow;
  - the clean-up pattern;
  - that `deny` and `ask` hold in the real CLI (Verify on the real Mac: a `git push` in an opened session asks; `legal_gate.py sign` is refused).
- **Coupling to Claude Code's flags.**
  - The design depends on `--permission-mode manual`, `--setting-sources`, `--settings`, `--add-dir`, `--append-system-prompt`, `-n` and the positional prompt.
  - If a flag is renamed, the open fails visibly: the Terminal window shows the CLI's error, and nothing runs without permission.
  - The radar check at Release re-reads `claude --help`.
- **Late clashes.** A session can still meet a Land or Update now started later by the owner. Those runs keep their existing guards.
