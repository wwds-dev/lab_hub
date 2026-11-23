# Spec: vertical scrolling switches section only over the sidebar

Needs: define, build, verify, docs

Status: **Shipped in build 222 (2026-11-19).** Define approved by the owner 2026-11-18; review `docs/audit/scroll-sidebar-only-review.md` (no P0/P1); verify `docs/audit/scroll-sidebar-only-qa.md`.
In-flight check (`session_start.py --inflight`, 2026-11-18): no spec or worktree touches scrolling or `ui/swipe.py`.

## 1. Problem and evidence
The owner: "only scroll to the next section (eg from apps to websites) when the mouse is in the leftside menu, not in the main window. only scroll there inside the window and not between sections."
- Today `SwipeTabs` (`ui/swipe.py`) turns a vertical wheel or trackpad scroll into a section change anywhere in the window, as soon as the page under the pointer cannot scroll further or fits its window (`_candidates(..., vertical=True)`, `_on_wheel`).
- So scrolling a page to its end, or over a short page, jumps to the next section (Apps → Websites → …). Three-finger vertical swipes do the same (`_on_native_gesture`).

## 2. User and success measure
User: the owner, anywhere in the main window.
1. **Pointer over the left sidebar:** a vertical scroll moves between sections, as today (threshold, no wrap, one section per gesture unchanged).
2. **Pointer over the main page area:** a vertical scroll only scrolls that page. It never changes section, at the top, at the bottom, or on a page that fits.
3. Same for the three-finger vertical swipe: sidebar only.
Measured by tests: a synthetic vertical `QWheelEvent` over the sidebar changes section; one over a page that fits, and one over a page at its end, do not.

## 3. Scope and open question
- **In:** vertical wheel and vertical three-finger swipe.
- **Not changed (owner to confirm):** the sideways two-finger and three-finger swipes (spec'd 2026-10-07) keep changing section from anywhere. Your words were about scrolling, so I left them. Say so if sideways swipes should also be sidebar-only.

## 4. Design
`SwipeTabs` gets an optional `vertical_zone` widget. When set, a vertical gesture counts only if the widget under the pointer is that widget or inside it. The window passes its sidebar. Without it (direct use in tests) behaviour is unchanged. No new state, threads or boundaries; no ADR. No UI text changes, so no Design phase beyond this.

## 5. Phases
Define (this), Build, Verify, Document (CHANGELOG). Skipped: Case, Architect (no state/concurrency), Secure (no network, input or files), Comply and Launch (tier `internal`/`public`, no claim changes), Release (owner's call).
