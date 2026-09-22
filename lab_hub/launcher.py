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

import json
import os
import plistlib
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
    project: str  # folder path under the lab root
    entry: str  # entry script, relative to the project folder
    summary: str
    # What this app's windowless background copy is called, for apps that have
    # one. SONAR's launchd agent keeps settling hours with no window open, and
    # that is the point of it — worth reporting, but never as "the app is
    # open", which is the question the Launch button answers.
    service: str | None = None


# One tile per umbrella app, and nothing else. The agents and sub-modules that
# live inside these projects — Tunnel and Bug Spray inside Sentinel, the
# video pipeline inside Imprint, macro and Playmaker inside SONAR — are reached
# from their own app, never from here. Two doors to the same feature is how you
# end up with a standalone VPN Agent window that knows nothing about the
# Sentinel session that should own it.
SUITES: tuple[ExternalApp, ...] = (
    ExternalApp(
        key="sentinel_fork",
        name="Sentinel",
        project="sentinel_fork",
        entry="main.py",
        summary="Security and investigation command centre. Its agents — Chat, "
        "Trace, Bloodhound, Beacon, Forge, Tunnel and Bug Spray — live inside it.",
    ),
    ExternalApp(
        key="imprint",
        name="Imprint",
        project="imprint",
        entry="main.py",
        summary="The create-and-publish studio: writing, audio, video, social, "
        "web and gigs, each behind its own mode tab.",
    ),
    ExternalApp(
        key="sonar",
        name="SONAR",
        project="sonar",
        entry="main.py",
        summary="Market scanner and paper-trading terminal: live prices, "
        "prediction-market odds and a probability model, traded with paper money.",
        service="Engine",
    ),
)

BACKUP_SYNC_APPS: tuple[ExternalApp, ...] = (
    ExternalApp(
        key="backup_manager",
        name="Backup Control Center",
        project="backup_manager",
        entry="main.py",
        summary="Run and monitor the Google Drive rsync backup, and keep an eye "
        "on the other sync engines.",
    ),
    ExternalApp(
        key="git_autosync",
        name="git_autosync",
        project="git_autosync",
        entry="packaging/entry_point.py",
        summary="Commit and push the lab's repos on a schedule, with per-repo "
        "status and manual sync.",
    ),
)

UTILITIES: tuple[ExternalApp, ...] = (
    ExternalApp(
        key="unblock_tracker",
        name="Unblock Tracker",
        project="toolbox/unblock_tracker",
        entry="main.py",
        summary="Watch whether an Instagram profile has unblocked you, and get "
        "notified the moment it changes.",
    ),
)

# Every launchable app. There is no nesting any more, so this is simply the
# three groups in order — the menu bar and the self-test both read it.
PRIMARY_APPS: tuple[ExternalApp, ...] = SUITES
MENU_BAR_APPS: tuple[ExternalApp, ...] = SUITES + BACKUP_SYNC_APPS + UTILITIES
LAUNCHPAD: tuple[ExternalApp, ...] = MENU_BAR_APPS
APPS: tuple[ExternalApp, ...] = LAUNCHPAD


def bundle_path(app: ExternalApp) -> Path | None:
    """The installed .app, if it is there."""
    path = APPLICATIONS / f"{app.name}.app"
    return path if path.is_dir() else None


def _bundle_executable_path(bundle: Path) -> Path | None:
    """The binary inside a bundle, read from `CFBundleExecutable`."""
    macos = bundle / "Contents" / "MacOS"
    try:
        with (bundle / "Contents" / "Info.plist").open("rb") as handle:
            name = plistlib.load(handle).get("CFBundleExecutable")
    except (OSError, plistlib.InvalidFileException, AttributeError):
        name = None
    if name:
        candidate = macos / name
        if candidate.is_file():
            return candidate
    # No usable key: accept any single binary sitting in MacOS/ rather than
    # calling a working bundle broken.
    try:
        binaries = [child for child in macos.iterdir() if child.is_file()]
    except OSError:
        return None
    return binaries[0] if len(binaries) == 1 else None


def bundle_executable(app: ExternalApp) -> Path | None:
    """The binary inside the installed bundle, if there is one.

    Read from `CFBundleExecutable` rather than assumed to be the app's name:
    Sentinel's is `SentinelLauncher`, and an `osacompile` launcher's is always
    `applet`. A bundle whose executable is gone still looks installed to
    `is_dir`, and `open` on one fails with a LaunchServices number rather than
    a sentence.
    """
    bundle = bundle_path(app)
    return None if bundle is None else _bundle_executable_path(bundle)


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


def running_markers(app: ExternalApp, lab_root: Path) -> tuple[str, ...]:
    """Absolute paths that identify a running copy on a `ps` command line.

    Both the bundle and the checkout, and a match on **either** counts —
    because an installed bundle is not necessarily the process that keeps
    running. Sentinel's is a one-shot launcher: it execs the project's own
    python and exits, so moments after a successful launch nothing in the
    process table mentions the bundle at all, only `<project>/main.py`.
    Matching the bundle alone reported a running app as *Did not start*, and
    went on reporting it for as long as the window stayed open.

    Checking both is also what survives the next change of launcher. This
    bundle has been a PyInstaller build, an AppleScript applet and a compiled
    C stub inside one month; the checkout path is the stable half.

    Source runs are the entry script, which is why `launch` hands the
    interpreter an absolute path — with a relative one every project shows up
    as a bare `python main.py` and they cannot be told apart.
    """
    markers = []
    bundle = bundle_path(app)
    if bundle is not None:
        markers.append(str(bundle / "Contents" / "MacOS"))
    project = source_dir(app, lab_root)
    if project is not None:
        markers.append(str(project / app.entry))
    return tuple(markers)


# A process started with one of these has no window and never will, so it is
# not an answer to "is this app open?" — the tile's button raises a window.
# SONAR ships a launchd agent running `main.py --headless`, which keeps settling
# hours around the clock; matching the entry script alone meant that agent made
# the tile read *Running* permanently, offering to raise a window that does not
# exist even when the app had been properly quit.
#
# `--background` is deliberately NOT in this list. That is the whole app started
# without showing its window — it lives in the menu bar and can be raised, and
# it is how Lab Hub itself starts Backup Control Center and git_autosync. Those
# are running, and calling them stopped would offer a Launch button that starts
# a second copy.
NO_WINDOW_FLAGS = ("--headless",)


@dataclass(frozen=True)
class Presence:
    """What of this app is up: a window, a headless background copy, or both.

    They are different answers to different questions and must not be folded
    together. *Window* decides whether Launch would start a duplicate; SONAR's
    engine running under launchd says nothing about that, and treating it as
    "the app is open" offered to raise a window that did not exist.
    """

    window: bool
    service: bool


def presence(app: ExternalApp, lab_root: Path, table: str | None = None) -> Presence:
    """Classify every matching command line in one pass.

    Matched line by line rather than against the whole snapshot, so a flag on
    one process cannot be read off another's: a substring search over the
    joined table would see `--headless` somewhere in it and discount every app
    at once.
    """
    markers = running_markers(app, lab_root)
    if not markers:
        return Presence(window=False, service=False)

    snapshot = process_table() if table is None else table
    window = service = False
    for line in snapshot.splitlines():
        if not any(marker in line for marker in markers):
            continue
        if any(flag in line for flag in NO_WINDOW_FLAGS):
            service = True
        else:
            window = True
    return Presence(window=window, service=service)


def is_running(app: ExternalApp, lab_root: Path, table: str | None = None) -> bool:
    """Whether a copy *with a window* is up. The tile's button acts on this."""
    return presence(app, lab_root, table).window


def can_bring_to_front(app: ExternalApp) -> bool:
    """Only an installed bundle can be raised.

    A source run is a bare `python`, with no bundle identifier for `open` to
    address; raising it by pid needs System Events, which is assistive access
    the user would have to grant. Better to say so than to fail quietly.
    """
    return bundle_path(app) is not None


def is_launcher_bundle(bundle: Path) -> bool:
    """True when the .app only starts the real GUI in a separate process.

    An AppleScript applet that runs a project's main.py stays alive inside
    `do shell script` while the real GUI runs beside it, and it owns no window:
    `open -a` reaches the applet, which is deaf to the reopen event, so raising
    the app that way silently does nothing. Self-contained PyInstaller bundles
    name their executable after the app, so an executable called "applet" is
    the reliable tell for that shape.

    Sentinel used to be one. As of its V2 installer it is a compiled C stub
    (`SentinelLauncher`) that execs the project's python and **exits**, leaving
    no bundle process at all — so `open -a` runs the stub again, the second
    copy hands off to the running one and quits, and raising works without this
    path. Verified against the installed app: the pid does not change. Kept for
    the applets that remain, notably Bug Spray's.
    """
    plist = bundle / "Contents" / "Info.plist"
    try:
        result = subprocess.run(
            ["/usr/libexec/PlistBuddy", "-c", "Print :CFBundleExecutable", str(plist)],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and result.stdout.strip() == "applet"


def bring_to_front(app: ExternalApp, lab_root: Path) -> str:
    bundle = bundle_path(app)
    project = source_dir(app, lab_root)

    # A launcher bundle cannot raise its own GUI, so go at the entry script
    # instead. These apps dedupe themselves: the second copy hands off to the
    # running one, which comes forward, and then exits 0.
    if bundle is not None and project is not None and is_launcher_bundle(bundle):
        python = venv_python(project)
        if python is not None:
            try:
                handoff = subprocess.run(
                    [str(python), str(project / app.entry)],
                    cwd=project, capture_output=True, text=True,
                    env=child_env(), timeout=30,
                )
            except subprocess.SubprocessError as error:
                raise LaunchError(f"Could not raise {app.name}: {error}") from error
            if handoff.returncode != 0:
                raise LaunchError(
                    f"Could not raise {app.name} — its launcher exited with "
                    f"status {handoff.returncode}.\n\n"
                    f"{(handoff.stderr or handoff.stdout).strip()[-400:]}"
                )
            return f"Brought {app.name} to the front"

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


# The lab-wide scheme: v<MAJOR>.<BUILD>, the arc hand-set in a VERSION file and
# the build derived from `git rev-list --count HEAD`. A frozen bundle has no
# git, so its build is stamped into this file when it is packaged.
BUILD_INFO_NAME = "_build_info.json"


@dataclass(frozen=True)
class Version:
    """Which version the Launch button would actually start.

    `text` is empty when there is no evidence. That is deliberate: the question
    being answered is "is the app I am about to open the one I built", and an
    answer invented from the nearest number to hand is worse than none.
    """

    text: str = ""
    origin: str = ""  # bundle | checkout
    detail: str = ""  # where the number came from, for the tooltip

    @property
    def known(self) -> bool:
        return bool(self.text)


def bundle_runs_checkout(bundle: Path) -> bool:
    """True when the .app is a stub that runs the project's own source.

    Two shapes in the lab: Sentinel's compiled C launcher, which records the
    checkout it runs in `Resources/project_root.txt`, and an `osacompile`
    launcher, whose executable is always `applet`. Either way the bundle holds
    no application code, so its own version — Sentinel's Info.plist says 2.0,
    hand-typed once — describes nothing. The checkout is the answer.

    Deliberately separate from `is_launcher_bundle`, which asks whether `open`
    can raise the app. Same two bundles today, different questions.
    """
    if (bundle / "Contents" / "Resources" / "project_root.txt").is_file():
        return True
    executable = _bundle_executable_path(bundle)
    return executable is not None and executable.name == "applet"


def _stamped_version(bundle: Path) -> Version | None:
    """The build a frozen bundle was packaged from, if it recorded one."""
    for holder in ("Resources", "Frameworks"):
        stamp = bundle / "Contents" / holder / BUILD_INFO_NAME
        try:
            data = json.loads(stamp.read_text())
        except (OSError, ValueError):
            continue
        major, build = data.get("major"), data.get("build")
        if major is None or build is None:
            continue
        return Version(
            text=f"v{major}.{int(build):03d}",
            origin="bundle",
            detail=f"stamped into {bundle.name} when it was built",
        )
    return None


def _commit_count(project: Path) -> int | None:
    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=project, capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return int(result.stdout.strip()) if result.returncode == 0 else None


def _major(project: Path) -> str | None:
    """The product arc: the VERSION file, else the `## vN` heading in TODO.md.

    Split on the first dot because `sentinel_fork/VERSION` holds `2.001` — the
    whole version, hand-written, against a convention that says the build half
    is derived. Taking the arc and deriving the rest keeps that file honest
    without editing another project's tree.
    """
    try:
        raw = (project / "VERSION").read_text().strip()
        if raw:
            return raw.split(".")[0]
    except OSError:
        pass
    try:
        for line in (project / "TODO.md").read_text().splitlines():
            if line.startswith("## v") and line[4:5].isdigit() is False:
                continue
            if line.startswith("## v"):
                return line[4:].split()[0].split("—")[0].strip()
    except OSError:
        pass
    return None


def checkout_version(project: Path) -> Version:
    major = _major(project)
    build = _commit_count(project)
    if major is None or build is None:
        return Version()
    return Version(
        text=f"v{major}.{build:03d}",
        origin="checkout",
        detail=f"from the checkout at {project}",
    )


def version(app: ExternalApp, lab_root: Path) -> Version:
    """The version of whatever this tile would launch.

    Follows the launch path rather than guessing: a frozen bundle answers with
    the build stamped into it, a launcher bundle answers with the checkout it
    runs, and a tile with no bundle answers with the checkout it would start.
    A frozen bundle that carries no stamp answers *nothing* — borrowing the
    checkout's number there would describe code that is not what opens.
    """
    bundle = bundle_path(app)
    project = source_dir(app, lab_root)
    if bundle is not None and not bundle_runs_checkout(bundle):
        return _stamped_version(bundle) or Version()
    if project is not None:
        return checkout_version(project)
    return Version()


def status(app: ExternalApp, lab_root: Path) -> tuple[str, str]:
    """A (state, detail) pair for the UI. State is installed/source/missing."""
    bundle = bundle_path(app)
    if bundle is not None:
        return "installed", str(bundle)
    project = source_dir(app, lab_root)
    if project is not None:
        return "source", str(project)
    return "missing", f"not in /Applications, and no checkout at {lab_root / app.project}"


@dataclass(frozen=True)
class Readiness:
    """What can be said about an app *before* its Launch button is pressed.

    `status` answers "where would this start from"; this answers "would it
    start at all". They differ for the cases that used to fail only once the
    button was pressed: a checkout with no venv and no python3 on PATH, and a
    bundle that is still a directory but has lost its executable.
    """

    state: str  # installed | source | missing
    detail: str  # where it would be started from
    problem: str | None = None  # why it cannot be, if it cannot

    @property
    def ok(self) -> bool:
        return self.problem is None


def readiness(app: ExternalApp, lab_root: Path) -> Readiness:
    """Check now what `launch` would otherwise only discover on the way."""
    state, detail = status(app, lab_root)

    if state == "installed":
        if bundle_executable(app) is None:
            return Readiness(
                state,
                detail,
                "the installed bundle has no executable inside it — rebuild "
                "and reinstall it.",
            )
        return Readiness(state, detail)

    if state == "source":
        project = source_dir(app, lab_root)
        python = venv_python(project)
        if python is not None:
            return Readiness(state, f"{detail} ({python.parent.parent.name})")
        if shutil.which("python3"):
            return Readiness(state, f"{detail} (no venv — using python3 on PATH)")
        return Readiness(
            state,
            detail,
            f"{project} has no .venv and python3 is not on PATH, so there is "
            "no interpreter to run it with.",
        )

    return Readiness(
        state, detail, "not installed, and there is no source checkout to fall back on."
    )


def launch(app: ExternalApp, lab_root: Path, *, background: bool = False) -> str:
    """Start the app. Returns a line describing what was started."""
    extra_args = ["--background"] if background else []
    bundle = bundle_path(app)
    if bundle is not None:
        if bundle_executable(app) is None:
            # `open` on a gutted bundle fails with a LaunchServices number
            # rather than a sentence, so say it plainly here instead.
            raise LaunchError(
                f"{bundle} has no executable inside it. Rebuild {app.name} and "
                "reinstall it, or delete the bundle to fall back to its source "
                "checkout."
            )
        # -n so a second click brings up a new instance rather than silently
        # doing nothing when the app is already open but on another Space.
        command = ["open", "-a", str(bundle)]
        if extra_args:
            command.extend(["--args", *extra_args])
        result = subprocess.run(
            command,
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
    log = launch_log(app)
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
            [str(python), str(project / app.entry), *extra_args],
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


def launch_log(app: ExternalApp) -> Path:
    """Where a source-launched app's own output is written."""
    return Path(tempfile.gettempdir()) / f"lab-hub-launch-{app.key}.log"


def startup_log_hint(app: ExternalApp) -> str:
    """Where to look when an app was started but never came up.

    A bundle launched through `open` is not our child, so its output goes to
    the unified log rather than to us — naming the command is the difference
    between a dead end and a diagnosis.
    """
    executable = bundle_executable(app)
    if executable is not None:
        return (
            "Console.app, or: log show --predicate "
            f"'process == \"{executable.name}\"' --last 5m"
        )
    return str(launch_log(app))


def reveal(path: Path) -> None:
    """Show a file or folder in Finder."""
    subprocess.run(["open", "-R", str(path)], check=False)
