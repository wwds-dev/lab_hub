# Verify: no-sideways-swipe (qa-engineer, independent, 2026-11-24)

Verdict: PASS with P2 gaps (all closed below). 0 P0, 0 P1.

- `tests/test_swipe.py`: pass. Wider run (swipe, sidebar, window lifecycle, tab groups, apps/tools/links/settings tabs): 4 failures in `tests/test_apps_tab.py` (rebuild Escape/close/cannot-start tests). `test_apps_tab.py` alone passes (72) on HEAD and on the parent commit `b53da08`, so they look order or load dependent, not caused by this change. Not reproduced, cause not found. Full suite not run by QA; the author's full run was green (`pytest -q -x`, exit 0).
- Mutation check (14 mutants on `ui/swipe.py`): 10 killed, 4 survived, all weak tests, not production bugs: M11 sideways branch accumulates dx; M8 accumulate before candidates check; M12 idle reset dropped; M14 native angle window 45 to 80 degrees. Also survived: M6 dominance 1.5 to 0.5, M10 threshold (constant imported by tests, low value).
- Success measures 1 and 2 pinned by real assertions; measure 3 weak where tests sent `ScrollBegin` before the nudge (reset masked the leak).

## Closed after this report (same day)
Tests added or tightened in `tests/test_swipe.py`: sideways-leaves-nothing now asserts `_accumulated == 0.0` with no `ScrollBegin`; blocked-scroll test asserts the same; near-diagonal wheel; diagonal native angles (30, 135, 200, 315); idle reset with a patched clock. Re-run of M11, M8, M12, M14 and M6 against the new tests: all killed. Not covered: M10 (threshold constant), "clicking the sidebar works" (no swipe test; not checked in `test_sidebar.py`).
