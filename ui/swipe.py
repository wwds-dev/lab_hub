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

import shiboken6
from PySide6.QtCore import QEvent, QObject, QPointF, Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QStackedWidget,
    QTabWidget,
    QWidget,
)

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

# Marks a widget that already has a filter, so a rescan does not walk it twice. Per instance
# (see `_mark`): a mark left by a filter that has since died must not stop another one.
_MARK = "labHubSwipe"

# Never filtered, nor anything inside: a web view's internals are QtWebEngine's, and handing
# them to Python while they are being built is what crashed the app. A swipe over a web page
# scrolls the page instead of changing tab.
_SKIP = ("QWebEngineView",)

# macOS reports a swipe's direction as an angle: 0° right, 90° up, 180° left.
SWIPE_ANGLE_LEFT = 180.0
SWIPE_ANGLE_UP = 90.0
SWIPE_ANGLE_DOWN = 270.0


def _can_scroll_vertically(widget: QWidget) -> bool:
    """Whether this widget is a scroll area with somewhere up or down to go."""
    if not isinstance(widget, QAbstractScrollArea):
        return False
    if widget.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff:
        return False
    bar = widget.verticalScrollBar()
    return bar is not None and bar.maximum() > bar.minimum()


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

    Works on anything with the tab widget's index API — a ``QTabWidget``, or the
    ``QStackedWidget`` pages the window's sidebar drives.

    A wheel event is delivered to the deepest widget under the pointer and only
    reaches an ancestor if that widget ignores it, which the widgets inside a tab
    are under no obligation to do. So the filter goes on *every* widget of the
    window, not only on the tab widgets, and lets this decide first.

    Never on the ``QApplication``: an application-wide Python filter receives
    every event to every object, and PySide wraps each receiver, QtWebEngine's
    half-built internals included. That segfaulted the app as soon as a
    dashboard opened (`ui/application.py`). Widgets created later are picked up
    from their parent's ChildAdded/ChildPolished, on the next turn of the event
    loop, once they are fully built.
    """

    def __init__(self, *tab_widgets: QTabWidget | QStackedWidget, parent: QObject | None = None):
        # Parented so the filter dies with the window that owns it. Qt removes
        # an event filter when the filter object is destroyed, and leaving that
        # to the garbage collector means a closed window's filter can still be
        # deciding what a later window's swipes do.
        super().__init__(parent)
        # Innermost first, when more than one is registered: a swipe inside the
        # inner tabs moves them, and falls through to the outer ones only when
        # they run out. The window registers only its top row.
        self._tabs = list(tab_widgets)
        self._accumulated = 0.0
        self._armed = True
        self._last_event_at = 0.0
        self._root: QWidget | None = None
        self._pending: list[QWidget] | None = None  # set by install()
        self._mark = f"{_MARK}{id(self)}"

    def install(self, root: QWidget | None = None) -> None:
        """Filter `root` (default: the window that owns this) and every widget inside it."""
        self._root = root if root is not None else self._default_root()
        self._pending = []
        self._scan(self._root)

    def remove(self) -> None:
        root = getattr(self, "_root", None)
        if root is None or not shiboken6.isValid(root):
            return
        self._pending = None  # a rescan already queued must not put the filter back
        for widget in [root, *root.findChildren(QWidget)]:
            if widget.property(self._mark):
                widget.removeEventFilter(self)
                widget.setProperty(self._mark, None)

    def _default_root(self) -> QWidget:
        owner = self.parent()
        if isinstance(owner, QWidget):
            return owner.window()
        return self._tabs[0].window()

    def _scan(self, widget: QWidget) -> None:
        """Install on `widget` and its descendants, stopping at web views."""
        # A child that already has the filter is not walked again: it rescans its own
        # children when they arrive, so a rescan costs one level, not the whole window.
        stack = [(widget, True)]
        while stack:
            w, top = stack.pop()
            if not shiboken6.isValid(w) or any(w.inherits(name) for name in _SKIP):
                continue
            if w.property(self._mark):
                if not top:
                    continue
            else:
                w.installEventFilter(self)
                w.setProperty(self._mark, True)
            stack.extend((c, False) for c in w.children() if isinstance(c, QWidget))

    def _later(self, widget: QWidget) -> None:
        """Rescan `widget` on the next loop turn: its new child may still be under construction."""
        pending = getattr(self, "_pending", None)
        if pending is None:
            return  # filter used directly (tests), never installed
        if not pending:
            QTimer.singleShot(0, self._flush)
        if widget not in pending:
            pending.append(widget)

    def _flush(self) -> None:
        if self._pending is None:
            return  # removed meanwhile
        pending, self._pending = self._pending, []
        for widget in pending:
            self._scan(widget)

    # -- the filter ---------------------------------------------------------

    def eventFilter(self, obj, event):  # noqa: N802 (Qt's name)
        kind = event.type()
        if kind in (QEvent.ChildAdded, QEvent.ChildPolished):
            # Never event.child(): on ChildAdded it can be an object still being constructed.
            self._later(obj)
            return False
        if kind == QEvent.Wheel:
            return self._on_wheel(obj, event)
        if kind == QEvent.NativeGesture:
            return self._on_native_gesture(obj, event)
        return False

    def _on_native_gesture(self, obj, event) -> bool:
        if event.gestureType() != Qt.SwipeNativeGesture:
            return False
        if not isinstance(obj, QWidget):
            return False
        # The angle is the whole gesture, already recognised by macOS, so there
        # is no threshold to reach and nothing to accumulate.
        angle = event.value() % 360.0
        if abs(angle - SWIPE_ANGLE_UP) < 45.0 or abs(angle - SWIPE_ANGLE_DOWN) < 45.0:
            # Vertical: the pages are listed down the sidebar, so a swipe up
            # (the content moving up) goes to the next one, as scrolling does.
            return self._change_tab(
                self._candidates(obj, vertical=True),
                forward=abs(angle - SWIPE_ANGLE_UP) < 45.0,
            )
        forward = abs(angle - SWIPE_ANGLE_LEFT) < 90.0
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
        vertical = abs(delta.y()) > abs(delta.x()) * HORIZONTAL_DOMINANCE
        if not vertical and abs(delta.x()) <= abs(delta.y()) * HORIZONTAL_DOMINANCE:
            return False
        # Decided before anything is accumulated: a swipe that belongs to a
        # sideways-scrolling table (or, vertically, to a page that scrolls)
        # must leave no trace here, or the next swipe over the tabs would start
        # part-way to its threshold.
        candidates = self._candidates(obj, vertical=vertical)
        if not candidates:
            return False

        self._accumulated += delta.y() if vertical else delta.x()
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

    def _candidates(self, under_pointer: QWidget, *, vertical: bool = False):
        """Registered tab widgets above the pointer, innermost first.

        Empty if a scroll area between the pointer and the tabs can scroll the
        way the gesture goes: that widget has the better claim on it. So a
        vertical two-finger swipe changes page only over a page that fits its
        window; on one that scrolls, it scrolls.
        """
        can_scroll = _can_scroll_vertically if vertical else _can_scroll_horizontally
        found = []
        widget = under_pointer
        while widget is not None:
            if can_scroll(widget):
                return []
            if widget in self._tabs:
                found.append(widget)
            # A dialog's parent is the page that opened it, but it is its own
            # window: its scrolling belongs to it, never to the pages behind.
            if widget.isWindow():
                break
            widget = widget.parentWidget()
        return found
