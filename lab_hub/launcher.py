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
import shlex
import shutil
import signal
import socket
import subprocess
import tempfile
import time
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import urlsplit

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


# One tile per umbrella app, and nothing else. The agents and sub-modules that
# live inside these projects — Tunnel and Bug Spray inside Sentinel, the
# video pipeline inside Imprint, macro and Playmaker inside SONAR — are reached
# from their own app, never from here. Two doors to the same feature is how you
# end up with a standalone VPN Agent window that knows nothing about the
# Sentinel session that should own it.
SUITES: tuple[ExternalApp, ...] = (
    ExternalApp(
        key="sentinel",
        name="Sentinel",
        project="sentinel",
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
        service="Background engine",
    ),
    # Headroom is Provisio's `engine/`, not an app of its own — it gets no tile
    # for the same reason Tunnel does not. Provisio was a web app here (its
    # node server, opened in the browser) until 2026-10-07; it is now a native
    # window, /Applications/Provisio.app from its scripts/install_app.sh, that
    # starts and stops its own server and switches between a demo and a real
    # workspace. The browser-mode server and the app cannot run at once (vinext
    # allows one dev server per checkout), so this tile must not start one.
    ExternalApp(
        key="provisio",
        name="Provisio",
        project="provisio",
        entry="main.py",
        summary="Income-protection product design and review, with a Demo/Real "
        "workspace switch. Headroom, its solvency-filings engine, lives inside it.",
    ),
    # SYNDUSTRYX: renamed source, bundle and Lab registration together.
    # Source remains in the Codex workspace, linked as active/syndustryx.
    ExternalApp(
        key="syndustryx",
        name="SYNDUSTRYX",
        project="syndustryx",
        entry="server.py",
        summary="The Antfarm workstation: an animated factory over a local "
        "fulfilment engine, storefront and departments.",
        bundle_dir="dist",
        runs_from_source=False,
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

# Launched from their own card at the end of the Tools tab and nowhere else:
# no Apps tile and no menu bar entry. That is the user's call (2026-09-27) —
# a standalone app kept off the front page, not a sub-module of anything.
TOOLS_ONLY_APPS: tuple[ExternalApp, ...] = (
    ExternalApp(
        key="backstage",
        name="Backstage",
        project="backstage",
        entry="main.py",
        summary="Venture analytics: market signals, bounded pricing tests and "
        "the records behind them.",
    ),
)

# Every launchable app. There is no nesting any more, so this is simply the
# groups in order. The menu bar reads MENU_BAR_APPS; the self-test, the build
# report and Settings read APPS, which also covers the Tools-only apps.
PRIMARY_APPS: tuple[ExternalApp, ...] = SUITES
MENU_BAR_APPS: tuple[ExternalApp, ...] = SUITES + BACKUP_SYNC_APPS + UTILITIES
LAUNCHPAD: tuple[ExternalApp, ...] = MENU_BAR_APPS
APPS: tuple[ExternalApp, ...] = LAUNCHPAD + TOOLS_ONLY_APPS


def bundle_path(app: ExternalApp, lab_root: Path | None = None) -> Path | None:
    """The installed .app, if it is there.

    For an app with a `bundle_dir`, a bundle built inside its checkout counts
    when none is installed — resolved, because the checkout may be reached
    through a symlink and the process table only ever shows the real path.
    """
    path = APPLICATIONS / f"{app.name}.app"
    if path.is_dir():
        return path
    if app.bundle_dir is None or lab_root is None:
        return None
    built = lab_root / app.project / app.bundle_dir / f"{app.name}.app"
    return built.resolve() if built.is_dir() else None


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


def bundle_executable(app: ExternalApp, lab_root: Path | None = None) -> Path | None:
    """The binary inside the installed bundle, if there is one.

    Read from `CFBundleExecutable` rather than assumed to be the app's name:
    Sentinel's is `SentinelLauncher`, and an `osacompile` launcher's is always
    `applet`. A bundle whose executable is gone still looks installed to
    `is_dir`, and `open` on one fails with a LaunchServices number rather than
    a sentence.
    """
    bundle = bundle_path(app, lab_root)
    return None if bundle is None else _bundle_executable_path(bundle)


# A stub bundle writes the checkout it runs into its own Resources. That file
# is maintained by the project's installer, so it is right the moment the
# project moves — which is more than can be said for `ExternalApp.project`,
# a directory name hard-coded here and only corrected on the next Lab Hub build.
PROJECT_ROOT_FILE = "project_root.txt"


def recorded_project_root(bundle: Path) -> Path | None:
    """The checkout a bundle says it runs, read from inside the bundle.

    Only stub bundles carry this. It is the authority on where their code
    lives: when `sentinel_fork` was renamed to `sentinel`, Sentinel's installer
    rewrote this file the same day, while the copy of Lab Hub in /Applications
    went on looking for a directory that no longer existed.
    """
    stamp = bundle / "Contents" / "Resources" / PROJECT_ROOT_FILE
    try:
        recorded = stamp.read_text().strip()
    except OSError:
        return None
    return Path(recorded) if recorded else None


def source_dir(app: ExternalApp, lab_root: Path) -> Path | None:
    """The project checkout, if it has the entry script we expect.

    The configured lab folder is asked first, so the Settings tab still decides
    where projects are looked for. A stub bundle's own record is the fallback,
    and it is what survives a renamed checkout: the name here is a guess baked
    in at build time, and a stale guess used to take the version label, the
    build report and — worst — the running check down with it.
    """
    project = lab_root / app.project
    if (project / app.entry).is_file():
        return project

    bundle = bundle_path(app)
    if bundle is not None:
        recorded = recorded_project_root(bundle)
        if recorded is not None and (recorded / app.entry).is_file():
            return recorded
    return None


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
    as a bare `python main.py` and they cannot be told apart. That half comes
    from `source_dir`, which falls back to the checkout the bundle itself
    records: without that, a checkout renamed since this build drops the
    marker and leaves only the bundle — exactly the half that does not last.
    """
    markers = (bundle_marker(app, lab_root), checkout_marker(app, lab_root))
    return tuple(marker for marker in markers if marker is not None)


def bundle_marker(app: ExternalApp, lab_root: Path | None = None) -> str | None:
    """The installed bundle's own process, if there is a bundle."""
    bundle = bundle_path(app, lab_root)
    return None if bundle is None else str(bundle / "Contents" / "MacOS")


def checkout_marker(app: ExternalApp, lab_root: Path) -> str | None:
    """The entry script a source run shows on its command line."""
    project = source_dir(app, lab_root)
    return None if project is None else str(project / app.entry)


def hands_off_and_exits(bundle: Path) -> bool:
    """True when the bundle's own process is gone moments after the launch.

    Sentinel's stub execs the project's python and exits, so its
    `Contents/MacOS` path is in the process table for a fraction of a second
    and never again. Absence of that marker is therefore not evidence of
    anything, and `launch_is_observable` refuses to read it as such.

    Recording a project root is the tell: a bundle that names the checkout it
    runs holds no code of its own. The applet shape keeps its own process alive
    beside the app it started and embeds the path in its script instead, which
    is why it is not caught here and does not need to be.
    """
    return recorded_project_root(bundle) is not None


def launch_is_observable(app: ExternalApp, lab_root: Path) -> bool:
    """Whether *not* finding this app in the process table means anything.

    The honest answer is no for a stub bundle with no checkout to watch
    instead: nothing it leaves behind is durable, so a launch that worked and a
    launch that died look identical from here. Saying "Did not start" on that
    evidence is how a running Sentinel was reported dead for a minute at a
    time, and the caller is expected to say nothing rather than guess.
    """
    if checkout_marker(app, lab_root) is not None:
        return True
    bundle = bundle_path(app, lab_root)
    return bundle is not None and not hands_off_and_exits(bundle)


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

    A web app's window is the browser, so for one of those the question is
    whether its address answers, and nothing else: its process is on the
    table seconds before it listens, and "Running" then would offer a page
    that cannot load yet. The address also catches a server started by hand
    from its own `start-preview.command`, which runs by a relative path no
    marker can see. (The marker still matters to `stop`.)
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
    if app.served:
        window = serving(app)
    return Presence(window=window, service=service)


def is_running(app: ExternalApp, lab_root: Path, table: str | None = None) -> bool:
    """Whether a copy *with a window* is up. The tile's button acts on this."""
    return presence(app, lab_root, table).window


# A refused connection on loopback comes back at once; this only bounds the
# rare case of something listening and not accepting.
SERVE_PROBE_SECONDS = 0.2


def serving(app: ExternalApp) -> bool:
    """Whether something answers at a web app's address.

    A connect, not a request: the first page of a dev server compiles on
    demand and can take seconds, and this runs on the tile's poll. Every
    address `localhost` resolves to is tried, because a node server bound to
    `localhost` may be listening on ::1 only.
    """
    if app.url is None:
        return False
    parts = urlsplit(app.url)
    if parts.hostname is None:
        return False
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        with socket.create_connection(
            (parts.hostname, port), timeout=SERVE_PROBE_SECONDS
        ):
            return True
    except OSError:
        return False


def open_url(url: str) -> None:
    """Open an address in the default browser."""
    result = subprocess.run(
        ["open", url], capture_output=True, text=True, env=child_env()
    )
    if result.returncode != 0:
        raise LaunchError(result.stderr.strip() or f"'open' failed for {url}")


def can_bring_to_front(app: ExternalApp, lab_root: Path | None = None) -> bool:
    """Only an installed bundle can be raised.

    A source run is a bare `python`, with no bundle identifier for `open` to
    address; raising it by pid needs System Events, which is assistive access
    the user would have to grant. Better to say so than to fail quietly.

    A web app's "front" is its address, which can always be opened.
    """
    return app.served or bundle_path(app, lab_root) is not None


def server_pids(app: ExternalApp, lab_root: Path) -> list[int]:
    """The processes running this web app's server from its checkout.

    Found by the absolute entry path Lab Hub starts it with. A server started
    by hand runs by a relative path and is deliberately not found: stopping
    whatever happens to be listening on the port could be anything.
    """
    marker = checkout_marker(app, lab_root) if app.served else None
    if marker is None:
        return []
    try:
        table = subprocess.run(
            ["ps", "-Axo", "pid=,command="], capture_output=True, text=True, timeout=5
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    pids = []
    for line in table.splitlines():
        pid, _, command = line.strip().partition(" ")
        if marker in command and pid.isdigit():
            pids.append(int(pid))
    return pids


def stop(app: ExternalApp, lab_root: Path) -> str:
    """Stop a web app's server: the window it does not have cannot be closed.

    SIGTERM to the process group, which `launch` made the server the leader
    of, so the helpers a dev server starts (Wrangler's workerd) go with it.
    """
    pids = server_pids(app, lab_root)
    if not pids:
        raise LaunchError(
            f"Lab Hub can only stop a {app.name} server it can recognise. One "
            "started by hand is stopped where it was started — Control-C in "
            "its Terminal window."
        )
    for pid in pids:
        try:
            os.killpg(pid, signal.SIGTERM)
        except OSError:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
    return f"Stopped {app.name}"


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
    if app.url is not None:
        open_url(app.url)
        return f"Opened {app.name} in your browser"

    bundle = bundle_path(app, lab_root)
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
    # How many commits the installed build is behind its source, when both are
    # known. Only ever non-zero for a frozen bundle: a launcher bundle runs the
    # checkout, so it cannot be behind it.
    behind: int = 0

    @property
    def known(self) -> bool:
        return bool(self.text)

    @property
    def stale(self) -> bool:
        return self.behind > 0


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
    if recorded_project_root(bundle) is not None:
        return True
    executable = _bundle_executable_path(bundle)
    return executable is not None and executable.name == "applet"


def _stamped_build(bundle: Path) -> int | None:
    """The build number in a bundle's stamp, without the formatting."""
    for holder in ("Resources", "Frameworks"):
        try:
            data = json.loads(
                (bundle / "Contents" / holder / BUILD_INFO_NAME).read_text()
            )
        except (OSError, ValueError):
            continue
        build = data.get("build")
        if isinstance(build, int):
            return build
    return None


def _plist_version(bundle: Path) -> Version:
    """The release number in a bundle's Info.plist, for apps with no lab stamp."""
    try:
        with (bundle / "Contents" / "Info.plist").open("rb") as handle:
            raw = plistlib.load(handle).get("CFBundleShortVersionString")
    except (OSError, plistlib.InvalidFileException, AttributeError):
        return Version()
    if not isinstance(raw, str) or not raw.strip():
        return Version()
    return Version(
        text=f"v{raw.strip().lstrip('vV')}",
        origin="bundle",
        detail=f"the release number in {bundle.name}'s Info.plist",
    )


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


# Keyed on the mtime of the repository's HEAD, so a commit invalidates it and
# nothing else does. Without this the tile could not re-read the version on its
# poll: a `git rev-list` per app every three seconds is a subprocess storm for a
# number that changes when you commit.
_COUNT_CACHE: dict[tuple[str, int], int | None] = {}


def _head_stamp(project: Path) -> int | None:
    """When this repository last moved. None when it is not a repository."""
    head = project / ".git" / "HEAD"
    try:
        newest = head.stat().st_mtime_ns
    except OSError:
        return None
    # A commit on a branch rewrites the ref, not HEAD itself, so check both.
    try:
        ref = head.read_text().strip()
        if ref.startswith("ref: "):
            target = project / ".git" / ref[5:]
            newest = max(newest, target.stat().st_mtime_ns)
    except OSError:
        pass
    return newest


def _commit_count(project: Path) -> int | None:
    stamp = _head_stamp(project)
    if stamp is None:
        return None
    key = (str(project), stamp)
    if key in _COUNT_CACHE:
        return _COUNT_CACHE[key]
    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=project, capture_output=True, text=True, timeout=10,
        )
        count = int(result.stdout.strip()) if result.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError):
        count = None
    _COUNT_CACHE[key] = count
    return count


def _major(project: Path) -> str | None:
    """The product arc: the VERSION file, else the `## vN` heading in TODO.md.

    Split on the first dot because `sentinel/VERSION` holds `2.001` — the
    whole version, hand-written, against a convention that says the build half
    is derived. Taking the arc and deriving the rest keeps that file honest
    without editing another project's tree.

    Only a three-digit tail is a build, though — that is the lab's padded
    build format. Provisio's `2.0` is a release line, and its own footer
    stamps `v2.0.<count>`; cutting it to `2` would put a number on the tile
    that the app itself never shows.
    """
    try:
        raw = (project / "VERSION").read_text().strip().lstrip("vV")
        if raw:
            arc, _, tail = raw.partition(".")
            return arc if len(tail) == 3 and tail.isdigit() else raw
    except OSError:
        pass
    try:
        for line in (project / "TODO.md").read_text().splitlines():
            if line.startswith("## v") and line[4:5].isdigit() is False:
                continue
            if line.startswith("## v"):
                # Only a bare integer is a lab arc; SYNDUSTRYX's `## v0.6.20`
                # is its own release number, not a v<MAJOR>.<BUILD> arc.
                arc = line[4:].split()[0].split("—")[0].strip()
                return arc if arc.isdigit() else None
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
    bundle = bundle_path(app, lab_root)
    project = source_dir(app, lab_root)
    if bundle is not None and not bundle_runs_checkout(bundle):
        stamped = _stamped_version(bundle)
        if stamped is None and (project is None or _major(project) is None):
            # Outside the lab's scheme (SYNDUSTRYX): the bundle's own release
            # number is the only honest one, and it is not compared to a source.
            return _plist_version(bundle)
        if stamped is None:
            return Version()
        # A frozen bundle is only as new as its last build. Saying so is the
        # whole point of the number: "is the app I am about to open the one I
        # built?" — and the answer here is often no, because committing to a
        # project does not rebuild it.
        if project is not None:
            source = _commit_count(project)
            built = _stamped_build(bundle)
            if source is not None and built is not None and source > built:
                return replace(stamped, behind=source - built)
        return stamped
    if project is not None:
        return checkout_version(project)
    return Version()


# Where a project keeps the script that rebuilds and installs it. Checked in
# order; the first that exists is the one to name in the report.
BUILD_SCRIPTS = ("build_app.sh", "scripts/build_app.sh", "scripts/install_app.sh")


def build_script(project: Path) -> Path | None:
    for name in BUILD_SCRIPTS:
        candidate = project / name
        if candidate.is_file():
            return candidate
    return None


INSTALL_FLAG = "--install"


def install_command(project: Path, script: Path) -> str:
    """The shell line that rebuilds this project **and installs it**.

    The build scripts disagree, and silently: `sonar`, `unblock_tracker`,
    `lab_hub` and Sentinel build into `dist.noindex/` and only copy into
    /Applications when passed `--install`, while `backup_manager`,
    `git_autosync` and Imprint install by default. Handing over a command
    without the flag where it is needed costs several minutes of build and
    leaves the old app exactly where it was — the very thing the report exists
    to warn about.

    The flag is read from the script rather than kept in a table here. A table
    would be a second place to be wrong, and it would go stale the first time
    one of seven scripts changed its mind.
    """
    needs_flag = False
    try:
        text = script.read_text()
        needs_flag = f'== "{INSTALL_FLAG}"' in text or f"{INSTALL_FLAG})" in text
    except OSError:
        pass
    relative = script.relative_to(project)
    suffix = f" {INSTALL_FLAG}" if needs_flag else ""
    return f"cd {shlex.quote(str(project))} && ./{relative}{suffix}"


def dirty_checkout(project: Path) -> bool:
    """Whether the checkout has changes that are not committed.

    The commit count cannot see these — it only moves on commit — so a bundle
    built from the last commit looks level with its source while the source has
    since been edited. For a frozen app that is a real gap: those edits are not
    in what opens. For a launcher bundle it is not, because the edits *are*
    what opens.
    """
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project, capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


@dataclass(frozen=True)
class BuildStatus:
    """One line of the build report."""

    app: ExternalApp
    version: Version
    verdict: str  # current | behind | uncommitted | unknown | missing
    note: str
    script: Path | None = None
    command: str | None = None  # the shell line that would bring it up to date

    @property
    def needs_rebuild(self) -> bool:
        return self.verdict in ("behind", "uncommitted")


def build_status(app: ExternalApp, lab_root: Path) -> BuildStatus:
    """Whether what this tile would open is the newest thing available."""
    found = version(app, lab_root)
    project = source_dir(app, lab_root)
    script = build_script(project) if project is not None else None
    command = (
        install_command(project, script)
        if project is not None and script is not None
        else None
    )

    if project is None:
        return BuildStatus(
            app, found, "missing",
            "no checkout here, so there is nothing to compare it against.",
        )
    if found.origin == "bundle" and _major(project) is None:
        return BuildStatus(
            app, found, "unknown",
            "its release number comes from the bundle; it does not use the "
            "lab's version scheme, so there is nothing to compare it against.",
            script, command,
        )
    if not found.known:
        # Rebuilding only helps a project whose build stamps a version. One
        # outside the lab's scheme (SYNDUSTRYX: no VERSION file, no git) never
        # will, and telling the user to rebuild it would be advice that cannot
        # work.
        note = (
            "installed, but it carries no build stamp — rebuild it once and it "
            "will start reporting."
            if _major(project) is not None else
            "it does not use the lab's version scheme, so there is nothing to "
            "compare the build against."
        )
        return BuildStatus(app, found, "unknown", note, script, command)
    if found.origin == "checkout":
        # It runs the source, so it opens whatever the source says right now —
        # uncommitted edits included. It cannot be out of date.
        return BuildStatus(
            app, found, "current",
            "runs the checkout directly, so it is always what the source says.",
            script, command,
        )
    if found.stale:
        return BuildStatus(
            app, found, "behind",
            f"built at {found.text}, but the source is {found.behind} commits "
            "further on.", script, command,
        )
    if dirty_checkout(project):
        return BuildStatus(
            app, found, "uncommitted",
            "level with the last commit, but the checkout has uncommitted "
            "changes that are not in this build.", script, command,
        )
    return BuildStatus(app, found, "current", "matches its source.", script, command)


def build_report(
    lab_root: Path, apps: tuple[ExternalApp, ...] | None = None
) -> tuple[BuildStatus, ...]:
    return tuple(build_status(app, lab_root) for app in (apps or APPS))


def status(app: ExternalApp, lab_root: Path) -> tuple[str, str]:
    """A (state, detail) pair for the UI.

    State is installed/built/source/server/missing. *Built* is a bundle found
    in the checkout's `bundle_dir` rather than in /Applications; *server* is a
    web app's checkout, which is how it always runs, so not a lesser state the
    way *source* is.
    """
    bundle = bundle_path(app, lab_root)
    if bundle is not None:
        if bundle.parent == APPLICATIONS:
            return "installed", str(bundle)
        # Shown by the way the lab reaches it, not by where the symlink lands
        # (SYNDUSTRYX's real home is a generated Codex project folder).
        return "built", str(lab_root / app.project / app.bundle_dir / bundle.name)
    project = source_dir(app, lab_root)
    if project is not None:
        if app.served:
            return "server", f"{app.url} — served from {project}"
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

    state: str  # installed | built | source | server | missing
    detail: str  # where it would be started from
    problem: str | None = None  # why it cannot be, if it cannot

    @property
    def ok(self) -> bool:
        return self.problem is None


def readiness(app: ExternalApp, lab_root: Path) -> Readiness:
    """Check now what `launch` would otherwise only discover on the way."""
    state, detail = status(app, lab_root)

    if state in ("installed", "built"):
        if bundle_executable(app, lab_root) is None:
            return Readiness(
                state,
                detail,
                "the installed bundle has no executable inside it — rebuild "
                "and reinstall it.",
            )
        return Readiness(state, detail)

    if state == "server":
        project = source_dir(app, lab_root)
        if not (project / "node_modules").is_dir():
            return Readiness(
                state,
                detail,
                f"its dependencies are not installed — run `npm run install:ci` "
                f"in {project} once.",
            )
        return Readiness(state, detail)

    if state == "source" and not app.runs_from_source:
        where = f"{detail}/{app.bundle_dir}" if app.bundle_dir else "/Applications"
        return Readiness(
            state,
            detail,
            f"nothing built to launch: no {app.name}.app in {where}, and its "
            "checkout is not run directly. Build it first.",
        )

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
    bundle = bundle_path(app, lab_root)
    if bundle is not None:
        if bundle_executable(app, lab_root) is None:
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
    if not app.runs_from_source:
        raise LaunchError(
            f"There is no built {app.name}.app to launch, and its checkout at "
            f"{project} is not run directly. Build it first."
        )

    if app.runtime == "node":
        # Through a login shell: node lives wherever the user's profile puts
        # it, and a frozen app's PATH is bare. `exec` keeps one process, so the
        # command line shows node and the absolute entry rather than a shell.
        shell = os.environ.get("SHELL", "/bin/zsh")
        script = " ".join(
            shlex.quote(part)
            for part in ("node", str(project / app.entry), *app.args)
        )
        command = [shell, "-lc", f"exec {script}"]
        interpreter = "node"
    else:
        python = venv_python(project) or (
            Path(shutil.which("python3")) if shutil.which("python3") else None
        )
        if python is None:
            raise LaunchError(
                f"No interpreter to run {app.name} with: {project} has no .venv and "
                "python3 is not on PATH."
            )
        # Absolute, not `app.entry`: the command line is how a running copy is
        # recognised later, and every project's relative entry is the same
        # `main.py`.
        command = [str(python), str(project / app.entry), *app.args, *extra_args]
        interpreter = str(python)

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
            command,
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

    return f"Launched {app.name} from source ({project}) using {interpreter}"


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


def startup_log_hint(app: ExternalApp, lab_root: Path | None = None) -> str:
    """Where to look when an app was started but never came up.

    A bundle launched through `open` is not our child, so its output goes to
    the unified log rather than to us — naming the command is the difference
    between a dead end and a diagnosis.
    """
    executable = bundle_executable(app, lab_root)
    if executable is not None:
        return (
            "Console.app, or: log show --predicate "
            f"'process == \"{executable.name}\"' --last 5m"
        )
    return str(launch_log(app))


def open_terminal(path: Path) -> None:
    """Open a Terminal window at `path`.

    Paired with the clipboard rather than typing the command in: driving
    Terminal would need an Apple Events grant, and a window that runs something
    the moment it opens is the wrong shape for a command that replaces an
    installed app. Paste and read it first.
    """
    subprocess.run(
        ["open", "-a", "Terminal", str(path)], check=False, env=child_env()
    )


def reveal(path: Path) -> None:
    """Show a file or folder in Finder."""
    subprocess.run(["open", "-R", str(path)], check=False)
