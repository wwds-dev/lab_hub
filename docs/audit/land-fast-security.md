# Security review: land-fast (2026-11-17)

Reviewer: `security-engineer` agent, read-only. Playbook last reviewed 2026-11-11. The Security surface section of `app-context.md` is still empty, so the scope came from the brief. The reviewer ran `tests/test_land_fast.py` (23 passed). There was no dependency audit, because the diff changes no manifest.

**Summary:** the change adds no way for branch content to land. It is stricter than before.

| # | Sev | Finding | Disposition |
|---|---|---|---|
| 1 | P1 (pre-existing) | A branch can change `.claude/settings.json`, hooks or agent prompts with no conflict, through a plain merge or a Claude merge of other files. The change lands unreviewed and is pushed to a public repo. `protected()` applies only to conflicted files. | **Not fixed. Owner decision**, spec land-fast §11. Recommended: a follow-up spec that diffs the merge result against the default tip for `.claude/` paths. |
| 2 | P2 | Taking the default branch's copy drops the branch's edits to Foundry-owned files. In the Foundry HQ those files are the source, not copies. | Fixed in part. The Foundry rule now applies only in repos that have `docs/foundry/app-context.md` (an app Foundry installed into); the HQ has none, so the files are protected there. The dropped files are named in the progress line and in a `FOUNDRY files taken from …` log line. In apps, dropping them is the owner's §5.1 A decision. |
| 3 | P3 | The blocker kind was found by a substring match on text the branch controls. | Fixed. Matching is anchored at the start of the message. |
| 4 | P3 | A failing tip stays cached when Resolve runs outside Land. | No change needed. Land is the only caller of `repo_tidy.apply`/`claude_resolve.resolve` (`grep` of `ui/` and `lab_hub/`), and every Land clears its repo's entries. |

Checked by the reviewer with no finding:
- Path tricks: case, nested `.claude`, `..`, quoting. Unicode was not verified on HFS+.
- Argument injection in `_take_default`: `--` plus `:(literal)`, and the sha is a full SHA.
- A symlink used to edit through into `.claude/` is caught by the "changed files outside the conflict" guard.
- Skipping the base run cannot let untested code land: every landed commit passes its own test run.
