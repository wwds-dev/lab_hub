"""Starting, stopping and raising the standalone apps.

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
import shlex
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path

from . import state
from .registry import ExternalApp

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


def open_url(url: str) -> None:
    """Open an address in the default browser."""
    result = subprocess.run(
        ["open", url], capture_output=True, text=True, env=child_env()
    )
    if result.returncode != 0:
        raise LaunchError(result.stderr.strip() or f"'open' failed for {url}")



def server_pids(app: ExternalApp, lab_root: Path) -> list[int]:
    """The processes running this web app's server from its checkout.

    Found by the absolute entry path Lab Hub starts it with. A server started
    by hand runs by a relative path and is deliberately not found: stopping
    whatever happens to be listening on the port could be anything.
    """
    marker = state.checkout_marker(app, lab_root) if app.served else None
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

    bundle = state.bundle_path(app, lab_root)
    project = state.source_dir(app, lab_root)

    # A launcher bundle cannot raise its own GUI, so go at the entry script
    # instead. These apps dedupe themselves: the second copy hands off to the
    # running one, which comes forward, and then exits 0.
    if bundle is not None and project is not None and is_launcher_bundle(bundle):
        python = state.venv_python(project)
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


def launch(app: ExternalApp, lab_root: Path, *, background: bool = False) -> str:
    """Start the app. Returns a line describing what was started."""
    extra_args = ["--background"] if background else []
    bundle = state.bundle_path(app, lab_root)
    if bundle is not None:
        if state.bundle_executable(app, lab_root) is None:
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

    project = state.source_dir(app, lab_root)
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
        python = state.venv_python(project) or (
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
    executable = state.bundle_executable(app, lab_root)
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
