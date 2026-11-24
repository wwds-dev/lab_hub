# Spec: remove the sideways trackpad swipe that changes section

Needs: define, build, verify, docs

Status: **Define draft, awaiting the owner's gate.** Phase: Define, 2026-11-24.
In-flight check (`session_start.py --inflight`, 2026-11-24): `scroll-sidebar-only` is shipped (build 222) and left sideways swipes alone (its §3); no other spec or worktree touches `ui/swipe.py`.

## 1. Problem and evidence
Owner, 2026-11-24: "remove the feature that scrolls in the menu up and down when the user scrolls on the trackpad from left to right and reverse."
- `SwipeTabs` (`ui/swipe.py`, wired at `ui/main_window.py:233`) turns a sideways two-finger scroll (`QEvent.Wheel`) and a sideways three-finger swipe (`NativeGesture`) into a section change (Apps, Websites, …) from anywhere in the window (spec'd 2026-10-07).
- The sidebar moves one entry up or down per gesture, so a sideways wobble on the trackpad changes the page by accident.

## 2. Success measure
1. A sideways two-finger scroll or three-finger swipe, over the sidebar or any page, never changes section.
2. Unchanged: vertical scroll and vertical three-finger swipe over the sidebar still change section; over a page they only scroll it (`scroll-sidebar-only`); clicking the sidebar works.
3. Measured by tests: a synthetic horizontal `QWheelEvent` and a left/right `SwipeNativeGesture` change nothing; the vertical-over-sidebar tests still pass.

## 3. Scope
- `ui/swipe.py`: drop the horizontal paths (`_can_scroll_horizontally`, the horizontal branch of `_on_wheel`, left/right in `_on_native_gesture`); keep the vertical-zone behaviour. Update the module docstring.
- `ui/main_window.py:228-233`: comment only.
- `tests/test_swipe.py`: horizontal tests become "does nothing" tests; CHANGELOG; README if it mentions swipes.
- Not in scope: renaming `SwipeTabs`, the three-finger vertical swipe, any new setting.

## 4. Phases
Define (this, **GATE**: user-visible removal), Build, Review (independent), Verify, Document. Skipped: Case, Architect (no state, concurrency or boundary), Secure (no network, input or files), Comply and Launch (internal removal, no claim), Release (owner's call).
