"""Starting Lab Hub at login.

A LaunchAgent rather than a System Events login item, for one reason: a login
item cannot pass arguments. This app lives in the menu bar, so starting it at
login should leave it *in* the menu bar — throwing a window across the screen
every time you log in is worse than not starting at all. The agent runs
`open -a … --args --background`, which the app reads to skip showing its window.
That background start also ensures the backup and repository-sync companions
are running. Lab Hub then watches for sleep/resume and repeats the same quiet
check after every wake.

Writing the plist is enough; it takes effect at the next login. The agent is
deliberately not bootstrapped into the running session — that would launch a
second copy immediately, which the single-instance guard would only turn away.

Same shape as the lab's other agents (`com.netrunner3000.git-autosync`), so
`launchctl list` and System Settings › Login Items show them together.
"""

from __future__ import annotations

import plistlib
import sys
from pathlib import Path

from . import APP_NAME, BUNDLE_ID

LABEL = f"{BUNDLE_ID}.login"
AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
PLIST_PATH = AGENTS_DIR / f"{LABEL}.plist"

# Read back in `ui.main_window.run`.
BACKGROUND_FLAG = "--background"

INSTALLED_BUNDLE = Path("/Applications") / f"{APP_NAME}.app"


class LoginItemError(RuntimeError):
    """Raised when the agent cannot be written or has nothing to point at."""


def bundle() -> Path | None:
    """The .app an agent should launch, or None if there is nothing installed.

    Prefers the bundle this process is running from, so a copy started from
    somewhere other than /Applications registers itself rather than a different
    build. Running from source there is no bundle at all — the installed one is
    the only sensible target, and if that is missing the feature is unavailable.
    """
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve()
        for parent in executable.parents:
            if parent.suffix == ".app":
                return parent
    return INSTALLED_BUNDLE if INSTALLED_BUNDLE.is_dir() else None


def is_enabled() -> bool:
    return PLIST_PATH.is_file()


def target() -> Path | None:
    """The bundle the installed agent actually launches.

    Read from the plist rather than recomputed: an agent written before the app
    moved would otherwise be reported as pointing somewhere it does not.
    """
    if not is_enabled():
        return None
    try:
        with PLIST_PATH.open("rb") as handle:
            arguments = plistlib.load(handle).get("ProgramArguments", [])
    except (OSError, plistlib.InvalidFileException):
        return None
    for argument in arguments:
        if str(argument).endswith(".app"):
            return Path(argument)
    return None


def enable() -> Path:
    """Write the agent. Returns the bundle it will launch."""
    app = bundle()
    if app is None:
        raise LoginItemError(
            f"{APP_NAME} is not installed in /Applications, so there is no app "
            "for a login agent to start. Run ./build_app.sh --install first."
        )

    agent = {
        "Label": LABEL,
        "ProgramArguments": [
            "/usr/bin/open",
            "-a",
            str(app),
            "--args",
            BACKGROUND_FLAG,
        ],
        "RunAtLoad": True,
    }

    try:
        AGENTS_DIR.mkdir(parents=True, exist_ok=True)
        with PLIST_PATH.open("wb") as handle:
            plistlib.dump(agent, handle)
    except OSError as error:
        raise LoginItemError(f"Could not write {PLIST_PATH}: {error}") from error
    return app


def disable() -> None:
    try:
        PLIST_PATH.unlink(missing_ok=True)
    except OSError as error:
        raise LoginItemError(f"Could not remove {PLIST_PATH}: {error}") from error
