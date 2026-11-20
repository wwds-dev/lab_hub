# QA: scroll-sidebar-only

Role: qa-engineer work, 2026-11-19. Production code unchanged; tests and docs only.
Inputs: spec `docs/specs/scroll-sidebar-only.md`, review `docs/audit/scroll-sidebar-only-review.md` (P2-1, P2-2).

## Tests added (`tests/test_swipe.py`, end of file)
- `test_a_vertical_scroll_over_a_child_of_the_sidebar_changes_section`: wheel sent to a nav button (`sidebar.button_for(...)`) and to the footer `refresh_button`. (P2-1)
- `test_a_three_finger_vertical_swipe_over_a_child_of_the_sidebar_changes_section`: same two widgets, native swipe. (P2-1)
- `test_a_destroyed_vertical_zone_counts_as_outside_it`: `shiboken6.delete(sidebar)`, then `_in_vertical_zone` is False, a vertical wheel over a page returns False, no crash, section unchanged. (P2-2)

## Mutation check of `ui/swipe.py` `_in_vertical_zone` (line 293)
| # | Mutant | Result |
|---|---|---|
| M1 | `(widget is zone or zone.isAncestorOf(widget))` -> `(widget is zone)` | killed: 2 failed (the two child-of-sidebar tests); 38 passed |
| M2 | drop `shiboken6.isValid(zone) and` | killed: 1 failed (`test_a_destroyed_vertical_zone_counts_as_outside_it`); 39 passed |

Before M1 the pre-existing tests were all green, confirming the review's P2-1 claim. `ui/swipe.py` restored after each mutant;
sha1 before and after identical (`19241359ffa7...`), `git status` shows it unmodified.

## Runs
- `tests/test_swipe.py`: 40 passed (12.3 s) with the tests added, main checkout venv.
- Full suite: not run (about 19 min); the change touches only a test file and docs. Not verified.

## Success measure
Met for the spec's behaviour: sidebar (bare, child, footer) changes section by wheel and three-finger vertical swipe; pages never do; sideways unchanged.

## Verdict
Verify: pass, no open findings. Review P3-3 and P3-4 stay as notes.
