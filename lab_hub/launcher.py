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

And never the inherited environment either — see `child_env`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

APPLICATIONS = Path("/Applications")

# How long to watch a source-launched process before assuming it is healthy.
# A Qt app that is going to abort does so inside QApplication(), well under a
# second; one that survives this long is up.
STARTUP_GRACE_SECONDS = 1.5

# Variables a frozen Lab Hub exports so its own bundled Qt and Python can find
# themselves. A child inherits them and then loads *our* Qt plugins against
# *its* Qt — two incompatible Qt builds in one process, which calls qFatal
# inside QApplication() and aborts before a window ever appears. PyInstaller
# stashes the pre-launch value of these as <VAR>_ORIG; restore that where it
# exists, drop ours otherwise.
INHERITED_VARS = (
    "QT_PLUGIN_PATH",
    "QT_QPA_PLATFORM_PLUGIN_PATH",
    "QT_QPA_PLATFORM",
    "QML2_IMPORT_PATH",
    "QML_IMPORT_PATH",
    "DYLD_LIBRARY_PATH",
    "DYLD_FRAMEWORK_PATH",
    "DYLD_FALLBACK_LIBRARY_PATH",
    "DYLD_FALLBACK_FRAMEWORK_PATH",
    "DYLD_INSERT_LIBRARIES",
    "LD_LIBRARY_PATH",
    "PYTHONHOME",
    "PYTHONPATH",
    "SSL_CERT_FILE",
)


def child_env() -> dict[str, str]:
    """The environment a launched app should see: ours, minus our own runtime."""
    env = dict(os.environ)
    for name in INHERITED_VARS:
        original = env.pop(f"{name}_ORIG", None)
        env.pop(name, None)
        if original:
            env[name] = original
    env.pop("_MEIPASS2", None)
    return env


class LaunchError(RuntimeError):
    """Raised when an app cannot be found or started."""


@dataclass(frozen=True)
class ExternalApp:
    key: str
    name: str  # display name and installed bundle name
    project: str  # folder name under the lab root
    entry: str  # entry script, relative to the project folder
    summary: str


# The launchpad — every app Lab Hub can start, on one front page.
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
    ExternalApp(
        key="vpn_agent",
        name="VPN Agent",
        project="vpn_agent",
        entry="main.py",
        summary="Run a VPN you own end to end: monitor a tunnel with a kill "
        "switch, or build the WireGuard/OpenVPN server at the far end.",
    ),
    ExternalApp(
        key="unblock_tracker",
        name="Unblock Tracker",
        project="unblock_tracker",
        entry="main.py",
        summary="Watch whether an Instagram profile has unblocked you, and get "
        "notified the moment it changes.",
    ),
)

# Everything launchable. One tuple now that Unblock Tracker is a tile like the
# rest; kept as a separate name because the self-test reads it.
APPS: tuple[ExternalApp, ...] = LAUNCHPAD


def bundle_path(app: ExternalApp) -> Path | None:
    """The installed .app, if it is there."""
    path = APPLICATIONS / f"{app.name}.app"
    return path if path.is_dir() else None


def source_dir(app: ExternalApp, lab_root: Path) -> Path | None:
    """The project checkout, if it has the entry script we expect."""
    project = lab_root / app.project
    return project if (project / app.entry).is_file() else None


def venv_python(project: Path) -> Path | None:
    for name in (".venv", "venv"):
        candidate = project / name / "bin" / "python"
        if candidate.is_file():
            return candidate
    return None


def process_table() -> str:
    """One snapshot of every running command line.

    Taken once per refresh and shared across the cards: a `pgrep` per app would
    be four processes spawned every few seconds for a label that rarely changes.
    """
    try:
        return subprocess.run(
            ["ps", "-Axo", "command="], capture_output=True, text=True, timeout=5
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def running_marker(app: ExternalApp, lab_root: Path) -> str | None:
    """The absolute path that appears in the command line of a running copy.

    Installed apps are their bundle executable. Source runs are the entry
    script, which is why `launch` hands the interpreter an absolute path — with
    a relative one every project shows up as a bare `python main.py` and they
    cannot be told apart.
    """
    bundle = bundle_path(app)
    if bundle is not None:
        return str(bundle / "Contents" / "MacOS")
    project = source_dir(app, lab_root)
    if project is not None:
        return str(project / app.entry)
    return None


def is_running(app: ExternalApp, lab_root: Path, table: str | None = None) -> bool:
    marker = running_marker(app, lab_root)
    if marker is None:
        return False
    return marker in (process_table() if table is None else table)


def can_bring_to_front(app: ExternalApp) -> bool:
    """Only an installed bundle can be raised.

    A source run is a bare `python`, with no bundle identifier for `open` to
    address; raising it by pid needs System Events, which is assistive access
    the user would have to grant. Better to say so than to fail quietly.
    """
    return bundle_path(app) is not None


def bring_to_front(app: ExternalApp, lab_root: Path) -> str:
    bundle = bundle_path(app)
    if bundle is None:
        raise LaunchError(
            f"{app.name} is already running, but Lab Hub can only raise apps "
            "installed in /Applications. Switch to it from the Dock or with "
            "⌘-Tab."
        )
    result = subprocess.run(
        ["open", "-a", str(bundle)], capture_output=True, text=True, env=child_env()
    )
    if result.returncode != 0:
        raise LaunchError(result.stderr.strip() or f"'open' failed for {bundle}")
    return f"Brought {app.name} to the front"


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
            ["open", "-a", str(bundle)],
            capture_output=True,
            text=True,
            env=child_env(),
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

    python = venv_python(project) or (
        Path(shutil.which("python3")) if shutil.which("python3") else None
    )
    if python is None:
        raise LaunchError(
            f"No interpreter to run {app.name} with: {project} has no .venv and "
            "python3 is not on PATH."
        )

    # Output goes to a file rather than DEVNULL. A child that dies during
    # startup is the case worth diagnosing, and discarding its stderr is what
    # turns "it crashed and here is why" into "nothing happened".
    log = Path(tempfile.gettempdir()) / f"lab-hub-launch-{app.key}.log"
    try:
        handle = log.open("w")
    except OSError:
        handle = subprocess.DEVNULL

    try:
        # Detached, so quitting Lab Hub does not take the app down with it.
        process = subprocess.Popen(
            # Absolute, not `app.entry`: the command line is how a running copy
            # is recognised later, and every project's relative entry is the
            # same `main.py`.
            [str(python), str(project / app.entry)],
            cwd=project,
            start_new_session=True,
            stdout=handle,
            stderr=subprocess.STDOUT,
            env=child_env(),
        )
    except OSError as error:
        raise LaunchError(f"Could not start {app.name}: {error}") from error
    finally:
        if handle is not subprocess.DEVNULL:
            handle.close()

    # Watch it briefly. A Qt app that is going to fail fails immediately, and
    # reporting that here beats leaving the user to wonder why no window came up.
    deadline = time.monotonic() + STARTUP_GRACE_SECONDS
    while time.monotonic() < deadline:
        code = process.poll()
        if code is None:
            time.sleep(0.05)
            continue
        if code != 0:
            raise LaunchError(
                f"{app.name} started and then exited with status {code}.\n\n"
                f"{_log_tail(log)}"
            )
        break  # exited cleanly and immediately — odd, but not an error

    return f"Launched {app.name} from source ({project}) using {python}"


def _log_tail(log: Path, lines: int = 12) -> str:
    try:
        captured = log.read_text(errors="replace").strip().splitlines()
    except OSError:
        return f"No output was captured (see {log})."
    if not captured:
        return f"It produced no output (see {log})."
    return "\n".join(captured[-lines:])


def reveal(path: Path) -> None:
    """Show a file or folder in Finder."""
    subprocess.run(["open", "-R", str(path)], check=False)
