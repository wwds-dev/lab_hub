# Review: no-sideways-swipe (code-reviewer, independent, 2026-11-24)

Commit cb1be90. Reviewer ran `tests/test_swipe.py`: all pass. 0 P0, 0 P1.

Verified by reading: sideways and diagonal wheel returns early in `_on_wheel` (`ui/swipe.py:223`) before anything accumulates; native 0/180/135/225 degrees fall through to `return False` (`:197`); vertical-over-sidebar unchanged; `_can_scroll_horizontally`, `SWIPE_ANGLE_LEFT` and `vertical=` are gone. Tests not weakened.

## P2
1. Stale names and claims: `HORIZONTAL_DOMINANCE` now gates the vertical path (rename to `VERTICAL_DOMINANCE`); README still lists "the sideways-scroll veto" among the mutation-tested rules.
2. The once-per-gesture latch (`ui/swipe.py:206-217`) swallows any wheel event for up to 0.4 s after a section change, a sideways scroll over a wide table included. Inherited, not a section change; spec measure holds.
3. `_candidates` docstring describes the page-ancestor walk, which only tests use; the zone branch is the live path.

## P3
4. Test gaps: no sideways-dominant wheel with a smaller vertical part, no |x| = |y| boundary, no native 135/225 degrees, no sideways input with two registered tab widgets.

Not verified: `ruff` (not installed in the venv).
