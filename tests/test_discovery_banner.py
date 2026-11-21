"""The banner that asks about a new project (spec apps-discovery §4.2, §12.1), and
the two small widgets it and the Settings list share.

The page that owns it (scan, the three handlers, focus after a click) is
`tests/test_apps_discovery_ui.py`.
"""

from __future__ import annotations

import gc

import pytest
import shiboken6
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from lab_hub import discovery

from ui import discovery_banner, theme
from ui.widgets import ElidedLabel, discard_widget, plain_tip


def suggestion(folder="kaila", name="Kaila", summary="Personal AI assistant.", entry=None):
    return discovery.Suggestion(folder, name, summary, entry)


_BANNERS: list = []


def make_banner() -> discovery_banner.SuggestionBanner:
    """A banner deleted for real at the end of the test. Its buttons are
    connected to closures over the banner, so left to the garbage collector it
    outlives the QApplication and Shiboken complains at interpreter exit."""
    banner = discovery_banner.SuggestionBanner()
    _BANNERS.append(banner)
    return banner


@pytest.fixture(autouse=True)
def _drop_banners():
    yield
    while _BANNERS:
        shiboken6.delete(_BANNERS.pop())


# --- the banner ---------------------------------------------------------------
def test_the_banner_words_tooltips_and_accessible_names(qapp):
    banner = make_banner()
    banner.set_suggestions((suggestion(),))
    row = banner.rows[0]

    assert discovery_banner.LEAD_IN == "New project in your lab folder:"
    assert [b.text() for b in (row.add_button, row.not_now_button, row.never_button)] == [
        "Add to Apps", "Not now", "Never for this folder"]
    assert row.add_button.toolTip() == (
        "Give it a tile here. Nothing is started or changed in the project.")
    assert row.not_now_button.toolTip() == "Ask again in 14 days."
    assert row.never_button.toolTip() == (
        "Do not ask about this folder again. You can undo this in Settings.")
    assert row.add_button.accessibleName() == "Add to Apps, Kaila"
    assert row.not_now_button.accessibleName() == "Not now, Kaila"
    assert row.never_button.accessibleName() == "Never for this folder, Kaila"
    for button in (row.add_button, row.not_now_button, row.never_button):
        assert button.accessibleDescription() == button.toolTip()
        assert not button.autoDefault() and not button.isDefault()
    assert row.accessibleName() == "New project: Kaila"
    assert row.add_button.objectName() == "primary"
    assert row.name.fullText() == "Kaila"
    assert row.sentence.text() == "Personal AI assistant."


def test_banner_text_from_a_readme_is_plain_text(qapp):
    banner = make_banner()
    banner.set_suggestions((suggestion(name="<b>Kaila</b>", summary="<i>hi</i> & <a href='x'>y</a>"),))
    row = banner.rows[0]

    assert row.name.textFormat() == Qt.TextFormat.PlainText
    assert row.sentence.textFormat() == Qt.TextFormat.PlainText
    assert row.name.fullText() == "<b>Kaila</b>"
    assert row.sentence.text() == "<i>hi</i> & <a href='x'>y</a>"
    banner.show_error("kaila", "<b>bad</b>")
    assert row.error.textFormat() == Qt.TextFormat.PlainText


def test_the_folder_is_shown_next_to_a_title_that_differs_from_it(qapp):
    banner = make_banner()
    banner.set_suggestions((suggestion("shopfront", "Shopfront HQ"),))
    row = banner.rows[0]

    assert row.name.fullText() == "Shopfront HQ"
    assert row.folder.text() == "(shopfront)"
    assert row.folder.textFormat() == Qt.TextFormat.PlainText
    assert row.accessibleName() == "New project: Shopfront HQ (shopfront)"
    assert discovery_banner.LEAD_IN == "New project in your lab folder:"
    assert row.add_button.accessibleName() == "Add to Apps, Shopfront HQ"


@pytest.mark.parametrize("name", ["Kaila", "kaila", "KAILA"])
def test_the_folder_is_left_out_when_it_is_the_title_ignoring_case(qapp, name):
    banner = make_banner()
    banner.set_suggestions((suggestion("kaila", name),))
    row = banner.rows[0]

    assert row.folder is None
    assert row.accessibleName() == f"New project: {name}"


def test_a_title_posing_as_another_app_still_shows_its_real_folder(qapp):
    banner = make_banner()
    banner.set_suggestions((suggestion("evil-thing", "Sentinel"),))

    assert banner.rows[0].folder.text() == "(evil-thing)"


def test_a_project_with_no_readme_has_no_second_line(qapp):
    banner = make_banner()
    banner.set_suggestions((suggestion(summary=discovery.FALLBACK_SUMMARY),))

    assert banner.rows[0].sentence is None


def test_the_banner_is_absent_when_empty_and_shows_three_rows_then_and_n_more(qapp):
    banner = make_banner()
    assert banner.isHidden()  # no card, no placeholder, no gap

    items = tuple(suggestion(f"p{i}", f"Project {i}") for i in range(5))
    banner.set_suggestions(items)
    assert not banner.isHidden()
    assert [r.suggestion.folder for r in banner.rows] == ["p0", "p1", "p2"]
    def more():
        return [l.text() for l in banner.findChildren(QLabel)
                if l.text().startswith("and ") and not l.isHidden()]

    assert more() == ["and 2 more"]

    banner.set_suggestions(items[:3])
    assert more() == []

    banner.set_suggestions(())
    assert banner.isHidden()
    assert banner.rows == []


def test_the_banner_rebuilds_only_when_the_set_changes(qapp):
    banner = make_banner()
    items = (suggestion("a", "A"), suggestion("b", "B"))
    assert banner.set_suggestions(items) is True
    first = banner.rows[0]

    assert banner.set_suggestions(tuple(items)) is False
    assert banner.rows[0] is first  # the button under the keyboard is not replaced

    assert banner.set_suggestions(items[1:]) is True
    assert [r.suggestion.folder for r in banner.rows] == ["b"]


def test_each_button_says_which_project_and_how(qapp):
    banner = make_banner()
    got = []
    banner.add_requested.connect(lambda s: got.append(("add", s.folder)))
    banner.not_now_requested.connect(lambda s: got.append(("not_now", s.folder)))
    banner.never_requested.connect(lambda s: got.append(("never", s.folder)))
    banner.set_suggestions((suggestion("a", "A"), suggestion("b", "B")))

    banner.rows[1].add_button.click()
    banner.rows[0].not_now_button.click()
    banner.rows[1].never_button.click()

    assert got == [("add", "b"), ("not_now", "a"), ("never", "b")]


def test_the_tab_order_is_add_not_now_never_row_by_row(qapp):
    banner = make_banner()
    banner.set_suggestions((suggestion("a", "A"), suggestion("b", "B")))
    chain = []
    start = banner.rows[0].add_button
    widget = start
    for _ in range(40):
        if isinstance(widget, QPushButton):
            chain.append(widget)
        widget = widget.nextInFocusChain()
        if widget is start:
            break
    wanted = [b for r in banner.rows for b in (r.add_button, r.not_now_button, r.never_button)]

    assert [b for b in chain if b in wanted] == wanted


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_three_long_rows_never_make_the_banner_wider_than_the_column(qapp, pristine_theme, mode):
    theme.apply(qapp, mode=mode)
    banner = make_banner()
    banner.set_suggestions(tuple(
        suggestion(f"p{i}" + "f" * 60, "N" * 60, "word " * 44) for i in range(5)))
    banner.show_error("p0" + "f" * 60, "Could not add " + "x" * 80 + ": " + "reason " * 20 + ".")

    assert banner.minimumSizeHint().width() <= 500
    banner.close()


def test_the_error_line_stays_with_its_row_and_focus_returns_to_add(qapp):
    banner = make_banner()
    banner.set_suggestions((suggestion("a", "A"), suggestion("b", "B")))

    banner.show_error("b", "Could not add B: disk full.")

    row = banner.rows[1]
    assert row.error.text() == "Could not add B: disk full."
    assert row.error.isVisibleTo(row) and row.error.objectName() == "stateBad"
    assert not banner.rows[0].error.isVisibleTo(banner.rows[0])
    assert banner.focusWidget() is row.add_button




def test_emptying_the_banner_and_dropping_it_does_not_crash(qapp):
    """Regression: a row taken out with `removeWidget` and deleted later was
    deleted a second time when the banner went (a segfault in the suite)."""
    banner = discovery_banner.SuggestionBanner()
    banner.set_suggestions((suggestion("a", "A"), suggestion("b", "B")))
    banner.set_suggestions(())
    del banner  # the last reference, while the discarded rows still wait to be deleted

    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gc.collect()


def test_a_row_can_be_replaced_from_inside_its_own_button_click(qapp):
    banner = make_banner()
    banner.set_suggestions((suggestion("a", "A"), suggestion("b", "B")))
    seen = []
    banner.add_requested.connect(
        lambda s: (banner.set_suggestions(()), seen.append(s.folder)))

    banner.rows[0].add_button.click()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    assert seen == ["a"] and banner.rows == []


# --- ElidedLabel and the helpers (ui/widgets.py) ---------------------------------
def test_an_elided_label_reads_as_typed_until_it_has_a_size(qapp):
    label = ElidedLabel("N" * 80)

    assert label.text() == "N" * 80 and label.toolTip() == ""
    assert label.textFormat() == Qt.TextFormat.PlainText


def test_an_elided_label_cuts_to_its_width_and_keeps_all_of_it_in_the_tooltip(qapp):
    host = QWidget()
    layout = QVBoxLayout(host)
    label = ElidedLabel("N" * 80)
    layout.addWidget(label)
    host.resize(200, 60)
    host.show()
    qapp.processEvents()

    assert label.text().endswith("…") and len(label.text()) < 80
    assert label.fontMetrics().horizontalAdvance(label.text()) <= label.width()
    assert "N" * 80 in label.toolTip()
    assert label.minimumSizeHint().width() == 0  # it never widens its row

    host.resize(900, 60)
    qapp.processEvents()
    assert label.text() == "N" * 80 and label.toolTip() == ""
    host.close()


def test_an_elided_label_can_cut_in_the_middle_and_carry_a_note(qapp):
    host = QWidget()
    layout = QVBoxLayout(host)
    label = ElidedLabel("a" * 40 + "z" * 40, Qt.TextElideMode.ElideMiddle)
    label.setNote("A note.")
    layout.addWidget(label)
    host.resize(200, 60)
    host.show()
    qapp.processEvents()

    assert "…" in label.text() and not label.text().endswith("…")
    assert label.text().startswith("a") and label.text().endswith("z")
    assert "A note." in label.toolTip()
    host.close()


def test_a_tooltip_from_plain_tip_shows_markup_as_typed(qapp):
    tip = plain_tip("<b>x</b> & y\nz")

    assert tip == "<qt>&lt;b&gt;x&lt;/b&gt; &amp; y<br>z</qt>"


def test_discard_widget_takes_it_out_of_the_layout(qapp):
    host = QWidget()
    layout = QVBoxLayout(host)
    child = QLabel("x")
    layout.addWidget(child)

    discard_widget(layout, child)

    assert layout.count() == 0 and child.isHidden()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_a_discarded_row_stays_alive_until_qt_has_deleted_it(qapp):
    """The row may be the one whose button is mid-click: dropping the last
    Python reference there would delete the button under its own signal. (With
    this PySide, `deleteLater` alone also keeps the wrapper until the object is
    destroyed, so removing `_DISCARDED` cannot fail this: it pins the behaviour,
    not the mechanism.)"""
    import gc
    import weakref

    host = QWidget()
    layout = QVBoxLayout(host)
    row = QWidget()
    QVBoxLayout(row).addWidget(QLabel("x"))
    layout.addWidget(row)
    alive = weakref.ref(row)

    discard_widget(layout, row)
    del row
    gc.collect()

    assert alive() is not None, "nothing but the keep-alive holds it now"
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gc.collect()
    assert alive() is None, "and it is let go once Qt has really deleted it"
