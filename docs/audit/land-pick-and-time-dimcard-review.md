# Review: land-pick-and-time, dimmed unticked card (late change)

Reviewer: code-reviewer (read-only; a different agent from the author). Date: 2026-11-19.
Scope: only the late change that dims an unticked Land card. It is not in `97ae832` (that commit is just the
activity log line). The code is in autosync `00c7bb0` (2026-11-19 09:09): `ui/theme.py:520-527`,
`tests/test_land_confirm.py:450-459`, QA note `docs/audit/land-pick-and-time-qa.md`. It uses the existing
`out` property set at `ui/land_confirm.py:188-190`. The rest of the spec was reviewed earlier
(`land-pick-and-time-review.md`). Released unreviewed in build 222. No code was changed.

## Verdict
No P0, no P1. The rule applies correctly. One P2 test gap, two P3.

## What was checked
- **Selector**: `QFrame#card[out="true"]` (`theme.py:524`) matches `RepoCard` (objectName `card`,
  `land_confirm.py:104`). `ClaudeBox` also uses `card` but never sets `out`, so it is untouched. The attribute
  selector is more specific than `QFrame#card` (`theme.py:517`) so it wins regardless of order.
- **Qt dynamic property**: Qt does not restyle on a property change; `_toggled` calls `unpolish`/`polish` right
  after `setProperty` (`land_confirm.py:188-190`), the correct pattern. Initial state has no property, which
  matches `[out="true"]` as false. Re-ticking sets "false", so the card returns to its normal look.
- **Children**: `QFrame#card QLabel { background: transparent }` is unchanged, so the labels draw on the
  transparent card. Name label switches to the `hint` object name (`:185-187`), the pills hide, "Left out" shows.
- **Palettes**: `_rgba(p.text, 0.25)` is the same helper used elsewhere; alpha is 0-255 (`theme.py:254-256`).
  Both palettes get the rule (the test checks the selector in GRAPHITE and PAPER).
- **Tests run**: `tests/test_land_confirm.py` with the swipe tests (result at the end of this report).

## Findings

### P2-1 The test pins the selector text, not the look
`tests/test_land_confirm.py:450-459` asserts the property flips and that the string `QFrame#card[out="true"]`
is somewhere in the stylesheet. It does not check the rule body. Deleting `background: transparent` or the
dashed border, or changing its alpha to something invisible, leaves the test green, so the "dimmed" outcome
the spec §2 promises is not guarded. The two mutants QA ran (renamed selector, property always "false") are
the ones this test does kill; a body mutant was not tried.
Fix: assert the rule's declarations (substring match on the block), or render the card offscreen and compare
the pixel at the border/background between ticked and unticked.

### P3-1 The evidence screenshot predates the rule
`docs/audit/land-pick-and-time-confirm.png` was last committed 2026-11-18 13:15 (`7aacfd2`); the QSS rule came
09:09 the next day. The screenshot is therefore from the name-dimmed-only version and does not show the dashed
card. Not verified on screen by this review either. Re-render before relying on it as evidence.

### P3-2 QA note carries the wrong date
`docs/audit/land-pick-and-time-qa.md` says "Settled 2026-11-18" for a change committed 2026-11-19 09:09.
Cosmetic; the owner's choice of a QSS rule is quoted there but the owner's words are not recorded.

## Not checked
Real display and real Land all (see the spec's own "not verified" note). Contrast of the dashed 25% border on the
PAPER palette was judged from the numbers only.

## For the owner: P0/P1
None.

## Run note
`tests/test_swipe.py tests/test_land_confirm.py`: 80 passed (9.4 s), run from the worktree with the main checkout venv, 2026-11-19. Full suite not run.
