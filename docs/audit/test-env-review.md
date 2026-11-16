# Review: test time limit and test PATH (spec land-from-tiles §10)

Reviewer: code-reviewer agent (independent, read-only), 2026-11-16; saved here by the build session because the reviewer may not write files. Scope: the uncommitted diff of `lab_hub/claude_resolve.py` and `tests/test_claude_resolve_env.py` on `claude/test-timeout-python`.

**P0: none. P1: none.** Suite at review time: exit 0, 696 collected; the new file alone 17 passed.

## P2 (all acted on in the same branch)
1. A mistyped limit silently fell back to 30 minutes, and the preview never showed the limit. Fixed: `timeout_note` puts the limit, or "its Test timeout line was not understood", into the preview text (`repo_tidy.py`).
2. "Per command" was untested with two commands. Fixed: test added.
3. The comment claimed a typo "cannot hold Land for a day"; the cap is per command and a branch has up to three test runs. Fixed: comment reworded. The cap itself (180 min) is unchanged.
4. A label that is a prefix of another shadowed the real line (`- Run tests timeout: …`). Fixed: the label must be followed by `:` or `(`.
5. A bare `git`/`python3` run by a repo's own tests now resolves to Homebrew's. Intended for `python3`; noted for `git`. Lab Hub's own git lookup is unchanged.

## P3
Loose parsing (`5 minimum`, unicode digits) tightened; fake result object in a test corrected. Not changed: a `## Commands` heading inside a code fence counts; the limit is not part of the preview-drift check (bounded, not safety-relevant); the hint to raise the limit shows even at the cap.

## Not verified
A real Land with a raised limit; an Intel Mac or a machine without Homebrew; lint and type checks.
