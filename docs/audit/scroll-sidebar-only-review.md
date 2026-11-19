# Review: scroll-sidebar-only

Reviewer: code-reviewer (read-only; a different agent from the author). Date: 2026-11-19.
Scope: PR #13, merge `a87ddba` (feature commits `d9e86f8`, `a1c084f`): `ui/swipe.py`, `ui/main_window.py:218`,
`tests/test_swipe.py:497-551`, CHANGELOG. Released unreviewed in build 222; this review closes that gap.
Tests run: `tests/test_swipe.py` + `tests/test_land_confirm.py` (result in the run note at the end).
No code was changed.

## Verdict
No P0, no P1. The change does what the spec says and the wiring is tested through the real `MainWindow`.
Two P2 test gaps and four P3 items.

## What was checked
- **Zone logic** (`ui/swipe.py:289-293`, `295-306`): with a zone set, a vertical gesture returns every registered
  tab widget over the sidebar and `[]` elsewhere; `vertical_zone=None` keeps the old path unchanged (direct-use
  tests still cover it). Horizontal gestures never reach the zone branch (`vertical` is False), so sideways
  swipes are unchanged, as the spec says.
- **Event flow**: `_on_wheel` and `_on_native_gesture` both go through `_candidates(..., vertical=True)`, so
  wheel and three-finger vertical swipe are both covered. Over a page the wheel handler returns False before
  anything is accumulated (`swipe.py:255-257`), so the page scrolls and no partial threshold carries over.
  `_change_tab` returning False lets the native gesture pass through.
- **Qt**: the filter is installed on every widget in the window (`_scan`), so a wheel over a sidebar button
  reaches it with `obj` = that button; `isAncestorOf` handles that. A wheel a child ignores propagates to its
  parent and is filtered again; inside the page that stays outside the zone. Dialogs and popups are separate
  windows, outside the zone. Web views are skipped (`_SKIP`), so they scroll natively. `shiboken6.isValid(zone)`
  guards a destroyed sidebar.
- **Regression**: the sidebar is not a scroll area (no scroll code in `ui/sidebar.py`), so taking its
  `_can_scroll` check out of the zone branch loses nothing today. The Tools sub-tabs are not registered with the
  filter, so no vertical fall-through is lost.

## Findings

### P2-1 The "pointer on a child of the sidebar" path is untested
`ui/swipe.py:293` (`widget is zone or zone.isAncestorOf(widget)`). Every test sends events to
`window.sidebar` itself (`tests/test_swipe.py:509-512`, `:540-546`). In use the pointer is almost always over a
page button, the header or the footer button, i.e. a descendant. Replacing the line with `widget is zone` leaves
all new tests green, while real scrolling over the sidebar's buttons would stop working. (Mutation not run;
derived from reading the tests. QA to confirm in Verify.)
Fix: add a test that sends the wheel to `window.sidebar.button_for(...)` and to the footer refresh button.

### P2-2 No test pins the old behaviour `vertical_zone=None`, now beside a zone
The existing direct-use tests (`tests/test_swipe.py:135-170`) cover `None`, so this is covered; but nothing tests a
destroyed zone (`shiboken6.isValid` false at `swipe.py:293`). Low risk, one-line test with `sip`/`deleteLater`.

### P3-1 Stale status line in the spec
`docs/specs/scroll-sidebar-only.md:3` still reads "waiting for the owner's approval. Not built." The define gate
was approved 2026-11-18 12:25 and it shipped in build 222. Update when Document is logged.

### P3-2 Review, Verify and Document were never logged
`docs/foundry/activity.jsonl:181-200`: define, build, release only. CHANGELOG has the entry; README and user docs
do not mention scrolling (grep found nothing), so nothing else to update. Verify (QA) has still not run: this
review does not replace it.

### P3-3 A gesture that starts over the sidebar and drifts onto a page is swallowed
`swipe.py:240-243`: once `_armed` is False the rest of the gesture returns True, before the zone check. A
gesture that changed section over the sidebar and then moves onto a page inside `IDLE_RESET_S` will not scroll
that page. Same as before the change for any pointer position; the new rule makes it more visible. Acceptable.

### P3-4 Future: a scrollable sidebar could not be wheel-scrolled
If the sidebar ever gets many entries inside a scroll area, the zone branch ignores `_can_scroll_vertically`,
so it would always switch section. Note for whoever adds that.

## Test coverage
Good: sidebar changes section (`:509`); page never changes section, both directions, both pages (`:515`); end of
a scrolling page does not move on (`:524`); three-finger vertical over page vs sidebar (`:540`); sideways still
works over a page (`:548`). The tests go through `window.swipe`, so removing `vertical_zone=` in
`ui/main_window.py:218` would fail them.

## For the owner: P0/P1
None.

## Run note
`tests/test_swipe.py tests/test_land_confirm.py`: 80 passed (9.4 s), run from the worktree with the main checkout venv, 2026-11-19. Full suite not run.
