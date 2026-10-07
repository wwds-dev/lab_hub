"""The lab's dashboards, read from the catalog the Lab Project Monitor uses.

`dashboard_catalog.json`, in the lab folder, is the single list: the Monitor's
Dashboards section and this tab both read it, so a dashboard added there shows
up here with no Lab Hub rebuild. Nothing is copied into this app.

A local entry opens through the Monitor's own server when that is up, because
its `/dashboards/<id>` route wraps an HTML fragment (the Antfarm workstation is
one) in a proper page. When the server is down the file opens directly — the
same fallback the Monitor's own page uses.
"""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

CATALOG_NAME = "dashboard_catalog.json"

# The Lab Project Monitor's server, kept up by its LaunchAgent
# (`com.netrunner3000.lab-project-monitor`).
MONITOR_HOST = "127.0.0.1"
MONITOR_PORT = 8765


@dataclass(frozen=True)
class Dashboard:
    id: str
    title: str
    description: str
    source: str  # Claude | ChatGPT
    kind: str  # Live | Plan | Report | Concept | …
    url: str | None = None
    path: str | None = None

    @property
    def local(self) -> bool:
        return self.url is None

    def available(self) -> bool:
        """A link always is; a local file only while it is still on disk."""
        if self.url:
            return True
        return bool(self.path) and Path(self.path).is_file()


def catalog_path(lab_root: Path) -> Path:
    """Where the catalog is: the lab folder, one up from `active/`.

    The configured lab root is the folder of projects, so the catalog sits
    beside it — unless the root was pointed at the lab folder itself.
    """
    for folder in (lab_root.parent, lab_root):
        candidate = folder / CATALOG_NAME
        if candidate.is_file():
            return candidate
    return lab_root.parent / CATALOG_NAME


class CatalogError(RuntimeError):
    """The catalog is missing or unreadable."""


def load(lab_root: Path) -> tuple[Dashboard, ...]:
    """Every catalog entry, in the catalog's own order."""
    path = catalog_path(lab_root)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise CatalogError(f"No dashboard catalog at {path}.") from error
    except (OSError, ValueError) as error:
        raise CatalogError(f"Could not read {path}: {error}") from error
    if not isinstance(raw, list):
        raise CatalogError(f"{path} is not a list of dashboards.")

    found = []
    for entry in raw:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        found.append(
            Dashboard(
                id=str(entry["id"]),
                title=str(entry.get("title") or entry["id"]),
                description=str(entry.get("description") or ""),
                source=str(entry.get("source") or ""),
                kind=str(entry.get("kind") or ""),
                url=entry.get("url") or None,
                path=entry.get("path") or None,
            )
        )
    return tuple(found)


def monitor_serving() -> bool:
    """Whether the Lab Project Monitor's server is listening."""
    try:
        with socket.create_connection((MONITOR_HOST, MONITOR_PORT), timeout=0.2):
            return True
    except OSError:
        return False


def target(dashboard: Dashboard, monitor_up: bool | None = None) -> str:
    """What to hand the browser: the link, the Monitor's route, or the file."""
    if dashboard.url:
        return dashboard.url
    up = monitor_serving() if monitor_up is None else monitor_up
    if up:
        return f"http://{MONITOR_HOST}:{MONITOR_PORT}/dashboards/{quote(dashboard.id)}"
    path = Path(dashboard.path or "")
    return path.as_uri() if path.is_absolute() else str(path)
