"""Projects in the lab folder that the Apps page does not list yet (spec apps-discovery).

Qt-free. Real temp folders, no mocks of the filesystem. `tests/conftest.py`
patches `discovery.suggestions` to nothing for every other test; this file
puts the real one back.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import tomllib
from datetime import date, timedelta
from pathlib import Path

import pytest

from lab_hub import discovery
from lab_hub.launcher import registry

REAL_SUGGESTIONS = discovery.suggestions  # taken at import, before any fixture patches it
TODAY = date(2026, 11, 21)


@pytest.fixture(autouse=True)
def real_discovery(no_real_discovery, monkeypatch):
    monkeypatch.setattr(discovery, "suggestions", REAL_SUGGESTIONS)
    yield
    registry.use(None)
    registry.last_error = None


@pytest.fixture
def lab(tmp_path):
    root = tmp_path / "lab"
    root.mkdir()
    return root


def make_project(root: Path, name: str, *, git="dir", marker=True, readme=None) -> Path:
    """A folder that passes every detection rule, unless told otherwise."""
    folder = root / name
    folder.mkdir(parents=True)
    if git == "dir":
        (folder / ".git").mkdir()
    elif git == "file":
        (folder / ".git").write_text("gitdir: ../imprint/.git/worktrees/x\n")
    if marker:
        (folder / "docs" / "foundry").mkdir(parents=True)
        (folder / "docs" / "foundry" / "app-context.md").write_text("# App context\n")
    if readme is not None:
        (folder / "README.md").write_text(readme)
    return folder


def real(path: Path) -> str:
    return os.path.realpath(path)


def scan(lab, registered=(), dismissed=None, today=TODAY):
    return discovery.scan(lab, registered, dismissed or {}, today)


def folders(found):
    return [s.folder for s in found]


# --- the rules: a positive control, then one breaker each -------------------
def test_a_folder_that_passes_every_rule_gives_exactly_one_suggestion(lab):
    make_project(lab, "kaila", readme="# Kaila\n\nPersonal AI assistant. More.\n")

    found = scan(lab)

    assert found == (
        discovery.Suggestion("kaila", "Kaila", "Personal AI assistant.", None),
    )


def _outside(tmp_path):
    return make_project(tmp_path / "elsewhere", "kaila")


def _symlink_outside(lab, tmp_path):
    (lab / "kaila").symlink_to(_outside(tmp_path))


def _symlink_inside(lab, tmp_path):
    held = make_project(lab / ".hold", "real")
    (lab / "kaila").symlink_to(held)


def _git_symlink(lab, tmp_path):
    folder = make_project(lab, "kaila", git=None)
    other = tmp_path / "somewhere" / ".git"
    other.mkdir(parents=True)
    (folder / ".git").symlink_to(other)


def _marker_symlink_inside(lab, tmp_path):
    folder = make_project(lab, "kaila", marker=False)
    (folder / "docs" / "foundry").mkdir(parents=True)
    (folder / "elsewhere.md").write_text("# x\n")
    (folder / "docs" / "foundry" / "app-context.md").symlink_to(folder / "elsewhere.md")


def _docs_symlink_outside(lab, tmp_path):
    folder = make_project(lab, "kaila", marker=False)
    far = tmp_path / "far" / "foundry"
    far.mkdir(parents=True)
    (far / "app-context.md").write_text("# x\n")
    (folder / "docs").symlink_to(far.parent)


BREAKERS = {
    "a .git file marks a linked worktree": lambda lab, t: make_project(lab, "kaila", git="file"),
    "no .git": lambda lab, t: make_project(lab, "kaila", git=None),
    "no app-context.md": lambda lab, t: make_project(lab, "kaila", marker=False),
    "hidden folder": lambda lab, t: make_project(lab, ".kaila"),
    "underscore folder": lambda lab, t: make_project(lab, "_kaila"),
    "symlink to outside the lab folder": _symlink_outside,
    "symlink to a project inside the lab folder": _symlink_inside,
    "a space in the name": lambda lab, t: make_project(lab, "my kaila"),
    "a quote in the name": lambda lab, t: make_project(lab, 'ka"ila'),
    "a newline in the name": lambda lab, t: make_project(lab, "ka\nila"),
    "a name over 64 characters": lambda lab, t: make_project(lab, "k" * 65),
    ".git is a symlink to a directory": _git_symlink,
    "app-context.md is a symlink": _marker_symlink_inside,
    "docs is a symlink out of the folder": _docs_symlink_outside,
    "a plain file, not a folder": lambda lab, t: (lab / "kaila").write_text("x"),
}


@pytest.mark.parametrize("breaker", BREAKERS)
def test_each_rule_alone_keeps_a_folder_from_being_suggested(lab, tmp_path, breaker):
    BREAKERS[breaker](lab, tmp_path)

    assert scan(lab) == ()


@pytest.mark.parametrize("name", [".kaila", "_kaila"])
def test_the_prefix_rule_holds_even_if_the_name_pattern_were_looser(lab, monkeypatch, name):
    """The name pattern also refuses a leading dot or underscore, so on its own
    it would hide a missing prefix rule from the table above."""
    import re

    monkeypatch.setattr(discovery, "NAME_OK", re.compile(r"[A-Za-z0-9._-]+"))
    make_project(lab, name)

    assert scan(lab) == ()


def test_a_registered_project_is_not_suggested_in_any_spelling(lab):
    make_project(lab, "kaila")
    here = real(lab / "kaila")

    assert scan(lab, [here]) == ()
    assert scan(lab, [here.upper()]) == (), "APFS is case-insensitive"
    assert scan(lab, [here + "/"]) == ()


def test_a_folder_holding_a_registered_project_is_not_suggested(lab):
    make_project(lab, "kaila")

    assert scan(lab, [real(lab / "kaila" / "sub")]) == ()
    assert folders(scan(lab, [real(lab / "kailax")])) == ["kaila"], "a sibling prefix is not inside it"


@pytest.mark.parametrize("name", ["lab_hub", "Lab_Hub"])
def test_lab_hub_itself_is_never_suggested(lab, name):
    make_project(lab, name)

    assert scan(lab) == ()


def test_a_never_answer_hides_a_folder_for_good(lab):
    make_project(lab, "kaila")
    answer = {"kaila": discovery.Dismissal("never", TODAY - timedelta(days=400))}

    assert scan(lab, dismissed=answer) == ()


def test_not_now_hides_for_13_days_and_asks_again_on_the_14th(lab):
    make_project(lab, "kaila")
    answered = discovery.Dismissal("not_now", TODAY)

    assert scan(lab, dismissed={"kaila": answered}, today=TODAY) == ()
    assert scan(lab, dismissed={"kaila": answered}, today=TODAY + timedelta(days=13)) == ()
    assert folders(scan(lab, dismissed={"kaila": answered},
                        today=TODAY + timedelta(days=14))) == ["kaila"]


def test_a_not_now_dated_in_the_future_is_expired_not_a_silent_hide(lab):
    make_project(lab, "kaila")
    future = discovery.Dismissal("not_now", TODAY + timedelta(days=30))

    assert folders(scan(lab, dismissed={"kaila": future})) == ["kaila"]


def test_a_dismissal_for_another_folder_changes_nothing(lab):
    make_project(lab, "kaila")

    assert folders(scan(lab, dismissed={"overseer": discovery.Dismissal("never", TODAY)})) == ["kaila"]


def test_worktrees_and_nested_repos_are_never_scanned(lab):
    make_project(lab / ".claude" / "worktrees", "kaila")
    make_project(lab / "kaila" / ".claude" / "worktrees", "x")
    outer = lab / "outer"
    outer.mkdir()
    make_project(outer, "inner")  # outer itself is no project

    assert scan(lab) == ()


def test_two_scans_in_a_row_give_the_same_answer(lab):
    make_project(lab, "kaila")
    make_project(lab, "overseer")

    assert scan(lab) == scan(lab)
    assert folders(scan(lab)) == ["kaila", "overseer"]


def test_suggestions_come_in_name_order(lab):
    for name in ("zed", "Alpha", "mid"):
        make_project(lab, name)

    assert folders(scan(lab)) == ["Alpha", "mid", "zed"]


def test_a_huge_folder_is_cut_off_at_the_entry_cap(lab):
    for number in range(discovery.SCAN_MAX_ENTRIES + 100):
        make_project(lab, f"p{number:04d}")

    assert len(scan(lab)) == discovery.SCAN_MAX_ENTRIES


def test_a_missing_or_unreadable_lab_folder_gives_nothing_and_no_error(tmp_path):
    assert scan(tmp_path / "no-such-folder") == ()
    (tmp_path / "file").write_text("x")
    assert scan(tmp_path / "file") == ()


def test_a_project_with_a_main_py_gets_it_as_its_entry(lab):
    make_project(lab, "kaila")
    (lab / "kaila" / "main.py").write_text("pass\n")
    make_project(lab, "linked")
    (lab / "linked" / "real.py").write_text("pass\n")
    (lab / "linked" / "main.py").symlink_to(lab / "linked" / "real.py")

    found = {s.folder: s.entry for s in scan(lab)}

    assert found == {"kaila": "main.py", "linked": None}


# --- suggestions(): the scan against the list in force -----------------------
def _in_force(*apps):
    registry.use(registry.Registry(suites=apps))


def _app(key, project=None):
    return registry.ExternalApp(key, key.title(), project or key, "main.py", "s")


@pytest.mark.parametrize("project", ["kaila", "./kaila", "KAILA", "kaila/", "kaila/sub"])
def test_suggestions_skip_whatever_any_group_registers(lab, project):
    make_project(lab, "kaila")
    make_project(lab, "overseer")
    registry.use(registry.Registry(utilities=(_app("k", project),)))

    assert folders(discovery.suggestions(lab, TODAY)) == ["overseer"]


def test_a_nested_registered_project_hides_the_folder_that_holds_it(lab):
    make_project(lab, "toolbox")
    registry.use(registry.Registry(utilities=(_app("ub", "toolbox/unblock_tracker"),)))

    assert discovery.suggestions(lab, TODAY) == ()


def test_suggestions_ask_nothing_while_the_local_file_is_unreadable(lab):
    make_project(lab, "kaila")
    registry.use(registry.Registry(suites=(_app("a"),)))
    assert folders(discovery.suggestions(lab, TODAY)) == ["kaila"]

    registry.local_ok = False

    assert discovery.suggestions(lab, TODAY) == ()


def test_suggestions_use_the_patchable_clock_by_default(lab, monkeypatch):
    make_project(lab, "kaila")
    registry.use(registry.Registry(suites=(_app("a"),)))
    discovery.dismiss("kaila", "not_now", TODAY)

    monkeypatch.setattr(discovery, "today", lambda: TODAY + timedelta(days=13))
    assert discovery.suggestions(lab) == ()
    monkeypatch.setattr(discovery, "today", lambda: TODAY + timedelta(days=14))
    assert folders(discovery.suggestions(lab)) == ["kaila"]


def test_a_dismissal_stored_on_disk_is_what_hides_a_folder(lab):
    make_project(lab, "kaila")
    registry.use(registry.Registry(suites=(_app("a"),)))

    discovery.dismiss("kaila", "never", TODAY)

    assert discovery.suggestions(lab, TODAY + timedelta(days=999)) == ()
    discovery.forget("kaila")
    assert folders(discovery.suggestions(lab, TODAY)) == ["kaila"]


def test_a_project_name_the_os_cannot_take_gives_no_suggestions_not_an_error(lab):
    """The registry refuses a NUL (`test_registry.py`), so this is the second
    line: a list put in force directly must not make the page's scan raise."""
    make_project(lab, "kaila")
    registry.use(registry.Registry(suites=(_app("a", "a\x00b"),)))

    assert discovery.suggestions(lab, TODAY) == ()


def test_with_no_app_list_at_all_there_is_nothing_to_suggest(lab, monkeypatch):
    make_project(lab, "kaila")
    monkeypatch.setattr(registry, "candidates", lambda lab_root=None: [])
    registry.use(None)

    assert discovery.suggestions(lab, TODAY) == ()


# --- no program is run -------------------------------------------------------
def test_the_scan_makes_no_subprocess_call(lab, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("discovery must not start a program")

    for owner, name in ((subprocess, "run"), (subprocess, "Popen"),
                        (subprocess, "check_output"), (subprocess, "call"),
                        (os, "system"), (os, "popen")):
        monkeypatch.setattr(owner, name, refuse)
    make_project(lab, "kaila", readme="# Kaila\n\nA thing.\n")
    registry.use(registry.Registry(suites=(_app("a"),)))

    assert folders(discovery.scan(lab, [], {}, TODAY)) == ["kaila"]
    assert folders(discovery.suggestions(lab, TODAY)) == ["kaila"]
    assert discovery.describe(lab / "kaila") == ("Kaila", "A thing.")
    discovery.hidden(lab, TODAY)


def test_the_module_imports_no_subprocess_at_all():
    tree = ast.parse(Path(discovery.__file__).read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])

    assert "subprocess" not in imported
    assert "pty" not in imported


# --- README text -------------------------------------------------------------
def readme(tmp_path, text: bytes | str, folder="proj") -> Path:
    project = tmp_path / folder
    project.mkdir(exist_ok=True)
    data = text.encode() if isinstance(text, str) else text
    (project / "README.md").write_bytes(data)
    return project


FALLBACK = discovery.FALLBACK_SUMMARY


def test_a_heading_and_its_first_sentence(tmp_path):
    project = readme(tmp_path, "# Shopfront HQ\n\nShopfront HQ is a tool. It does more.\n")

    assert discovery.describe(project) == ("Shopfront HQ", "Shopfront HQ is a tool.")


def test_no_readme_gives_the_folder_name_and_the_fallback_line(tmp_path):
    project = tmp_path / "overseer"
    project.mkdir()

    assert discovery.describe(project) == ("overseer", FALLBACK)
    assert FALLBACK == "A project in your lab folder."


def test_a_hash_inside_a_code_fence_is_not_the_title(tmp_path):
    project = readme(tmp_path, "```sh\n# not a title\n```\n\n# Real\n\nThe text.\n")

    assert discovery.describe(project)[0] == "Real"
    # and the fenced line is not the summary either
    assert discovery.describe(project)[1] == "The text."


def test_a_fenced_block_is_never_the_summary(tmp_path):
    project = readme(tmp_path, "# T\n\n```\nrm -rf everything\n```\n\nPlain words.\n")

    assert discovery.describe(project) == ("T", "Plain words.")


@pytest.mark.parametrize(
    "title",
    ["<script>alert(1)</script>", "a/b", "a\\b", "a & b", ".hidden", "x" * 61, "<b>bold</b>"],
)
def test_a_heading_that_is_not_a_plain_short_name_falls_back_to_the_folder(tmp_path, title):
    project = readme(tmp_path, f"# {title}\n\nText here.\n", folder="folder")

    assert discovery.describe(project) == ("folder", "Text here.")


def test_a_sixty_character_name_is_the_longest_taken(tmp_path):
    project = readme(tmp_path, f"# {'x' * 60}\n\nText.\n")

    assert discovery.describe(project)[0] == "x" * 60


def test_only_a_level_one_heading_names_the_project(tmp_path):
    project = readme(tmp_path, "## Sub\n\nText.\n", folder="folder")

    assert discovery.describe(project) == ("folder", "Text.")


def test_badges_html_tables_and_rules_are_skipped_to_the_first_real_paragraph(tmp_path):
    project = readme(tmp_path, (
        "# Name\n\n![badge](x.svg)\n[![b](y.svg)](z)\n\n<p align=center>logo</p>\n\n"
        "| a | b |\n|---|---|\n\n---\n\nReal text here. More.\n"
    ))

    assert discovery.describe(project) == ("Name", "Real text here.")


def test_a_readme_with_nothing_usable_gives_the_fallback(tmp_path):
    project = readme(tmp_path, "# Name\n\n![b](x)\n\n<div>x</div>\n")

    assert discovery.describe(project) == ("Name", FALLBACK)


def test_a_paragraph_is_its_wrapped_lines_cut_at_the_first_sentence(tmp_path):
    project = readme(tmp_path, "# T\n\nFirst line of it\nruns on. Second sentence.\n\nNext.\n")

    assert discovery.describe(project)[1] == "First line of it runs on."


@pytest.mark.parametrize("text, expected", [
    ("Is it? Yes.", "Is it?"),
    ("Wow! Then more.", "Wow!"),
    ("No stop at all", "No stop at all"),
    ("Version 2.5 is out", "Version 2.5 is out"),
])
def test_the_first_sentence_ends_at_a_stop_mark_followed_by_a_space(tmp_path, text, expected):
    project = readme(tmp_path, f"# T\n\n{text}\n")

    assert discovery.describe(project)[1] == expected


def test_a_long_sentence_is_cut_on_a_word_boundary_with_an_ellipsis(tmp_path):
    words = " ".join(f"word{n}" for n in range(200))
    project = readme(tmp_path, f"# T\n\n{words}\n")

    summary = discovery.describe(project)[1]

    assert len(summary) <= discovery.SUMMARY_MAX == 220
    assert summary.endswith("…")
    assert words.startswith(summary[:-1])
    assert words[len(summary) - 1] == " ", "cut between words, not inside one"


def test_a_five_megabyte_readme_is_read_to_the_cap_and_no_further(tmp_path, monkeypatch):
    project = readme(tmp_path, "# Big\n\n" + "word " * 1_000_000)
    wanted, got = [], []
    real_read = os.read

    def spy(fd, count):
        wanted.append(count)
        data = real_read(fd, count)
        got.append(len(data))
        return data

    monkeypatch.setattr(os, "read", spy)

    name, summary = discovery.describe(project)

    assert name == "Big" and summary.endswith("…") and len(summary) <= 220
    assert wanted and max(wanted) <= discovery.README_MAX_BYTES == 8192
    assert sum(got) <= 8192, "the total, not only each call: a loop to EOF would read 5 MB"


def test_invalid_utf8_is_replaced_not_raised(tmp_path):
    project = readme(tmp_path, b"# Ka\xffila\n\nText \xfe here.\n")

    name, summary = discovery.describe(project)

    assert name.startswith("Ka") and summary.startswith("Text")


def test_a_byte_order_mark_and_windows_line_endings_are_ignored(tmp_path):
    project = readme(tmp_path, b"\xef\xbb\xbf# Name\r\n\r\nLine one\r\ncontinues.\r\n")

    assert discovery.describe(project) == ("Name", "Line one continues.")


def test_control_bidi_zero_width_and_private_use_characters_are_dropped(tmp_path):
    project = readme(tmp_path, "# Ka\0ila‮\n\nEvil ‮text​ here\x07.\n")

    name, summary = discovery.describe(project)

    assert name == "Kaila" and summary == "Evil text here."
    for text in (name, summary):
        assert not any(c in text for c in "\0‮​\x07")


def test_surrogate_and_unassigned_code_points_are_dropped_too(tmp_path):
    # Cs cannot survive a UTF-8 decode, so `_clean` is tried directly; Cn (U+0378
    # is unassigned) comes through a real file.
    assert discovery._clean("a\ud800b\udfffc") == "abc"
    project = readme(tmp_path, "# Ka\u0378ila\n\nText\u0378 here.\n")

    assert discovery.describe(project) == ("Kaila", "Text here.")


def test_whitespace_runs_collapse_and_a_tab_is_a_space(tmp_path):
    project = readme(tmp_path, "# T\n\nOne\t\ttwo   three   four.\n")

    assert discovery.describe(project)[1] == "One two three four."


def test_a_fifo_or_symlink_readme_returns_instead_of_hanging(tmp_path):
    fifo = tmp_path / "fifo"
    fifo.mkdir()
    os.mkfifo(fifo / "README.md")
    target = tmp_path / "secret.txt"
    target.write_text("# Leaked\n\nSecret.\n")
    linked = tmp_path / "linked"
    linked.mkdir()
    (linked / "README.md").symlink_to(target)
    adir = tmp_path / "adir"
    (adir / "README.md").mkdir(parents=True)

    assert discovery.describe(fifo) == ("fifo", FALLBACK)
    assert discovery.describe(linked) == ("linked", FALLBACK)
    assert discovery.describe(adir) == ("adir", FALLBACK)


def _lstat_says_regular(monkeypatch, path: Path, like: Path) -> None:
    """The swap-after-`lstat` case: the check sees an ordinary file, the open
    then meets whatever was put in its place."""
    real, regular = os.lstat, os.lstat(like)

    def lstat(target, *args, **kwargs):
        return regular if os.fspath(target) == os.fspath(path) else real(target, *args, **kwargs)

    monkeypatch.setattr(os, "lstat", lstat)


def _swapped_in(tmp_path, make) -> tuple[Path, Path]:
    project = tmp_path / "swapped"
    project.mkdir()
    make(project / "README.md")
    plain = tmp_path / "plain.txt"
    plain.write_text("x")
    return project, plain


def test_a_readme_that_is_not_a_regular_file_is_never_opened(tmp_path, monkeypatch):
    project, _ = _swapped_in(tmp_path, os.mkfifo)
    opened = []
    real_open = os.open
    monkeypatch.setattr(os, "open", lambda *a, **k: opened.append(a) or real_open(*a, **k))

    assert discovery.describe(project) == ("swapped", FALLBACK)
    assert opened == [], "the lstat check comes before the open"


def test_a_link_swapped_in_after_the_lstat_check_is_still_not_followed(tmp_path, monkeypatch):
    target = tmp_path / "secret.txt"
    target.write_text("# Leaked\n\nSecret.\n")
    project, plain = _swapped_in(tmp_path, lambda path: path.symlink_to(target))
    _lstat_says_regular(monkeypatch, project / "README.md", plain)

    assert discovery.describe(project) == ("swapped", FALLBACK), "O_NOFOLLOW"


def test_a_pipe_swapped_in_after_the_lstat_check_does_not_hang_the_scan(tmp_path, monkeypatch):
    import threading

    project, plain = _swapped_in(tmp_path, os.mkfifo)
    fifo = project / "README.md"
    _lstat_says_regular(monkeypatch, fifo, plain)
    result = []
    worker = threading.Thread(target=lambda: result.append(discovery.describe(project)), daemon=True)

    worker.start()
    worker.join(3)
    hung = worker.is_alive()
    if hung:  # let the blocked open through so the thread does not outlive the test
        os.close(os.open(fifo, os.O_RDWR))
        worker.join(3)

    assert not hung, "O_NONBLOCK: opening a pipe nobody writes to must not wait"
    assert result == [("swapped", FALLBACK)]


def test_a_pipe_with_text_in_it_is_not_read_even_if_lstat_called_it_regular(tmp_path, monkeypatch):
    project, plain = _swapped_in(tmp_path, os.mkfifo)
    fifo = project / "README.md"
    _lstat_says_regular(monkeypatch, fifo, plain)
    writer = os.open(fifo, os.O_RDWR | os.O_NONBLOCK)
    try:
        os.write(writer, b"# Evil\n\nBad text.\n")

        assert discovery.describe(project) == ("swapped", FALLBACK), "the fstat check"
    finally:
        os.close(writer)


def test_an_empty_readme_gives_the_fallback(tmp_path):
    assert discovery.describe(readme(tmp_path, b"")) == ("proj", FALLBACK)


# --- the TOML writer ---------------------------------------------------------
HOSTILE = [
    'x"]]\n[[suites]]\nkey = "evil"',
    '"""',
    '"""\n[[suites]]\nkey="evil"\nname="E"\nproject="e"\nsummary="s"\n"""',
    "\\",
    "\\\"\\\\\"",
    "line separator here",
    "nul\x00byte",
    "bell\x07 del\x7f esc\x1b",
    "tab\there\r\nwindows",
    "emoji \U0001F600 and é and 中文",
    "'single' and 'quotes'",
    "# not a comment",
    "key = \"value\"",
    "",
    "plain",
]


def _one_entry(summary_literal: str) -> str:
    return ('[[suites]]\nkey = "k"\nname = "N"\nproject = "k"\n'
            f"summary = {summary_literal}\n")


@pytest.mark.parametrize("value", HOSTILE)
def test_a_hostile_string_round_trips_to_exactly_one_table_with_exact_values(value):
    data = tomllib.loads(_one_entry(discovery.toml_string(value)))

    assert data == {"suites": [{"key": "k", "name": "N", "project": "k", "summary": value}]}


def _entry_text_reads_back_exactly(value: str) -> bool:
    """The module's own path: `render_entry`, read back by `tomllib`."""
    text = discovery.render_entry(discovery.Suggestion("k", "N", value, None))
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return False
    return data == {"suites": [{"key": "k", "name": "N", "project": "k", "summary": value}]}


def test_the_hostile_table_would_catch_a_naive_writer(monkeypatch):
    """Mutation check, kept as a test and run through the module: the real
    `toml_string` passes every row, and with `f'"{v}"'` swapped in for it at
    least 8 rows stop reading back as written."""
    assert all(_entry_text_reads_back_exactly(value) for value in HOSTILE)

    monkeypatch.setattr(discovery, "toml_string", lambda value: f'"{value}"')

    assert sum(not _entry_text_reads_back_exactly(value) for value in HOSTILE) >= 8


def test_toml_string_escapes_every_control_character_and_nothing_raw_survives():
    out = discovery.toml_string("".join(chr(n) for n in range(0x20)) + "\x7f")

    assert "\n" not in out and "\r" not in out and "\x00" not in out
    assert out.startswith('"\\u0000') and out.endswith('\\u007f"')


@pytest.mark.parametrize("bad", ["\ud800", "ok\udfff", "x\udc00y"])
def test_a_lone_surrogate_raises(bad):
    with pytest.raises(discovery.DiscoveryError, match="surrogate"):
        discovery.toml_string(bad)


def test_render_entry_has_a_comment_the_table_and_one_line_per_field(monkeypatch):
    monkeypatch.setattr(discovery, "today", lambda: TODAY)

    text = discovery.render_entry(discovery.Suggestion("kaila", "Kaila", "A tool.", "main.py"))

    assert text == (
        "\n# Added by Lab Hub on 2026-11-21.\n[[suites]]\n"
        'key = "kaila"\nname = "Kaila"\nproject = "kaila"\nentry = "main.py"\nsummary = "A tool."\n'
    )
    assert "entry" not in discovery.render_entry(
        discovery.Suggestion("kaila", "Kaila", "A tool.", None))


# --- add(): the local file ---------------------------------------------------
KAILA = discovery.Suggestion("kaila", "Kaila", "Personal AI assistant.", None)
APPS_TOML = ('[[suites]]\nkey = "a"\nname = "A"\nproject = "a"\nentry = "main.py"\n'
             'summary = "s"\n')


@pytest.fixture
def listing(tmp_path, monkeypatch):
    path = tmp_path / "apps.toml"
    path.write_text(APPS_TOML)
    monkeypatch.setattr(registry, "candidates", lambda lab_root=None: [path])
    registry.use(None)
    registry.current()
    return path


def local_file() -> Path:
    return registry.local_path()


def test_add_writes_the_local_file_and_a_reload_shows_the_tile(listing):
    discovery.add(KAILA)

    assert registry.reload() is True
    tile = next(a for a in registry.current().suites if a.key == "kaila")
    assert tile.entry is None and tile.summary == "Personal AI assistant."
    assert [a.key for a in registry.current().suites] == ["a", "kaila"]
    assert registry.local_ok and registry.local_note is None
    assert [a.key for a in registry.current().apps] == ["a"], "no Launch, so not in apps"


def test_an_added_project_with_a_main_py_is_launchable(listing):
    discovery.add(discovery.Suggestion("tool", "Tool", "Does things.", "main.py"))
    registry.reload()

    tool = next(a for a in registry.current().suites if a.key == "tool")
    assert tool.launchable and tool.entry == "main.py"


def test_a_readme_title_cannot_make_a_tile_control_an_installed_app(listing, lab, tmp_path, monkeypatch):
    """A cloned SONAR keeps the README title "SONAR"; a hostile one says "Safari".
    The tile's name decides which `/Applications/<name>.app` it opens, so an
    added entry never matches a bundle by name (it runs its own source)."""
    from lab_hub import launcher

    applications = tmp_path / "Applications"
    (applications / "Safari.app").mkdir(parents=True)
    monkeypatch.setattr(launcher, "APPLICATIONS", applications)
    make_project(lab, "p6", readme="# Safari\n\nA fake browser. More.\n")
    (lab / "p6" / "main.py").write_text("print('hi')\n")
    found = discovery.scan(lab, (), {}, TODAY)
    assert (found[0].name, found[0].entry) == ("Safari", "main.py")

    discovery.add(found[0])
    registry.reload()
    tile = next(a for a in registry.current().suites if a.key == "p6")

    assert tile.local and tile.launchable
    assert launcher.bundle_path(tile, lab) is None
    assert launcher.can_bring_to_front(tile, lab) is False
    assert launcher.status(tile, lab)[0] == "source"
    # The same name from apps.toml is the installed app, as before.
    shipped = registry.ExternalApp("p6", "Safari", "p6", "main.py", "s")
    assert launcher.bundle_path(shipped, lab) == applications / "Safari.app"


def test_add_keeps_what_the_owner_already_wrote_in_the_file(listing):
    local_file().parent.mkdir(parents=True, exist_ok=True)
    mine = '# my own note\n[[suites]]\nkey = "mine"\nname = "Mine"\nproject = "mine"\nsummary = "m"'
    local_file().write_text(mine)  # no trailing newline, on purpose

    discovery.add(KAILA)

    text = local_file().read_text()
    assert text.startswith(mine + "\n")
    assert "# my own note" in text and "# Added by Lab Hub on" in text
    registry.reload()
    assert [a.key for a in registry.current().suites] == ["a", "mine", "kaila"]


def test_add_is_idempotent(listing):
    discovery.add(KAILA)
    once = local_file().read_bytes()

    discovery.add(KAILA)

    assert local_file().read_bytes() == once


def test_the_file_is_private_and_no_temp_file_is_left(listing):
    discovery.add(KAILA)

    assert local_file().stat().st_mode & 0o777 == 0o600
    assert [p.name for p in local_file().parent.iterdir()] == ["apps-local.toml"]


def test_a_hostile_readme_cannot_add_a_field_a_group_or_a_second_entry(listing):
    for index, value in enumerate(HOSTILE):
        hostile = discovery.Suggestion(f"p{index}", "P", value or "x", None)
        discovery.add(hostile)

    data = tomllib.loads(local_file().read_text())
    assert list(data) == ["suites"]
    assert len(data["suites"]) == len(HOSTILE)
    for index, entry in enumerate(data["suites"]):
        assert set(entry) == {"key", "name", "project", "summary"}
        assert entry["key"] == f"p{index}"
        assert entry["summary"] == (HOSTILE[index] or "x")
    registry.reload()
    assert registry.local_ok and registry.local_note is None
    assert [a.key for a in registry.current().suites] == ["a"] + [f"p{i}" for i in range(len(HOSTILE))]


@pytest.mark.parametrize("bad", [
    discovery.Suggestion("kaila", "A/B", "s", None),
    discovery.Suggestion("kaila", "A<b>", "s", None),
    discovery.Suggestion("ka ila", "Kaila", "s", None),
    discovery.Suggestion("kaila", "Kaila", "", None),
    discovery.Suggestion("kaila", "Kaila", "bad \ud800", None),
    discovery.Suggestion("a", "Dup", "same key as apps.toml", None),
])
def test_an_entry_the_registry_would_refuse_is_never_written(listing, bad):
    with pytest.raises(discovery.DiscoveryError):
        discovery.add(bad)

    assert not local_file().exists()


def test_add_checks_what_it_would_write_even_if_the_writer_were_broken(listing, monkeypatch):
    """The second layer (spec 13.3, verify before writing). With a naive writer
    this README makes two valid entries, so the registry's own rules accept the
    last one; only the comparison with the fields meant refuses it."""
    monkeypatch.setattr(discovery, "toml_string", lambda value: f'"{value}"')
    hostile = discovery.Suggestion(
        "p1", "P1", 'x"\n[[suites]]\nkey = "evil"\nname = "E"\nproject = "e"\nsummary = "z', None)

    with pytest.raises(discovery.DiscoveryError, match="did not read back"):
        discovery.add(hostile)

    assert not local_file().exists()


def test_add_refuses_a_file_that_would_outgrow_what_the_registry_reads(listing, monkeypatch):
    discovery.add(KAILA)
    before = local_file().read_bytes()
    monkeypatch.setattr(registry, "LOCAL_MAX_BYTES", len(before) + 20)
    registry.reload()
    assert registry.local_ok, "the file as it is still fits"

    with pytest.raises(discovery.DiscoveryError, match="too big"):
        discovery.add(discovery.Suggestion("overseer", "Overseer", "Another project.", None))

    assert local_file().read_bytes() == before


def test_add_refuses_a_local_file_it_cannot_parse_and_leaves_its_bytes(listing):
    local_file().parent.mkdir(parents=True, exist_ok=True)
    local_file().write_bytes(b"half saved [[ \xff")
    registry.reload()
    assert registry.local_ok is False

    with pytest.raises(discovery.DiscoveryError, match="cannot be read"):
        discovery.add(KAILA)

    assert local_file().read_bytes() == b"half saved [[ \xff"


def test_add_refuses_a_file_that_broke_since_the_last_reload(listing):
    local_file().parent.mkdir(parents=True, exist_ok=True)
    local_file().write_text("half saved [[")  # registry still thinks local_ok

    with pytest.raises(discovery.DiscoveryError, match="does not parse"):
        discovery.add(KAILA)
    assert local_file().read_text() == "half saved [["

    local_file().write_text('[[suites]]\nkey = "x"\n')  # valid TOML, not a valid entry
    with pytest.raises(discovery.DiscoveryError, match="does not parse"):
        discovery.add(KAILA)
    assert local_file().read_text() == '[[suites]]\nkey = "x"\n'


def test_add_refuses_a_local_file_that_is_a_link(listing, tmp_path):
    local_file().parent.mkdir(parents=True, exist_ok=True)
    elsewhere = tmp_path / "elsewhere.toml"
    elsewhere.write_text("")
    local_file().symlink_to(elsewhere)

    with pytest.raises(discovery.DiscoveryError):
        discovery.add(KAILA)

    assert elsewhere.read_text() == ""


def test_a_failed_replace_leaves_the_original_and_no_temp_file(listing, monkeypatch):
    discovery.add(discovery.Suggestion("first", "First", "s", None))
    before = local_file().read_bytes()

    def fail(src, dst):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(discovery.DiscoveryError, match="No space left"):
        discovery.add(KAILA)

    assert local_file().read_bytes() == before
    assert [p.name for p in local_file().parent.iterdir()] == ["apps-local.toml"]


def test_a_change_made_while_writing_aborts_the_write(listing, monkeypatch):
    discovery.add(discovery.Suggestion("first", "First", "s", None))
    real_fsync = os.fsync

    def edit_then_sync(fd):
        with local_file().open("a") as handle:  # the owner saves the file by hand
            handle.write("# edited by hand\n")
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", edit_then_sync)
    with pytest.raises(discovery.DiscoveryError, match="changed while Lab Hub was writing"):
        discovery.add(KAILA)

    assert local_file().read_text().endswith("# edited by hand\n")
    assert "kaila" not in local_file().read_text()
    assert [p.name for p in local_file().parent.iterdir()] == ["apps-local.toml"]


def test_a_file_that_appears_while_writing_is_not_overwritten(listing, monkeypatch):
    real_fsync = os.fsync

    def create_then_sync(fd):
        local_file().write_text("# made by hand\n")
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", create_then_sync)
    with pytest.raises(discovery.DiscoveryError, match="changed while"):
        discovery.add(KAILA)

    assert local_file().read_text() == "# made by hand\n"


def test_a_planted_link_at_the_temp_name_is_not_followed(listing, tmp_path):
    """The temp file is created with O_EXCL, so a link put at its name cannot
    send the write somewhere else."""
    victim = tmp_path / "victim.txt"
    local_file().parent.mkdir(parents=True, exist_ok=True)
    (local_file().parent / f"apps-local.toml.{os.getpid()}.tmp").symlink_to(victim)

    with pytest.raises(discovery.DiscoveryError):
        discovery.add(KAILA)
    (local_file().parent / f"apps-dismissed.json.{os.getpid()}.tmp").symlink_to(victim)
    with pytest.raises(discovery.DiscoveryError):
        discovery.dismiss("kaila", "never", TODAY)

    assert not victim.exists()
    assert not local_file().exists()


def test_add_clears_a_leftover_dismissal_for_that_folder(listing):
    discovery.dismiss("kaila", "not_now", TODAY - timedelta(days=30))

    discovery.add(KAILA)

    assert "kaila" not in discovery.load_dismissed()


def test_an_unwritable_support_folder_is_a_discovery_error_not_a_crash(listing, monkeypatch):
    real_open = os.open

    def refuse(path, flags, *args, **kwargs):
        if str(path).endswith(".tmp"):
            raise PermissionError(13, "Permission denied")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", refuse)
    with pytest.raises(discovery.DiscoveryError, match="Permission denied"):
        discovery.add(KAILA)
    with pytest.raises(discovery.DiscoveryError, match="Permission denied"):
        discovery.dismiss("kaila", "never", TODAY)


# --- dismissals --------------------------------------------------------------
def dismissed_file() -> Path:
    return discovery.dismissed_path()


def write_dismissed(data) -> None:
    dismissed_file().parent.mkdir(parents=True, exist_ok=True)
    dismissed_file().write_bytes(data if isinstance(data, bytes) else json.dumps(data).encode())


def test_the_files_live_in_the_support_folder(isolated_config):
    assert discovery.dismissed_path() == isolated_config / "apps-dismissed.json"


def test_dismissals_round_trip_and_both_answers_are_kept(isolated_config):
    discovery.dismiss("kaila", "never", date(2026, 11, 1))
    discovery.dismiss("overseer", "not_now", TODAY)

    assert discovery.load_dismissed() == {
        "kaila": discovery.Dismissal("never", date(2026, 11, 1)),
        "overseer": discovery.Dismissal("not_now", TODAY),
    }
    assert json.loads(dismissed_file().read_text()) == {
        "kaila": {"answer": "never", "at": "2026-11-01"},
        "overseer": {"answer": "not_now", "at": "2026-11-21"},
    }


def test_dismiss_uses_the_patchable_clock_by_default(isolated_config, monkeypatch):
    monkeypatch.setattr(discovery, "today", lambda: date(2026, 12, 25))

    discovery.dismiss("kaila", "not_now")

    assert discovery.load_dismissed()["kaila"].at == date(2026, 12, 25)


def test_dismissing_the_same_folder_again_replaces_its_answer(isolated_config):
    discovery.dismiss("kaila", "not_now", TODAY)
    discovery.dismiss("kaila", "never", TODAY)

    assert discovery.load_dismissed() == {"kaila": discovery.Dismissal("never", TODAY)}


def test_not_an_answer_is_refused(isolated_config):
    with pytest.raises(discovery.DiscoveryError, match="not an answer"):
        discovery.dismiss("kaila", "maybe", TODAY)

    assert not dismissed_file().exists()


@pytest.mark.parametrize("junk", [
    b"{not json", b"[1, 2]", b'"text"', b"\xff\xfe", b"null", b"123",
])
def test_a_corrupt_or_wrong_shaped_file_reads_as_nothing_dismissed(isolated_config, junk):
    write_dismissed(junk)

    assert discovery.load_dismissed() == {}


def test_an_empty_or_missing_file_reads_as_nothing_dismissed(isolated_config):
    assert discovery.load_dismissed() == {}
    write_dismissed(b"")
    assert discovery.load_dismissed() == {}


def test_an_oversized_file_reads_as_nothing_dismissed(isolated_config):
    body = {"kaila": {"answer": "never", "at": "2026-11-21"}, "pad": "x" * 70_000}
    write_dismissed(body)

    assert discovery.load_dismissed() == {}


def test_an_entry_with_an_unknown_answer_or_a_bad_shape_is_ignored(isolated_config):
    write_dismissed({
        "good": {"answer": "never", "at": "2026-11-21"},
        "weird": {"answer": "forever", "at": "2026-11-21"},
        "shape": ["never"],
        "bare": "never",
    })

    assert list(discovery.load_dismissed()) == ["good"]


def test_an_unparsable_date_on_not_now_counts_as_expired(isolated_config, lab):
    make_project(lab, "kaila")
    write_dismissed({"kaila": {"answer": "not_now", "at": "yesterday"}})
    registry.use(registry.Registry(suites=(_app("a"),)))

    assert folders(discovery.suggestions(lab, TODAY)) == ["kaila"]


def test_a_corrupt_file_is_kept_as_dot_bad_before_an_answer_overwrites_it(isolated_config):
    write_dismissed(b"{older answers, damaged")

    discovery.dismiss("kaila", "never", TODAY)

    bad = dismissed_file().with_name("apps-dismissed.json.bad")
    assert bad.read_bytes() == b"{older answers, damaged"
    assert discovery.load_dismissed() == {"kaila": discovery.Dismissal("never", TODAY)}


def test_a_second_corruption_does_not_overwrite_the_first_dot_bad(isolated_config):
    write_dismissed(b"{bad1")
    discovery.dismiss("kaila", "never", TODAY)
    write_dismissed(b"{bad2")
    discovery.dismiss("kaila", "never", TODAY)
    write_dismissed(b"{bad3")
    discovery.dismiss("kaila", "never", TODAY)

    name = dismissed_file().name
    kept = {n: dismissed_file().with_name(n).read_bytes()
            for n in (name + ".bad", name + ".bad.1", name + ".bad.2")}
    assert kept == {name + ".bad": b"{bad1", name + ".bad.1": b"{bad2", name + ".bad.2": b"{bad3"}
    assert "kaila" in discovery.load_dismissed()


def test_a_valid_file_is_not_set_aside(isolated_config):
    discovery.dismiss("kaila", "never", TODAY)
    discovery.dismiss("overseer", "never", TODAY)

    assert not dismissed_file().with_name("apps-dismissed.json.bad").exists()


def test_forget_takes_one_answer_back_and_keeps_the_rest(isolated_config):
    discovery.dismiss("kaila", "never", TODAY)
    discovery.dismiss("overseer", "never", TODAY)

    discovery.forget("kaila")

    assert list(discovery.load_dismissed()) == ["overseer"]


def test_forgetting_what_was_never_answered_writes_nothing(isolated_config):
    discovery.forget("kaila")
    assert not dismissed_file().exists()

    write_dismissed(b"{corrupt")
    discovery.forget("kaila")
    assert dismissed_file().read_bytes() == b"{corrupt"
    assert not dismissed_file().with_name("apps-dismissed.json.bad").exists()


def test_a_failed_replace_leaves_the_answers_as_they_were(isolated_config, monkeypatch):
    discovery.dismiss("kaila", "never", TODAY)
    before = dismissed_file().read_bytes()

    def fail(src, dst):
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(discovery.DiscoveryError):
        discovery.dismiss("overseer", "never", TODAY)

    assert dismissed_file().read_bytes() == before
    assert [p.name for p in dismissed_file().parent.iterdir()] == ["apps-dismissed.json"]


def test_a_change_made_while_writing_an_answer_aborts_it(isolated_config, monkeypatch):
    discovery.dismiss("kaila", "never", TODAY)
    real_fsync = os.fsync

    def edit_then_sync(fd):
        write_dismissed({"hand": {"answer": "never", "at": "2026-01-01"}})
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", edit_then_sync)
    with pytest.raises(discovery.DiscoveryError, match="changed while"):
        discovery.dismiss("overseer", "never", TODAY)

    assert list(discovery.load_dismissed()) == ["hand"]


def test_a_link_or_folder_in_the_files_place_is_refused_not_followed(isolated_config, tmp_path):
    elsewhere = tmp_path / "elsewhere.json"
    elsewhere.write_text('{"kaila": {"answer": "never", "at": "2026-11-21"}}')
    dismissed_file().parent.mkdir(parents=True, exist_ok=True)
    dismissed_file().symlink_to(elsewhere)

    assert discovery.load_dismissed() == {}
    with pytest.raises(discovery.DiscoveryError):
        discovery.dismiss("overseer", "never", TODAY)
    assert "overseer" not in elsewhere.read_text()


def test_hidden_lists_live_answers_by_name_with_the_date_a_not_now_ends(isolated_config, lab):
    for name in ("zed", "kaila", "old", "gone", "mid"):
        if name != "gone":
            make_project(lab, name)
    discovery.dismiss("zed", "never", date(2020, 1, 1))
    discovery.dismiss("kaila", "not_now", TODAY - timedelta(days=13))
    discovery.dismiss("old", "not_now", TODAY - timedelta(days=14))  # lapsed: asked again
    discovery.dismiss("gone", "never", TODAY)  # its folder is gone
    discovery.dismiss("mid", "never", TODAY)

    rows = discovery.hidden(lab, TODAY)

    assert [(f, d.answer, until) for f, d, until in rows] == [
        ("kaila", "not_now", TODAY + timedelta(days=1)),
        ("mid", "never", None),
        ("zed", "never", None),
    ]


def test_hidden_survives_a_hostile_folder_name_in_the_file(isolated_config, lab):
    write_dismissed({"nul\u0000byte": {"answer": "never", "at": "2026-11-21"},
                     "../up": {"answer": "never", "at": "2026-11-21"}})

    assert discovery.hidden(lab, TODAY) == []


def test_the_constants_are_the_ones_the_spec_names():
    assert (discovery.NOT_NOW_DAYS, discovery.README_MAX_BYTES, discovery.SUMMARY_MAX,
            discovery.NAME_MAX, discovery.SCAN_MAX_ENTRIES) == (14, 8192, 220, 60, 400)
    assert discovery.NAME_OK.fullmatch("kaila") and not discovery.NAME_OK.fullmatch("a b")
