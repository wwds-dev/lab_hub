"""Changing section with a vertical trackpad scroll or swipe (sideways ones do nothing).

Driven with synthetic events shaped the way macOS shapes the real ones: a
two-finger page swipe arrives as a run of ``QEvent.Wheel`` with scroll phases,
a three-finger one as a single ``QEvent.NativeGesture``. The gesture itself
cannot be produced from a test, so what is pinned here is everything after the
event arrives — the direction, the once-per-gesture latch, the momentum tail,
and who is allowed to take the gesture away from the tabs.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QNativeGestureEvent, QPointingDevice, QWheelEvent
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QScrollArea,
    QTabWidget,
    QWidget,
)

from ui.swipe import SWIPE_THRESHOLD, SwipeTabs

STEP = int(SWIPE_THRESHOLD)  # one event large enough to cross the threshold


def wheel(widget, dx, dy=0, phase=Qt.ScrollUpdate):
    """A trackpad scroll event, as macOS delivers it (pixelDelta, phases)."""
    return QWheelEvent(
        QPointF(5, 5),
        QPointF(widget.mapToGlobal(QPoint(5, 5))),
        QPoint(dx, dy),
        QPoint(dx, dy),
        Qt.NoButton,
        Qt.NoModifier,
        phase,
        False,
        Qt.MouseEventSynthesizedBySystem,
    )


def native_swipe(widget, angle):
    return QNativeGestureEvent(
        Qt.SwipeNativeGesture,
        QPointingDevice.primaryPointingDevice(),
        3,  # fingers
        QPointF(5, 5),
        QPointF(5, 5),
        QPointF(widget.mapToGlobal(QPoint(5, 5))),
        angle,
        QPointF(0, 0),
    )


def sideways_across(swipe, widget, dx):
    """One whole sideways gesture: begin, a move past the threshold, end."""
    send(swipe, widget, wheel(widget, 0, 0, Qt.ScrollBegin))
    consumed = send(swipe, widget, wheel(widget, dx))
    send(swipe, widget, wheel(widget, 0, 0, Qt.ScrollEnd))
    return consumed


def send(swipe, widget, event):
    """What QApplication's filter would do, without the real event loop."""
    return swipe.eventFilter(widget, event)


def swipe_across(swipe, widget, dy, *, phases=True):
    """One whole vertical gesture: begin, a move past the threshold, end."""
    if phases:
        send(swipe, widget, wheel(widget, 0, 0, Qt.ScrollBegin))
    consumed = send(swipe, widget, wheel(widget, 0, dy))
    if phases:
        send(swipe, widget, wheel(widget, 0, 0, Qt.ScrollEnd))
    return consumed


# ---------------------------------------------------------------------------
# A plain tab widget
# ---------------------------------------------------------------------------


@pytest.fixture
def tabs(qapp):
    w = QTabWidget()
    for name in ("One", "Two", "Three"):
        w.addTab(QLabel(name), name)
    w.resize(400, 300)
    swipe = SwipeTabs(w)
    yield w, swipe, w.widget(0)
    w.deleteLater()


def test_fingers_up_go_to_the_next_tab(tabs):
    w, swipe, page = tabs
    assert swipe_across(swipe, page, -STEP) is True
    assert w.currentIndex() == 1


def test_fingers_down_go_back(tabs):
    w, swipe, page = tabs
    w.setCurrentIndex(2)
    assert swipe_across(swipe, w.widget(2), STEP) is True
    assert w.currentIndex() == 1


def test_one_gesture_changes_one_tab(tabs):
    """A real swipe is a stream of deltas. Each must not be its own tab."""
    w, swipe, page = tabs
    send(swipe, page, wheel(page, 0, 0, Qt.ScrollBegin))
    for _ in range(10):
        send(swipe, page, wheel(page, 0, -STEP))
    send(swipe, page, wheel(page, 0, 0, Qt.ScrollEnd))
    assert w.currentIndex() == 1


def test_momentum_after_the_fingers_lift_is_ignored(tabs):
    """Inertia keeps delivering deltas; acting on them flips several tabs."""
    w, swipe, page = tabs
    swipe_across(swipe, page, -STEP)
    assert w.currentIndex() == 1
    for _ in range(5):
        send(swipe, page, wheel(page, 0, -STEP, phase=Qt.ScrollMomentum))
    assert w.currentIndex() == 1


def test_a_short_nudge_does_not_change_tab(tabs):
    w, swipe, page = tabs
    send(swipe, page, wheel(page, 0, 0, Qt.ScrollBegin))
    assert send(swipe, page, wheel(page, 0, -int(SWIPE_THRESHOLD / 4))) is False
    assert w.currentIndex() == 0


def test_a_mostly_vertical_swipe_with_wobble_still_counts(tabs):
    w, swipe, page = tabs
    send(swipe, page, wheel(page, 0, 0, Qt.ScrollBegin))
    assert send(swipe, page, wheel(page, -STEP, -STEP * 3)) is True
    assert w.currentIndex() == 1


def test_a_vertical_swipe_over_a_page_that_fits_changes_tab(tabs):
    """The pages are listed down the sidebar, so fingers up goes to the next."""
    w, swipe, page = tabs
    assert swipe_across(swipe, page, 0) is False  # no movement, no change
    send(swipe, page, wheel(page, 0, 0, Qt.ScrollBegin))
    assert send(swipe, page, wheel(page, 0, -STEP)) is True
    assert w.currentIndex() == 1
    send(swipe, page, wheel(page, 0, 0, Qt.ScrollEnd))
    assert send(swipe, page, wheel(page, 0, STEP)) is True
    assert w.currentIndex() == 0


def test_a_vertical_scroll_over_a_scrolling_page_keeps_the_gesture(tabs):
    """A page taller than its window scrolls; the tabs do not take that."""
    w, swipe, _ = tabs
    area = QScrollArea()
    inner = QLabel("x")
    inner.setFixedHeight(4000)
    area.setWidget(inner)
    area.resize(200, 100)
    w.addTab(area, "Tall")
    w.setCurrentWidget(area)
    area.show()
    QApplication.processEvents()
    assert area.verticalScrollBar().maximum() > 0, "fixture is not scrollable"
    before = w.currentIndex()
    send(swipe, area.viewport(), wheel(area.viewport(), 0, 0, Qt.ScrollBegin))
    assert send(swipe, area.viewport(), wheel(area.viewport(), 0, -STEP)) is False
    assert w.currentIndex() == before


def test_a_three_finger_vertical_swipe_changes_tab(tabs):
    w, swipe, page = tabs
    assert send(swipe, page, native_swipe(page, 90.0)) is True  # up: next
    assert w.currentIndex() == 1
    assert send(swipe, page, native_swipe(page, 270.0)) is True  # down: previous
    assert w.currentIndex() == 0


def test_it_does_not_wrap_past_the_last_tab(tabs):
    w, swipe, page = tabs
    w.setCurrentIndex(w.count() - 1)
    last = w.widget(w.count() - 1)
    assert swipe_across(swipe, last, -STEP) is False
    assert w.currentIndex() == w.count() - 1


def test_it_does_not_wrap_before_the_first_tab(tabs):
    w, swipe, page = tabs
    assert swipe_across(swipe, page, STEP) is False
    assert w.currentIndex() == 0


def test_a_sideways_three_finger_swipe_does_nothing(tabs):
    """Removed 2026-11-24 (spec no-sideways-swipe): left and right change no tab."""
    w, swipe, page = tabs
    w.setCurrentIndex(1)
    assert send(swipe, page, native_swipe(page, 180.0)) is False  # left
    assert send(swipe, page, native_swipe(page, 0.0)) is False  # right
    assert w.currentIndex() == 1


def test_a_sideways_scroll_does_nothing(tabs):
    """Removed 2026-11-24: neither direction, neither with phases nor momentum."""
    w, swipe, page = tabs
    w.setCurrentIndex(1)
    for dx in (-STEP, STEP, -STEP * 5, STEP * 5):
        assert sideways_across(swipe, w.widget(1), dx) is False
    for _ in range(5):
        assert send(swipe, page, wheel(page, -STEP, phase=Qt.ScrollMomentum)) is False
    assert w.currentIndex() == 1


def test_a_sideways_scroll_leaves_nothing_behind(tabs):
    """Sideways deltas must not count towards a later vertical gesture."""
    w, swipe, page = tabs
    for _ in range(5):
        send(swipe, page, wheel(page, -STEP))
    send(swipe, page, wheel(page, 0, 0, Qt.ScrollBegin))
    assert send(swipe, page, wheel(page, 0, -int(SWIPE_THRESHOLD / 4))) is False
    assert w.currentIndex() == 0


def test_other_native_gestures_are_left_alone(tabs):
    """Pinch-to-zoom must not move the tabs."""
    w, swipe, page = tabs
    event = QNativeGestureEvent(
        Qt.ZoomNativeGesture,
        QPointingDevice.primaryPointingDevice(),
        2,
        QPointF(5, 5),
        QPointF(5, 5),
        QPointF(5, 5),
        0.5,
        QPointF(0, 0),
    )
    assert send(swipe, page, event) is False
    assert w.currentIndex() == 0


# ---------------------------------------------------------------------------
# Something else wants the gesture
# ---------------------------------------------------------------------------


def _scrolling_page(tabs_widget, height):
    """A tab page holding a scroll area whose content is `height` tall."""
    area = QScrollArea()
    inner = QLabel("x")
    inner.setFixedHeight(height)
    area.setWidget(inner)
    area.resize(200, 100)
    tabs_widget.addTab(area, "Tall")
    tabs_widget.setCurrentWidget(area)
    area.show()
    QApplication.processEvents()
    return area


def test_content_that_fits_does_not_block_the_gesture(tabs):
    """A scroll area with nowhere to go vertically is not using the scroll."""
    w, swipe, _ = tabs
    area = _scrolling_page(w, 20)
    assert area.verticalScrollBar().maximum() == 0
    before = w.currentIndex()
    assert swipe_across(swipe, area.viewport(), STEP) is True
    assert w.currentIndex() == before - 1


def test_a_blocked_scroll_leaves_nothing_behind(tabs):
    """The vetoed scroll must not count towards the next one."""
    w, swipe, _ = tabs
    area = _scrolling_page(w, 4000)
    page_index = w.currentIndex()
    for _ in range(5):
        send(swipe, area.viewport(), wheel(area.viewport(), 0, STEP))
    assert w.currentIndex() == page_index
    # Now a small nudge over the tabs themselves, well under the threshold.
    send(swipe, w, wheel(w, 0, 0, Qt.ScrollBegin))
    assert send(swipe, w, wheel(w, 0, STEP // 4)) is False
    assert w.currentIndex() == page_index


# ---------------------------------------------------------------------------
# Nested tabs — Lab Hub's real shape
# ---------------------------------------------------------------------------


@pytest.fixture
def nested(qapp):
    outer = QTabWidget()
    inner = QTabWidget()
    for name in ("Tool A", "Tool B"):
        inner.addTab(QLabel(name), name)
    outer.addTab(QLabel("Apps"), "Apps")
    outer.addTab(inner, "Tools")
    outer.addTab(QLabel("Settings"), "Settings")
    outer.resize(400, 300)
    yield outer, inner, SwipeTabs(inner, outer)
    outer.deleteLater()


def test_a_swipe_inside_tools_moves_between_the_tools(nested):
    outer, inner, swipe = nested
    outer.setCurrentIndex(1)
    assert swipe_across(swipe, inner.widget(0), -STEP) is True
    assert inner.currentIndex() == 1
    assert outer.currentIndex() == 1, "the window's own tabs must not move too"


def test_swiping_past_the_last_tool_leaves_tools(nested):
    """Otherwise Tools is a room you can swipe into and never out of."""
    outer, inner, swipe = nested
    outer.setCurrentIndex(1)
    inner.setCurrentIndex(inner.count() - 1)
    assert swipe_across(swipe, inner.widget(inner.count() - 1), -STEP) is True
    assert outer.currentIndex() == 2
    assert inner.currentIndex() == inner.count() - 1


def test_swiping_back_before_the_first_tool_leaves_tools(nested):
    outer, inner, swipe = nested
    outer.setCurrentIndex(1)
    inner.setCurrentIndex(0)
    assert swipe_across(swipe, inner.widget(0), STEP) is True
    assert outer.currentIndex() == 0


def test_the_outer_tab_bar_always_moves_the_outer_tabs(nested):
    """The tab strip is not inside any tool, so it is unambiguous."""
    outer, inner, swipe = nested
    outer.setCurrentIndex(1)
    assert swipe_across(swipe, outer.tabBar(), -STEP) is True
    assert outer.currentIndex() == 2
    assert inner.currentIndex() == 0


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


def test_the_window_swipes_the_top_row_only(window):
    """Apps to Settings, and nothing else (the user's call, 2026-10-07)."""
    assert isinstance(window.swipe, SwipeTabs)
    assert window.swipe._tabs == [window.tabs]


def test_a_swipe_over_the_sidebar_on_a_tool_page_moves_the_top_row(window):
    """Not the Tools sub-tabs: those are reached by clicking."""
    window.tabs.setCurrentWidget(window.tools_tabs)
    window.tools_tabs.setCurrentWidget(window.convert_tab)

    assert swipe_across(window.swipe, window.sidebar, -STEP) is True

    assert window.sidebar.title_of(window.tabs.currentWidget()) == "Settings"
    assert window.tools_tabs.currentWidget() is window.convert_tab


def test_a_swipe_back_over_the_sidebar_from_tools_leaves_the_tool_where_it_was(window):
    """Started mid-row on purpose: from the first tool page the old two-row
    wiring fell through to the top row as well, and could not be told apart."""
    window.tabs.setCurrentWidget(window.tools_tabs)
    window.tools_tabs.setCurrentWidget(window.narrator_tab)

    assert swipe_across(window.swipe, window.sidebar, STEP) is True

    assert window.sidebar.title_of(window.tabs.currentWidget()) == "Backup and Sync"
    assert window.tools_tabs.currentWidget() is window.narrator_tab


def test_a_swipe_moves_the_real_window_tabs(window):
    window.tabs.setCurrentIndex(0)
    assert swipe_across(window.swipe, window.sidebar, -STEP) is True
    assert window.sidebar.title_of(window.tabs.currentWidget()) == "Websites"


def test_the_filter_dies_with_the_window(window):
    """An app-level filter that outlives its window decides later windows' swipes."""
    assert window.swipe.parent() is window


def test_a_dialog_over_the_tabs_does_not_swipe_them(tabs):
    """Regression (2026-11-16): scrolling inside Resolve repos moved the page
    behind it from Apps to Websites. A dialog is its own window; its parent
    page must not claim its gestures."""
    from PySide6.QtWidgets import QDialog, QVBoxLayout

    w, swipe, page = tabs
    dialog = QDialog(page)
    inner = QLabel("progress", dialog)
    QVBoxLayout(dialog).addWidget(inner)
    assert swipe._candidates(inner) == []
    assert swipe_across(swipe, inner, -STEP) is False
    assert w.currentIndex() == 0
    dialog.deleteLater()


# ---------------------------------------------------------------------------
# Where the filter goes (regression: an app-wide filter crashed QtWebEngine)
# ---------------------------------------------------------------------------


class QWebEngineView(QWidget):
    """Stands in for the real view: matched by class name, as `inherits` does."""


def _filtered(widget, swipe):
    """Whether the filter really sits on `widget`: a wheel sent to it reaches `swipe`."""
    seen = []
    original = swipe.eventFilter

    def spy(obj, event):
        if obj is widget and event.type() == event.Type.Wheel:
            seen.append(obj)
        return False

    swipe.eventFilter = spy
    try:
        QApplication.sendEvent(widget, wheel(widget, 0, 0, Qt.ScrollBegin))
    finally:
        swipe.eventFilter = original
    return bool(seen)


def test_install_filters_every_widget_of_the_window_but_not_the_application(qapp, monkeypatch):
    calls = []
    monkeypatch.setattr(type(qapp), "installEventFilter", lambda self, f: calls.append(f), raising=False)
    w = QTabWidget()
    page = QWidget()
    child = QLabel("x", page)
    w.addTab(page, "One")
    swipe = SwipeTabs(w, parent=w)
    swipe.install()
    assert calls == [], "never on the QApplication"
    for widget in (w, page, child, w.tabBar()):
        assert _filtered(widget, swipe)
    swipe.remove()
    assert not _filtered(child, swipe)
    w.deleteLater()


def test_widgets_added_later_are_filtered_on_the_next_loop_turn(qapp):
    w = QTabWidget()
    w.addTab(QLabel("One"), "One")
    swipe = SwipeTabs(w, parent=w)
    swipe.install()
    late = QWidget()
    inner = QLabel("deep", late)
    w.addTab(late, "Late")
    QApplication.processEvents()
    assert _filtered(late, swipe) and _filtered(inner, swipe)
    w.deleteLater()


def test_a_web_view_and_everything_inside_it_is_never_filtered(qapp):
    w = QTabWidget()
    view = QWebEngineView()
    inside = QWidget(view)
    w.addTab(view, "Web")
    swipe = SwipeTabs(w, parent=w)
    swipe.install()
    later = QWebEngineView()
    QWidget(later)
    w.addTab(later, "Later web")
    QApplication.processEvents()
    assert _filtered(w, swipe)
    assert not _filtered(view, swipe) and not _filtered(inside, swipe)
    assert not _filtered(later, swipe)
    w.deleteLater()


def test_a_filtered_widget_still_swipes_after_install(qapp):
    w = QTabWidget()
    for name in ("One", "Two"):
        w.addTab(QLabel(name), name)
    w.resize(400, 300)
    swipe = SwipeTabs(w, parent=w)
    swipe.install()
    page = w.widget(0)
    QApplication.sendEvent(page, wheel(page, 0, 0, Qt.ScrollBegin))
    QApplication.sendEvent(page, wheel(page, 0, -STEP))
    assert w.currentIndex() == 1
    w.deleteLater()


def test_remove_also_cancels_a_rescan_already_queued(qapp):
    w = QTabWidget()
    w.addTab(QLabel("One"), "One")
    swipe = SwipeTabs(w, parent=w)
    swipe.install()
    late = QLabel("late")
    w.addTab(late, "Late")  # queues a rescan
    swipe.remove()
    QApplication.processEvents()
    assert not _filtered(late, swipe)
    w.deleteLater()


def test_a_mark_left_by_a_dead_filter_does_not_block_a_new_one(qapp):
    w = QTabWidget()
    page = QLabel("page")
    w.addTab(page, "One")
    first = SwipeTabs(w)
    first.install(w)
    first.deleteLater()
    QApplication.processEvents()
    second = SwipeTabs(w, parent=w)
    second.install()
    assert _filtered(page, second)
    w.deleteLater()


# ---------------------------------------------------------------------------
# Vertical scrolling changes section only over the sidebar (spec scroll-sidebar-only)
# ---------------------------------------------------------------------------


def _vertical(swipe, widget, dy):
    send(swipe, widget, wheel(widget, 0, 0, Qt.ScrollBegin))
    return send(swipe, widget, wheel(widget, 0, dy))


def test_a_vertical_scroll_over_the_sidebar_changes_section(window):
    window.tabs.setCurrentIndex(0)
    assert _vertical(window.swipe, window.sidebar, -STEP) is True
    assert window.sidebar.title_of(window.tabs.currentWidget()) == "Websites"


def test_a_vertical_scroll_over_a_page_never_changes_section(window):
    window.tabs.setCurrentIndex(1)
    for target in (window.tabs.currentWidget(), window.apps_tab):
        for dy in (-STEP, STEP):
            assert _vertical(window.swipe, target, dy) is False
            send(window.swipe, target, wheel(target, 0, 0, Qt.ScrollEnd))
    assert window.tabs.currentIndex() == 1


def test_a_vertical_scroll_at_the_end_of_a_scrolling_page_does_not_move_on(window):
    area = QScrollArea()
    inner = QLabel("x")
    inner.setFixedHeight(4000)
    area.setWidget(inner)
    area.resize(200, 100)
    window.tabs.addWidget(area)
    window.tabs.setCurrentWidget(area)
    area.show()
    QApplication.processEvents()
    area.verticalScrollBar().setValue(area.verticalScrollBar().maximum())
    before = window.tabs.currentIndex()
    assert _vertical(window.swipe, area.viewport(), -STEP) is False
    assert window.tabs.currentIndex() == before


def test_a_three_finger_vertical_swipe_over_a_page_does_not_change_section(window):
    window.tabs.setCurrentIndex(1)
    assert send(window.swipe, window.apps_tab, native_swipe(window.apps_tab, 90.0)) is False
    assert window.tabs.currentIndex() == 1
    assert send(window.swipe, window.sidebar, native_swipe(window.sidebar, 90.0)) is True
    assert window.tabs.currentIndex() == 2


def test_a_sideways_swipe_changes_no_section_anywhere(window):
    """Removed 2026-11-24 (spec no-sideways-swipe): page, sidebar or tab strip."""
    window.tabs.setCurrentIndex(1)
    for target in (window.apps_tab, window.sidebar, window.tabs.currentWidget()):
        for dx in (-STEP, STEP):
            assert sideways_across(window.swipe, target, dx) is False
        for angle in (180.0, 0.0):
            assert send(window.swipe, target, native_swipe(target, angle)) is False
    assert window.tabs.currentIndex() == 1


def test_a_vertical_scroll_over_a_child_of_the_sidebar_changes_section(window):
    """The pointer is usually on a nav button or the footer, not the bare sidebar."""
    button = window.sidebar.button_for(window.tabs.widget(0))
    assert button is not None and button is not window.sidebar
    assert window.sidebar.isAncestorOf(button)
    for child in (button, window.refresh_button):
        assert window.sidebar.isAncestorOf(child)
        window.tabs.setCurrentIndex(0)
        assert _vertical(window.swipe, child, -STEP) is True
        assert window.tabs.currentIndex() == 1
        send(window.swipe, child, wheel(child, 0, 0, Qt.ScrollEnd))


def test_a_three_finger_vertical_swipe_over_a_child_of_the_sidebar_changes_section(window):
    button = window.sidebar.button_for(window.tabs.widget(0))
    for child in (button, window.refresh_button):
        window.tabs.setCurrentIndex(1)
        assert send(window.swipe, child, native_swipe(child, 90.0)) is True
        assert window.tabs.currentIndex() == 2


def test_a_destroyed_vertical_zone_counts_as_outside_it(window):
    import shiboken6

    window.tabs.setCurrentIndex(1)
    zone = window.swipe._vertical_zone
    assert zone is window.sidebar
    shiboken6.delete(zone)
    assert not shiboken6.isValid(zone)
    assert window.swipe._in_vertical_zone(window.apps_tab) is False
    assert _vertical(window.swipe, window.apps_tab, -STEP) is False
    assert window.tabs.currentIndex() == 1
