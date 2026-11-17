# Security review: land-confirm-dialog

Reviewer: `security-engineer` (independent, read-only, Sonnet), 2026-11-17. Target: commits `4072f72` and `b2c0ab5`, plus the uncommitted P3-4 and P3-5 edits in `lab_hub/land.py`. Not run: the dialog itself and any tests; the reviewer read the code. `app-context.md` "Security surface" is still a placeholder.

**Verdict: no P0 or P1.**

Threat model:
- Assets: the owner's repos (merge, push, branch delete), Claude Code spend, and code sent to Anthropic.
- Trust boundary: git output (branch names, reasons) and `lsof` output (process names, which any local process sets itself) shown in Qt labels, a tooltip and Details.

## Checks that held
- **Markup injection.** Every label uses `_label`, which sets PlainText (`ui/progress_window.py:53`). The one tooltip goes through `_plain_tip`, which escapes the text. Details is a `QPlainTextEdit`. The window title and button texts are constants.
- **Disclosure integrity.** `LandPlan.cost` uses the same inputs as `claude_notice`. A plan that can run a Claude merge always yields the panel. The panel sits outside the scroll area, cannot be collapsed, and Details does not hide it.
- **Return and Escape.** Every button has autoDefault and default off. Escape rejects.
- **Subprocess.** `lsof` comes from a fixed search path and runs from an argument list, with no shell. It has a timeout, and the output is parsed line by line.

## Findings
- **P2-1. Real process names in the public repo.** `docs/specs/land-confirm-dialog-screenshot*.png` show the lab's repo names (already public), process names (`gk`, `gk_3_1_80`, `node`, `zsh`, `claude`) and process counts. That is a mild fingerprint of the owner's machine. No home path or username is visible. Fix: commit screenshots made from demo data, and keep the real-lab ones out of the repo.
- **P3-1. Process names are shown verbatim and without length limit.** A process can name itself, for example "Nothing else to do here until this is cleared.", or something long. Details lists every one. Not verified: whether `lsof -F` escapes a newline in a name; if it did not, a fake `p` or `n` line could be forged. Fix: strip control characters and cut names in `processes_in`, and cap the Details list ("and N more").
- **P3-2. No test ties the panel to the cards.** Nothing checks that `claude_panel` is non-None whenever any card shows a Claude Code amount. Fix: add that test.
- **P3-3. One `lsof` run per busy worktree, with a 30 s timeout each.** Planning runs on the worker thread. Several busy worktrees each run `lsof` again. Fix: run `lsof` once per plan, and use a shorter timeout.

## Disposition
Fixed by the author on the owner's "fix the left items", 2026-11-17:
- P2-1: the committed screenshots now use demo data (`web-app`, `api`; process names `shell`, `editor`, `server`). The real-lab screenshots stay outside the repo, in the session notes folder. The earlier real-lab PNGs remain in git history (commits `4072f72` and `b2c0ab5`); removing them from history needs a rewrite of `main`, the owner's call.
- P3-1: `land_resolve._shown_name` replaces control characters with "?" and cuts a name to 40 characters (`NAME_MAX`). On macOS, `lsof` reports the kernel's short command name (16 characters at most), so the cut is a guard. Details keeps every process, as spec §2.8 requires. Not verified: whether `lsof -F` escapes a newline in a name. The parse and the display are now safe either way, but a forged `p` or `n` line would still be parsed.
- P3-2: `test_the_panel_total_is_the_old_notices_amounts` asserts the panel exists exactly when a card shows a Claude Code amount.
- P3-3: `prep` runs `lsof` once per repo, and only when a worktree is busy (`cwd_listing`, shared by every stop). The timeout is now 10 s (`LSOF_TIMEOUT`). Tested: `test_one_lsof_run_serves_every_busy_worktree_of_a_repo`.
