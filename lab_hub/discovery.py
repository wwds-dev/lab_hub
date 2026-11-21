"""Projects in the lab folder that the Apps page does not list yet.

Spec `docs/specs/apps-discovery.md`, ADR 0007. Qt-free, like the rest of this
package, and it never runs a program: a scan is `lstat` and one 8 KiB README
read per project that qualifies, so it is cheap enough for the GUI thread at
startup and on Refresh (it measured under 1 ms on the real lab folder).

What it keeps, both under `config.SUPPORT_DIR`, looked up at call time because
the tests move that folder:

* `apps-dismissed.json`, the owner's "Not now" and "Never" answers;
* `apps-local.toml`, the entries the owner chose to add. Only `add` writes it,
  and `launcher.registry` reads it as a second source behind `apps.toml`.

Folder names and README text are untrusted: a project's README can say
anything. Nothing read from either is ever executed or rendered as markup. Text
goes into a TOML file only through `toml_string`, and the entry that results is
parsed back and compared with what was meant before a byte is written.
"""

from __future__ import annotations

import itertools
import json
import os
import stat
import tomllib
import unicodedata
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from . import config
from .launcher import registry

NOT_NOW_DAYS = 14
README_MAX_BYTES = 8192
SUMMARY_MAX = 220
NAME_MAX = 60
SCAN_MAX_ENTRIES = 400
DISMISSED_MAX_BYTES = 64 * 1024
# What a folder may be called to be suggested: the registry's own key rule, so
# a suggestion can always be written as an entry.
NAME_OK = registry.KEY_OK
DISMISSED_NAME = "apps-dismissed.json"
APP_CONTEXT = Path("docs") / "foundry" / "app-context.md"
FALLBACK_SUMMARY = "A project in your lab folder."
ANSWERS = ("never", "not_now")


class DiscoveryError(Exception):
    """A state file could not be read or written, or an entry could not be checked."""


@dataclass(frozen=True)
class Suggestion:
    folder: str
    name: str
    summary: str
    entry: str | None


@dataclass(frozen=True)
class Dismissal:
    answer: str  # "never" | "not_now"
    at: date


def today() -> date:
    """The one clock. The UI passes it and tests patch it."""
    return date.today()


def _day(given: date | None) -> date:
    # A parameter named `today` shadows the function inside most of this module.
    return given if given is not None else today()


# -- the state files ---------------------------------------------------------
def dismissed_path() -> Path:
    return config.SUPPORT_DIR / DISMISSED_NAME


def _read_capped(fd: int, cap: int) -> bytes:
    """Up to `cap` + 1 bytes, so a caller can tell a file over the cap."""
    chunks: list[bytes] = []
    wanted = cap + 1
    while wanted > 0:
        chunk = os.read(fd, wanted)
        if not chunk:
            break
        chunks.append(chunk)
        wanted -= len(chunk)
    return b"".join(chunks)


def _snapshot(path: Path, cap: int) -> tuple[bytes | None, tuple[int, int, int] | None]:
    """The file's bytes (None when over `cap`) and its identity.

    `(b"", None)` when there is no file. A link, a device or a pipe is refused:
    these files are Lab Hub's own, and following a link out of the support
    folder is how a write would land somewhere else.
    """
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return b"", None
    except OSError as error:
        raise DiscoveryError(f"cannot read {path}: {error.strerror or error}") from error
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise DiscoveryError(f"{path} is not a regular file")
        data = _read_capped(fd, cap)
    except OSError as error:
        raise DiscoveryError(f"cannot read {path}: {error.strerror or error}") from error
    finally:
        os.close(fd)
    identity = (info.st_ino, info.st_size, info.st_mtime_ns)
    return (None if len(data) > cap else data), identity


def _identity(path: Path) -> tuple[int, int, int] | None:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return None
    return (info.st_ino, info.st_size, info.st_mtime_ns)


def _exists(path: Path) -> bool:
    try:
        return _identity(path) is not None
    except (OSError, ValueError):  # ValueError: a NUL in a name from the file
        return False


def _replace_file(path: Path, data: bytes, expected: tuple[int, int, int] | None) -> None:
    """Write `data` over `path` atomically, only if `path` is still as it was read.

    A temp file in the same folder (never an existing one, owner-only), fsync,
    then `os.replace`. A hand edit that lands between the read and the replace
    changes the target's inode, size or time and is caught here; at worst one
    Add is lost and offered again at the next Refresh.
    """
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if _identity(path) != expected:
            raise DiscoveryError(
                f"{path.name} changed while Lab Hub was writing it; try again"
            )
        os.replace(tmp, path)
    except OSError as error:
        raise DiscoveryError(f"cannot write {path}: {error.strerror or error}") from error
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


# -- dismissals ---------------------------------------------------------------
def _parse_dismissed(raw: bytes | None) -> dict[str, Dismissal] | None:
    """The answers in a file's bytes; None when the file is corrupt.

    An entry whose answer is not `never` or `not_now` is ignored. An `at` that
    is not a date becomes `date.min`: for "not now" that reads as long expired,
    so a damaged file can only ever cause an extra question.
    """
    if raw is None:
        return None
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    found: dict[str, Dismissal] = {}
    for folder, item in data.items():
        # A key that is not a folder name `scan` could have suggested (a path
        # such as "../outside") is never looked up on disk or shown: ignored.
        if not isinstance(folder, str) or not NAME_OK.fullmatch(folder):
            continue
        if not isinstance(item, dict) or item.get("answer") not in ANSWERS:
            continue
        try:
            at = date.fromisoformat(str(item.get("at")))
        except ValueError:
            at = date.min
        found[str(folder)] = Dismissal(item["answer"], at)
    return found


def load_dismissed() -> dict[str, Dismissal]:
    """The owner's answers. Missing, unreadable or malformed reads as none."""
    try:
        raw, _ = _snapshot(dismissed_path(), DISMISSED_MAX_BYTES)
    except DiscoveryError:
        return {}
    return _parse_dismissed(raw) or {}


def dismissed_ok() -> bool:
    """False when the answers file is there but cannot be read: damaged, over
    its size cap, or not a regular file. Nothing is hidden then (`load_dismissed`
    reads it as empty), and Settings says so. A missing or empty file is fine."""
    try:
        raw, _ = _snapshot(dismissed_path(), DISMISSED_MAX_BYTES)
    except DiscoveryError:
        return False
    return _parse_dismissed(raw) is not None


def _hides(item: Dismissal, now: date) -> bool:
    if item.answer == "never":
        return True
    # A date in the future is expired too: the file never hides for long.
    return item.at <= now < item.at + timedelta(days=NOT_NOW_DAYS)


def _dump(answers: Mapping[str, Dismissal]) -> bytes:
    body = {
        folder: {"answer": item.answer, "at": item.at.isoformat()}
        for folder, item in sorted(answers.items())
    }
    return (json.dumps(body, indent=2) + "\n").encode("utf-8")


def _free_bad_name(path: Path) -> Path:
    """`<name>.bad`, or `.bad.1`, `.bad.2`, ... when that is taken: a second
    corruption must not overwrite the answers the first one set aside."""
    candidate = path.with_name(path.name + ".bad")
    number = 0
    while _identity(candidate) is not None:
        number += 1
        candidate = path.with_name(f"{path.name}.bad.{number}")
    return candidate


def _update_dismissed(change: Callable[[dict[str, Dismissal]], None]) -> None:
    """Read, apply `change`, write atomically. A corrupt file is kept as
    `<name>.bad` first, so the older answers are not lost to the overwrite."""
    path = dismissed_path()
    raw, expected = _snapshot(path, DISMISSED_MAX_BYTES)
    answers = _parse_dismissed(raw)
    if answers is None:
        try:
            os.replace(path, _free_bad_name(path))
        except OSError as error:
            raise DiscoveryError(
                f"cannot set aside {path}: {error.strerror or error}"
            ) from error
        answers, expected = {}, None
    change(answers)
    _replace_file(path, _dump(answers), expected)


def dismiss(folder: str, answer: str, today: date | None = None) -> None:
    """Remember "Not now" or "Never" for a folder."""
    if answer not in ANSWERS:
        raise DiscoveryError(f"not an answer: {answer!r}")
    day = _day(today)

    def change(answers: dict[str, Dismissal]) -> None:
        answers[folder] = Dismissal(answer, day)

    _update_dismissed(change)


def forget(folder: str) -> None:
    """Take a folder's answer back, so it is suggested again."""
    if folder not in load_dismissed():
        return  # nothing to undo, and a corrupt file is not touched for it

    def change(answers: dict[str, Dismissal]) -> None:
        answers.pop(folder, None)

    _update_dismissed(change)


def hidden(
    lab_root: Path, today: date | None = None
) -> list[tuple[str, Dismissal, date | None]]:
    """What Settings lists: (folder, answer, asked-again-on) by name.

    Only answers still in force, and only for a folder that is still there: a
    lapsed "Not now" is simply asked again, and a deleted folder has nothing to
    show again. The date is None for "never".
    """
    now = _day(today)
    rows = []
    for folder, item in load_dismissed().items():
        if not _hides(item, now):
            continue
        if not _exists(Path(lab_root) / folder):
            continue
        until = None if item.answer == "never" else item.at + timedelta(days=NOT_NOW_DAYS)
        rows.append((folder, item, until))
    rows.sort(key=lambda row: row[0].casefold())
    return rows


# -- README text --------------------------------------------------------------
_DROPPED = frozenset({"Cc", "Cf", "Cs", "Co", "Cn"})


def _clean(line: str) -> str:
    """Whitespace collapsed; control, format (bidi, zero-width), surrogate,
    private-use and unassigned characters dropped."""
    line = line.replace("\t", " ")
    kept = "".join(c for c in line if unicodedata.category(c) not in _DROPPED)
    return " ".join(kept.split())


def _read_readme(project: Path) -> str | None:
    """At most `README_MAX_BYTES` of a regular, non-link README.md, else None."""
    path = project / "README.md"
    try:
        if not stat.S_ISREG(os.lstat(path).st_mode):
            return None
        # O_NONBLOCK: a FIFO swapped in after the check must not hang the scan.
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        data = os.read(fd, README_MAX_BYTES)
    except OSError:
        return None
    finally:
        os.close(fd)
    return data.decode("utf-8", errors="replace").removeprefix("﻿")


def _is_fence(line: str) -> bool:
    return line.startswith(("```", "~~~"))


def _is_rule(line: str) -> bool:
    return len(line) >= 3 and set(line) <= set("-=*_ ")


def _heading(line: str) -> tuple[int, str] | None:
    """(level, text) of an ATX heading line, else None."""
    hashes = len(line) - len(line.lstrip("#"))
    if not 1 <= hashes <= 6 or not line[hashes:hashes + 1] == " ":
        return None
    return hashes, line[hashes:].strip().rstrip("#").strip()


def _first_sentence(text: str) -> str:
    """Cut at the first `. `, `! ` or `? ` ("e.g. " can cut early: accepted),
    then at `SUMMARY_MAX` characters on a word boundary, with an ellipsis."""
    for index in range(len(text) - 1):
        if text[index] in ".!?" and text[index + 1] == " ":
            text = text[:index + 1]
            break
    if len(text) <= SUMMARY_MAX:
        return text
    room = text[:SUMMARY_MAX - 1]
    if " " in room:
        room = room.rsplit(" ", 1)[0]
    return room.rstrip(" ,;:-") + "…"


def _name_ok(text: str) -> bool:
    return (
        1 <= len(text) <= NAME_MAX
        and not any(c in text for c in "/\\<>&")
        and not text.startswith(".")
    )


def describe(project: Path) -> tuple[str, str]:
    """(name, summary) for a project, from its README.md; never raises.

    The name is the first `# ` heading outside a code fence, if it is a plain
    short one; else the folder name. The summary is the first paragraph after
    it that is not a heading, badge, tag line, table row or fence, cut at its
    first sentence and at 220 characters. A README that gives none of this
    (missing, unreadable, only badges) gives the folder name and a fixed line.
    """
    folder = Path(project).name
    text = _read_readme(Path(project))
    if text is None:
        return folder, FALLBACK_SUMMARY

    # (kind, cleaned text, heading level): text, blank, skip or heading.
    lines: list[tuple[str, str, int]] = []
    fenced = False
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = _clean(raw)
        head = _heading(line)
        if _is_fence(line):
            fenced = not fenced
            lines.append(("skip", "", 0))
        elif fenced:
            lines.append(("skip", "", 0))
        elif not line:
            lines.append(("blank", "", 0))
        elif head is not None:
            lines.append(("heading", head[1], head[0]))
        elif line.startswith(("![", "[![", "<", "|")) or _is_rule(line):
            lines.append(("skip", "", 0))
        else:
            lines.append(("text", line, 0))

    name = folder
    start = 0
    for index, (kind, title, level) in enumerate(lines):
        if kind == "heading" and level == 1:
            if _name_ok(title):
                name = title
            start = index + 1
            break

    paragraph: list[str] = []
    summary = ""
    for kind, line, _level in lines[start:]:
        if kind == "text":
            paragraph.append(line)
            continue
        if paragraph:
            break
    if paragraph:
        summary = _first_sentence(" ".join(paragraph))
    return name, summary or FALLBACK_SUMMARY


# -- the scan -----------------------------------------------------------------
def scan(
    lab_root: Path,
    registered: Collection[str],
    dismissed: Mapping[str, Dismissal],
    today: date,
) -> tuple[Suggestion, ...]:
    """The projects directly under `lab_root` that are not registered yet.

    Pure over the folder: `lstat` calls and one README read per project that
    qualifies, no program run, no network. `registered` is real paths. Worktrees
    under `.claude/worktrees` and nested repositories are never reached: only
    direct children are looked at, and at most `SCAN_MAX_ENTRIES` of them.
    Each test below is one line marked `# condition:`.
    """
    root = Path(lab_root)
    taken = {path.casefold().rstrip("/") for path in registered}
    try:
        entries = os.scandir(root)
    except OSError:
        return ()
    found: list[Suggestion] = []
    with entries:
        for entry in itertools.islice(entries, SCAN_MAX_ENTRIES):
            name = entry.name
            try:
                # condition: a real top-level directory, so a link is never suggested
                if not entry.is_dir(follow_symlinks=False):
                    continue
            except OSError:
                continue
            # condition: the name does not start with "." or "_"
            if name.startswith((".", "_")):
                continue
            # condition: the name is plain letters, digits, "." "_" "-"
            if not NAME_OK.fullmatch(name):
                continue
            folder = Path(entry.path)
            try:
                # condition: .git is a directory (a .git file marks a linked worktree)
                if not stat.S_ISDIR(os.lstat(folder / ".git").st_mode):
                    continue
                marker = folder / APP_CONTEXT
                # condition: Foundry's app-context.md is a regular file, not a link
                if not stat.S_ISREG(os.lstat(marker).st_mode):
                    continue
            except OSError:
                continue
            real = os.path.realpath(folder)
            # condition: the app-context.md really lies inside the folder
            if not os.path.realpath(marker).startswith(real + "/"):
                continue
            # condition: not Lab Hub itself (its tile is built in code)
            if name.casefold() in registry.RESERVED:
                continue
            here = real.casefold()
            # condition: not registered (same folder, or a registered project inside it)
            if here in taken or any(other.startswith(here + "/") for other in taken):
                continue
            # condition: not dismissed
            if name in dismissed and _hides(dismissed[name], today):
                continue
            title, summary = describe(folder)
            try:
                runnable = stat.S_ISREG(os.lstat(folder / "main.py").st_mode)
            except OSError:
                runnable = False
            found.append(Suggestion(name, title, summary, "main.py" if runnable else None))
    found.sort(key=lambda item: item.folder.casefold())
    return tuple(found)


def suggestions(lab_root: Path, today: date | None = None) -> tuple[Suggestion, ...]:
    """What to ask the owner about: the scan against the list in force.

    Nothing while the local file cannot be read (Add would have nowhere safe to
    write), and nothing when there is no app list at all.
    """
    if not registry.local_ok:
        return ()
    try:
        current = registry.current()
    except registry.RegistryError:
        return ()
    root = Path(lab_root)
    paths = [app.project for group in current.groups() for app in group]
    paths += sorted(registry.RESERVED)
    try:
        registered = [os.path.realpath(root / path) for path in paths]
    except (OSError, ValueError):  # a name the OS cannot take (the registry refuses NUL)
        return ()
    return scan(root, registered, load_dismissed(), _day(today))


# -- writing an entry ---------------------------------------------------------
def toml_string(value: str) -> str:
    """A TOML basic string for any text, and nothing but that string.

    No TOML writer is installed and `tomllib` only reads. Backslash and quote
    are escaped, and every code point below U+0020 and U+007F is written as
    `\\uXXXX`, so a raw newline, a stray quote or a `\"\"\"` can never appear
    and end the string early. A lone surrogate cannot be written as UTF-8, so
    it raises.
    """
    out = ['"']
    for char in value:
        code = ord(char)
        if 0xD800 <= code <= 0xDFFF:
            raise DiscoveryError("text with a lone surrogate cannot be written")
        if char == "\\":
            out.append("\\\\")
        elif char == '"':
            out.append('\\"')
        elif code < 0x20 or code == 0x7F:
            out.append(f"\\u{code:04x}")
        else:
            out.append(char)
    out.append('"')
    return "".join(out)


def _fields(s: Suggestion) -> dict[str, str]:
    fields = {"key": s.folder, "name": s.name, "project": s.folder}
    if s.entry is not None:
        fields["entry"] = s.entry
    fields["summary"] = s.summary
    return fields


def render_entry(s: Suggestion) -> str:
    """The text `add` appends: a comment, the table header and one line a field."""
    lines = ["", f"# Added by Lab Hub on {today().isoformat()}.", "[[suites]]"]
    lines += [f"{key} = {toml_string(value)}" for key, value in _fields(s).items()]
    return "\n".join(lines) + "\n"


def _local_text(path: Path) -> tuple[str, tuple[int, int, int] | None]:
    raw, identity = _snapshot(path, registry.LOCAL_MAX_BYTES)
    if raw is None:
        raise DiscoveryError(f"{path} is too big to read")
    try:
        return raw.decode("utf-8"), identity
    except UnicodeDecodeError as error:
        raise DiscoveryError(f"{path} is not UTF-8 text") from error


def add(s: Suggestion) -> None:
    """Give a suggestion a tile: append its entry to `apps-local.toml`.

    The file is appended to, so comments and hand edits survive. Before a byte
    is written the new text must parse as TOML with exactly one more `suites`
    table holding exactly the fields meant (a hostile README cannot add a field,
    a group or a second entry), pass the registry's own rules, and survive the
    merge against the list in force. Otherwise nothing is written and the error
    says why. Adding a key that is already there changes nothing.
    """
    if not registry.local_ok:
        raise DiscoveryError(
            "your added projects file cannot be read, so nothing can be added to it"
        )
    path = registry.local_path()
    old_text, expected = _local_text(path)
    try:
        before = tomllib.loads(old_text)
        existing = registry.parse(old_text, path, local=True).suites
    except (tomllib.TOMLDecodeError, RecursionError, registry.RegistryError) as error:
        raise DiscoveryError(f"{path} does not parse: {error}") from error
    if any(app.key == s.folder for app in existing):
        _forget_quietly(s.folder)
        return

    joiner = "" if not old_text or old_text.endswith("\n") else "\n"
    new_text = old_text + joiner + render_entry(s)
    _verify(before, new_text, s, path)
    data = new_text.encode("utf-8")
    if len(data) > registry.LOCAL_MAX_BYTES:
        raise DiscoveryError("your added projects file would be too big to read back")
    _replace_file(path, data, expected)
    _forget_quietly(s.folder)


def _verify(before: dict, new_text: str, s: Suggestion, path: Path) -> None:
    why = f"cannot add {s.folder}: "
    try:
        after = tomllib.loads(new_text)
    except tomllib.TOMLDecodeError as error:
        raise DiscoveryError(why + f"the entry does not parse ({error})") from error
    old_suites = before.get("suites", [])
    expected = dict(before)
    expected["suites"] = [*old_suites, _fields(s)]
    if after != expected:
        raise DiscoveryError(why + "the entry did not read back as written")
    try:
        parsed = registry.parse(new_text, path, local=True)
        mine = parsed.suites[-1]
        merged, _notes = registry.merge_local(registry.current(), (mine,))
    except registry.RegistryError as error:
        raise DiscoveryError(why + str(error)) from error
    if mine not in merged.suites:
        raise DiscoveryError(why + "it clashes with an app that is already listed")


def _forget_quietly(folder: str) -> None:
    # A leftover answer for a folder that is now added is harmless: it is
    # ignored while the tile exists.
    try:
        forget(folder)
    except DiscoveryError:
        pass
