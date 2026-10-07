"""The dashboard catalog, read the way the Lab Project Monitor reads it."""

from __future__ import annotations

import json

import pytest

from lab_hub import dashboards


def _catalog(lab, entries):
    active = lab / "active"
    active.mkdir(parents=True, exist_ok=True)
    (lab / dashboards.CATALOG_NAME).write_text(json.dumps(entries))
    return active


def test_the_catalog_sits_beside_the_projects_folder(tmp_path):
    active = _catalog(tmp_path, [])

    assert dashboards.catalog_path(active) == tmp_path / dashboards.CATALOG_NAME


def test_entries_keep_the_catalogs_order(tmp_path):
    page = tmp_path / "page.html"
    page.write_text("<div></div>")
    active = _catalog(tmp_path, [
        {"id": "b", "title": "B", "description": "d", "source": "Claude",
         "kind": "Live", "url": "https://claude.ai/artifact/x"},
        {"id": "a", "title": "A", "description": "d", "source": "ChatGPT",
         "kind": "Concept", "path": str(page)},
    ])

    found = dashboards.load(active)

    assert [d.id for d in found] == ["b", "a"]
    assert found[0].available() and not found[0].local
    assert found[1].available() and found[1].local


def test_a_local_file_that_is_gone_is_unavailable(tmp_path):
    active = _catalog(tmp_path, [
        {"id": "a", "title": "A", "path": str(tmp_path / "gone.html")},
    ])

    assert not dashboards.load(active)[0].available()


def test_a_missing_catalog_is_an_error_with_its_path(tmp_path):
    with pytest.raises(dashboards.CatalogError, match="dashboard_catalog.json"):
        dashboards.load(tmp_path / "active")


def test_a_broken_catalog_is_an_error(tmp_path):
    (tmp_path / "active").mkdir()
    (tmp_path / dashboards.CATALOG_NAME).write_text("{not json")

    with pytest.raises(dashboards.CatalogError):
        dashboards.load(tmp_path / "active")


def test_a_link_opens_as_itself():
    entry = dashboards.Dashboard("x", "X", "", "", "", url="https://example.test/")

    assert dashboards.target(entry, monitor_up=True) == "https://example.test/"


def test_a_local_file_goes_through_the_monitor_when_it_is_up(tmp_path):
    """Its route wraps an HTML fragment — the Antfarm workstation is one — in
    a proper page."""
    entry = dashboards.Dashboard("antfarm workstation", "A", "", "", "", path=str(tmp_path / "a.html"))

    assert dashboards.target(entry, monitor_up=True) == (
        "http://127.0.0.1:8765/dashboards/antfarm%20workstation"
    )


def test_a_local_file_opens_directly_when_the_monitor_is_down(tmp_path):
    entry = dashboards.Dashboard("a", "A", "", "", "", path=str(tmp_path / "a.html"))

    assert dashboards.target(entry, monitor_up=False) == (tmp_path / "a.html").as_uri()


def test_the_real_catalog_parses():
    """The lab's own catalog, when this checkout sits in the lab."""
    from lab_hub import config

    root = config.Settings().resolved_lab_root()
    if not dashboards.catalog_path(root).is_file():
        pytest.skip("no lab catalog on this machine")

    assert dashboards.load(root)
