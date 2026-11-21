"""The Apps page's side of spec apps-discovery: a tile with no launch command,
Lab Hub's own tile, and the banner that asks about new projects.

The detection and the files are `tests/test_discovery.py`; the worker thread is
`tests/test_own_verdict.py`. What is checked here is what the owner sees and
what a click does, against a real temp lab folder and a real (temp) support
folder.
"""

from __future__ import annotations

import threading
from datetime import date
from pathlib import Path

import pytest
import shiboken6
from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QPushButton, QScrollArea

from lab_hub import config, discovery, hygiene, launcher, progress, self_update, version
from lab_hub.launcher import registry
from lab_hub.launcher.state import BuildStatus, Version

from ui import apps_tab, theme
from ui.apps_tab import (BEHIND_TIP, NO_LAUNCH_HINT, NO_LAUNCH_TIP, OWN_HINT, AppCard, AppsTab,
                         OwnCard, plain_tip)
from ui.own_verdict import OwnResult, OwnVerdict
from ui.progress_window import BuildCheckWindow

from .test_discovery import make_project
from .test_own_verdict import _REAL_REQUEST

REAL_SUGGESTIONS = discovery.suggestions  # taken at import, before the conftest fixture patches it
TODAY = date(2026, 11, 21)

KAILA = launcher.ExternalApp("kaila", "Kaila", "kaila", None, "Personal AI assistant.")


def suggestion(folder="kaila", name="Kaila", summary="Personal AI assistant.", entry=None):
    return discovery.Suggestion(folder, name, summary, entry)


_TABS: list = []


@pytest.fixture(autouse=True)
def _drop_tabs():
    """Pages deleted for real at the end of each test (the `_drop_tabs`
    precedent in tests/test_self_update.py)."""
    yield
    while _TABS:
        tab = _TABS.pop()
        tab._poll.stop()
        tab._own_verdict.shutdown()
        if tab._hygiene_proc is not None:
            tab._hygiene_proc.kill()
            tab._hygiene_proc.waitForFinished(2000)
        # A LayoutRequest queued a singleShot(0, equalise): run it now, while the
        # cards exist, so no later test's event loop meets a deleted tile.
        QCoreApplication.processEvents()
        shiboken6.delete(tab)
        QCoreApplication.processEvents()
    registry.use(None)
    registry.last_error = None


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(discovery, "today", lambda: TODAY)


@pytest.fixture
def real_scan(monkeypatch):
    monkeypatch.setattr(discovery, "suggestions", REAL_SUGGESTIONS)


@pytest.fixture
def lab(tmp_path):
    root = tmp_path / "lab"
    root.mkdir()
    return root


def _tab(lab: Path, apps=None, discover=True, **kwargs) -> AppsTab:
    if apps is None:
        apps = lambda: launcher.SUITES + (self_update.OWN_TILE,)  # noqa: E731
    tab = AppsTab(config.Settings(lab_root=str(lab)), apps=apps, discover=discover, **kwargs)
    _TABS.append(tab)
    return tab


def _visible(widget, parent) -> bool:
    """Visible unless hidden itself, whether or not the page is on screen."""
    return widget.isVisibleTo(parent)


# --- a tile with no launch command -----------------------------------------
def test_a_no_launch_tile_has_no_launch_button_and_no_state_pill(qapp, lab):
    (lab / "kaila").mkdir()
    card = AppCard(KAILA)
    card.refresh(lab, table="")

    assert not _visible(card.launch_button, card)
    assert not _visible(card.state, card)
    assert card.stop_button is None
    assert card.name.fullText() == "Kaila"
    assert card.summary.text() == "Personal AI assistant."


def test_the_no_launch_hint_and_the_name_tooltip_are_the_approved_words(qapp, lab):
    card = AppCard(KAILA)
    card.refresh(lab, table="")

    assert card.service.text() == "No launch button: it has no app to open yet."
    assert NO_LAUNCH_HINT == "No launch button: it has no app to open yet."
    assert NO_LAUNCH_TIP == (
        "Lab Hub shows its version and repo state. Add a launch entry to the "
        "registry when it has an app to open."
    )
    assert NO_LAUNCH_TIP in card.name.toolTip()
    # A tooltip is mouse-only: the same words are the accessible description.
    assert card.name.accessibleDescription() == NO_LAUNCH_TIP


def test_pressing_launch_on_a_no_launch_tile_does_nothing(qapp, lab, monkeypatch):
    card = AppCard(KAILA)
    called = []
    monkeypatch.setattr(launcher, "launch", lambda *a, **k: called.append("launch"))
    monkeypatch.setattr(launcher, "bring_to_front", lambda *a, **k: called.append("raise"))
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: called.append("box"))

    card._launch()
    card.launch_button.click()

    assert called == []
    assert card._pending_since is None


def test_a_no_launch_tile_never_asks_whether_it_is_running(qapp, lab, monkeypatch):
    """No readiness, presence or process table: nothing to start or find."""
    for name in ("readiness", "presence", "process_table"):
        monkeypatch.setattr(
            launcher, name, lambda *a, **k: pytest.fail(f"launcher.{name} was called"))
    card = AppCard(KAILA)

    card.refresh(lab)
    card._update_button(None)  # the one place Launch is worded: a belt

    assert not _visible(card.launch_button, card)


def test_open_in_terminal_is_always_there_on_a_no_launch_tile(qapp, lab, monkeypatch):
    project = lab / "kaila"
    project.mkdir()
    opened = []
    monkeypatch.setattr(launcher, "open_terminal", opened.append)
    card = AppCard(KAILA)

    card.refresh(lab)  # no hygiene report has named the repo

    assert _visible(card.terminal_button, card)
    card.terminal_button.click()
    assert opened == [project]


def test_open_in_terminal_comes_back_after_a_refresh_or_a_landed_outcome(qapp, lab):
    """Refresh (clear_outcome) and a Land that went well both hide the button on
    a launchable tile; here the next poll must put it back."""
    from lab_hub import land

    card = AppCard(KAILA)
    card.refresh(lab)

    card.clear_outcome()
    assert not _visible(card.terminal_button, card)
    card.refresh(lab)
    assert _visible(card.terminal_button, card)

    card.show_outcome(land.LandResult("kaila", "landed", "Landed."))
    card.refresh(lab)
    assert _visible(card.terminal_button, card)

    card.set_landing("Merging…")  # mid-Land the button stays out of the way
    card.refresh(lab)
    assert not _visible(card.terminal_button, card)


def test_open_in_terminal_sits_beside_land_on_a_no_launch_tile(qapp):
    card = AppCard(KAILA)

    assert card.buttons.indexOf(card.land_button) < card.buttons.indexOf(card.terminal_button)
    assert card.extra.indexOf(card.terminal_button) == -1
    # And a launchable tile keeps it under its path, as it was.
    other = AppCard(launcher.ExternalApp("a", "A", "a", "main.py", "s"))
    assert other.buttons.indexOf(other.terminal_button) == -1


def test_a_launchable_tile_is_as_it_was(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "none")
    card = AppCard(launcher.ExternalApp("a", "App", "a", "main.py", "s"))

    card.refresh(tmp_path, table="")

    assert _visible(card.launch_button, card)
    assert not _visible(card.terminal_button, card)  # only after a Land that failed
    assert card.state.text() == "Not found"
    assert card.service.text() == ""


def test_launch_stays_before_land_in_the_button_row(qapp):
    card = AppCard(KAILA)

    assert card.buttons.indexOf(card.launch_button) < card.buttons.indexOf(card.land_button)


def test_a_no_launch_tile_offers_land_like_any_tile(qapp, lab):
    card = AppCard(KAILA)
    row = hygiene.RepoRow("kaila", (lab / "kaila").resolve(), "main",
                          problems=("1 branch not merged into main",))

    card.refresh_hygiene(row)

    assert _visible(card.land_button, card)
    assert card.hygiene.text() == "1 branch to land"


def test_a_no_launch_tile_says_where_the_project_is_or_that_it_is_not(qapp, lab):
    card = AppCard(KAILA)
    card.refresh(lab)
    assert card.detail.text() == f"no folder at {lab / 'kaila'}"

    (lab / "kaila").mkdir()
    card.refresh(lab)
    assert card.detail.text() == str(lab / "kaila")


def test_a_name_and_summary_from_a_readme_are_plain_text(qapp):
    """A README can say anything; the label must not render it as markup."""
    card = AppCard(launcher.ExternalApp(
        "x", "<b>Bold</b>", "x", None, "<i>italic</i> <a href='http://x'>link</a>"))

    assert card.name.textFormat() == Qt.TextFormat.PlainText
    assert card.summary.textFormat() == Qt.TextFormat.PlainText
    assert card.name.fullText() == "<b>Bold</b>"
    launchable = AppCard(launcher.ExternalApp("y", "<b>Y</b>", "y", "main.py", "<i>s</i>"))
    assert launchable.name.textFormat() == Qt.TextFormat.PlainText
    assert launchable.summary.textFormat() == Qt.TextFormat.PlainText


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_a_long_name_and_summary_do_not_widen_a_no_launch_tile(qapp, pristine_theme, mode):
    theme.apply(qapp, mode=mode)
    long = launcher.ExternalApp(
        "x", "A" * 60, "x", None, "word " * 44)  # the longest a README name and summary can be
    for app in (long, self_update.OWN_TILE):
        card = AppCard(app) if app is long else OwnCard(app)
        card.version.setText("v2.208 · 126 behind · and a very long tail of words")
        card.hygiene.setText("2 unpushed commits · 1 commit behind · 2 branches to land")
        card.refresh(Path("/nonexistent"))
        assert card.minimumSizeHint().width() <= apps_tab.TILE_MIN_WIDTH, app.name


def test_a_cut_name_keeps_the_full_name_and_the_words_in_its_tooltip(qapp, lab):
    card = AppCard(launcher.ExternalApp("x", "N" * 60, "x", None, "s"))
    card.resize(380, 200)
    card.show()
    qapp.processEvents()

    assert card.name.text().endswith("…")
    assert "N" * 60 in card.name.toolTip() and NO_LAUNCH_TIP in card.name.toolTip()
    card.close()


# --- Lab Hub's own tile ------------------------------------------------------
def test_lab_hub_tile_is_the_last_one_and_is_an_own_card(window):
    cards = window.apps_tab.cards

    assert cards[-1].app == self_update.OWN_TILE
    assert isinstance(cards[-1], OwnCard)
    assert [c.app.key for c in cards].count("lab_hub") == 1
    assert not any(isinstance(c, OwnCard) for c in cards[:-1])


def test_lab_hub_tile_has_no_launch_stop_or_update_buttons(window):
    card = window.apps_tab.cards[-1]
    labels = {b.text() for b in card.findChildren(QPushButton) if b.isVisibleTo(card)}

    assert not _visible(card.launch_button, card)
    assert card.stop_button is None
    assert labels <= {"Open in Terminal", "Land"}
    assert not any("Update" in label or "Quit" in label or "front" in label
                   for label in labels)


def test_lab_hub_tile_shows_the_running_build_and_the_approved_words(qapp, lab):
    tab = _tab(lab, apps=lambda: (self_update.OWN_TILE,))
    card = tab.cards[0]

    assert card.version.text() == version.version_string()
    assert card.version.toolTip() == plain_tip(version.tooltip())
    assert card.service.text() == "You are using it: it has no Launch button."
    assert OWN_HINT == card.service.text()
    assert card.summary.text() == "This app: the launcher for the lab's projects."
    assert card.name.fullText() == "Lab Hub"
    assert card.name.toolTip() == ""  # the registry advice is not for Lab Hub


def _row(verdict="current", note="", behind=0):
    return BuildStatus(self_update.SELF, Version("v2", "bundle", behind=behind), verdict, note)


def test_the_verdict_line_and_the_behind_suffix(qapp, lab):
    card = OwnCard(self_update.OWN_TILE)
    card.refresh(lab)
    assert card.verdict.text() == ""  # blank until the worker answers

    card.set_verdict(OwnResult(row=_row("current")))
    assert card.verdict.text() == "up to date"
    assert card.version.text() == version.version_string()
    assert card.version.objectName() == "hint"

    card.set_verdict(OwnResult(row=_row("behind", behind=3)))
    assert card.verdict.text() == "3 commits older than its source"
    assert card.version.text() == f"{version.version_string()} · 3 behind"
    assert card.version.objectName() == "stateWarn"
    assert BEHIND_TIP == "A newer build is ready to install: use Check builds."
    assert card.version.toolTip() == plain_tip(version.tooltip() + "\n" + BEHIND_TIP)

    card.set_verdict(OwnResult(row=_row("current", note="runs the checkout directly, so ...")))
    assert card.verdict.text() == "runs the checkout directly"
    assert card.version.objectName() == "hint" and "behind" not in card.version.text()


def test_a_projects_version_text_is_shown_as_typed_never_as_markup(qapp, lab, monkeypatch):
    """A VERSION file is the project's own; `<b>` in it must not render."""
    marked = Version(text="<b>BOLD</b>.007", origin="checkout", detail="from <i>VERSION</i>",
                     commit="abc1234")
    monkeypatch.setattr(launcher, "version", lambda app, root: marked)
    card = AppCard(KAILA)

    card.refresh_version(lab)

    assert card.version.textFormat() == Qt.TextFormat.PlainText
    assert "<b>" in card.version.text(), "the characters are kept, not interpreted"
    tip = card.version.toolTip()
    assert tip.startswith("<qt>") and "&lt;i&gt;VERSION&lt;/i&gt;" in tip and "<i>" not in tip

    monkeypatch.setattr(launcher, "version",
                        lambda app, root: Version(detail="read <b>VERSION</b> failed"))
    card.refresh_version(lab)
    assert "<b>" not in card.version.toolTip() and "&lt;b&gt;" in card.version.toolTip()


def test_a_failed_verdict_leaves_the_line_blank_with_the_reason(qapp, lab):
    card = OwnCard(self_update.OWN_TILE)

    card.set_verdict(OwnResult(error="git is not installed"))

    assert card.verdict.text() == ""
    assert "git is not installed" in card.verdict.toolTip()
    assert card.version.text() == version.version_string()


def test_the_verdict_arrives_through_the_worker(qapp, lab, monkeypatch):
    monkeypatch.setattr(OwnVerdict, "request", _REAL_REQUEST)
    seen = []

    def fake(root, **kwargs):
        seen.append((root, threading.current_thread()))
        return _row("current")

    monkeypatch.setattr(self_update, "self_status", fake)
    tab = _tab(lab, apps=lambda: (self_update.OWN_TILE,))
    tab._own_verdict._thread.join(5)
    tab._own_verdict._drain()

    assert seen[0][0] == lab
    assert seen[0][1] is not threading.main_thread()
    assert tab.cards[0].verdict.text() == "up to date"
    # A rebuilt tile shows the last result at once, not blank until the next run.
    tab._shown = []
    tab._sync_cards()
    assert tab.cards[0].verdict.text() == "up to date"


def test_three_polls_call_self_status_zero_times(qapp, lab, monkeypatch):
    """The verdict costs git: only startup and Refresh ask for it, never the poll."""
    monkeypatch.setattr(OwnVerdict, "request", _REAL_REQUEST)
    calls = []
    monkeypatch.setattr(self_update, "self_status",
                        lambda root, **kw: calls.append(root) or _row())
    tab = _tab(lab, apps=lambda: (self_update.OWN_TILE,))
    tab._own_verdict._thread.join(5)
    tab._own_verdict._drain()
    assert len(calls) == 1  # startup

    for _ in range(3):
        tab.refresh()  # the 3 s poll
    tab.show()  # showEvent refreshes too
    qapp.processEvents()

    assert len(calls) == 1
    assert tab._own_verdict._thread is None

    tab.recheck()  # Refresh asks again
    tab._own_verdict._thread.join(5)
    tab._own_verdict._drain()
    assert len(calls) == 2


def test_a_page_without_lab_hub_never_asks_for_the_verdict(qapp, lab, monkeypatch):
    monkeypatch.setattr(OwnVerdict, "request", lambda self, root: pytest.fail("asked"))

    tab = _tab(lab, apps=lambda: (KAILA,), discover=False)
    tab.recheck()


def test_land_shows_on_lab_hub_tile_when_its_repo_needs_attention(qapp, lab, monkeypatch):
    (lab / "lab_hub").mkdir()
    row = hygiene.RepoRow("lab_hub", (lab / "lab_hub").resolve(), "main",
                          problems=("2 uncommitted files",))
    tab = _tab(lab, apps=lambda: (self_update.OWN_TILE,))
    monkeypatch.setattr(tab, "hygiene_report", lambda: hygiene.Report(rows=(row,)))

    tab._apply_hygiene()

    card = tab.cards[0]
    assert _visible(card.land_button, card)
    assert card.hygiene.text() == "2 files to land"
    planned = []
    # No real Lander thread: only what the page asks it to look at.
    monkeypatch.setattr(tab.lander, "plan", lambda repos: planned.append(list(repos)) or True)

    card.land_button.click()  # asks the page, exactly as any tile does

    assert planned == [[("lab_hub", row.path)]]
    assert tab._landing_cards["lab_hub"] is card
    assert card.land_button.text() == "Landing…" and card.outcome.text() == "Looking at the repo…"


def test_a_clean_lab_hub_repo_offers_no_land(qapp, lab, monkeypatch):
    (lab / "lab_hub").mkdir()
    row = hygiene.RepoRow("lab_hub", (lab / "lab_hub").resolve(), "main")
    tab = _tab(lab, apps=lambda: (self_update.OWN_TILE,))
    monkeypatch.setattr(tab, "hygiene_report", lambda: hygiene.Report(rows=(row,)))

    tab._apply_hygiene()

    assert not _visible(tab.cards[0].land_button, tab.cards[0])


def test_check_builds_has_exactly_one_lab_hub_row_with_the_tile_present(window, monkeypatch):
    """The tile reads the existing row; it must not add a second one. The real
    `build_report` runs, over a registry with one launchable app, so a change
    that made it count Lab Hub too would show two rows here."""
    alpha = launcher.ExternalApp("alpha", "Alpha", "alpha", "main.py", "s")
    registry.use(registry.Registry(suites=(alpha,)))
    own = BuildStatus(self_update.SELF, Version("v2", "bundle"), "current", "matches")
    monkeypatch.setattr(self_update, "self_status", lambda *a, **k: own)
    views = []
    real = progress.build_check_view

    def record(*args, **kwargs):
        view = real(*args, **kwargs)
        views.append(view)
        return view

    monkeypatch.setattr(apps_tab.progress, "build_check_view", record)
    monkeypatch.setattr(BuildCheckWindow, "ask", lambda self: None)
    assert window.apps_tab.cards[-1].app == self_update.OWN_TILE

    window.apps_tab.show_build_report()

    names = [item.name for item in views[0].items]
    assert sum("Lab Hub" in name for name in names) == 1, names
    assert sum("Alpha" in name for name in names) == 1, names
    assert len(names) == 2, names


# --- the page: scan, answers, files -------------------------------------------
def _page_with_projects(lab, monkeypatch, *names):
    """A page over a real lab folder, scanning for real."""
    monkeypatch.setattr(discovery, "suggestions", REAL_SUGGESTIONS)
    for name in names:
        make_project(lab, name, readme=f"# {name.title()}\n\nAbout {name}. More.\n")
    return _tab(lab)


def test_the_page_scans_at_startup_and_on_refresh_but_never_on_the_poll(qapp, lab, monkeypatch):
    scans = []
    monkeypatch.setattr(discovery, "suggestions", lambda *a, **k: scans.append(a) or ())
    tab = _tab(lab)
    assert len(scans) == 1

    for _ in range(3):
        tab.refresh()
    tab.show()
    qapp.processEvents()
    assert len(scans) == 1

    tab.recheck()
    assert len(scans) == 2


@pytest.mark.parametrize("error", [ValueError("embedded null byte"), OSError("gone"), RuntimeError("x")])
def test_a_scan_that_raises_shows_nothing_and_does_not_fail_the_page(qapp, lab, monkeypatch, error):
    def explode(*args, **kwargs):
        raise error

    monkeypatch.setattr(discovery, "suggestions", explode)

    tab = _tab(lab)  # the startup scan
    tab.recheck()  # and Refresh

    assert tab.banner.rows == []
    assert not tab.banner.isVisibleTo(tab)


def test_a_new_lab_folder_in_settings_rescans_and_asks_for_the_verdict_again(
        qapp, lab, tmp_path, monkeypatch):
    other = tmp_path / "other"
    other.mkdir()
    tab = _page_with_projects(lab, monkeypatch, "kaila")
    assert [r.suggestion.folder for r in tab.banner.rows] == ["kaila"]
    asked = []
    monkeypatch.setattr(OwnVerdict, "request", lambda self, root: asked.append(root))

    tab.apply_settings(config.Settings(lab_root=str(other)))

    assert tab.banner.rows == [], "the banner followed the folder"
    assert asked == [config.Settings(lab_root=str(other)).resolved_lab_root()]
    make_project(other, "overseer", readme="# Overseer\n\nAbout it.\n")
    tab.apply_settings(config.Settings(lab_root=str(other)))
    assert [r.suggestion.folder for r in tab.banner.rows] == ["overseer"]


def test_only_the_apps_page_asks(qapp, lab, monkeypatch):
    monkeypatch.setattr(discovery, "suggestions",
                        lambda *a, **k: pytest.fail("a page that did not ask scanned"))

    tab = _tab(lab, apps=lambda: (KAILA,), discover=False)
    tab.recheck()

    assert tab.banner is None and tab.local_note is None


def test_new_projects_become_banner_rows(qapp, lab, monkeypatch):
    tab = _page_with_projects(lab, monkeypatch, "kaila", "overseer")

    assert [r.suggestion.folder for r in tab.banner.rows] == ["kaila", "overseer"]
    assert tab.banner.rows[0].name.fullText() == "Kaila"
    assert tab.banner.rows[0].sentence.text() == "About kaila."


def test_the_banner_is_the_first_thing_in_the_column(qapp, lab, monkeypatch):
    tab = _page_with_projects(lab, monkeypatch, "kaila")
    column = tab.column

    first = [column.itemAt(i).widget() for i in range(column.count()) if column.itemAt(i).widget()]
    assert first[0] is tab.local_note and first[1] is tab.banner
    assert first[2].objectName() == "sectionTitle"


def test_add_writes_the_file_gives_a_tile_and_says_so(qapp, lab, isolated_config, monkeypatch):
    tab = _page_with_projects(lab, monkeypatch, "kaila", "overseer")
    changed, said = [], []
    tab.apps_changed.connect(lambda: changed.append(True))
    tab.launched.connect(said.append)
    area = tab.findChild(QScrollArea)
    scrolled = []
    monkeypatch.setattr(area, "ensureWidgetVisible", lambda w, *a: scrolled.append(w))

    tab.banner.rows[0].add_button.click()
    qapp.processEvents()

    text = (isolated_config / "apps-local.toml").read_text()
    assert 'key = "kaila"' in text and 'name = "Kaila"' in text
    assert "entry" not in text  # no main.py, so a no-launch tile
    assert changed == [True]
    assert said == ["Added Kaila to Apps."]
    assert [r.suggestion.folder for r in tab.banner.rows] == ["overseer"]
    keys = [c.app.key for c in tab.cards]
    assert "kaila" in keys and keys[-1] == "lab_hub"  # a tile, and Lab Hub's still last
    card = next(c for c in tab.cards if c.app.key == "kaila")
    assert not _visible(card.launch_button, card)
    assert scrolled == [card]
    # Focus: the next row's Add to Apps.
    assert tab.focusWidget() is tab.banner.rows[0].add_button


def test_adding_the_last_row_moves_focus_to_the_page(qapp, lab, monkeypatch):
    tab = _page_with_projects(lab, monkeypatch, "kaila")

    tab.banner.rows[0].add_button.click()

    assert tab.banner.rows == []
    assert not tab.banner.isVisibleTo(tab)
    assert tab.focusWidget() is tab.findChild(QScrollArea)


def test_not_now_hides_the_row_for_fourteen_days(qapp, lab, isolated_config, monkeypatch):
    tab = _page_with_projects(lab, monkeypatch, "kaila", "overseer")
    said, changed = [], []
    tab.launched.connect(said.append)
    tab.apps_changed.connect(lambda: changed.append(True))

    tab.banner.rows[0].not_now_button.click()

    assert said == ["Kaila: not asked for 14 days."]
    assert discovery.load_dismissed()["kaila"] == discovery.Dismissal("not_now", TODAY)
    assert [r.suggestion.folder for r in tab.banner.rows] == ["overseer"]
    assert not (isolated_config / "apps-local.toml").exists()
    assert changed == []  # the list did not change
    assert tab.focusWidget() is tab.banner.rows[0].add_button


def test_never_hides_the_row_for_good_and_says_how_to_undo(qapp, lab, monkeypatch):
    tab = _page_with_projects(lab, monkeypatch, "kaila")
    said = []
    tab.launched.connect(said.append)

    tab.banner.rows[0].never_button.click()

    assert said == ["Kaila hidden. You can undo this in Settings."]
    assert discovery.load_dismissed()["kaila"].answer == "never"
    assert tab.banner.rows == []
    tab.recheck()  # and a Refresh does not bring it back
    assert tab.banner.rows == []


def test_a_failed_add_keeps_the_row_and_says_why(qapp, lab, monkeypatch):
    tab = _page_with_projects(lab, monkeypatch, "kaila")
    changed, said = [], []
    tab.apps_changed.connect(lambda: changed.append(True))
    tab.launched.connect(said.append)

    def boom(s):
        raise discovery.DiscoveryError("cannot write /x: disk full")

    monkeypatch.setattr(discovery, "add", boom)
    row = tab.banner.rows[0]
    row.add_button.click()

    assert tab.banner.rows == [row]
    assert row.error.text() == "Could not add Kaila: cannot write /x: disk full."
    assert row.add_button.isEnabled() and row.never_button.isEnabled()
    assert tab.focusWidget() is row.add_button
    assert changed == [] and said == []


def test_a_failed_answer_keeps_the_row_and_says_it_will_be_asked_again(qapp, lab, monkeypatch):
    tab = _page_with_projects(lab, monkeypatch, "kaila")

    def boom(*a, **k):
        raise discovery.DiscoveryError("cannot write /x: read-only")

    monkeypatch.setattr(discovery, "dismiss", boom)
    row = tab.banner.rows[0]
    row.never_button.click()

    assert tab.banner.rows == [row]
    assert row.error.text() == (
        "Could not save your answer for Kaila: cannot write /x: read-only. "
        "It will be asked again.")


def test_two_refreshes_in_a_row_leave_the_same_row(qapp, lab, monkeypatch):
    tab = _page_with_projects(lab, monkeypatch, "kaila")
    row = tab.banner.rows[0]

    tab.recheck()
    tab.recheck()

    assert tab.banner.rows == [row]


def test_a_broken_local_file_is_a_quiet_line_not_an_error_colour(qapp, lab, monkeypatch):
    tab = _tab(lab)
    assert not _visible(tab.local_note, tab)

    monkeypatch.setattr(registry, "local_note", "Your added projects file was ignored: x. "
                                               "The list is as it was.")
    tab.recheck()

    note = tab.local_note
    assert _visible(note, tab)
    assert note.text().startswith("Your added projects file was ignored")
    assert note.textFormat() == Qt.TextFormat.PlainText
    assert note.objectName() == "hint"
    assert str(registry.local_path()) in note.toolTip()
    assert note.wordWrap()
    assert note.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse


# --- the window -----------------------------------------------------------------
def test_the_status_bar_carries_a_broken_local_files_note(window, isolated_config):
    isolated_config.mkdir(parents=True, exist_ok=True)
    (isolated_config / "apps-local.toml").write_text("this is [not toml\n")

    window.refresh_all()

    message = window.statusBar().currentMessage()
    assert message.startswith("Refreshed")
    assert "Your added projects file was ignored" in message
    assert registry.local_note in message
    assert window.apps_tab.local_note.isVisibleTo(window.apps_tab)


def test_an_unbroken_refresh_says_only_refreshed(window):
    window.refresh_all()

    assert window.statusBar().currentMessage() == "Refreshed."


def test_the_window_refreshes_everything_after_an_add(window):
    window.statusBar().clearMessage()

    window.apps_tab.apps_changed.emit()

    assert window.statusBar().currentMessage().startswith("Refreshed")


def test_giving_a_project_back_in_settings_makes_the_apps_page_ask_again(window, monkeypatch):
    monkeypatch.setattr(discovery, "suggestions", lambda *a, **k: (suggestion(),))
    assert window.apps_tab.banner.rows == []

    window.settings_tab.suggestions_changed.emit()

    assert [r.suggestion.folder for r in window.apps_tab.banner.rows] == ["kaila"]


def test_the_apps_page_is_built_with_discovery_on(window):
    assert window.apps_tab.banner is not None
    assert window.backup_sync_tab.banner is None
    assert window.unblock_tracker_tab.banner is None
    assert window.backstage_tab.banner is None


def _focus_chain(start):
    chain, widget = [], start
    for _ in range(400):
        chain.append(widget)
        widget = widget.nextInFocusChain()
        if widget is start:
            break
    return chain


def test_tab_reaches_the_banner_before_the_tiles_even_when_it_was_rebuilt(qapp, lab, monkeypatch):
    """The banner is built before the tiles, but a row made after an answer is a
    newer widget: Tab must still go banner, then tiles, then the page's own
    buttons (design 12.1.7). The chain is a cycle, so what is asserted is the
    order from the banner's first button on: its buttons, the tiles', then the
    page's."""
    tab = _page_with_projects(lab, monkeypatch, "kaila", "overseer", "shopfront")
    tab.banner.rows[0].not_now_button.click()  # a rebuild, with the tiles already there
    banner_buttons = [b for r in tab.banner.rows for b in (r.add_button, r.not_now_button,
                                                             r.never_button)]
    first_tile_button = tab.cards[0].land_button
    page_button = tab.show_land_button

    chain = _focus_chain(banner_buttons[0])

    assert [w for w in chain if w in banner_buttons] == banner_buttons
    assert chain.index(banner_buttons[-1]) < chain.index(first_tile_button) \
        < chain.index(page_button)
