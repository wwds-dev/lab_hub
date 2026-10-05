"""Changing tab with a trackpad swipe.

macOS has two different horizontal swipes and the app sees them as two
different Qt events, so both are handled here:

* **Two fingers** — System Settings ▸ Trackpad ▸ "Swipe between pages" set to
  *Scroll left and right with two fingers* (the default). macOS sends this as an
  ordinary horizontal scroll, which arrives as ``QEvent.Wheel``.
* **Three fingers** — the same setting on *Swipe with three fingers*. macOS
  sends ``NSEventTypeSwipe``, which Qt delivers as ``QEvent.NativeGesture``
  with ``Qt.SwipeNativeGesture``.

Which one actually reaches the app is the user's setting, not ours. Note that a
three-finger horizontal swipe is *also* what "Swipe between full-screen apps"
uses (``TrackpadThreeFingerHorizSwipeGesture = 2``, the macOS default); while
that is selected the window server consumes the gesture and no application ever
sees it. There is nothing to fix in code when that happens — it is the setting.

Two things this deliberately does not do. It never wraps around from the last
tab to the first: the macOS page-swipe does not, and a navigation gesture that
loops makes it impossible to tell the ends from the middle. And it will not
take a swipe away from something that can genuinely use it — a wide table can
scroll sideways, and stealing the gesture from the row of columns the user is
trying to reach would be worse than having no gesture at all.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QEvent, QObject, QPointF, Qt
from PySide6.QtWidgets import QAbstractScrollArea, QApplication, QTabWidget, QWidget

# How far the fingers must travel before the tab changes. Trackpad scrolls
# arrive as a stream of small deltas, so this is the accumulated total over one
# gesture, not a single event's delta.
SWIPE_THRESHOLD = 120.0

# A swipe has to be clearly sideways. Without this a vertical scroll with any
# wobble in it changes tab, which reads as the app losing your place.
HORIZONTAL_DOMINANCE = 1.5

# A mouse wheel and some trackpad drivers send no scroll phases at all, so
# there is no "gesture ended" to reset on. Treat a pause as the end instead.
IDLE_RESET_S = 0.4

# macOS reports a swipe's direction as an angle: 0° right, 90° up, 180° left.
SWIPE_ANGLE_LEFT = 180.0


def _can_scroll_horizontally(widget: QWidget) -> bool:
    """Whether this widget is a scroll area with somewhere left or right to go.

    A scroll area that *has* a horizontal scrollbar but no range (the content
    fits) is not using the gesture for anything, so the tabs may have it.
    """
    if not isinstance(widget, QAbstractScrollArea):
        return False
    if widget.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff:
        return False
    bar = widget.horizontalScrollBar()
    return bar is not None and bar.maximum() > bar.minimum()


class SwipeTabs(QObject):
    """Turns horizontal trackpad swipes into tab changes.

    Installed on the ``QApplication`` rather than on the tab widgets. A wheel
    event is delivered to the deepest widget under the pointer and only reaches
    an ancestor if that widget ignores it, which the widgets inside a tab are
    under no obligation to do — filtering at the application lets this decide
    first, and consume the event so nothing sees it twice.
    """

    def __init__(self, *tab_widgets: QTabWidget, parent: QObject | None = None):
        # Parented so the filter dies with the window that owns it. Qt removes
        # an event filter when the filter object is destroyed, and leaving that
        # to the garbage collector means a closed window's filter can still be
        # deciding what a later window's swipes do.
        super().__init__(parent)
        # Innermost first: a swipe inside Tools should move the tools, and only
        # fall through to the window's own tabs when the tools run out.
        self._tabs = list(tab_widgets)
        self._accumulated = 0.0
        self._armed = True
        self._last_event_at = 0.0

    def install(self, app: QApplication | None = None) -> None:
        (app or QApplication.instance()).installEventFilter(self)

    def remove(self, app: QApplication | None = None) -> None:
        (app or QApplication.instance()).removeEventFilter(self)

    # -- the filter ---------------------------------------------------------

    def eventFilter(self, obj, event):  # noqa: N802 (Qt's name)
        if event.type() == QEvent.Wheel:
            return self._on_wheel(obj, event)
        if event.type() == QEvent.NativeGesture:
            return self._on_native_gesture(obj, event)
        return False

    def _on_native_gesture(self, obj, event) -> bool:
        if event.gestureType() != Qt.SwipeNativeGesture:
            return False
        if not isinstance(obj, QWidget):
            return False
        # The angle is the whole gesture, already recognised by macOS, so there
        # is no threshold to reach and nothing to accumulate.
        forward = abs(event.value() - SWIPE_ANGLE_LEFT) < 90.0
        return self._change_tab(self._candidates(obj), forward=forward)

    def _on_wheel(self, obj, event) -> bool:
        if not isinstance(obj, QWidget):
            return False
        phase = event.phase()
        # Momentum is the flick coasting to a stop after the fingers have left
        # the trackpad. Acting on it turns one swipe into several tabs.
        if phase == Qt.ScrollMomentum:
            return False
        now = time.monotonic()
        if (phase in (Qt.ScrollBegin, Qt.ScrollEnd)
                or now - self._last_event_at > IDLE_RESET_S):
            self._accumulated = 0.0
            self._armed = True
        self._last_event_at = now
        if phase in (Qt.ScrollBegin, Qt.ScrollEnd):
            return False
        if not self._armed:
            # Already changed tab for this gesture; swallow the rest of it so
            # the content underneath does not scroll as well.
            return True

        delta = event.pixelDelta()
        if delta.isNull():
            delta = event.angleDelta()
        if abs(delta.x()) <= abs(delta.y()) * HORIZONTAL_DOMINANCE:
            return False
        # Decided before anything is accumulated: a swipe that belongs to a
        # sideways-scrolling table must leave no trace here, or the next swipe
        # over the tabs would start part-way to its threshold.
        candidates = self._candidates(obj)
        if not candidates:
            return False

        self._accumulated += delta.x()
        if abs(self._accumulated) < SWIPE_THRESHOLD:
            return False

        # A negative x moves the view to the right — the same direction a page
        # swipe goes forward in. Verified against QAbstractScrollArea rather
        # than assumed, since Qt's sign convention is easy to get backwards.
        if not self._change_tab(candidates, forward=self._accumulated < 0):
            return False
        self._armed = False
        self._accumulated = 0.0
        return True

    # -- deciding what moves ------------------------------------------------

    def _change_tab(self, candidates, *, forward: bool) -> bool:
        """Move the innermost tabs that still have somewhere to go.

        Falling outward matters: every tool lives inside the Tools tab, so
        without it a swipe could get into Tools and never back out again.
        """
        for tabs in candidates:
            target = tabs.currentIndex() + (1 if forward else -1)
            if 0 <= target < tabs.count():
                tabs.setCurrentIndex(target)
                return True
        # Nothing could move: at the end of the outermost tabs. Let the event
        # through rather than silently eating it.
        return False

    def _candidates(self, under_pointer: QWidget):
        """Registered tab widgets above the pointer, innermost first.

        Empty if a scroll area between the pointer and the tabs can scroll
        sideways: that widget has the better claim on the gesture.
        """
        found = []
        widget = under_pointer
        while widget is not None:
            if _can_scroll_horizontally(widget):
                return []
            if widget in self._tabs:
                found.append(widget)
            widget = widget.parentWidget()
        return found
