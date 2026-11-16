# Code review: Resolve wastes nothing (spec repo-tidy §12)

Reviewer: `code-reviewer` subagent (read-only), 2026-11-16. Branch `claude/resolve-preflight`, uncommitted change. The reviewer has no write tool, so the build session saved its report here unchanged in substance.

Scope: `lab_hub/claude_resolve.py` (work root, tests on the default branch first, `DELETE:`, `last_tries`), `lab_hub/hygiene.py` (badge), `ui/repo_tidy_dialogs.py` (Last Resolve column), `ui/apps_tab.py` (texts), tests.

Test runs by the reviewer: the four touched test files (129 tests) and the full suite passed.

## P0 / P1

None. Nothing touches the main checkout before the final `merge --ff-only`. Every new git call goes through `_Tmp.git` (explicit `--git-dir`/`--work-tree`, hooks off). A `DELETE:` path must equal an entry of the unmerged list.

## P2

- **P2-1 — the clean-up before the merge had no test** (`claude_resolve.py`, the `reset --hard` / `clean -ffdxq` condition). With it disabled, every test still passed. Without the reset, a tracked file that main's own tests rewrite would end up in `before_changed`, so the outside-change check would skip it and it would be committed into the merge.
- **P2-2 — `git rm` treated the `DELETE:` name as a glob.** With files `d/*`, `d/x` and `d/y`, `DELETE: d/*` removed all three. The removed files vanish from both the index and the worktree, so the outside-change check misses them.
- **P2-3 — the prompt invited deleting a "moved" file.** That drops the other side's edits, with no way to carry them to the new path.
- **P2-4 — the new UI and copy were untested:** the Last Resolve column and the Check repos and tooltip texts.

## P3

- **P3-1:** main's tests ran again for every conflicting branch.
- **P3-2:** a repeated `DELETE:` line failed the branch, after a paid Claude run.
- **P3-3:** `last_tries` matched a landed line by substring, so `/lab/x y` cleared `/lab/x`.
- **P3-4:** the badge for a diverged repo dropped "behind", and lines it did not recognise showed "1 item · 1 item".
- **P3-5:** the Resolve tooltip implied that tests gate every merge.
- **P3-6:** the fallback work folder is not re-checked for whitespace or ownership.

## Fixes (build session, 2026-11-16)

| Finding | Fix | Test |
|---|---|---|
| P2-1 | None needed; the guard was already there, and the new test proves it. | `test_a_tracked_file_the_main_tests_rewrite_is_not_merged`; mutation: removing the whole condition is caught |
| P2-2 | `git rm -- :(literal)<name>` | `test_a_deletion_is_literal_not_a_glob` (`d[x].txt` next to `dx.txt`) |
| P2-3 | **Mitigated, not removed.** The prompt now allows a deletion only when the other side's changes are already present elsewhere or no longer matter, and asks Claude to say why. Requiring an unchanged keep-side, as suggested, would disable the feature: git only reports a modify/delete conflict when the keep-side changed the file. The dropped edits stay in history through the merge's second parent. **Owner may veto this (spec §12.5).** | prompt test |
| P2-4 | Tests added. | `test_review_fills_the_last_resolve_column`; the report test checks the info line and both tooltips |
| P3-1 | A pass is cached per (repo, default tip, test command) within the Lab Hub process. | `test_main_is_tested_once_per_tip` |
| P3-2 | Duplicate names are dropped. | `test_a_repeated_deletion_line_is_fine` |
| P3-3 | The landed line is parsed with an anchored regex. | `test_a_landed_line_clears_only_its_own_repo` |
| P3-4 | Diverged shows both counts; unrecognised lines are summed ("2 items"). | parametrised badge test |
| P3-5 | Tooltip: "for a conflict, Claude Code resolves it and the tests decide". | report test |
| P3-6 | Not fixed. On macOS the fallback is the per-user `$TMPDIR` folder, and it is used only when the home path has whitespace. | — |

## Mutation check (Verify, 2026-11-16)

19 mutations on a scratch copy, all caught:
- the whitespace fallback;
- the tests-on-main gate, the clean-up (whole condition), and the cache lookup and store;
- the `DELETE:` checks: in the conflict list, both sides keep it, the call itself, literal pathspec, de-duplication;
- `last_tries`: start pairing, the landed pop and landed removal;
- the badge: singular/plural and unknown lines;
- the Last Resolve sha match and its tooltip.
