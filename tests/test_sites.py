"""What a website's answer means, without asking any website."""

from __future__ import annotations

from lab_hub import sites

SITE = sites.Website("x", "example.test", "https://example.test/", "", host="Netlify")


def test_an_ok_answer_is_online():
    status = sites.classify(SITE, 200, None, 0.42)

    assert status.label == "Online"
    assert status.up
    assert "0.4s" in status.detail


def test_a_redirect_still_counts_as_up():
    assert sites.classify(SITE, 301, None, 0.1).up


def test_a_404_at_the_front_door_is_down():
    """bookadatewithme.com did exactly this: Netlify answering for the domain
    with nothing deployed behind it."""
    status = sites.classify(SITE, 404, None, 0.3)

    assert not status.up
    assert status.label == "Error 404"
    assert "Netlify" in status.detail
    assert "no page" in status.detail


def test_no_answer_is_unreachable_and_says_why():
    status = sites.classify(SITE, None, "Host not found", 10.0)

    assert status.label == "Unreachable"
    assert "Host not found" in status.detail


def test_a_lab_relative_source_resolves_under_the_lab(tmp_path):
    (tmp_path / "altmerch_store").mkdir()
    site = sites.Website("a", "a.test", "https://a.test/", "", source="altmerch_store")

    assert sites.source_dir(site, tmp_path) == tmp_path / "altmerch_store"


def test_a_missing_source_is_none(tmp_path):
    site = sites.Website("a", "a.test", "https://a.test/", "", source="gone")

    assert sites.source_dir(site, tmp_path) is None


def test_a_home_relative_source_is_expanded(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "Websites" / "b").mkdir(parents=True)
    site = sites.Website("b", "b.test", "https://b.test/", "", source="~/Websites/b")

    assert sites.source_dir(site, tmp_path / "lab") == tmp_path / "Websites" / "b"


def test_the_registered_sites():
    assert [site.name for site in sites.SITES] == [
        "altmerch.store", "bookadatewithme.com",
    ]
    assert all(site.url.startswith("https://") for site in sites.SITES)
