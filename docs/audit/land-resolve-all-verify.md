# Verify: land-resolve-all (2026-11-17)

QA: `qa-engineer` agent, which is not the author. It ran mutations on a copy of the worktree, using
`pytest -q -x tests/test_land_resolve.py tests/test_land.py`.

The author kept editing during this run, so the results below are for the earlier copy. A second QA run
on the final code is recorded at the end.

## First run (on the earlier copy)
- **Full suite:** 766 passed, 1 skipped (Imprint is not checked out), 0 failed.
- **Mutations:** 10 of 20 killed.
  - Killed: a, b, c, d, e, g, h, i, j, s. These cover secret names, `gitleaks:allow`, scanning in a
    subfolder, the archive sha guard, the link-repair guard, retrying failed merges, the size rule, the
    land-mode commit rule, the `.gitignore` append and the safe names.
  - Survived:
    - f: "Landed" while `open_items` is not empty
    - k: a non-zero gitleaks exit is ignored
    - l: an unreadable gitleaks report counts as clean
    - m: a reply with no VERDICT line archives the branch
    - n: `apply_step` does not re-check its guard
    - o: a clean orphan detached HEAD is not rescued
    - p: `archive` skips the dirty-worktree check
    - q: no push after triage
    - r: `open_items` ignores ahead and behind
    - t: `restore` skips the tag sha check
- **Success measures:**
  - 3 and 4 are covered.
  - 1 is covered by a fixture stand-in. The real-lab screenshot is still owed.
  - 2 is mostly covered. Gitleaks failing and a rejected push are untested.
  - 5 is partly covered. The rescue and archive wording is untested.
- **Verdict: pass with gaps.**

## Gaps closed after the first run
Tests added in `tests/test_land_resolve.py`, one for each survivor: f, k, l, m, n, o, p, q, r and t,
plus the wording for measure 5. The second run is below.

## Second run (final code, 2026-11-17)
- **Mutations:** 27 planted, 26 killed (`a`–`z`, plus `e2`). The previous survivors f and k–t are now
  killed.
- **The one survivor, q,** removed the push after triage. It survived because no test had a branch
  landing on Claude's verdict. The author added `test_a_branch_landed_on_claudes_verdict_is_pushed`. The
  author re-planted q, and the new test failed, as it should.
- **Measure 5:** `test_each_prep_step_says_what_it_will_do` now asserts the preview wording for each step.
- **Full suite on the final code:** 791 passed, 1 skipped. That run came before the last two tests.
- **Live eval:** real Claude Code (`sonnet`) on a toy repo with two branches.
  - An abandoned joke-banner experiment got **archive**.
  - A tested `subtract` fix got **land**.
  - Both verdicts are correct. Total cost $0.0268, recorded with `model_use.py --purpose eval`.
- **Still owed:** measure 1, the real-lab Land all screenshot and log. That needs the owner to run Land on
  the lab.

**Verdict after fixes: pass, except measure 1, which needs the real-lab run.**
