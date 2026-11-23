"""Where each registered app is, whether it is up, and which build it is.

Everything here only *looks*: the bundle in /Applications (or a checkout's
`bundle_dir`), the checkout and its venv, the process table, the version a
tile would open, the build report and the readiness check that decides whether
Launch is offered at all. Starting, stopping and raising an app is
`control`'s job; which apps exist is `registry`'s.
"""

from __future__ import annotations

import json
import os
import plistlib
import re
import shlex
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import urlsplit

from . import registry
from .registry import ExternalApp

APPLICATIONS = Path("/Applications")


def commits_further(count: int) -> str:
    """"1 commit further on", "3 commits further on" (spec land-update-gaps §3.3)."""
    return f"{count} commit{'' if count == 1 else 's'} further on"


def bundle_path(app: ExternalApp, lab_root: Path | None = None) -> Path | None:
    """The installed .app, if it is there.

    For an app with a `bundle_dir`, a bundle built inside its checkout counts
    when none is installed — resolved, because the checkout may be reached
    through a symlink and the process table only ever shows the real path.
    """
    if not app.launchable:
        # Nothing to launch, so no bundle: a stray `<name>.app` is not this
        # project's, and reporting it would offer a Launch that has no target.
        return None
    # A name read from the owner's local file came from a README, so it must
    # not pick an installed bundle: that app's tile would then control someone
    # else's installed app.
    if not app.local:
        for name in (app.bundle_name, *app.legacy_bundles):
            path = APPLICATIONS / f"{name}.app"
            if path.is_dir():
                return path
    if app.bundle_dir is None or lab_root is None:
        return None
    built = lab_root / app.project / app.bundle_dir / f"{app.bundle_name}.app"
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
    if not app.launchable:
        # No entry script to look for: the folder itself is the checkout.
        return project if project.is_dir() else None
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
    markers = (bundle_marker(app, lab_root), checkout_marker(app, lab_root), *legacy_bundle_markers(app))
    return tuple(dict.fromkeys(marker for marker in markers if marker is not None))


def legacy_bundle_markers(app: ExternalApp) -> tuple[str, ...]:
    """Installed bundles under an older name, which may still be running.

    After a rename, Update now installs the new bundle beside the old one (the
    owner removes the old one), so a copy started from the old bundle must
    still read as running: otherwise Launch starts a second copy.
    """
    if app.local or not app.launchable:
        return ()
    found = (APPLICATIONS / f"{name}.app" for name in app.legacy_bundles)
    return tuple(str(bundle / "Contents" / "MacOS") for bundle in found if bundle.is_dir())


def bundle_marker(app: ExternalApp, lab_root: Path | None = None) -> str | None:
    """The installed bundle's own process, if there is a bundle."""
    bundle = bundle_path(app, lab_root)
    return None if bundle is None else str(bundle / "Contents" / "MacOS")


def checkout_marker(app: ExternalApp, lab_root: Path) -> str | None:
    """The entry script a source run shows on its command line."""
    if not app.launchable:
        return None
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



def can_bring_to_front(app: ExternalApp, lab_root: Path | None = None) -> bool:
    """Only an installed bundle can be raised.

    A source run is a bare `python`, with no bundle identifier for `open` to
    address; raising it by pid needs System Events, which is assistive access
    the user would have to grant. Better to say so than to fail quietly.

    A web app's "front" is its address, which can always be opened.
    """
    return app.served or bundle_path(app, lab_root) is not None


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
    # known. A frozen bundle is compared with its stamp; a launcher bundle with
    # the root it records, when that is not the working checkout.
    behind: int = 0
    # The commit this build came from, short form, and whether the checkout it
    # came from had uncommitted changes. Empty / False when there is no evidence:
    # never borrowed from another origin.
    commit: str = ""
    dirty: bool = False
    # Why there is no commit, for the tooltip, when `commit` is empty.
    commit_note: str = ""
    # True when a comparison with the working checkout was wanted but this
    # build's commit is not in that checkout's history (another branch, a
    # shallow clone): the count would compare two histories, so none is given.
    behind_unknown: bool = False
    # The recorded project root a launcher bundle runs, when that is not the
    # working checkout. Set even when the root cannot be read (text is empty).
    root: str = ""

    @property
    def known(self) -> bool:
        return bool(self.text)

    @property
    def stale(self) -> bool:
        return self.behind > 0

    @property
    def marker(self) -> str:
        """The tile text: `v<major>.<build>+g<sha7>[-dirty]`, Provisio's grammar.

        Without a commit it is `text` alone, so a missing commit is visible as
        missing rather than filled in from somewhere else.
        """
        if not self.text or not self.commit:
            return self.text
        return f"{self.text}+g{self.commit}" + ("-dirty" if self.dirty else "")


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
        commit_note="this app is outside the lab version scheme, so it has no commit",
    )


_COMMIT_RE = re.compile(r"[0-9a-f]{7,40}")


def installs_dir() -> Path:
    """Where Update now records which commit it installed an app from, for
    apps whose own build stamps no commit (SYNDUSTRYX: its plist pins 0.6.53)."""
    from ..config import SUPPORT_DIR

    return SUPPORT_DIR / "installs"


def _bundle_executable(bundle: Path) -> Path | None:
    try:
        with (bundle / "Contents" / "Info.plist").open("rb") as handle:
            name = plistlib.load(handle).get("CFBundleExecutable")
    except (OSError, plistlib.InvalidFileException, AttributeError):
        return None
    return bundle / "Contents" / "MacOS" / name if isinstance(name, str) and name else None


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
    except OSError:
        return ""
    return digest.hexdigest()


def worktree_tree(project: Path) -> str:
    """A fingerprint of the checkout as it is: the tree `git add -A` would
    write (tracked and untracked files, ignored ones left out), built in a
    throwaway index so the real one is untouched. "" when git cannot tell."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(tmp) / "index"),
                   GIT_OPTIONAL_LOCKS="0")
        try:
            added = subprocess.run(["git", "add", "-A"], cwd=project, env=env,
                                   capture_output=True, timeout=60)
            if added.returncode != 0:
                return ""
            tree = subprocess.run(["git", "write-tree"], cwd=project, env=env,
                                  capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            return ""
    return tree.stdout.strip() if tree.returncode == 0 else ""


def install_tree(app: ExternalApp, bundle: Path) -> str:
    """The checkout fingerprint Update now recorded right after installing
    this bundle, or "" (no record, or the bundle has changed since)."""
    if install_record(app, bundle) is None:
        return ""
    try:
        tree = json.loads((installs_dir() / f"{app.key}.json").read_text()).get("tree")
    except (OSError, ValueError, AttributeError):
        return ""
    return tree if isinstance(tree, str) and _COMMIT_RE.fullmatch(tree) else ""


def install_record(app: ExternalApp, bundle: Path) -> tuple[str, bool] | None:
    """(commit, dirty) Update now recorded for this bundle, or None.

    Only believed while the installed executable is the one recorded: a bundle
    replaced by anything else (a manual install, an older copy put back from
    the Trash) no longer matches, and then nothing is claimed.
    """
    try:
        data = json.loads((installs_dir() / f"{app.key}.json").read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    commit = _stamped_commit(data)
    want = data.get("executable_sha256")
    executable = _bundle_executable(bundle)
    if not commit or not isinstance(want, str) or executable is None:
        return None
    if _sha256(executable) != want:
        return None
    return commit, data.get("dirty") is True


def _stamped_commit(data: dict) -> str:
    commit = data.get("commit")
    commit = commit.strip() if isinstance(commit, str) else ""
    return commit if _COMMIT_RE.fullmatch(commit) else ""


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
            commit=_stamped_commit(data),
            commit_note="" if _stamped_commit(data) else (
                f"{bundle.name}'s build stamp records no commit"
            ),
        )
    return None


# Keyed on the mtime of the repository's HEAD, so a commit invalidates it and
# nothing else does. Without this the tile could not re-read the version on its
# poll: a `git rev-list` per app every three seconds is a subprocess storm for a
# number that changes when you commit.
_COUNT_CACHE: dict[tuple[str, int], int | None] = {}


def _head_stamp(project: Path) -> int | None:
    """When this repository last moved. None when it is not a repository."""
    git_dir = _git_dir(project)
    if git_dir is None:
        return None
    head = git_dir / "HEAD"
    try:
        newest = head.stat().st_mtime_ns
    except OSError:
        return None
    # A commit on a branch rewrites the ref, not HEAD itself, so check both.
    # A worktree keeps its HEAD in its own git dir and its refs in the
    # repository's common one.
    try:
        ref = head.read_text().strip()
        if ref.startswith("ref: "):
            for base in (git_dir, _common_dir(git_dir)):
                target = base / ref[5:]
                if target.exists():
                    newest = max(newest, target.stat().st_mtime_ns)
                    break
    except OSError:
        pass
    return newest


def _git_dir(project: Path) -> Path | None:
    """The repository's git dir: `.git` itself, or where a worktree's points."""
    dot = project / ".git"
    if dot.is_dir():
        return dot
    try:
        text = dot.read_text().strip()
    except OSError:
        return None
    if not text.startswith("gitdir: "):
        return None
    pointed = Path(text[len("gitdir: "):])
    return pointed if pointed.is_absolute() else project / pointed


def _common_dir(git_dir: Path) -> Path:
    try:
        common = Path((git_dir / "commondir").read_text().strip())
    except OSError:
        return git_dir
    return common if common.is_absolute() else git_dir / common


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


_COMMIT_CACHE: dict[tuple[str, int], str] = {}
_SHALLOW_CACHE: dict[tuple[str, int], bool] = {}


def _is_shallow(project: Path) -> bool:
    """A shallow clone's commit count is only the fetched depth, not a build."""
    stamp = _head_stamp(project)
    if stamp is None:
        return False
    key = (str(project), stamp)
    if key not in _SHALLOW_CACHE:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--is-shallow-repository"],
                cwd=project, capture_output=True, text=True, timeout=10,
            )
            _SHALLOW_CACHE[key] = result.stdout.strip() == "true"
        except (OSError, subprocess.SubprocessError):
            _SHALLOW_CACHE[key] = False
    return _SHALLOW_CACHE[key]


def _head_commit(project: Path) -> str:
    """Short hash of HEAD, cached on the same key as the count. "" if unknown."""
    stamp = _head_stamp(project)
    if stamp is None:
        return ""
    key = (str(project), stamp)
    if key in _COMMIT_CACHE:
        return _COMMIT_CACHE[key]
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=7", "HEAD"],
            cwd=project, capture_output=True, text=True, timeout=10,
        )
        commit = result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        commit = ""
    _COMMIT_CACHE[key] = commit
    return commit


# Uncommitted edits move neither HEAD nor its ref, so the key above cannot see
# them. A short time-to-live keeps `git status` to one run per checkout per
# window instead of one per poll. Mostly the GUI thread; Lab Hub's own tile
# verdict (`ui/own_verdict.py`) also fills it from one worker thread. That is
# safe: these caches are plain dict gets and sets, atomic under the GIL, and a
# value computed twice is the same value.
DIRTY_TTL_SECONDS = 10.0
_DIRTY_CACHE: dict[tuple[str, int | None], tuple[float, bool]] = {}


def _is_dirty(project: Path) -> bool:
    now = time.monotonic()
    key = (str(project), _head_stamp(project))
    hit = _DIRTY_CACHE.get(key)
    if hit is not None and now - hit[0] < DIRTY_TTL_SECONDS:
        return hit[1]
    dirty = dirty_checkout(project)
    _DIRTY_CACHE[key] = (now, dirty)
    return dirty


_BEHIND_CACHE: dict[tuple, int | None] = {}


def _commits_behind(source: Path, built_commit: str, built: int | None,
                    current: int | None, *, counts_comparable: bool = True,
                    ) -> int | None:
    """Cached on `source`'s HEAD: a refresh must not re-run git per tile."""
    key = (str(source), _head_stamp(source), built_commit, built, current,
           counts_comparable)
    if key not in _BEHIND_CACHE:
        _BEHIND_CACHE[key] = _commits_behind_uncached(
            source, built_commit, built, current, counts_comparable
        )
    return _BEHIND_CACHE[key]


def _commits_behind_uncached(source: Path, built_commit: str, built: int | None,
                             current: int | None, counts_comparable: bool,
                             ) -> int | None:
    """How many commits `source`'s HEAD is past the build; 0 when level or ahead.

    None when the answer cannot be given: the build's commit is not in
    `source`'s history and `counts_comparable` is False (the counts would come
    from two different repositories). Prefers the commit: a count names
    different code on different branches. `built..HEAD` is 0 for a build that
    already contains HEAD, however many commits it holds that HEAD lacks.
    """
    if built_commit:
        try:
            known = subprocess.run(
                ["git", "cat-file", "-e", f"{built_commit}^{{commit}}"],
                cwd=source, capture_output=True, text=True, timeout=10,
            ).returncode == 0
            if known:
                result = subprocess.run(
                    ["git", "rev-list", "--count", f"{built_commit}..HEAD"],
                    cwd=source, capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0:
                    return max(int(result.stdout.strip()), 0)
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
        if not counts_comparable:
            return None
    if current is not None and built is not None and current > built:
        return current - built
    return 0


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


RELEASE_MANIFEST = "release-manifest.json"


def _release_number(project: Path) -> str | None:
    """The release a project declares for itself, for apps with no lab VERSION.

    SYNDUSTRYX numbers its releases 0.6.x in `release-manifest.json`, the same
    number its bundle's Info.plist carries.
    """
    try:
        raw = json.loads((project / RELEASE_MANIFEST).read_text()).get("version")
    except (OSError, ValueError, AttributeError):
        return None
    return raw.strip().lstrip("vV") if isinstance(raw, str) and raw.strip() else None


def _commits_since_release(project: Path, release: str) -> int | None:
    """Commits made since `release` first appeared in the project's manifest.

    A bundle with no build stamp cannot say which commit it was built from, and
    a signed one cannot be given one. Its release number can still be placed in
    history: the commit that first wrote it into the manifest is where that
    release was cut. None when the history does not show it.
    """
    try:
        found = subprocess.run(
            ["git", "log", "--format=%H", "-S", f'"version": "{release}"',
             "--", RELEASE_MANIFEST],
            cwd=project, capture_output=True, text=True, timeout=15,
        )
        commits = found.stdout.split()
        if found.returncode != 0 or not commits:
            return None
        counted = subprocess.run(
            ["git", "rev-list", "--count", f"{commits[-1]}..HEAD"],
            cwd=project, capture_output=True, text=True, timeout=15,
        )
        return int(counted.stdout.strip()) if counted.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def checkout_version(project: Path) -> Version:
    major = _major(project)
    build = _commit_count(project)
    if major is None or build is None:
        return Version()
    commit = _head_commit(project)
    return Version(
        text=f"v{major}.unknown" if _is_shallow(project) else f"v{major}.{build:03d}",
        origin="checkout",
        detail=f"from the checkout at {project}",
        commit=commit,
        dirty=bool(commit) and _is_dirty(project),
        commit_note="" if commit else f"git could not name HEAD in {project}",
    )


def _same_dir(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return a == b


def version(app: ExternalApp, lab_root: Path) -> Version:
    """The version of whatever this tile would launch.

    Follows the launch path rather than guessing: a frozen bundle answers with
    the build stamped into it, a launcher bundle answers with the checkout it
    runs, and a tile with no bundle answers with the checkout it would start.
    A frozen bundle that carries no stamp answers *nothing* — borrowing the
    checkout's number there would describe code that is not what opens.

    A project with no launch command opens nothing, so its version is simply
    its checkout's (Kaila's tile), never a bundle's.
    """
    if not app.launchable:
        project = source_dir(app, lab_root)
        return checkout_version(project) if project is not None else Version()
    bundle = bundle_path(app, lab_root)
    project = source_dir(app, lab_root)
    if bundle is not None and not bundle_runs_checkout(bundle):
        stamped = _stamped_version(bundle)
        if stamped is None and (project is None or _major(project) is None):
            # Outside the lab's scheme (SYNDUSTRYX): the bundle's own release
            # number is the version. Where the source declares releases too,
            # place the bundle's in its history to say how far behind it is.
            plist = _plist_version(bundle)
            record = install_record(app, bundle) if plist.known else None
            if record is not None and project is not None:
                commit, dirty = record
                behind = _commits_behind(project, commit, None, None,
                                         counts_comparable=False)
                return replace(
                    plist, commit=commit[:7], dirty=dirty, commit_note="",
                    detail=f"{plist.detail}; Lab Hub's Update now installed it "
                           f"from commit {commit[:7]}",
                    behind=behind or 0, behind_unknown=behind is None,
                )
            release = _release_number(project) if project is not None else None
            if plist.known and release is not None and plist.text.lstrip("v") != release:
                since = _commits_since_release(project, plist.text.lstrip("v"))
                if since:
                    return replace(plist, behind=since)
            return plist
        if stamped is None:
            return Version()
        # A frozen bundle is only as new as its last build. Saying so is the
        # whole point of the number: "is the app I am about to open the one I
        # built?" — and the answer here is often no, because committing to a
        # project does not rebuild it.
        if project is not None:
            behind = _commits_behind(
                project, stamped.commit, _stamped_build(bundle),
                _commit_count(project), counts_comparable=not stamped.commit,
            )
            if behind is None:
                return replace(stamped, behind_unknown=True)
            if behind:
                return replace(stamped, behind=behind)
        return stamped
    if bundle is not None:
        # A launcher bundle runs the root it records, which is not always the
        # working checkout: Provisio's runs a release clone. Read that root,
        # and say how far the working checkout has moved past it. A root that
        # cannot be read is *unknown*, never the working checkout's build: that
        # would name code the Launch button does not open.
        root = recorded_project_root(bundle)
        if root is not None and (
            project is None or not _same_dir(root, project)
        ):
            return _recorded_root_version(bundle, root, app, project)
    if project is not None:
        return checkout_version(project)
    return Version()


def _recorded_root_version(
    bundle: Path, root: Path, app: ExternalApp, project: Path | None
) -> Version:
    if app.entry is None:
        return Version()  # unreachable: `version` returns before it for these
    unreadable = None
    if not (root / app.entry).is_file():
        unreadable = "is missing or has no " + app.entry
    elif _head_stamp(root) is None:
        unreadable = "is not a git checkout"
    elif _major(root) is None:
        unreadable = "has no VERSION arc"
    if unreadable is not None:
        return Version(
            origin="bundle", root=str(root),
            detail=f"{bundle.name} runs {root}, which {unreadable}",
        )
    installed = replace(
        checkout_version(root),
        detail=f"the root {bundle.name} runs, {root}",
        root=str(root),
    )
    if not installed.known:
        return Version(
            origin="bundle", root=str(root),
            detail=f"{bundle.name} runs {root}, whose build git could not read",
        )
    if project is None:
        return installed
    behind = _commits_behind(
        project, installed.commit, _commit_count(root),
        _commit_count(project), counts_comparable=False,
    )
    if behind is None:
        # The root holds commits the working checkout lacks (it may be ahead).
        # Ask the root's own history about the working checkout's HEAD instead.
        behind = _behind_in_root(root, project)
    if behind is None:
        return replace(installed, behind_unknown=True)
    return replace(installed, behind=behind) if behind else installed


_ROOT_BEHIND_CACHE: dict[tuple, int | None] = {}


def _behind_in_root(root: Path, project: Path) -> int | None:
    key = (str(root), _head_stamp(root), str(project), _head_stamp(project))
    if key not in _ROOT_BEHIND_CACHE:
        _ROOT_BEHIND_CACHE[key] = _behind_in_root_uncached(root, project)
    return _ROOT_BEHIND_CACHE[key]


def _behind_in_root_uncached(root: Path, project: Path) -> int | None:
    """Commits the working checkout is past `root`, counted inside `root`'s repo.

    Works when the working checkout's HEAD is known to the root (the root is
    level or ahead, or they diverged from a shared commit). None when it is not.
    """
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=project,
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        if not _COMMIT_RE.fullmatch(head):
            return None
        known = subprocess.run(
            ["git", "cat-file", "-e", f"{head}^{{commit}}"], cwd=root,
            capture_output=True, text=True, timeout=10,
        ).returncode == 0
        if not known:
            return None
        counted = subprocess.run(
            ["git", "rev-list", "--count", f"HEAD..{head}"], cwd=root,
            capture_output=True, text=True, timeout=10,
        )
        return int(counted.stdout.strip()) if counted.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


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


def needs_terminal(script: Path) -> bool:
    """Whether the install script refuses to run without a terminal.

    Provisio's `install_app.sh` checks `[ ! -t 0 ]` and stops: it must be run
    by hand, because it asks the owner to type "install". Lab Hub's Update now
    runs commands with no terminal, so such a script can only fail there — it
    is handed over instead. Read from the script, like the install flag.
    """
    try:
        text = script.read_text()
    except OSError:
        return False
    return "-t 0" in text


RELEASE_RUNBOOK = "docs/RUNBOOK-release.md"
# Where a project with no build script Lab Hub knows says how to build it,
# first match wins (SYNDUSTRYX: desktop/BUILDING.md).
BUILD_GUIDES = ("desktop/BUILDING.md", "BUILDING.md", "docs/BUILDING.md",
                RELEASE_RUNBOOK, "docs/RELEASE.md", "RELEASE.md")


def build_guide(project: Path) -> Path | None:
    for name in BUILD_GUIDES:
        candidate = project / name
        if candidate.is_file():
            return candidate
    return None


def registered_build_command(app: ExternalApp, project: Path) -> str | None:
    """Build with the app's own `build` command and install `build_output`.

    The installed bundle is moved to the Trash (dated, so it can be put back)
    only after the build produced a new one; then the new one is copied in.
    """
    if not app.build or not app.build_output:
        return None
    built = shlex.quote(app.build_output)
    bundle = APPLICATIONS / f"{app.bundle_name}.app"
    installed = shlex.quote(str(bundle))
    trash = f'"$HOME/.Trash/{app.bundle_name} before update $(date +%Y-%m-%d-%H%M%S).app"'
    records = shlex.quote(str(installs_dir()))
    record = shlex.quote(str(installs_dir() / f"{app.key}.json"))
    plist = shlex.quote(str(bundle / "Contents" / "Info.plist"))
    # The build stamps no commit, so record the one it was built from (and
    # whether the checkout had changes before the build touched it), tied to
    # the installed executable's hash: install_record() reads it back.
    # `tree` fingerprints the checkout as the build left it: SYNDUSTRYX's build
    # rewrites its own release-manifest.json, which must not read as "changes
    # not in this build" (worktree_tree computes the same in Python).
    stamp = (
        f"mkdir -p {records} && "
        f"exe=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleExecutable' {plist}) && "
        f"idx=$(mktemp -u) && GIT_INDEX_FILE=\"$idx\" git add -A && "
        f"tree=$(GIT_INDEX_FILE=\"$idx\" git write-tree) && rm -f \"$idx\" && "
        f"printf '{{\"commit\": \"%s\", \"dirty\": %s, \"tree\": \"%s\", "
        f"\"executable_sha256\": \"%s\"}}\\n' "
        f"\"$commit\" \"$dirty\" \"$tree\" "
        f"\"$(shasum -a 256 {installed}/Contents/MacOS/\"$exe\" | cut -d' ' -f1)\" > {record}"
    )
    # A build may rewrite tracked files of its own (SYNDUSTRYX stamps
    # `built_at` into release-manifest.json). Left behind, Resolve commits
    # them, the source moves a commit past the install, and the tile reads
    # "1 behind" after every update. So tracked files the build changed, and
    # only those (`$pre` lists what was already changed before it), are put
    # back to HEAD once the bundle exists. Edits made before the build stay.
    restore = (
        'git diff --name-only HEAD | grep -vxF -f "$pre" | '
        'while IFS= read -r f; do git checkout -q HEAD -- "$f"; done; rm -f "$pre"'
    )
    return (
        f"cd {shlex.quote(str(project))} && commit=$(git rev-parse HEAD) && "
        f"dirty=$([ -n \"$(git status --porcelain)\" ] && echo true || echo false) && "
        f"pre=$(mktemp) && git diff --name-only HEAD > \"$pre\" && "
        f"{app.build} && test -d {built} && {{ {restore}; }} && "
        f"{{ [ ! -e {installed} ] || mv {installed} {trash}; }} && "
        f"ditto {built} {installed} && {stamp}"
    )


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
    # The installer must be run by hand, in a terminal: Update now skips it and
    # the report hands it over instead.
    by_hand: bool = False
    # The app runs a release clone that is behind: `command` moves the clone
    # forward and nothing here runs an installer or runs that command.
    forward: bool = False
    # The checkout, for Open in Terminal, and the doc that says how to build
    # it when Lab Hub has no command for it.
    project: Path | None = None
    guide: Path | None = None
    # Lab Hub's own row (spec self-update): its command only builds, and Lab
    # Hub restarts to install the result.
    restarts: bool = False

    @property
    def needs_rebuild(self) -> bool:
        return self.verdict in ("behind", "uncommitted")

    @property
    def runs_in_app(self) -> bool:
        """A rebuild Update now can run itself."""
        return (self.needs_rebuild and bool(self.command)
                and not self.by_hand and not self.forward)


def build_status(app: ExternalApp, lab_root: Path) -> BuildStatus:
    """Whether what this tile would open is the newest thing available, and
    how to bring it up to date.

    A launcher bundle that records a root other than the working checkout
    (Provisio: its release clone) is installed from that root, never from the
    working checkout — its installer refuses the main checkout. An installer
    that needs a terminal is marked `by_hand`, so Update now does not run it
    only to watch it refuse.
    """
    if not app.launchable:
        # Without this a checkout-origin version would read "runs the checkout
        # directly", which is untrue of a thing that runs nothing.
        return BuildStatus(
            app, version(app, lab_root), "unknown",
            "it has no launch command, so there is no build to compare.",
        )
    row = _build_status(app, lab_root)
    script, command = row.script, row.command
    root = Path(row.version.root) if row.version.root else None
    if root is not None and root.is_dir():
        script = build_script(root)
        command = install_command(root, script) if script is not None else None
    by_hand = script is not None and needs_terminal(script)
    note = row.note
    forward = False
    if root is not None and root.is_dir() and row.needs_rebuild:
        # The installer builds from the clone it sits in, so on a clone that is
        # behind it rebuilds the same old build. The clone has to move first,
        # and that is a release step (CI, legal check) the owner takes: Lab Hub
        # shows the command and runs nothing in the clone.
        quoted = shlex.quote(str(root))
        command = (f"git -C {quoted} fetch origin && "
                   f"git -C {quoted} merge --ff-only origin/main")
        by_hand, forward = False, True
        runbook = root / RELEASE_RUNBOOK
        around = (f"Follow {runbook} for the steps around it" if runbook.is_file()
                  else "Use the project's release runbook for the steps around it")
        count = (f"{row.version.behind} commit"
                 f"{'' if row.version.behind == 1 else 's'}")
        note = (f"{note} Its release clone {root} is {count} behind the source; "
                "the installer would rebuild that same clone and change nothing. "
                f"Move the clone forward instead. {around}: CI and the legal "
                "check before it, dependencies and the selftest after. Use a "
                "commit that passed CI instead of origin/main if you have one, "
                "and merge and push the source to main first if it is not "
                "there. Then press Refresh.")
    if row.needs_rebuild and by_hand:
        guide = (root or source_dir(app, lab_root) or Path()) / RELEASE_RUNBOOK
        steps = (f" Follow {guide} first." if guide.is_file() else "")
        note = (f"{note} Its installer only runs by hand, in a terminal, so "
                f"Update now leaves it to you.{steps}")
    project = source_dir(app, lab_root)
    guide = None
    if row.needs_rebuild and command is None:
        guide = build_guide(project) if project is not None else None
        how = f"follow {guide}" if guide else "rebuild it the project's own way"
        note = (f"{note} Lab Hub has no rebuild command for it: none of "
                f"{', '.join(BUILD_SCRIPTS)} exists, so {how}.")
    return replace(row, script=script, command=command, by_hand=by_hand,
                   forward=forward, note=note, project=project, guide=guide)


def _build_status(app: ExternalApp, lab_root: Path) -> BuildStatus:
    found = version(app, lab_root)
    project = source_dir(app, lab_root)
    script = build_script(project) if project is not None else None
    command = (
        install_command(project, script)
        if project is not None and script is not None
        else registered_build_command(app, project) if project is not None
        else None
    )

    if project is None:
        return BuildStatus(
            app, found, "missing",
            "no checkout here, so there is nothing to compare it against.",
        )
    if (
        found.origin == "bundle"
        and _major(project) is None
        and _release_number(project) is None
    ):
        return BuildStatus(
            app, found, "unknown",
            "its release number comes from the bundle; it does not use the "
            "lab's version scheme, so there is nothing to compare it against.",
            script, command,
        )
    if found.root and not found.known:
        return BuildStatus(
            app, found, "unknown",
            f"{found.detail}; Launch would not open the working checkout, so "
            "its build cannot be compared with the source.", script, command,
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
    if found.behind_unknown:
        where = f"the root it runs, {found.root}" if found.root else "its stamp"
        return BuildStatus(
            app, found, "unknown",
            f"{where} is at {found.commit}, a commit the working checkout does "
            "not have, so how far behind it is cannot be told.", script, command,
        )
    if found.stale:
        return BuildStatus(
            app, found, "behind",
            f"built at {found.text}, but the source is {commits_further(found.behind)}.",
            script, command,
        )
    if found.root:
        return BuildStatus(
            app, found, "current",
            f"runs {found.root} and is level with the source.", script, command,
        )
    if found.origin == "checkout":
        # It runs the source, so it opens whatever the source says right now —
        # uncommitted edits included. It cannot be out of date.
        return BuildStatus(
            app, found, "current",
            "runs the checkout directly, so it is always what the source says.",
            script, command,
        )
    if dirty_checkout(project):
        bundle = bundle_path(app, lab_root)
        recorded = install_tree(app, bundle) if bundle is not None else ""
        if recorded and recorded == worktree_tree(project):
            return BuildStatus(
                app, found, "current",
                "matches the checkout it was built from, including the files "
                "its own build rewrites.", script, command,
            )
        return BuildStatus(
            app, found, "uncommitted",
            "level with the last commit, but the checkout has uncommitted "
            "changes that are not in this build.", script, command,
        )
    return BuildStatus(app, found, "current", "matches its source.", script, command)


def build_report(
    lab_root: Path, apps: tuple[ExternalApp, ...] | None = None
) -> tuple[BuildStatus, ...]:
    chosen = apps or registry.current().apps
    return tuple(build_status(app, lab_root) for app in chosen if app.launchable)


def status(app: ExternalApp, lab_root: Path) -> tuple[str, str]:
    """A (state, detail) pair for the UI.

    State is installed/built/source/server/missing. *Built* is a bundle found
    in the checkout's `bundle_dir` rather than in /Applications; *server* is a
    web app's checkout, which is how it always runs, so not a lesser state the
    way *source* is.
    """
    if not app.launchable:
        project = source_dir(app, lab_root)
        if project is not None:
            return "source", str(project)
        return "missing", f"no checkout at {lab_root / app.project}"
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

    if not app.launchable:
        return Readiness(
            state, detail, "it has no launch command, so there is nothing to start"
        )

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
            f"nothing built to launch: no {app.bundle_name}.app in {where}, and its "
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
