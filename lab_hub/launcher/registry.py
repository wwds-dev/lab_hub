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
"""

from __future__ import annotations

import sys
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

REGISTRY_NAME = "apps.toml"
# Lab Hub's own checkout, relative to the lab folder: <lab>/lab_hub/lab_hub/.
CHECKOUT_REGISTRY = Path("lab_hub") / "lab_hub" / REGISTRY_NAME
# The package's copy: the checkout's file from source, and the bundled one
# frozen (build_app.sh adds it under lab_hub/, which is where __file__ points).
PACKAGE_REGISTRY = Path(__file__).resolve().parents[1] / REGISTRY_NAME


class RegistryError(ValueError):
    """Raised when the app list cannot be read or is not well formed."""


@dataclass(frozen=True)
class ExternalApp:
    key: str
    name: str  # display name and installed bundle name
    project: str  # folder path under the lab root
    entry: str  # entry script, relative to the project folder
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

    @property
    def served(self) -> bool:
        return self.url is not None


# The groups, in the order the file lists them and the window shows them.
GROUPS = ("suites", "backup_sync", "utilities", "tools_only")

_REQUIRED = ("key", "name", "project", "entry", "summary")
_FIELDS = {f.name: f for f in fields(ExternalApp)}


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
    # the groups in order. The menu bar reads `menu_bar_apps`; the self-test,
    # the build report and Settings read `apps`, which also covers the
    # Tools-only apps.
    @property
    def primary_apps(self) -> tuple[ExternalApp, ...]:
        return self.suites

    @property
    def menu_bar_apps(self) -> tuple[ExternalApp, ...]:
        return self.suites + self.backup_sync + self.utilities

    @property
    def launchpad(self) -> tuple[ExternalApp, ...]:
        return self.menu_bar_apps

    @property
    def apps(self) -> tuple[ExternalApp, ...]:
        return self.launchpad + self.tools_only


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
    values = dict(raw)
    for name, value in values.items():
        if name == "args":
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                raise RegistryError(f"{where}.args must be a list of strings")
            values[name] = tuple(value)
        elif name == "runs_from_source":
            if not isinstance(value, bool):
                raise RegistryError(f"{where}.runs_from_source must be true or false")
        elif not isinstance(value, str):
            raise RegistryError(f"{where}.{name} must be a string")
    return ExternalApp(**values)


def parse(text: str, source: Path | None = None) -> Registry:
    """Build a registry from the TOML text of an app list."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise RegistryError(f"not valid TOML: {error}") from error
    unknown = sorted(set(data) - set(GROUPS))
    if unknown:
        raise RegistryError(
            f"unknown group(s): {', '.join(unknown)} (expected {', '.join(GROUPS)})"
        )
    groups: dict[str, tuple[ExternalApp, ...]] = {}
    seen: set[str] = set()
    for group in GROUPS:
        raw = data.get(group, [])
        if not isinstance(raw, list):
            raise RegistryError(f"{group} must be an array of tables ([[{group}]])")
        apps = tuple(_app(group, index, item) for index, item in enumerate(raw))
        for app in apps:
            if app.key in seen:
                raise RegistryError(f"the key '{app.key}' is used twice")
            seen.add(app.key)
        groups[group] = apps
    if not seen:
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


_current: Registry | None = None
last_error: str | None = None


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
        return found
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
    global _current
    _current = registry


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
