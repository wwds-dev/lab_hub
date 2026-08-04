"""Finding and starting the standalone apps.

Each of these is a separate project with its own repo, venv and packaged
bundle. Two ways to start one, tried in order:

1. the installed /Applications bundle — what the user normally has, and the
   only option that works when Lab Hub is itself running as a frozen .app;
2. the source checkout, run with that project's own venv — so the launcher
   still works on a machine where nothing has been packaged yet.

Never `sys.executable`: frozen, that is Lab Hub's own binary, and handing it a
script path runs it inside this app's bundled interpreter with this app's
dependencies.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

APPLICATIONS = Path("/Applications")


class LaunchError(RuntimeError):
    """Raised when an app cannot be found or started."""


@dataclass(frozen=True)
class ExternalApp:
    key: str
    name: str  # display name and installed bundle name
    project: str  # folder name under the lab root
    entry: str  # entry script, relative to the project folder
    summary: str


UNBLOCK_TRACKER = ExternalApp(
    key="unblock_tracker",
    name="Unblock Tracker",
    project="unblock_tracker",
    entry="main.py",
    summary="Watch whether an Instagram profile has unblocked you, and get "
    "notified the moment it changes.",
)

# The launchpad — the apps reached for often enough to earn a front page.
# Unblock Tracker is deliberately not here: it is occasional, so it lives on its
# own tab instead of competing for attention with the two daily tools.
LAUNCHPAD: tuple[ExternalApp, ...] = (
    ExternalApp(
        key="sentinel_ai",
        name="Sentinel AI",
        project="sentinel_ai",
        entry="main.py",
        summary="The multi-agent workspace, with the ebook→audiobook narrator "
        "bundled in.",
    ),
    ExternalApp(
        key="sonar",
        name="SONAR",
        project="sonar",
        entry="main.py",
        summary="Market scanner and paper-trading terminal: live prices, "
        "prediction-market odds and a probability model, traded with paper money.",
    ),
    ExternalApp(
        key="git_autosync",
        name="git_autosync",
        project="git_autosync",
        entry="packaging/entry_point.py",
        summary="Commit and push the lab's repos on a schedule, with per-repo "
        "status and manual sync.",
    ),
    ExternalApp(
        key="backup_manager",
        name="Backup Control Center",
        project="backup_manager",
        entry="main.py",
        summary="Run and monitor the Google Drive rsync backup, and keep an eye "
        "on the other sync engines.",
    ),
)

# Everything launchable, wherever it appears in the UI. Used by the self-test.
APPS: tuple[ExternalApp, ...] = LAUNCHPAD + (UNBLOCK_TRACKER,)


def bundle_path(app: ExternalApp) -> Path | None:
    """The installed .app, if it is there."""
    path = APPLICATIONS / f"{app.name}.app"
    return path if path.is_dir() else None


def source_dir(app: ExternalApp, lab_root: Path) -> Path | None:
    """The project checkout, if it has the entry script we expect."""
    project = lab_root / app.project
    return project if (project / app.entry).is_file() else None


def _venv_python(project: Path) -> Path | None:
    for name in (".venv", "venv"):
        candidate = project / name / "bin" / "python"
        if candidate.is_file():
            return candidate
    return None


def status(app: ExternalApp, lab_root: Path) -> tuple[str, str]:
    """A (state, detail) pair for the UI. State is installed/source/missing."""
    bundle = bundle_path(app)
    if bundle is not None:
        return "installed", str(bundle)
    project = source_dir(app, lab_root)
    if project is not None:
        return "source", str(project)
    return "missing", f"not in /Applications, and no checkout at {lab_root / app.project}"


def launch(app: ExternalApp, lab_root: Path) -> str:
    """Start the app. Returns a line describing what was started."""
    bundle = bundle_path(app)
    if bundle is not None:
        # -n so a second click brings up a new instance rather than silently
        # doing nothing when the app is already open but on another Space.
        result = subprocess.run(
            ["open", "-a", str(bundle)], capture_output=True, text=True
        )
        if result.returncode != 0:
            raise LaunchError(result.stderr.strip() or f"'open' failed for {bundle}")
        return f"Launched {app.name} from {bundle}"

    project = source_dir(app, lab_root)
    if project is None:
        raise LaunchError(
            f"{app.name} is not installed in /Applications, and no source "
            f"checkout was found at {lab_root / app.project}.\n\n"
            "Set the lab folder on the Settings tab if your projects live "
            "somewhere else."
        )

    python = _venv_python(project) or (
        Path(shutil.which("python3")) if shutil.which("python3") else None
    )
    if python is None:
        raise LaunchError(
            f"No interpreter to run {app.name} with: {project} has no .venv and "
            "python3 is not on PATH."
        )

    try:
        # Detached, so quitting Lab Hub does not take the app down with it.
        subprocess.Popen(
            [str(python), app.entry],
            cwd=project,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as error:
        raise LaunchError(f"Could not start {app.name}: {error}") from error

    return f"Launched {app.name} from source ({project}) using {python}"


def reveal(path: Path) -> None:
    """Show a file or folder in Finder."""
    subprocess.run(["open", "-R", str(path)], check=False)
