"""Status rows under a tile's version (spec tile-status-rows §2)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from lab_hub import hygiene, launcher
from lab_hub.launcher.state import Version
from ui.apps_tab import AppCard
from ui.status_rows import StatusRows, update_text

APP = launcher.ExternalApp("s", "SONAR", "s", "main.py", "summary")


def _card(monkeypatch, found: Version, row: hygiene.RepoRow | None = None) -> AppCard:
    monkeypatch.setattr(launcher, "version", lambda app, root: found)
    card = AppCard(APP)
    card.refresh_version(Path("/lab"))
    card.refresh_hygiene(row)
    return card


def _row(*problems: str, error: str = "") -> hygiene.RepoRow:
    return hygiene.RepoRow("s", Path("/lab/s"), "main", problems=problems, error=error)


STALE_DIRTY = Version(text="v2.447", origin="bundle", detail="x", behind=3,
                      commit="96b469c", dirty=True)
CLEAN = Version(text="v2.447", origin="bundle", detail="x", commit="96b469c")


def test_all_three_facts_get_a_row_each_and_the_version_is_only_the_id(qapp, monkeypatch):
    card = _card(monkeypatch, STALE_DIRTY, _row("1 branch not merged into main"))
    assert card.version.text() == "v2.447+g96b469c"
    assert card.version.objectName() == "hint"
    assert card.status.texts() == [
        "Installed build is 3 commits old",
        "1 branch waiting to land",
        "Built from uncommitted changes",
    ]
    assert [r.kind for r in card.status.rows] == ["update", "land", "uncommitted"]


@pytest.mark.parametrize("found,row,expected", [
    (Version(text="v1", origin="bundle", commit="abc1234", behind=1), None,
     ["Installed build is 1 commit old"]),
    (CLEAN, _row("2 worktrees with uncommitted changes"), ["2 worktrees waiting to land"]),
    (Version(text="v1", origin="checkout", commit="abc1234", dirty=True), None,
     ["Uncommitted changes in source"]),
    (CLEAN, _row(error="git failed"), ["Repo not readable"]),
])
def test_each_fact_alone(qapp, monkeypatch, found, row, expected):
    assert _card(monkeypatch, found, row).status.texts() == expected


def test_only_the_symbol_is_coloured(qapp, monkeypatch):
    card = _card(monkeypatch, STALE_DIRTY, _row("1 branch not merged into main", ))
    symbols = [w for w in card.status.findChildren(QLabel)
               if w.objectName() not in ("statusText", "statusLink")]
    assert [s.objectName() for s in symbols] == ["statusAccent", "stateWarn", "stateWarn"]
    texts = card.status.findChildren(QLabel, "statusText")
    assert len(texts) == 3


def test_up_to_date_needs_evidence(qapp, monkeypatch):
    # Known version, a report row with nothing to land: say so.
    assert _card(monkeypatch, CLEAN, _row()).status.texts() == ["Up to date, nothing to land"]
    # No report row, or no known version: say nothing rather than guess.
    assert _card(monkeypatch, CLEAN, None).status.texts() == []
    assert _card(monkeypatch, Version(), _row()).status.texts() == []
    assert _card(monkeypatch, CLEAN, None).status.isHidden()
    # A number with nothing compared is not evidence (review P1).
    no_commit = Version(text="v2.447", origin="bundle", detail="x")
    unknown = Version(text="v2.447", origin="bundle", detail="x", commit="96b469c",
                      behind_unknown=True)
    assert _card(monkeypatch, no_commit, _row()).status.texts() == []
    assert _card(monkeypatch, unknown, _row()).status.texts() == []


def test_own_tile_says_up_to_date_only_after_its_check_says_so(qapp):
    from lab_hub import self_update
    from ui.apps_tab import OwnCard
    from ui.own_verdict import OwnResult
    from .test_apps_discovery_ui import _row as build_row

    card = OwnCard(self_update.OWN_TILE)
    card.refresh_hygiene(_row())
    assert card.status.texts() == []  # check not back yet
    card.set_verdict(OwnResult(error="git failed"))
    assert card.status.texts() == []
    card.set_verdict(OwnResult(row=build_row("current", note="runs the checkout directly, so ...")))
    assert card.status.texts() == []
    card.set_verdict(OwnResult(row=build_row("current")))
    assert card.status.texts() == ["Up to date, nothing to land"]


def test_a_checkouts_uncommitted_files_are_said_once(qapp, monkeypatch):
    dirty = Version(text="v1", origin="checkout", commit="abc1234", dirty=True)
    card = _card(monkeypatch, dirty, _row("3 uncommitted files"))
    assert card.status.texts() == ["3 files waiting to land"]


def test_land_button_counts_what_the_badge_counts(qapp, monkeypatch):
    card = _card(monkeypatch, CLEAN, _row("1 branch not merged into main",
                                          "2 worktrees with uncommitted changes"))
    assert card.land_button.text() == "Land (3)"
    card.refresh_hygiene(_row("something worded another way"))
    assert card.land_button.text() == "Land"


def test_land_count_property():
    assert _row("3 uncommitted files", "1 unpushed commit").land_count == 4
    assert _row("diverged: 2 unpushed, 1 behind").land_count == 3
    assert _row("odd line").land_count == 0
    assert _row("1 branch not merged into main", "odd line").land_count == 0  # cannot count all
    assert _row(error="x").land_count == 0
    assert _row().land_count == 0


def test_check_builds_link_only_where_the_page_has_it(qapp, monkeypatch):
    card = _card(monkeypatch, STALE_DIRTY)
    assert card.status.findChildren(QLabel, "statusLink") == []
    card.set_check_builds_available(True)
    links = card.status.findChildren(QLabel, "statusLink")
    assert len(links) == 1 and "Check builds" in links[0].text()
    fired = []
    card.check_builds_requested.connect(lambda: fired.append(True))
    links[0].linkActivated.emit("check-builds")
    assert fired == [True]
    # The words beside it stay plain text.
    words = card.status.findChildren(QLabel, "statusText")[0]
    assert words.textFormat() == Qt.TextFormat.PlainText


def test_rows_are_not_rebuilt_when_nothing_changed(qapp, monkeypatch):
    card = _card(monkeypatch, STALE_DIRTY)
    before = card.status.findChildren(QLabel, "statusText")[0]
    card.refresh_version(Path("/lab"))  # the three-second poll
    assert card.status.findChildren(QLabel, "statusText")[0] is before


def test_update_text_wording():
    assert update_text(1) == "Installed build is 1 commit old"
    assert update_text(10) == "Installed build is 10 commits old"
    assert update_text(0) == update_text(-1) == "Installed build is older than its source"


def test_status_text_is_plain_never_markup(qapp):
    rows = StatusRows()
    from ui.status_rows import Row
    rows.set_rows([Row("land", "<b>1</b> branch waiting to land")])
    label = rows.findChildren(QLabel, "statusText")[0]
    assert label.text() == "<b>1</b> branch waiting to land"
    from PySide6.QtCore import Qt
    assert label.textFormat() == Qt.TextFormat.PlainText
