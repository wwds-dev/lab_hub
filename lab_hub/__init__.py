"""Lab Hub — one front door for the lab's desktop tools.

Two kinds of thing live behind this app, and the distinction is deliberate:

* Standalone apps (including Unblock Tracker, git_autosync and Backup Control
  Center) are full
  PySide6 applications with their own windows, state and lifecycles. Hosting
  them in-process would mean running three event loops' worth of UI inside one,
  so they are *launched* instead — their installed .app if there is one, the
  source tree otherwise.
* **Tools** (EPUB→PDF, the image utilities) were single-file scripts with their
  configuration hardcoded at the top. They have no UI to preserve, so they are
  reimplemented here as library functions and driven from tabs.
"""

import sys
from pathlib import Path

APP_NAME = "Lab Hub"
BUNDLE_ID = "com.netrunner3000.labhub"


def resource_path(*parts: str) -> Path:
    """Locate a bundled file, running from source or from a frozen .app."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return base.joinpath(*parts)


# Licence texts and notices that must travel with the app (AGPL-3.0 for Lab
# Hub, LGPL-3.0 with the GPL-3.0 it incorporates for Qt). build_app.sh bundles
# them; the self-test and Settings tab find them through resource_path.
LICENCE_FILES = (
    "THIRD_PARTY_NOTICES.md",
    "LICENSE",
    "LICENSES/LGPL-3.0.txt",
    "LICENSES/GPL-3.0.txt",
)


def licence_paths() -> list[Path]:
    """Where each licence file is, running from source or from a frozen .app."""
    return [resource_path(*name.split("/")) for name in LICENCE_FILES]


def asset_path(name: str) -> Path:
    """Locate a bundled asset, running from source or from a frozen .app."""
    return resource_path("assets", name)
