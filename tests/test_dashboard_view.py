"""The Dashboards page: a list, and the chosen dashboard showing beside it."""

from __future__ import annotations

import json
import os

from PySide6.QtWidgets import QLabel

from lab_hub import config, dashboards
from ui.dashboard_view import DashboardsPage, DashboardViewer
from ui.links_tab import DashboardsTab


class FakeView(QLabel):
    """Stands in for a web view: records the address it was told to load."""

    def __init__(self) -> None:
        super().__init__()
        self.loaded = ""
        self.reloads = 0

    def setUrl(self, url) -> None:
        self.loaded = url.toString()

    def reload(self) -> None:
        self.reloads += 1


def _settings(lab_root) -> config.Settings:
    s = config.Settings()
    s.lab_root = str(lab_root)
    return s


def _lab(tmp_path, entries):
    active = tmp_path / "active"
    active.mkdir(exist_ok=True)
    (tmp_path / dashboards.CATALOG_NAME).write_text(json.dumps(entries))
    return active


def _entries(tmp_path):
    page = tmp_path / "p.html"
    page.write_text("<html><body>x</body></html>")
    return [
        {"id": "r", "title": "Remote one", "kind": "Live", "url": "https://claude.ai/artifact/r"},
        {"id": "l", "title": "Local one", "kind": "Report", "path": str(page)},
        {"id": "b", "title": "Both one", "kind": "Live", "url": "https://claude.ai/artifact/b",
         "path": str(page)},
        {"id": "g", "title": "Gone", "kind": "Report", "path": str(tmp_path / "gone.html")},
    ]


def _viewer(tmp_path):
    made = []

    def factory():
        view = FakeView()
        made.append(view)
        return view

    active = _lab(tmp_path, _entries(tmp_path))
    viewer = DashboardViewer(_settings(active), view_factory=factory)
    viewer.activate()
    return viewer, made


def test_embed_address_prefers_the_link_unless_the_local_copy_is_asked_for(tmp_path):
    page = tmp_path / "p.html"
    page.write_text("<div></div>")
    both = dashboards.Dashboard("b", "B", "", "", "", url="https://x.test/", path=str(page))
    link = dashboards.Dashboard("r", "R", "", "", "", url="https://x.test/")
    local = dashboards.Dashboard("l", "L", "", "", "", path=str(page))
    gone = dashboards.Dashboard("g", "G", "", "", "", path=str(tmp_path / "no.html"))

    assert dashboards.embed_address(both, monitor_up=False) == "https://x.test/"
    assert dashboards.embed_address(both, prefer_local=True, monitor_up=False) == page.as_uri()
    assert dashboards.embed_address(link, prefer_local=True) == "https://x.test/"
    assert dashboards.embed_address(local, monitor_up=False) == page.as_uri()
    assert dashboards.embed_address(gone) is None


def test_the_list_shows_every_entry_with_where_it_lives(qapp, tmp_path):
    viewer, _ = _viewer(tmp_path)

    rows = [viewer.list.item(i).text() for i in range(viewer.list.count())]

    assert rows == [
        "Remote one\nRemote · Live",
        "Local one\nLocal · Report",
        "Both one\nBoth · Live",
        "Gone\nLocal · Report",
    ]


def test_choosing_a_dashboard_loads_it_once_and_keeps_it(qapp, tmp_path):
    viewer, made = _viewer(tmp_path)
    assert [v.loaded for v in made] == ["https://claude.ai/artifact/r"]

    viewer.list.setCurrentRow(2)
    viewer.list.setCurrentRow(0)
    viewer.list.setCurrentRow(2)

    assert [v.loaded for v in made] == [
        "https://claude.ai/artifact/r",
        "https://claude.ai/artifact/b",
    ]
    assert viewer.stack.currentWidget() is made[1]


def test_a_both_entry_can_switch_to_its_local_copy(qapp, tmp_path):
    viewer, made = _viewer(tmp_path)
    viewer.list.setCurrentRow(2)
    assert not viewer.source_button.isHidden()

    viewer._toggle_source()

    assert made[-1].loaded.startswith("file:") or "127.0.0.1" in made[-1].loaded
    assert viewer.stack.currentWidget() is made[-1]


def test_the_source_switch_is_only_for_entries_that_have_both(qapp, tmp_path):
    viewer, _ = _viewer(tmp_path)

    for row, expected_hidden in ((0, True), (1, True), (2, False)):
        viewer.list.setCurrentRow(row)
        assert viewer.source_button.isHidden() is expected_hidden


def test_an_entry_with_nothing_to_show_says_so_and_loads_nothing(qapp, tmp_path):
    viewer, made = _viewer(tmp_path)

    viewer.list.setCurrentRow(3)

    assert viewer.stack.currentWidget() is viewer.message
    assert "nothing that can be shown" in viewer.message.text()
    assert not viewer.browser_button.isEnabled()
    assert len(made) == 1  # only the first row's view, from opening the page


def test_reload_reloads_the_view_on_screen(qapp, tmp_path):
    viewer, made = _viewer(tmp_path)

    viewer.reload_button.click()

    assert made[0].reloads == 1


def test_a_changed_catalog_is_picked_up_and_the_choice_kept(qapp, tmp_path):
    viewer, _ = _viewer(tmp_path)
    viewer.list.setCurrentRow(2)
    catalog = tmp_path / dashboards.CATALOG_NAME
    entries = _entries(tmp_path) + [{"id": "n", "title": "New", "url": "https://n.test/"}]
    catalog.write_text(json.dumps(entries))
    stat = catalog.stat()
    os.utime(catalog, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))

    viewer.refresh()

    assert viewer.list.count() == 5
    assert viewer.current_entry().id == "b"


def test_the_page_swaps_between_the_viewer_and_the_tiles(qapp, tmp_path):
    viewer, _ = _viewer(tmp_path)
    page = DashboardsPage(DashboardsTab(_settings(tmp_path / "active")), viewer)
    assert page.stack.currentWidget() is viewer

    page.toggle.click()
    assert page.stack.currentWidget() is page.tiles
    assert page.toggle.text() == "Show in window"
    page.toggle.click()

    assert page.stack.currentWidget() is viewer


def test_a_missing_catalog_shows_the_reason_not_an_empty_list(qapp, tmp_path):
    viewer = DashboardViewer(_settings(tmp_path / "active"), view_factory=FakeView)

    assert viewer.list.count() == 0
    assert "dashboard_catalog.json" in viewer.message.text()


def test_nothing_loads_until_the_page_is_on_screen(qapp, tmp_path):
    made = []
    active = _lab(tmp_path, _entries(tmp_path))
    viewer = DashboardViewer(_settings(active), view_factory=lambda: made.append(FakeView()) or made[-1])

    viewer.list.setCurrentRow(2)
    assert made == []

    viewer.activate()

    assert [v.loaded for v in made] == ["https://claude.ai/artifact/b"]


def _unopened_viewer(tmp_path):
    made = []

    def factory():
        view = FakeView()
        made.append(view)
        return view

    active = _lab(tmp_path, _entries(tmp_path))
    return DashboardViewer(_settings(active), view_factory=factory), made


def test_the_first_web_view_is_made_at_launch_and_fetches_nothing(monkeypatch, qapp, tmp_path):
    """Made on the first visit, it froze and redrew the whole window (owner, 2026-11-23)."""
    from ui import dashboard_view

    monkeypatch.setattr(dashboard_view, "web_available", lambda: True)
    viewer, made = _unopened_viewer(tmp_path)

    assert viewer.prepare() is True
    assert viewer.prepare() is False  # one is enough
    assert [v.loaded for v in made] == ["about:blank"]
    assert viewer.stack.indexOf(made[0]) >= 0


def test_the_first_dashboard_uses_the_view_made_at_launch(monkeypatch, qapp, tmp_path):
    from ui import dashboard_view

    monkeypatch.setattr(dashboard_view, "web_available", lambda: True)
    viewer, made = _unopened_viewer(tmp_path)
    viewer.prepare()

    viewer.activate()

    assert len(made) == 1
    assert made[0].loaded == "https://claude.ai/artifact/r"
    assert viewer.stack.currentWidget() is made[0]
    viewer.list.setCurrentRow(2)
    assert len(made) == 2 and viewer.stack.currentWidget() is made[1]


def test_no_view_is_made_at_launch_without_the_web_engine(monkeypatch, qapp, tmp_path):
    from ui import dashboard_view

    monkeypatch.setattr(dashboard_view, "web_available", lambda: False)
    viewer, made = _unopened_viewer(tmp_path)

    assert viewer.prepare() is False
    assert made == []


def test_lab_hub_draws_through_the_gpu_from_the_start():
    """Without it the first web view rebuilds a fullscreen window, which macOS
    animates as leaving fullscreen and coming back."""
    from ui.main_window import prepare_qt_environment

    env: dict[str, str] = {}
    prepare_qt_environment(env)
    assert env["QT_WIDGETS_RHI"] == "1"


def test_a_gpu_drawing_choice_the_owner_made_is_kept():
    from ui.main_window import prepare_qt_environment

    env = {"QT_WIDGETS_RHI": "0"}
    prepare_qt_environment(env)
    assert env["QT_WIDGETS_RHI"] == "0"


def test_a_web_view_starts_in_the_window_colour_not_white(monkeypatch, qapp, tmp_path):
    """The default white page flashed before the first dashboard painted."""
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QWidget

    from ui import dashboard_view

    painted = []

    class Stub:
        class PersistentCookiesPolicy:
            ForcePersistentCookies = 0

        def __init__(self, *a, **k):
            pass

        def __getattr__(self, name):
            return lambda *a, **k: None

    class Page(Stub):
        def setBackgroundColor(self, colour):
            painted.append(colour)

    import PySide6.QtWebEngineCore as core
    import PySide6.QtWebEngineWidgets as widgets

    monkeypatch.setattr(core, "QWebEngineProfile", type("Profile", (Stub,), {}))
    monkeypatch.setattr(core, "QWebEnginePage", Page)
    monkeypatch.setattr(widgets, "QWebEngineView", type("View", (Stub,), {}))
    monkeypatch.setattr(config, "SUPPORT_DIR", tmp_path)

    owner = QWidget()
    dashboard_view._real_view_factory(owner)()
    assert painted == [owner.palette().color(QPalette.ColorRole.Window)]
