"""Which apps Lab Hub knows about: `ExternalApp` and the groups they sit in.

The list itself is data, in `lab_hub/apps.toml`, not code. It used to be a
tuple in `launcher.py`, which meant a new app reached the installed Lab Hub
only on its next rebuild. Now it is read at startup and again whenever the
window's Refresh asks (`reload`), so adding an app is an edit and a Cmd+R.

Where it is read from (`candidates`):

* from source, the package's own `apps.toml` — which is the checkout's;
* frozen, the checkout's copy first (`<lab folder>/lab_hub/lab_hub/apps.toml`),
  then the copy bundled at build time. The checkout is the one that gets
  edited, so it wins whenever it is there and parses — the same reasoning as
  `state.source_dir` trusting a bundle's own record over a name baked in here.

A file that does not parse never empties the hub: `reload` keeps the last good
list and says what was wrong in `last_error`.

A second, local source sits behind it (spec `apps-discovery`, ADR 0007): the
projects the owner chose to add from the Apps page live in
`<Application Support>/Lab Hub/apps-local.toml`, never in the tracked
`apps.toml`. It is read after that file on every `reload`, may list only
`[[suites]]`, and `apps.toml` wins any clash. A local file that cannot be read
keeps the last good local part and is reported in `local_note`, **not** in
`last_error`: `main.py --selftest` fails on `last_error`, and a failed self-test
rolls an update back, so a typo in the owner's own file must not be able to.
"""

from __future__ import annotations

import os
import posixpath
import re
import stat
import sys
import tomllib
import unicodedata
from dataclasses import dataclass, fields, replace
from pathlib import Path

REGISTRY_NAME = "apps.toml"
# Lab Hub's own checkout, relative to the lab folder: <lab>/lab_hub/lab_hub/.
CHECKOUT_REGISTRY = Path("lab_hub") / "lab_hub" / REGISTRY_NAME
# The package's copy: the checkout's file from source, and the bundled one
# frozen (build_app.sh adds it under lab_hub/, which is where __file__ points).
PACKAGE_REGISTRY = Path(__file__).resolve().parents[1] / REGISTRY_NAME
# The owner's own additions, beside the rest of Lab Hub's state (`local_path`).
LOCAL_NAME = "apps-local.toml"
LOCAL_MAX_BYTES = 256 * 1024
# Keys and projects no registry file may define: Lab Hub's own tile is built in
# code (`self_update.OWN_TILE`), so it can be neither hidden nor edited. A test
# keeps this in step with `self_update.SELF`.
RESERVED = frozenset({"lab_hub"})
# What a key may be, and what discovery may name a folder: no space, quote or
# control character can reach a TOML line or a path.
KEY_OK = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


class RegistryError(ValueError):
    """Raised when the app list cannot be read or is not well formed."""


@dataclass(frozen=True)
class ExternalApp:
    key: str
    name: str  # display name (and bundle name unless `bundle` is set)
    project: str  # folder path under the lab root
    # Entry script, relative to the project folder. None is a project with no
    # launch command (Kaila today): it gets a tile with its version and repo
    # state and no Launch button, no menu bar entry and no build row.
    entry: str | None
    summary: str
    # What this app's windowless background copy is called, for apps that have
    # one. SONAR's launchd agent keeps settling hours with no window open, and
    # that is the point of it — worth reporting, but never as "the app is
    # open", which is the question the Launch button answers.
    service: str | None = None
    # A web app: its checkout runs a local server and the browser is its
    # window. Provisio is one. "Running" then means the address answers, and
    # the button opens it rather than raising anything.
    url: str | None = None
    # What runs `entry` for a source launch, and with which arguments. A web
    # app's server is a node script, not a python one.
    runtime: str = "python"
    args: tuple[str, ...] = ()
    # Where inside the checkout a built bundle is looked for when none is
    # installed in /Applications — for an app whose builder stops at its own
    # `dist/` and has no installer, like SYNDUSTRYX's.
    bundle_dir: str | None = None
    # Whether the checkout itself is the app. SYNDUSTRYX's `server.py` is its
    # engine without the window, on the port the Lab Project Monitor already
    # holds, so only its built bundle is ever launched.
    runs_from_source: bool = True
    # For a project with none of the build scripts Lab Hub knows: the command
    # that builds it (run in the checkout), and the bundle it writes, relative
    # to the checkout. Update now runs the build, moves the installed bundle
    # to the Trash and copies the new one into /Applications. SYNDUSTRYX's
    # `build_desktop.py` writes `dist/SYNDUSTRYX.app` and installs nothing.
    build: str | None = None
    build_output: str | None = None
    # The `/Applications/<bundle>.app` name when it differs from the display
    # name: SYNDUSTRYX shows "SynCorp Inc." and installs `SynCorp.app`.
    bundle: str | None = None
    # Older installed bundle names still found (never built or installed), so
    # a rename does not lose the copy in /Applications before the next build.
    legacy_bundles: tuple[str, ...] = ()
    # Update's safety gate (spec update-preflight-gate): a command run in the
    # checkout after the build and before the installed bundle is replaced.
    # `{installed}` is the bundle now in /Applications (the new name, else a
    # legacy one) and `{candidate}` the built one, each shell-quoted. A nonzero
    # exit stops Update with its output and installs nothing. With no bundle
    # installed (a first install) it is skipped.
    preflight: str | None = None
    # Refuse to build and install while the checkout has uncommitted changes.
    require_clean: bool = False
    # Read from the owner's local file (`LOCAL_NAME`), never from a TOML key:
    # `parse(local=True)` sets it. Its name came from a README, so it never
    # selects an installed `/Applications/<name>.app` (`state.bundle_path`): a
    # clone of SONAR keeps the title "SONAR" and must run its own source, not
    # open the installed SONAR.
    local: bool = False

    @property
    def bundle_name(self) -> str:
        return self.bundle or self.name

    @property
    def served(self) -> bool:
        return self.url is not None

    @property
    def launchable(self) -> bool:
        return self.entry is not None


# The groups, in the order the file lists them and the window shows them.
GROUPS = ("suites", "backup_sync", "utilities", "tools_only")

_REQUIRED = ("key", "name", "project", "summary")
# `local` is set by the reader, not by a file.
_FIELDS = {f.name: f for f in fields(ExternalApp) if f.name != "local"}
# Fields that only mean something for an app Lab Hub can start or build.
_NEEDS_ENTRY = ("url", "service", "args", "bundle_dir", "build", "build_output", "bundle", "legacy_bundles",
                "preflight", "require_clean")


@dataclass(frozen=True)
class Registry:
    """One reading of the app list."""

    suites: tuple[ExternalApp, ...] = ()
    backup_sync: tuple[ExternalApp, ...] = ()
    utilities: tuple[ExternalApp, ...] = ()
    # Launched from their own card at the end of the Tools tab and nowhere
    # else: no Apps tile and no menu bar entry (the user's call, 2026-09-27).
    tools_only: tuple[ExternalApp, ...] = ()
    source: Path | None = None  # where it was read from; not part of equality

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Registry):
            return NotImplemented
        return self.groups() == other.groups()

    def __hash__(self) -> int:
        return hash(self.groups())

    def groups(self) -> tuple[tuple[ExternalApp, ...], ...]:
        return tuple(getattr(self, name) for name in GROUPS)

    # Every launchable app. There is no nesting any more, so these are simply
    # the groups in order, minus the apps with no launch command. The menu bar
    # reads `menu_bar_apps`; the self-test, the build report and Settings read
    # `apps`, which also covers the Tools-only apps. `suites` (and `SUITES`,
    # `primary_apps`) stay unfiltered: the Apps page shows a no-launch tile.
    @property
    def primary_apps(self) -> tuple[ExternalApp, ...]:
        return self.suites

    @property
    def menu_bar_apps(self) -> tuple[ExternalApp, ...]:
        return tuple(
            app for app in self.suites + self.backup_sync + self.utilities
            if app.launchable
        )

    @property
    def launchpad(self) -> tuple[ExternalApp, ...]:
        return self.menu_bar_apps

    @property
    def apps(self) -> tuple[ExternalApp, ...]:
        return self.launchpad + tuple(app for app in self.tools_only if app.launchable)


def _app(group: str, index: int, raw: object) -> ExternalApp:
    where = f"{group}[{index}]"
    if not isinstance(raw, dict):
        raise RegistryError(f"{where} is not a table")
    unknown = sorted(set(raw) - set(_FIELDS))
    if unknown:
        raise RegistryError(f"{where} has unknown field(s): {', '.join(unknown)}")
    missing = [name for name in _REQUIRED if not raw.get(name)]
    if missing:
        raise RegistryError(f"{where} is missing: {', '.join(missing)}")
    if "entry" in raw and not raw["entry"]:
        raise RegistryError(f"{where}.entry is empty (leave it out for a project with no launch command)")
    if "entry" not in raw:
        extra = [name for name in _NEEDS_ENTRY if name in raw]
        if raw.get("runs_from_source") is False:
            extra.append("runs_from_source = false")
        if extra:
            raise RegistryError(
                f"{where} has no entry, so it cannot set {', '.join(extra)}"
            )
    values = dict(raw)
    for name, value in values.items():
        if name == "args":
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                raise RegistryError(f"{where}.args must be a list of strings")
            values[name] = tuple(value)
        elif name == "legacy_bundles":
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                raise RegistryError(f"{where}.legacy_bundles must be a list of strings")
            values[name] = tuple(value)
        elif name in ("runs_from_source", "require_clean"):
            if not isinstance(value, bool):
                raise RegistryError(f"{where}.{name} must be true or false")
        elif not isinstance(value, str):
            raise RegistryError(f"{where}.{name} must be a string")
    values.setdefault("entry", None)
    _check_text(where, values)
    return ExternalApp(**values)


def _check_text(where: str, values: dict) -> None:
    """The fields that become a path, a bundle name or a message-box line.

    `name` is joined into `/Applications/<name>.app` and shown in boxes that
    render rich text; `project` and `entry` are joined onto the lab folder when
    an app is launched. Both files go through this.
    """
    if not KEY_OK.fullmatch(values["key"]):
        raise RegistryError(
            f"{where}.key must be letters, digits, '.', '_' or '-' (up to 64)"
        )
    names = [("name", values["name"])]
    if "bundle" in values:
        names.append(("bundle", values["bundle"]))
    names += [("legacy_bundles", value) for value in values.get("legacy_bundles", ())]
    for field, name in names:
        if not name or any(c in name for c in "/\\<>&") or any(unicodedata.category(c) == "Cc" for c in name):
            raise RegistryError(
                f"{where}.{field} must not be empty or hold / \\ < > & or a control character"
            )
    for field in ("project", "entry"):
        path = values[field]
        if path is None:
            continue
        if any(unicodedata.category(c) == "Cc" for c in path):
            # A NUL would make `os.path.realpath` raise in the scan, and the
            # file is the owner's to mistype: it must never get past here.
            raise RegistryError(f"{where}.{field} must not hold a control character")
        if path.startswith("/") or ".." in path.replace("\\", "/").split("/"):
            raise RegistryError(
                f"{where}.{field} must be a relative path with no '..': {path!r}"
            )
    if posixpath.normpath(values["project"]) == ".":
        raise RegistryError(f"{where}.project must be a folder, not the lab folder itself")


def parse(text: str, source: Path | None = None, *, local: bool = False) -> Registry:
    """Build a registry from the TOML text of an app list.

    `local` is the owner's own file (`LOCAL_NAME`): only `[[suites]]` is
    allowed, because it is the Apps page and nothing else (the tray, Backup and
    Tools code then never meets an entry with no launch command), and it may
    list no apps at all.
    """
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise RegistryError(f"not valid TOML: {error}") from error
    except RecursionError as error:  # a value nested thousands deep
        raise RegistryError("not valid TOML: nested too deeply") from error
    allowed = ("suites",) if local else GROUPS
    unknown = sorted(set(data) - set(allowed))
    if unknown:
        raise RegistryError(
            f"unknown group(s): {', '.join(unknown)} (expected {', '.join(allowed)})"
        )
    groups: dict[str, tuple[ExternalApp, ...]] = {}
    seen: set[str] = set()
    for group in allowed:
        raw = data.get(group, [])
        if not isinstance(raw, list):
            raise RegistryError(f"{group} must be an array of tables ([[{group}]])")
        apps = tuple(_app(group, index, item) for index, item in enumerate(raw))
        if local:
            apps = tuple(replace(app, local=True) for app in apps)
        for app in apps:
            if app.key in seen:
                raise RegistryError(f"the key '{app.key}' is used twice")
            seen.add(app.key)
        groups[group] = apps
    if not seen and not local:
        raise RegistryError("it lists no apps")
    return Registry(**groups, source=source)


def load(path: Path) -> Registry:
    """Read one app list file."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise RegistryError(f"cannot read {path}: {error}") from error
    try:
        return parse(text, path)
    except RegistryError as error:
        raise RegistryError(f"{path}: {error}") from error


def candidates(lab_root: Path | None = None, frozen: bool | None = None) -> list[Path]:
    """The files to try, best first."""
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    if not frozen:
        return [PACKAGE_REGISTRY]
    if lab_root is None:
        from lab_hub import config

        lab_root = config.load().resolved_lab_root()
    return [lab_root / CHECKOUT_REGISTRY, PACKAGE_REGISTRY]


def local_path() -> Path:
    """The owner's added projects, read at call time: tests move `SUPPORT_DIR`."""
    from lab_hub import config

    return config.SUPPORT_DIR / LOCAL_NAME


def _clash_key(path: str) -> str:
    # APFS is case-insensitive, so `KAILA` and `./Kaila` are the same folder.
    return posixpath.normpath(path).casefold()


def _overlap(a: str, b: str) -> bool:
    """Equal, or one lies inside the other."""
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


def merge_local(
    base: Registry, local: tuple[ExternalApp, ...]
) -> tuple[Registry, tuple[str, ...]]:
    """`base` with the local entries after its suites, and why any were dropped.

    Pure: no filesystem. `apps.toml` always wins, so an entry is dropped, with a
    note naming it, when its key is Lab Hub's own tile or is taken, or when its
    project is, holds or lies inside one already listed. Kept entries go after
    the hand-written suites, launchable ones first (no-launch tiles come last).
    """
    keys = {app.key for app in base.suites + base.backup_sync
            + base.utilities + base.tools_only} | set(RESERVED)
    projects = [_clash_key(app.project) for app in base.suites + base.backup_sync
                + base.utilities + base.tools_only]
    projects += [_clash_key(name) for name in RESERVED]
    kept: list[ExternalApp] = []
    notes: list[str] = []
    for app in local:
        if app.key in RESERVED:
            notes.append(f"{app.key} is Lab Hub's own tile and cannot be added.")
            continue
        if app.key in keys:
            notes.append(f"{app.key} is already in apps.toml: the apps.toml entry is used.")
            continue
        mine = _clash_key(app.project)
        if any(_overlap(mine, other) for other in projects):
            notes.append(
                f"{app.key} is already in apps.toml (project {app.project}): "
                "the apps.toml entry is used."
            )
            continue
        kept.append(app)
        keys.add(app.key)
    kept.sort(key=lambda app: not app.launchable)  # stable: file order otherwise
    merged = Registry(
        suites=base.suites + tuple(kept), backup_sync=base.backup_sync,
        utilities=base.utilities, tools_only=base.tools_only, source=base.source,
    )
    return merged, tuple(notes)


def _read_local() -> tuple[tuple[ExternalApp, ...] | None, str | None]:
    """(entries, None) for the local file; ((), None) when it is absent, which
    is not broken; (None, why) when it cannot be read or does not parse."""
    path = local_path()
    # Opened as `discovery._snapshot` opens it: a link, a pipe or a device is a
    # bad file, never followed and never waited on (a FIFO's open blocks, and
    # this runs on the GUI thread at startup and on every Refresh).
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return (), None
    except OSError as error:
        return None, f"cannot read {path}: {error.strerror or error}"
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None, f"{path} is not a regular file"
        chunks: list[bytes] = []
        wanted = LOCAL_MAX_BYTES + 1
        while wanted > 0:
            chunk = os.read(fd, wanted)
            if not chunk:
                break
            chunks.append(chunk)
            wanted -= len(chunk)
        raw = b"".join(chunks)
    except OSError as error:
        return None, f"cannot read {path}: {error.strerror or error}"
    finally:
        os.close(fd)
    if len(raw) > LOCAL_MAX_BYTES:
        return None, f"{path} is over {LOCAL_MAX_BYTES // 1024} KiB"
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None, f"{path} is not UTF-8 text"
    try:
        return parse(text, path, local=True).suites, None
    except RegistryError as error:
        return None, f"{path}: {error}"


_current: Registry | None = None
last_error: str | None = None
# The local source, kept apart from `last_error` (see the module docstring).
# `local_ok` is False while the file cannot be read: discovery then suggests
# nothing and refuses to write into a file it cannot parse. `_last_local` is
# the last good local part, which a bad file leaves in force.
local_note: str | None = None
local_ok: bool = True
_last_local: tuple[ExternalApp, ...] = ()


def _with_local(found: Registry) -> Registry:
    """`found` plus the local file, setting `local_note`, `local_ok`."""
    global local_note, local_ok, _last_local
    entries, why = _read_local()
    notes: list[str] = []
    if entries is None:
        local_ok = False
        notes.append(
            f"Your added projects file was ignored: {(why or '').rstrip('.')}. "
            "The list is as it was."
        )
    else:
        local_ok, _last_local = True, entries
    merged, clashes = merge_local(found, _last_local)
    local_note = " ".join(notes + list(clashes)) or None
    return merged


def _read(lab_root: Path | None) -> Registry | None:
    """The first candidate that parses, noting why any earlier one did not."""
    global last_error
    errors = []
    for path in candidates(lab_root):
        if not path.is_file():
            continue
        try:
            found = load(path)
        except RegistryError as error:
            errors.append(str(error))
            continue
        last_error = "; ".join(errors) or None
        return _with_local(found)
    last_error = "; ".join(errors) or "no app list found"
    return None


def current() -> Registry:
    """The app list in force, read on first use."""
    global _current
    if _current is None:
        found = _read(None)
        if found is None:
            raise RegistryError(last_error or "no app list found")
        _current = found
    return _current


def reload(lab_root: Path | None = None) -> bool:
    """Read the list again. True when the apps changed.

    Keeps the list in force when nothing readable is found, so a half-saved
    edit cannot empty every tab; `last_error` says what went wrong.
    """
    global _current
    previous = _current
    found = _read(lab_root)
    if found is None:
        return False
    _current = found
    return previous is not None and found != previous


def use(registry: Registry | None) -> None:
    """Put a list in force directly — for tests; None re-reads on next use."""
    global _current, local_note, local_ok, _last_local
    _current = registry
    local_note, local_ok, _last_local = None, True, ()


_ALIASES = {
    "SUITES": "suites",
    "BACKUP_SYNC_APPS": "backup_sync",
    "UTILITIES": "utilities",
    "TOOLS_ONLY_APPS": "tools_only",
    "PRIMARY_APPS": "primary_apps",
    "MENU_BAR_APPS": "menu_bar_apps",
    "LAUNCHPAD": "launchpad",
    "APPS": "apps",
}


def __getattr__(name: str):
    # The old constants, answered from the list in force rather than frozen at
    # import, so `launcher.APPS` after a Refresh is the new list.
    if name in _ALIASES:
        return getattr(current(), _ALIASES[name])
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
