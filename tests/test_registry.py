"""The app list is data (lab_hub/apps.toml), re-read on Refresh."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lab_hub import launcher
from lab_hub.launcher import registry

ONE_APP = """
[[suites]]
key = "a"
name = "A"
project = "a"
entry = "main.py"
summary = "s"
"""


NO_LAUNCH = """
[[suites]]
key = "kaila"
name = "Kaila"
project = "kaila"
summary = "s"
"""


@pytest.fixture(autouse=True)
def _restore_registry():
    yield
    registry.use(None)
    registry.last_error = None


def test_the_shipped_list_keeps_every_registered_app_as_it_was():
    """Moving the list out of code must not change a single tile."""
    found = registry.load(registry.PACKAGE_REGISTRY)

    assert [a.key for a in found.suites] == [
        "sentinel", "imprint", "sonar", "provisio", "syndustryx", "backstage",
    ]
    assert [a.key for a in found.backup_sync] == ["backup_manager", "git_autosync"]
    assert [a.key for a in found.utilities] == ["unblock_tracker"]
    assert [a.key for a in found.tools_only] == []
    sonar = next(a for a in found.suites if a.key == "sonar")
    assert sonar.service == "Background engine"
    syndustryx = next(a for a in found.suites if a.key == "syndustryx")
    assert syndustryx.bundle_dir is None and syndustryx.runs_from_source is False
    autosync = found.backup_sync[1]
    assert autosync.entry == "packaging/entry_point.py"
    assert found.menu_bar_apps == found.suites + found.backup_sync + found.utilities
    assert found.apps == found.menu_bar_apps + found.tools_only


def test_the_old_constants_read_the_list_in_force():
    registry.use(registry.parse(ONE_APP))

    assert [a.key for a in launcher.SUITES] == ["a"]
    assert [a.key for a in launcher.APPS] == ["a"]
    assert launcher.TOOLS_ONLY_APPS == ()


@pytest.mark.parametrize(
    "text, complaint",
    [
        ("not toml [", "not valid TOML"),
        ("[[suites]]\nkey = 'a'\n", "missing"),
        (ONE_APP + "colour = 'red'\n", "unknown field"),
        (ONE_APP.replace("suites", "nonsense"), "unknown group"),
        (ONE_APP + ONE_APP.replace("[[suites]]", "[[utilities]]"), "used twice"),
        (ONE_APP + "runs_from_source = 'no'\n", "true or false"),
        ("", "lists no apps"),
    ],
)
def test_a_malformed_list_is_refused_with_a_reason(text, complaint):
    with pytest.raises(registry.RegistryError, match=complaint):
        registry.parse(text)


def test_frozen_reads_the_checkout_first_then_the_bundle(tmp_path):
    paths = registry.candidates(tmp_path, frozen=True)

    assert paths == [
        tmp_path / "lab_hub" / "lab_hub" / "apps.toml",
        registry.PACKAGE_REGISTRY,
    ]
    assert registry.candidates(tmp_path, frozen=False) == [registry.PACKAGE_REGISTRY]


def test_reload_picks_up_a_new_app_and_says_so(tmp_path, monkeypatch):
    listing = tmp_path / "apps.toml"
    listing.write_text(ONE_APP)
    monkeypatch.setattr(registry, "candidates", lambda lab_root=None: [listing])
    registry.use(None)
    assert [a.key for a in registry.current().apps] == ["a"]

    assert registry.reload() is False  # nothing changed

    listing.write_text(ONE_APP + ONE_APP.replace('"a"', '"b"').replace('"A"', '"B"'))
    assert registry.reload() is True
    assert [a.key for a in launcher.APPS] == ["a", "b"]


def test_a_broken_edit_keeps_the_last_good_list(tmp_path, monkeypatch):
    listing = tmp_path / "apps.toml"
    listing.write_text(ONE_APP)
    monkeypatch.setattr(registry, "candidates", lambda lab_root=None: [listing])
    registry.use(None)
    registry.current()

    listing.write_text("half saved [[")

    assert registry.reload() is False
    assert [a.key for a in launcher.APPS] == ["a"]
    assert "not valid TOML" in (registry.last_error or "")


def test_a_broken_checkout_copy_falls_back_to_the_next(tmp_path, monkeypatch):
    broken = tmp_path / "broken.toml"
    broken.write_text("nope [[")
    good = tmp_path / "good.toml"
    good.write_text(ONE_APP)
    monkeypatch.setattr(registry, "candidates", lambda lab_root=None: [broken, good])

    registry.use(None)

    assert registry.current().source == good
    assert str(broken) in (registry.last_error or "")


def test_patching_the_facade_reaches_the_part_that_reads_it(tmp_path, monkeypatch):
    """`launcher.X = …` must land where X is read, not on the facade alone."""
    monkeypatch.setattr(launcher, "APPLICATIONS", tmp_path)

    assert launcher.state.APPLICATIONS == Path(tmp_path)


# --- optional `entry`: a project with no launch command (spec apps-discovery) --
def test_an_entry_is_optional_and_its_absence_means_no_launch_command():
    found = registry.parse(NO_LAUNCH + ONE_APP, local=False).suites

    kaila = next(a for a in found if a.key == "kaila")
    assert kaila.entry is None and not kaila.launchable
    assert next(a for a in found if a.key == "a").launchable


def test_every_shipped_entry_is_launchable_and_passes_the_new_field_rules():
    found = registry.load(registry.PACKAGE_REGISTRY)

    assert all(a.launchable for a in found.apps)
    assert len(found.apps) == 9
    assert found.apps == found.suites + found.backup_sync + found.utilities


def test_the_shipped_entries_are_not_local_and_a_file_cannot_say_it_is():
    assert not any(app.local for app in registry.load(registry.PACKAGE_REGISTRY).apps)
    with pytest.raises(registry.RegistryError, match="unknown field"):
        registry.parse(ONE_APP + "local = true\n")
    with pytest.raises(registry.RegistryError, match="unknown field"):
        registry.parse(ONE_APP + "local = true\n", local=True)


def test_only_launchable_apps_are_in_apps_menu_bar_apps_and_launchpad():
    found = registry.parse(ONE_APP + NO_LAUNCH)

    assert [a.key for a in found.suites] == ["a", "kaila"]  # the Apps page shows it
    assert [a.key for a in found.apps] == ["a"]
    assert [a.key for a in found.menu_bar_apps] == ["a"]
    assert [a.key for a in found.launchpad] == ["a"]
    registry.use(found)
    assert [a.key for a in launcher.SUITES] == ["a", "kaila"]
    assert [a.key for a in launcher.APPS] == ["a"]


def test_a_no_launch_entry_in_any_group_stays_out_of_tools_only_apps():
    found = registry.parse(ONE_APP + NO_LAUNCH.replace("suites", "tools_only"))

    assert [a.key for a in found.tools_only] == ["kaila"]
    assert [a.key for a in found.apps] == ["a"]


@pytest.mark.parametrize(
    "extra",
    [
        'url = "http://x"',
        'service = "Engine"',
        'args = ["--x"]',
        'bundle_dir = "dist"',
        'build = "make"',
        'build_output = "dist/K.app"',
        "runs_from_source = false",
    ],
)
def test_an_entry_less_app_cannot_set_what_only_a_launch_command_needs(extra):
    with pytest.raises(registry.RegistryError, match="has no entry, so it cannot set"):
        registry.parse(NO_LAUNCH + extra + "\n")


def test_an_empty_entry_is_refused_rather_than_read_as_no_launch_command():
    with pytest.raises(registry.RegistryError, match="entry is empty"):
        registry.parse(NO_LAUNCH + 'entry = ""\n')


@pytest.mark.parametrize(
    "field, value, complaint",
    [
        ("key", "a b", "key must be"),
        ("key", "-a", "key must be"),
        ("key", "a/b", "key must be"),
        ("key", "x" * 65, "key must be"),
        ("name", "A/B", "name must not"),
        ("name", "A<b>", "name must not"),
        ("name", "A&B", "name must not"),
        ("name", "A\\B", "name must not"),
        ("name", "A\u0007B", "name must not"),
        ("project", "../x", "project must be a relative"),
        ("project", "a/../../x", "project must be a relative"),
        ("project", "/etc", "project must be a relative"),
        ("project", "a\u0000b", "project must not hold a control character"),
        ("project", "a\nb", "project must not hold a control character"),
        ("project", ".", "not the lab folder itself"),
        ("project", "./", "not the lab folder itself"),
        ("project", "a/..", "project must be a relative"),
        ("entry", "m\u0000.py", "entry must not hold a control character"),
        ("entry", "../main.py", "entry must be a relative"),
        ("entry", "/bin/sh", "entry must be a relative"),
    ],
)
def test_the_fields_that_become_paths_and_bundle_names_are_checked(field, value, complaint):
    entry = {"key": "a", "name": "A", "project": "a", "entry": "main.py", "summary": "s"}
    entry[field] = value
    # json.dumps writes a valid TOML basic string for these values.
    text = "[[suites]]\n" + "\n".join(f"{k} = {json.dumps(v)}" for k, v in entry.items())
    with pytest.raises(registry.RegistryError, match=complaint):
        registry.parse(text)


DEEP = "a = " + "[" * 5000 + "]" * 5000 + "\n"  # well under the size cap, deep enough to recurse


def test_a_value_nested_thousands_deep_is_a_bad_file_not_a_crash():
    with pytest.raises(registry.RegistryError, match="nested too deeply"):
        registry.parse(DEEP + ONE_APP)


def test_a_deeply_nested_apps_toml_is_reported_in_last_error(tmp_path, monkeypatch):
    path = tmp_path / "apps.toml"
    path.write_text(ONE_APP)
    monkeypatch.setattr(registry, "candidates", lambda lab_root=None: [path])
    registry.use(None)
    registry.current()

    path.write_text(DEEP + ONE_APP)

    assert registry.reload() is False
    assert [a.key for a in launcher.APPS] == ["a"]
    assert "nested too deeply" in (registry.last_error or "")


def test_a_nested_project_and_entry_path_are_fine():
    found = registry.parse(
        ONE_APP.replace('project = "a"', 'project = "toolbox/a"')
        .replace('entry = "main.py"', 'entry = "packaging/entry_point.py"')
    )

    assert found.suites[0].project == "toolbox/a"


# --- the local file ---------------------------------------------------------
@pytest.fixture
def listing(tmp_path, monkeypatch):
    """apps.toml with one app, and the local file's (absent) place."""
    path = tmp_path / "apps.toml"
    path.write_text(ONE_APP)
    monkeypatch.setattr(registry, "candidates", lambda lab_root=None: [path])
    registry.use(None)
    return path


def _local(text: str) -> Path:
    path = registry.local_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_the_local_path_follows_the_support_folder(isolated_config):
    assert registry.local_path() == isolated_config / "apps-local.toml"
    assert registry.LOCAL_NAME == "apps-local.toml"


def test_local_entries_join_after_the_hand_written_suites_launchable_first(listing):
    _local(NO_LAUNCH + ONE_APP.replace('"a"', '"b"').replace('"A"', '"B"'))

    found = registry.current()

    assert [a.key for a in found.suites] == ["a", "b", "kaila"]
    assert registry.local_note is None and registry.local_ok
    assert [a.key for a in found.apps] == ["a", "b"]


def test_entries_read_from_the_local_file_are_marked_local(listing):
    _local(NO_LAUNCH)

    found = {a.key: a for a in registry.current().suites}

    assert found["kaila"].local is True
    assert found["a"].local is False


def test_an_absent_local_file_is_not_a_broken_one(listing):
    found = registry.current()

    assert [a.key for a in found.suites] == ["a"]
    assert registry.local_ok and registry.local_note is None


def test_deleting_the_local_file_removes_the_added_tiles(listing):
    path = _local(NO_LAUNCH)
    assert [a.key for a in registry.current().suites] == ["a", "kaila"]

    path.unlink()

    assert registry.reload() is True
    assert [a.key for a in registry.current().suites] == ["a"]


def test_a_local_edit_makes_reload_say_the_list_changed(listing):
    registry.current()
    assert registry.reload() is False  # nothing changed

    _local(NO_LAUNCH)

    assert registry.reload() is True
    assert registry.reload() is False


def test_an_entry_the_hand_written_file_has_wins_and_says_so(listing):
    _local(ONE_APP.replace('summary = "s"', 'summary = "local copy"'))

    found = registry.current()

    assert [a.summary for a in found.suites] == ["s"]
    assert "a is already in apps.toml" in registry.local_note
    assert registry.local_ok, "a clash is not a broken file"
    assert registry.last_error is None


@pytest.mark.parametrize(
    "project",
    ["a", "./a", "A", "a/inside", "./A/"],
)
def test_a_local_project_on_a_listed_folder_yields_in_any_spelling(listing, project):
    entry = NO_LAUNCH.replace('project = "kaila"', f'project = "{project}"')
    _local(entry)

    assert [a.key for a in registry.current().suites] == ["a"]
    assert "kaila is already in apps.toml" in registry.local_note


def test_a_local_project_holding_a_listed_one_yields(listing, tmp_path):
    listing.write_text(ONE_APP.replace('project = "a"', 'project = "toolbox/a"'))
    registry.use(None)
    _local(NO_LAUNCH.replace('project = "kaila"', 'project = "toolbox"'))

    assert [a.key for a in registry.current().suites] == ["a"]
    assert "kaila" in registry.local_note


def test_lab_hubs_own_key_and_folder_are_reserved(listing):
    _local(NO_LAUNCH.replace('key = "kaila"', 'key = "lab_hub"')
           + NO_LAUNCH.replace('key = "kaila"', 'key = "mine"').replace('"kaila"', '"Lab_Hub"'))

    found = registry.current()

    assert [a.key for a in found.suites] == ["a"]
    assert "lab_hub is Lab Hub's own tile" in registry.local_note
    assert registry.RESERVED == frozenset({"lab_hub"})


@pytest.mark.parametrize(
    "text",
    [
        "half saved [[",
        NO_LAUNCH + "colour = 'red'\n",
        NO_LAUNCH.replace("suites", "utilities"),
        NO_LAUNCH.replace('project = "kaila"', 'project = "../x"'),
        NO_LAUNCH.replace('key = "kaila"', 'key = "a/b"'),
        NO_LAUNCH.replace('name = "Kaila"', 'name = "Ka<i>la"'),
        NO_LAUNCH + 'url = "http://x"\n',
    ],
)
def test_a_broken_local_file_leaves_the_list_as_it_was_and_says_why(listing, text):
    _local(text)

    found = registry.current()

    assert [a.key for a in found.suites] == ["a"]
    assert registry.local_ok is False
    assert registry.local_note.startswith("Your added projects file was ignored")
    assert registry.local_note.endswith("The list is as it was.")
    assert registry.last_error is None, "last_error fails the self-test, which rolls an update back"


def test_a_broken_local_file_keeps_the_last_good_local_part(listing):
    path = _local(NO_LAUNCH)
    assert [a.key for a in registry.current().suites] == ["a", "kaila"]

    path.write_text("half saved [[")

    assert registry.reload() is False
    assert [a.key for a in registry.current().suites] == ["a", "kaila"]
    assert registry.local_ok is False and registry.local_note

    path.write_text(NO_LAUNCH)
    registry.reload()
    assert registry.local_ok is True and registry.local_note is None


def test_the_last_good_local_part_is_merged_against_the_new_apps_toml(listing):
    path = _local(NO_LAUNCH)
    registry.current()
    path.write_text("half saved [[")
    listing.write_text(ONE_APP + NO_LAUNCH)  # apps.toml now lists kaila itself

    registry.reload()

    assert [a.key for a in registry.current().suites] == ["a", "kaila"]
    assert "kaila is already in apps.toml" in registry.local_note
    assert registry.local_ok is False


def test_a_bad_local_file_at_first_use_does_not_raise(listing):
    _local("half saved [[")

    found = registry.current()

    assert [a.key for a in found.suites] == ["a"]
    assert registry.local_ok is False and registry.local_note


def test_a_deeply_nested_local_file_is_a_note_and_never_stops_the_hub(listing):
    _local(DEEP + NO_LAUNCH)

    found = registry.current()  # must not raise RecursionError

    assert [a.key for a in found.suites] == ["a"]
    assert registry.local_ok is False
    assert "nested too deeply" in registry.local_note
    assert registry.last_error is None


def test_a_local_file_that_is_not_text_or_too_big_is_broken_not_fatal(listing):
    path = _local("")
    path.write_bytes(b"\xff\xfe not utf-8")
    registry.current()
    assert registry.local_ok is False and "UTF-8" in registry.local_note

    path.write_bytes(b"# " + b"x" * registry.LOCAL_MAX_BYTES + b"\n")
    registry.reload()
    assert registry.local_ok is False and "KiB" in registry.local_note


def test_a_local_file_may_list_no_apps(listing):
    _local("# nothing added yet\n")

    assert [a.key for a in registry.current().suites] == ["a"]
    assert registry.local_ok and registry.local_note is None


def test_use_resets_the_local_state_between_tests(listing):
    _local("half saved [[")
    registry.current()
    assert registry.local_ok is False

    registry.use(None)

    assert registry.local_ok is True and registry.local_note is None
    assert registry._last_local == ()


def test_merge_local_is_pure_and_keeps_the_base(tmp_path):
    base = registry.parse(ONE_APP)
    kaila = registry.parse(NO_LAUNCH).suites

    merged, notes = registry.merge_local(base, kaila)

    assert notes == ()
    assert [a.key for a in merged.suites] == ["a", "kaila"]
    assert [a.key for a in base.suites] == ["a"]
    assert merged.source == base.source
    assert merged != base, "equality sees the local entries, so reload notices an edit"


def test_merge_local_keeps_only_the_first_of_two_local_entries_with_one_key():
    base = registry.parse(ONE_APP)
    kaila = registry.parse(NO_LAUNCH).suites[0]
    twin = registry.ExternalApp("kaila", "Twin", "twin", None, "s")  # a hand edit can do this

    merged, notes = registry.merge_local(base, (kaila, twin))

    assert [a.name for a in merged.suites] == ["A", "Kaila"]
    assert len(notes) == 1 and notes[0].startswith("kaila is already in apps.toml")


def test_the_reserved_keys_match_lab_hubs_own_row_and_tile():
    from lab_hub import self_update

    assert {self_update.SELF.key, self_update.SELF.project} <= registry.RESERVED
    assert {self_update.OWN_TILE.key, self_update.OWN_TILE.project} <= registry.RESERVED
