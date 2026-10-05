"""Changing tab with a trackpad swipe.

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


def send(swipe, widget, event):
    """What QApplication's filter would do, without the real event loop."""
    return swipe.eventFilter(widget, event)


def swipe_across(swipe, widget, dx, *, phases=True):
    """One whole gesture: begin, a move past the threshold, end."""
    if phases:
        send(swipe, widget, wheel(widget, 0, 0, Qt.ScrollBegin))
    consumed = send(swipe, widget, wheel(widget, dx))
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


def test_swiping_left_goes_to_the_next_tab(tabs):
    w, swipe, page = tabs
    assert swipe_across(swipe, page, -STEP) is True
    assert w.currentIndex() == 1


def test_swiping_right_goes_back(tabs):
    w, swipe, page = tabs
    w.setCurrentIndex(2)
    assert swipe_across(swipe, w.widget(2), STEP) is True
    assert w.currentIndex() == 1


def test_one_gesture_changes_one_tab(tabs):
    """A real swipe is a stream of deltas. Each must not be its own tab."""
    w, swipe, page = tabs
    send(swipe, page, wheel(page, 0, 0, Qt.ScrollBegin))
    for _ in range(10):
        send(swipe, page, wheel(page, -STEP))
    send(swipe, page, wheel(page, 0, 0, Qt.ScrollEnd))
    assert w.currentIndex() == 1


def test_momentum_after_the_fingers_lift_is_ignored(tabs):
    """Inertia keeps delivering deltas; acting on them flips several tabs."""
    w, swipe, page = tabs
    swipe_across(swipe, page, -STEP)
    assert w.currentIndex() == 1
    for _ in range(5):
        send(swipe, page, wheel(page, -STEP, phase=Qt.ScrollMomentum))
    assert w.currentIndex() == 1


def test_a_short_nudge_does_not_change_tab(tabs):
    w, swipe, page = tabs
    send(swipe, page, wheel(page, 0, 0, Qt.ScrollBegin))
    assert send(swipe, page, wheel(page, -int(SWIPE_THRESHOLD / 4))) is False
    assert w.currentIndex() == 0


def test_a_vertical_scroll_never_changes_tab(tabs):
    """A sideways component big enough on its own still loses to a bigger
    vertical one — otherwise any wobble in a scroll changes tab."""
    w, swipe, page = tabs
    send(swipe, page, wheel(page, 0, 0, Qt.ScrollBegin))
    assert send(swipe, page, wheel(page, -STEP, -STEP * 3)) is False
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


def test_a_three_finger_swipe_changes_tab(tabs):
    """macOS sends NSEventTypeSwipe as a single already-recognised gesture."""
    w, swipe, page = tabs
    assert send(swipe, page, native_swipe(page, 180.0)) is True  # left
    assert w.currentIndex() == 1
    assert send(swipe, page, native_swipe(page, 0.0)) is True  # right
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


def _scrolling_page(tabs_widget, width):
    """A tab page holding a scroll area whose content is `width` wide."""
    area = QScrollArea()
    inner = QLabel("x")
    inner.setFixedWidth(width)
    area.setWidget(inner)
    area.resize(200, 100)
    tabs_widget.addTab(area, "Wide")
    tabs_widget.setCurrentWidget(area)
    area.show()
    QApplication.processEvents()
    return area


def test_a_sideways_scrolling_table_keeps_the_gesture(tabs):
    """A wide table has a real use for a horizontal swipe; the tabs do not win."""
    w, swipe, _ = tabs
    area = _scrolling_page(w, 4000)
    assert area.horizontalScrollBar().maximum() > 0, "fixture is not scrollable"
    before = w.currentIndex()
    assert before > 0, "swipe back, so a tab change is available to be refused"
    assert swipe_across(swipe, area.viewport(), STEP) is False
    assert w.currentIndex() == before


def test_content_that_fits_does_not_block_the_gesture(tabs):
    """A scroll area with nowhere to go sideways is not using the swipe."""
    w, swipe, _ = tabs
    area = _scrolling_page(w, 50)
    assert area.horizontalScrollBar().maximum() == 0
    before = w.currentIndex()
    assert swipe_across(swipe, area.viewport(), STEP) is True
    assert w.currentIndex() == before - 1


def test_a_blocked_swipe_leaves_nothing_behind(tabs):
    """The vetoed swipe must not count towards the next one."""
    w, swipe, _ = tabs
    area = _scrolling_page(w, 4000)
    page_index = w.currentIndex()
    for _ in range(5):
        send(swipe, area.viewport(), wheel(area.viewport(), STEP))
    assert w.currentIndex() == page_index
    # Now a small nudge over the tabs themselves, well under the threshold.
    send(swipe, w, wheel(w, 0, 0, Qt.ScrollBegin))
    assert send(swipe, w, wheel(w, STEP // 4)) is False
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


def test_the_window_installs_it_over_both_tab_levels(window):
    assert isinstance(window.swipe, SwipeTabs)
    assert window.swipe._tabs == [window.tools_tabs, window.tabs], (
        "innermost first, or a swipe inside Tools moves the wrong tabs"
    )


def test_a_swipe_moves_the_real_window_tabs(window):
    window.tabs.setCurrentIndex(0)
    assert swipe_across(window.swipe, window.apps_tab, -STEP) is True
    assert window.tabs.tabText(window.tabs.currentIndex()) == "Backup and Sync"


def test_the_filter_dies_with_the_window(window):
    """An app-level filter that outlives its window decides later windows' swipes."""
    assert window.swipe.parent() is window
