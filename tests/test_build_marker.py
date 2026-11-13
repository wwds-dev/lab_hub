"""The build marker on a tile: `v<major>.<build>+g<sha7>[-dirty]`, one rule for all.

Specs: docs/specs/lab-wide-build-marker.md, success measures 0-6. The git-backed
tests build real repositories in tmp_path, because the thing being claimed is
about commits and a stub of git would only agree with itself.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from lab_hub import launcher
from ui.apps_tab import AppCard

from .fakes import make_bundle

ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


def git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, env=ENV, check=True, capture_output=True, text=True
    ).stdout.strip()


def commit(repo, name):
    (repo / name).write_text(name)
    git(repo, "add", name)
    git(repo, "commit", "-qm", name)


def make_repo(path, commits):
    path.mkdir(parents=True)
    git(path, "init", "-q")
    (path / "VERSION").write_text("2.0\n")
    (path / "main.py").write_text("pass\n")
    git(path, "add", "VERSION", "main.py")
    git(path, "commit", "-qm", "c1")
    for n in range(2, commits + 1):
        commit(path, f"f{n}")
    return path


@pytest.fixture(autouse=True)
def _fresh_caches(monkeypatch):
    for cache in (launcher.state._COMMIT_CACHE, launcher.state._COUNT_CACHE,
                  launcher.state._DIRTY_CACHE, launcher.state._BEHIND_CACHE,
                  launcher.state._SHALLOW_CACHE, launcher.state._ROOT_BEHIND_CACHE):
        cache.clear()
    yield


def _launcher_bundle(apps_dir, name, root):
    bundle = make_bundle(apps_dir, name)
    (bundle / "Contents" / "Resources").mkdir(parents=True, exist_ok=True)
    (bundle / "Contents" / "Resources" / launcher.PROJECT_ROOT_FILE).write_text(str(root))
    return bundle


def _app(name="Provisio", project="provisio"):
    return launcher.ExternalApp(project, name, project, "main.py", "")


# -- grammar (measure 1, 3, 4) -------------------------------------------------
def test_marker_has_commit_and_dirty_suffix():
    v = launcher.Version(text="v2.0.153", commit="c534bbb")
    assert v.marker == "v2.0.153+gc534bbb"
    assert launcher.Version(text="v2.0.153", commit="c534bbb", dirty=True).marker == (
        "v2.0.153+gc534bbb-dirty"
    )


def test_marker_without_a_commit_has_no_g_and_never_dirty():
    assert launcher.Version(text="v2.0.153", dirty=True).marker == "v2.0.153"
    assert launcher.Version().marker == ""


# -- measure 0: the Provisio case, with real git ------------------------------
def test_launcher_bundle_reads_its_recorded_root_and_says_how_far_behind(tmp_path, monkeypatch):
    work = make_repo(tmp_path / "lab" / "provisio", 5)
    release = tmp_path / "rel"
    git(tmp_path, "clone", "-q", str(work), str(release))
    git(release, "reset", "-q", "--hard", "HEAD~2")
    apps = tmp_path / "Applications"
    apps.mkdir()
    monkeypatch.setattr(launcher, "APPLICATIONS", apps)
    _launcher_bundle(apps, "Provisio", release)

    found = launcher.version(_app(), tmp_path / "lab")

    assert found.text == "v2.0.003"
    assert found.commit == git(release, "rev-parse", "--short=7", "HEAD")
    assert found.behind == 2 and found.stale
    assert str(release) in found.detail


def test_launcher_bundle_running_the_working_checkout_is_not_behind(tmp_path, monkeypatch):
    work = make_repo(tmp_path / "lab" / "provisio", 4)
    apps = tmp_path / "Applications"
    apps.mkdir()
    monkeypatch.setattr(launcher, "APPLICATIONS", apps)
    _launcher_bundle(apps, "Provisio", work)

    found = launcher.version(_app(), tmp_path / "lab")

    assert found.text == "v2.0.004" and not found.stale
    assert found.commit == git(work, "rev-parse", "--short=7", "HEAD")


def _install(tmp_path, monkeypatch, root, commits=3):
    make_repo(tmp_path / "lab" / "provisio", commits)
    apps = tmp_path / "Applications"
    apps.mkdir(exist_ok=True)
    monkeypatch.setattr(launcher, "APPLICATIONS", apps)
    _launcher_bundle(apps, "Provisio", root)
    return tmp_path / "lab"


def _unknown_naming(found, root, why):
    assert not found.known and found.marker == ""
    assert found.root == str(root) and str(root) in found.detail and why in found.detail


def test_a_missing_recorded_root_is_unknown_and_names_the_root(tmp_path, monkeypatch):
    root = tmp_path / "gone"
    lab = _install(tmp_path, monkeypatch, root)

    _unknown_naming(launcher.version(_app(), lab), root, "missing")


def test_a_recorded_root_that_is_not_git_is_unknown(tmp_path, monkeypatch):
    root = tmp_path / "plain"
    root.mkdir()
    (root / "main.py").write_text("pass\n")
    (root / "VERSION").write_text("2.0\n")
    lab = _install(tmp_path, monkeypatch, root)

    _unknown_naming(launcher.version(_app(), lab), root, "not a git checkout")


def test_a_recorded_root_without_a_version_arc_is_unknown(tmp_path, monkeypatch):
    root = make_repo(tmp_path / "rel", 2)
    git(root, "rm", "-q", "VERSION")
    git(root, "commit", "-qm", "drop VERSION")
    lab = _install(tmp_path, monkeypatch, root)

    found = launcher.version(_app(), lab)

    _unknown_naming(found, root, "no VERSION arc")
    assert "v2.0.003" not in found.detail


def test_a_recorded_root_without_the_entry_script_is_unknown(tmp_path, monkeypatch):
    root = tmp_path / "rel"
    root.mkdir()
    lab = _install(tmp_path, monkeypatch, root)

    _unknown_naming(launcher.version(_app(), lab), root, "missing or has no main.py")


def test_an_unreadable_root_is_unknown_even_with_no_working_checkout(tmp_path, monkeypatch):
    apps = tmp_path / "Applications"
    apps.mkdir()
    monkeypatch.setattr(launcher, "APPLICATIONS", apps)
    _launcher_bundle(apps, "Provisio", tmp_path / "gone")

    found = launcher.version(_app(), tmp_path / "empty-lab")

    assert not found.known and "gone" in found.detail


def test_the_tile_names_an_unreadable_root_in_its_tooltip(qapp, tmp_path, monkeypatch):
    root = tmp_path / "gone"
    lab = _install(tmp_path, monkeypatch, root)
    card = AppCard(_app())

    card.refresh_version(lab)

    assert card.version.text() == ""
    assert str(root) in card.version.toolTip()


def test_build_report_is_unknown_for_an_unreadable_root(tmp_path, monkeypatch):
    root = tmp_path / "gone"
    lab = _install(tmp_path, monkeypatch, root)

    row = launcher.build_status(_app(), lab)

    assert row.verdict == "unknown" and str(root) in row.note
    assert "working checkout" in row.note


def test_build_report_calls_a_lagging_launcher_bundle_behind(tmp_path, monkeypatch):
    work = make_repo(tmp_path / "lab" / "provisio", 5)
    release = tmp_path / "rel"
    git(tmp_path, "clone", "-q", str(work), str(release))
    git(release, "reset", "-q", "--hard", "HEAD~2")
    apps = tmp_path / "Applications"
    apps.mkdir()
    monkeypatch.setattr(launcher, "APPLICATIONS", apps)
    _launcher_bundle(apps, "Provisio", release)

    row = launcher.build_status(_app(), tmp_path / "lab")

    assert row.verdict == "behind"


# -- measure 1/2/3: stamped bundles -------------------------------------------
def _stamp(bundle, **payload):
    target = bundle / "Contents" / "Resources"
    target.mkdir(parents=True, exist_ok=True)
    (target / launcher.BUILD_INFO_NAME).write_text(json.dumps(payload))


def test_stamped_bundle_shows_its_stamped_commit_never_the_checkouts(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    _stamp(make_bundle(tmp_path, "SONAR"), major="2", build=3, commit="abc1234")
    make_repo(tmp_path / "sonar", 3)

    found = launcher.version(_app("SONAR", "sonar"), tmp_path)

    assert found.marker == "v2.003+gabc1234"
    assert not found.dirty


def test_stamped_bundle_without_a_commit_says_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    _stamp(make_bundle(tmp_path, "SONAR"), major="2", build=3)
    make_repo(tmp_path / "sonar", 3)

    found = launcher.version(_app("SONAR", "sonar"), tmp_path)

    assert found.marker == "v2.003" and found.commit == ""
    assert "no commit" in found.commit_note


def test_stamped_bundle_behind_is_counted_from_its_commit(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    repo = make_repo(tmp_path / "sonar", 5)
    built = git(repo, "rev-parse", "--short=7", "HEAD~2")
    _stamp(make_bundle(tmp_path, "SONAR"), major="2", build=3, commit=built)

    assert launcher.version(_app("SONAR", "sonar"), tmp_path).behind == 2


# -- measure 4: dirty ----------------------------------------------------------
def test_checkout_with_uncommitted_changes_shows_dirty(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "none")
    repo = make_repo(tmp_path / "sonar", 2)
    assert launcher.version(_app("SONAR", "sonar"), tmp_path).marker.endswith(
        git(repo, "rev-parse", "--short=7", "HEAD")
    )
    launcher.state._DIRTY_CACHE.clear()
    (repo / "stray.txt").write_text("x")

    assert launcher.version(_app("SONAR", "sonar"), tmp_path).marker.endswith("-dirty")


def test_dirty_check_runs_git_status_once_per_window(tmp_path, monkeypatch):
    repo = make_repo(tmp_path / "sonar", 1)
    calls = []
    real = launcher.state.dirty_checkout
    monkeypatch.setattr(
        launcher.state, "dirty_checkout", lambda p: calls.append(p) or real(p)
    )

    for _ in range(5):
        launcher.state._is_dirty(repo)

    assert len(calls) == 1


def test_dirty_check_runs_again_after_the_window(tmp_path, monkeypatch):
    repo = make_repo(tmp_path / "sonar", 1)
    calls = []
    monkeypatch.setattr(launcher.state, "dirty_checkout", lambda p: calls.append(p) or False)
    clock = [100.0]
    monkeypatch.setattr(launcher.state.time, "monotonic", lambda: clock[0])

    launcher.state._is_dirty(repo)
    clock[0] += launcher.state.DIRTY_TTL_SECONDS + 1
    launcher.state._is_dirty(repo)

    assert len(calls) == 2


def test_head_commit_is_cached_against_head(tmp_path, monkeypatch):
    repo = make_repo(tmp_path / "sonar", 1)
    calls = []
    real = launcher.state.subprocess.run
    monkeypatch.setattr(
        launcher.state.subprocess, "run", lambda *a, **k: calls.append(a) or real(*a, **k)
    )

    for _ in range(4):
        launcher.state._head_commit(repo)

    assert len(calls) == 1


# -- measure 6: outside the scheme --------------------------------------------
def test_app_outside_the_scheme_keeps_its_text_and_says_why(tmp_path, monkeypatch):
    import plistlib

    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    bundle = make_bundle(tmp_path, "SYNDUSTRYX")
    with (bundle / "Contents" / "Info.plist").open("wb") as handle:
        plistlib.dump({"CFBundleExecutable": "SYNDUSTRYX",
                       "CFBundleShortVersionString": "0.6.20"}, handle)

    found = launcher.version(_app("SYNDUSTRYX", "syndustryx"), tmp_path)

    assert found.marker == "v0.6.20"
    assert "outside the lab version scheme" in found.commit_note


# -- the tile (measures 0, 1, 3, 6) -------------------------------------------
def test_tile_text_and_tooltip_for_the_provisio_case(qapp, tmp_path, monkeypatch):
    work = make_repo(tmp_path / "lab" / "provisio", 5)
    release = tmp_path / "rel"
    git(tmp_path, "clone", "-q", str(work), str(release))
    git(release, "reset", "-q", "--hard", "HEAD~2")
    apps = tmp_path / "Applications"
    apps.mkdir()
    monkeypatch.setattr(launcher, "APPLICATIONS", apps)
    _launcher_bundle(apps, "Provisio", release)
    sha = git(release, "rev-parse", "--short=7", "HEAD")
    card = AppCard(_app())

    card.refresh_version(tmp_path / "lab")

    assert card.version.text() == f"v2.0.003+g{sha} · 2 behind"
    assert sha in card.version.toolTip() and "2 commits further on" in card.version.toolTip()


def test_tile_tooltip_says_when_the_commit_is_unknown(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    _stamp(make_bundle(tmp_path, "SONAR"), major="2", build=3)
    card = AppCard(_app("SONAR", "sonar"))

    card.refresh_version(tmp_path)

    assert card.version.text() == "v2.003"
    assert "Commit unknown" in card.version.toolTip()


def test_tile_for_a_clean_checkout_has_no_dirty(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "none")
    repo = make_repo(tmp_path / "sonar", 2)
    card = AppCard(_app("SONAR", "sonar"))

    card.refresh_version(tmp_path)

    assert card.version.text() == f"v2.0.002+g{git(repo, 'rev-parse', '--short=7', 'HEAD')}"


# -- stamp script (scope: commit required) ------------------------------------
def test_stamp_script_refuses_to_write_without_a_commit(tmp_path, monkeypatch, capsys):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    try:
        import stamp_version
    finally:
        sys.path.pop(0)
    monkeypatch.setattr(stamp_version, "PROJECT_ROOT", tmp_path)
    (tmp_path / "VERSION").write_text("2\n")
    monkeypatch.setattr(
        stamp_version, "_git", lambda *a: "" if a[0] == "rev-parse" else "7"
    )

    assert stamp_version.main() == 1
    assert not (tmp_path / launcher.BUILD_INFO_NAME).exists()
    assert "commit" in capsys.readouterr().err


# -- review findings -----------------------------------------------------------
def test_a_build_that_already_contains_head_is_not_behind(tmp_path, monkeypatch):
    """Stamped commit is ahead of a checkout sitting on an older branch tip."""
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    repo = make_repo(tmp_path / "sonar", 3)
    git(repo, "branch", "feature")
    git(repo, "checkout", "-q", "feature")
    commit(repo, "extra")
    built = git(repo, "rev-parse", "--short=7", "HEAD")
    git(repo, "checkout", "-q", "-")
    _stamp(make_bundle(tmp_path, "SONAR"), major="2", build=4, commit=built)

    assert launcher.version(_app("SONAR", "sonar"), tmp_path).behind == 0


def test_a_diverged_build_counts_only_head_s_own_commits(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    repo = make_repo(tmp_path / "sonar", 2)
    git(repo, "checkout", "-q", "-b", "other")
    commit(repo, "x1")
    built = git(repo, "rev-parse", "--short=7", "HEAD")
    git(repo, "checkout", "-q", "-")
    commit(repo, "m1")
    commit(repo, "m2")
    _stamp(make_bundle(tmp_path, "SONAR"), major="2", build=3, commit=built)

    assert launcher.version(_app("SONAR", "sonar"), tmp_path).behind == 2


def test_launcher_root_with_a_commit_unknown_to_the_working_checkout_is_unknown(
        tmp_path, monkeypatch, qapp):
    """Counts from two unrelated histories must not be compared."""
    make_repo(tmp_path / "lab" / "provisio", 5)
    release = make_repo(tmp_path / "rel", 3)
    commit(release, "only-in-release")
    apps = tmp_path / "Applications"
    apps.mkdir()
    monkeypatch.setattr(launcher, "APPLICATIONS", apps)
    _launcher_bundle(apps, "Provisio", release)

    found = launcher.version(_app(), tmp_path / "lab")

    assert found.behind_unknown and not found.stale and found.behind == 0
    card = AppCard(_app())
    card.refresh_version(tmp_path / "lab")
    assert "behind" not in card.version.text()
    assert "cannot be told" in card.version.toolTip()


def test_a_dirty_release_root_shows_dirty(tmp_path, monkeypatch):
    work = make_repo(tmp_path / "lab" / "provisio", 3)
    release = tmp_path / "rel"
    git(tmp_path, "clone", "-q", str(work), str(release))
    (release / "stray").write_text("x")
    apps = tmp_path / "Applications"
    apps.mkdir()
    monkeypatch.setattr(launcher, "APPLICATIONS", apps)
    _launcher_bundle(apps, "Provisio", release)

    assert launcher.version(_app(), tmp_path / "lab").marker.endswith("-dirty")


def test_dirty_cache_is_dropped_by_a_new_commit(tmp_path, monkeypatch):
    repo = make_repo(tmp_path / "sonar", 1)
    (repo / "stray").write_text("x")
    assert launcher.state._is_dirty(repo) is True
    (repo / "stray").unlink()
    commit(repo, "next")

    assert launcher.state._is_dirty(repo) is False


def test_head_commit_cache_is_invalidated_by_a_commit(tmp_path):
    repo = make_repo(tmp_path / "sonar", 1)
    first = launcher.state._head_commit(repo)
    commit(repo, "next")

    assert launcher.state._head_commit(repo) not in ("", first)


@pytest.mark.parametrize("bad", ["unknown", "--all", "", 7, "ZZZZZZZ", "abc"])
def test_a_malformed_stamped_commit_is_ignored(tmp_path, monkeypatch, bad):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    _stamp(make_bundle(tmp_path, "SONAR"), major="2", build=3, commit=bad)

    found = launcher.version(_app("SONAR", "sonar"), tmp_path)

    assert found.commit == "" and found.marker == "v2.003"


# -- verify-round fixes ---------------------------------------------------------
def _unrelated_root(tmp_path, monkeypatch):
    make_repo(tmp_path / "lab" / "provisio", 5)
    release = make_repo(tmp_path / "rel", 3)
    commit(release, "only-in-release")
    apps = tmp_path / "Applications"
    apps.mkdir()
    monkeypatch.setattr(launcher, "APPLICATIONS", apps)
    _launcher_bundle(apps, "Provisio", release)
    return tmp_path / "lab", release


def test_build_report_is_unknown_when_behind_cannot_be_told(tmp_path, monkeypatch):
    lab, release = _unrelated_root(tmp_path, monkeypatch)

    row = launcher.build_status(_app(), lab)

    assert row.verdict == "unknown"
    assert str(release) in row.note and "the working checkout" in row.note
    assert "runs the checkout directly" not in row.note


def test_build_report_for_a_level_recorded_root_names_the_root(tmp_path, monkeypatch):
    work = make_repo(tmp_path / "lab" / "provisio", 3)
    release = tmp_path / "rel"
    git(tmp_path, "clone", "-q", str(work), str(release))
    apps = tmp_path / "Applications"
    apps.mkdir()
    monkeypatch.setattr(launcher, "APPLICATIONS", apps)
    _launcher_bundle(apps, "Provisio", release)

    row = launcher.build_status(_app(), tmp_path / "lab")

    assert row.verdict == "current" and str(release) in row.note
    assert "runs the checkout directly" not in row.note


def test_a_recorded_root_ahead_of_the_working_checkout_is_not_behind(tmp_path, monkeypatch):
    work = make_repo(tmp_path / "lab" / "provisio", 3)
    release = tmp_path / "rel"
    git(tmp_path, "clone", "-q", str(work), str(release))
    commit(release, "ahead")
    apps = tmp_path / "Applications"
    apps.mkdir()
    monkeypatch.setattr(launcher, "APPLICATIONS", apps)
    _launcher_bundle(apps, "Provisio", release)

    found = launcher.version(_app(), tmp_path / "lab")

    assert found.text == "v2.0.004" and found.behind == 0 and not found.behind_unknown


def test_a_symlinked_root_equal_to_the_working_checkout_is_not_a_second_root(
        tmp_path, monkeypatch):
    work = make_repo(tmp_path / "lab" / "provisio", 3)
    link = tmp_path / "link"
    link.symlink_to(work)
    apps = tmp_path / "Applications"
    apps.mkdir()
    monkeypatch.setattr(launcher, "APPLICATIONS", apps)
    _launcher_bundle(apps, "Provisio", link)

    found = launcher.version(_app(), tmp_path / "lab")

    assert found.root == "" and found.origin == "checkout"


def test_a_stamp_commit_unknown_to_the_checkout_is_not_compared_by_count(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    make_repo(tmp_path / "sonar", 9)
    _stamp(make_bundle(tmp_path, "SONAR"), major="2", build=3, commit="deadbee")

    found = launcher.version(_app("SONAR", "sonar"), tmp_path)

    assert found.behind_unknown and found.behind == 0 and found.marker == "v2.003+gdeadbee"


def test_a_stamp_without_a_commit_still_compares_counts(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)
    make_repo(tmp_path / "sonar", 9)
    _stamp(make_bundle(tmp_path, "SONAR"), major="2", build=3)

    assert launcher.version(_app("SONAR", "sonar"), tmp_path).behind == 6


def test_a_shallow_checkout_does_not_claim_a_build_number(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path / "none")
    source = make_repo(tmp_path / "src", 5)
    shallow = tmp_path / "sonar"
    git(tmp_path, "clone", "-q", "--depth", "1", f"file://{source}", str(shallow))

    found = launcher.version(_app("SONAR", "sonar"), tmp_path)

    assert found.text == "v2.0.unknown"
    assert found.commit == git(shallow, "rev-parse", "--short=7", "HEAD")


def test_behind_is_not_recomputed_while_head_is_unchanged(tmp_path, monkeypatch):
    work = make_repo(tmp_path / "lab" / "provisio", 5)
    release = tmp_path / "rel"
    git(tmp_path, "clone", "-q", str(work), str(release))
    git(release, "reset", "-q", "--hard", "HEAD~2")
    apps = tmp_path / "Applications"
    apps.mkdir()
    monkeypatch.setattr(launcher, "APPLICATIONS", apps)
    _launcher_bundle(apps, "Provisio", release)
    launcher.version(_app(), tmp_path / "lab")  # warm every cache
    seen = []
    real = launcher.state.subprocess.run
    monkeypatch.setattr(
        launcher.state.subprocess, "run", lambda *a, **k: seen.append(a) or real(*a, **k)
    )

    for _ in range(3):
        launcher.version(_app(), tmp_path / "lab")

    assert seen == [], "git ran again for unchanged repositories"


def test_unknown_behind_is_also_cached(tmp_path, monkeypatch):
    lab, _release = _unrelated_root(tmp_path, monkeypatch)
    launcher.version(_app(), lab)
    seen = []
    real = launcher.state.subprocess.run
    monkeypatch.setattr(
        launcher.state.subprocess, "run", lambda *a, **k: seen.append(a) or real(*a, **k)
    )

    launcher.version(_app(), lab)

    assert seen == []


def test_a_diverged_root_whose_histories_are_not_shared_is_unknown(tmp_path, monkeypatch):
    work = make_repo(tmp_path / "lab" / "provisio", 3)
    release = tmp_path / "rel"
    git(tmp_path, "clone", "-q", str(work), str(release))
    commit(release, "only-in-release")
    commit(work, "w1")
    commit(work, "w2")
    apps = tmp_path / "Applications"
    apps.mkdir()
    monkeypatch.setattr(launcher, "APPLICATIONS", apps)
    _launcher_bundle(apps, "Provisio", release)

    found = launcher.version(_app(), tmp_path / "lab")

    assert found.behind_unknown and found.behind == 0
