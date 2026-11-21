"""Lab Hub updates itself: its own build row, and the helper that swaps the bundle.

Spec `docs/specs/self-update.md`, ADR 0003. Qt-free, like the rest of this
package.

A running app cannot safely overwrite its own bundle: `build_app.sh --install`
deletes `/Applications/Lab Hub.app` while the process may still load files from
it. So Update now builds without `--install` (the script's own self-test still
runs), and it builds in a private clone of the shared checkout at the commit
`main` was at when the row was shown (spec §11, ADR 0006): other sessions'
edits and commits there can neither block nor enter the update. As soon as that
build passes Lab Hub copies it out of the clone into a folder of its own
(`stage_build`), checked against that same commit. Once Lab Hub has quit, a
detached helper does the swap:

1. wait for the old process to exit (it must, or `SingleInstance` would turn
   the new copy away), replacing nothing if it does not;
2. copy the staged bundle next to the installed one;
3. rename the installed one aside as the single previous build, and the new
   one into place, each only onto a path that no longer exists;
4. self-test the installed copy, and put the previous build back if it fails;
5. record the outcome and start whatever is installed. A state it cannot
   repair is recorded as `broken`, with where the previous build is, and
   nothing is opened.

The helper is a fixed script in this file. It takes its values as positional
parameters, all computed and checked here, and runs with a fixed environment
and absolute tool paths; nothing it runs comes from a checkout's or a build's
output.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass, replace
from pathlib import Path

from .config import SUPPORT_DIR
from .launcher import ExternalApp, build_status, source_dir
from .launcher.state import BuildStatus

APP_BUNDLE = "Lab Hub.app"
EXECUTABLE = "Lab Hub"
# Module constants, never arguments: tests point them at temporary folders and
# a shim, the shipped app uses these.
APPLICATIONS = Path("/Applications")
UPDATE_DIR = SUPPORT_DIR / "update"
OPEN = "/usr/bin/open"
WAIT_S = 60  # for the old Lab Hub to quit
LATE_WAIT_S = 600  # after that, how long to keep watching to reopen it
SELFTEST_S = 120  # for the installed copy's self-test
DIST = "dist.noindex"
MAIN_BRANCH = "main"
GIT_TIMEOUT_S = 10
OUTCOME_MAX_BYTES = 4096
_SHA = re.compile(r"[0-9a-f]{40}")
_UNSET = object()  # "ask the running process", as opposed to an explicit None

# Lab Hub as a build-report row. It has no registry entry and no menu bar entry;
# its Apps tile is `OWN_TILE` below. It keeps `entry="main.py"` because
# `self_status` compares the installed bundle against this checkout. Its key
# and project are in `registry.RESERVED`, so no registry file can define them.
SELF = ExternalApp(
    key="lab_hub",
    name="Lab Hub",
    project="lab_hub",
    entry="main.py",
    summary="This app.",
)

# Lab Hub's own tile on the Apps page (spec `apps-discovery` §5, ADR 0007):
# built here, never read from a registry file, so it can be neither hidden nor
# edited. No entry, so it is the no-launch kind: no Launch, Bring to front,
# Stop or Quit, and it is in no group, so the tray and Settings never see it.
OWN_TILE = ExternalApp(
    key="lab_hub",
    name="Lab Hub",
    project="lab_hub",
    entry=None,
    summary="This app: the launcher for the lab's projects.",
)

_RUNS_DIRECTLY = "runs the checkout directly"


# -- which copy is running --------------------------------------------------
def running_bundle(executable: str | None = None, frozen: bool | None = None) -> Path | None:
    """The `.app` this process runs from, or None when it runs from source."""
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    if not frozen:
        return None
    exe = Path(executable or sys.executable)
    try:
        exe = exe.resolve()
    except OSError:
        pass
    for parent in exe.parents:
        if parent.suffix == ".app":
            return parent
    return None


def installed_target() -> Path:
    return APPLICATIONS / APP_BUNDLE


def _same(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return a == b


# -- the checkout -----------------------------------------------------------
def _git(project: Path, *args: str) -> tuple[int | None, str]:
    """(exit code, stdout). None for the code when git could not run at all."""
    try:
        result = subprocess.run(
            ["git", *args], cwd=project, capture_output=True, text=True,
            timeout=GIT_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return None, ""
    return result.returncode, result.stdout.strip()


def main_commit(project: Path) -> str | None:
    """The full SHA `main` points at in the shared checkout, or None. Only the
    ref is read: the checkout's branch, edits and status do not matter, since
    Update now builds this commit in a clone of its own (spec §11)."""
    code, out = _git(project, "rev-parse", "--verify", "--quiet", f"refs/heads/{MAIN_BRANCH}^{{commit}}")
    return out if code == 0 and _SHA.fullmatch(out) else None


def snapshot() -> Path:
    """The clone Update now builds Lab Hub in, under `update/snapshot/`."""
    return UPDATE_DIR / "snapshot" / SELF.project


def build_command(project: Path, commit: str) -> str:
    """Clone the shared checkout privately, check out `commit` and build there
    (self-test included, no install: the helper installs after Lab Hub quits).

    A clone, not a worktree: a worktree is registered in the shared repository,
    where Land and Tidy would list it and could remove it mid-build (ADR 0006).
    A local clone hard-links the objects and copies none of the repository's
    hooks or config; clone and checkout run with hooks and templates off, so
    no global hook runs either (review P3-1). The folders above the snapshot
    must not be symlinks, so `rm -rf` cannot be pointed elsewhere (security
    P3-1)."""
    if not _SHA.fullmatch(commit):
        raise ValueError(f"not a full commit: {commit!r}")
    q, snap = shlex.quote, snapshot()
    update, parent = q(str(snap.parent.parent)), q(str(snap.parent))
    return (f"[ ! -L {update} ] && [ ! -L {parent} ] && /bin/mkdir -p {parent} && "
            f"/bin/chmod 700 {update} {parent} && /bin/rm -rf {q(str(snap))} && "
            f"git -c core.hooksPath=/dev/null clone --template= --quiet --no-checkout "
            f"-- {q(str(project))} {q(str(snap))} && "
            f"git -C {q(str(snap))} -c core.hooksPath=/dev/null "
            f"-c advice.detachedHead=false checkout --quiet --detach {commit} && "
            f"/bin/ln -s {q(str(project / '.venv'))} {q(str(snap / '.venv'))} && "
            f"cd {q(str(snap))} && ./build_app.sh")


_COMMIT_IN_COMMAND = re.compile(r" checkout --quiet --detach ([0-9a-f]{40}) && ")


def planned_commit(command: str | None, project: Path) -> str | None:
    """The commit a Lab Hub build command builds, or None when the command is
    not exactly one `build_command` makes for this checkout."""
    found = _COMMIT_IN_COMMAND.search(command or "")
    if found is None or command != build_command(project, found.group(1)):
        return None
    return found.group(1)


def built_bundle() -> Path:
    return snapshot() / DIST / APP_BUNDLE


def staged_bundle() -> Path:
    return UPDATE_DIR / "staged" / APP_BUNDLE


# -- the build-report row ---------------------------------------------------
def verdict_line(row: BuildStatus) -> str:
    """One line for Lab Hub's tile from its build row (`self_status`).

    The words are the build report's own: "up to date", "N commits older than
    its source", "runs the checkout directly". A row that could not be judged
    says what `build_status` said. The tile's tooltip for the behind case is
    the UI's (spec §7); it has no Update now button, only a pointer to Check
    builds.
    """
    if row.verdict == "behind":
        count = row.version.behind
        if count > 0:
            return f"{count} commit{'' if count == 1 else 's'} older than its source"
        return "older than its source"
    if row.verdict == "current":
        if row.note.startswith(_RUNS_DIRECTLY):
            return _RUNS_DIRECTLY
        return "up to date"
    return row.note


def self_status(lab_root: Path, *, running: object = _UNSET) -> BuildStatus:
    """Lab Hub's own row: the installed build against its checkout, and the
    command Update now may run for it (None, with the reason in the note, when
    it may not)."""
    bundle = running_bundle() if running is _UNSET else running
    project = source_dir(SELF, lab_root)
    if bundle is None:
        # It runs its checkout, so it is whatever the source says (spec §2.7),
        # like every other app that runs from source.
        row = build_status(SELF, lab_root)
        return replace(
            row, verdict="current", restarts=True, command=None, by_hand=False,
            forward=False, guide=None,
            note=f"{_RUNS_DIRECTLY}, so it is always what the source "
                 "says; Update now has nothing to restart.")
    row = replace(build_status(SELF, lab_root), restarts=True)

    def held(reason: str) -> BuildStatus:
        note = row.note
        if row.needs_rebuild:
            note = f"{note} Update now leaves Lab Hub alone: {reason}."
        return replace(row, command=None, by_hand=False, forward=False,
                       guide=None, note=note)

    if not _same(bundle, installed_target()):
        return held(f"this copy runs from {bundle}, not {installed_target()}")
    installed = row.version.commit
    if project is None or row.verdict not in ("current", "behind", "uncommitted"):
        return replace(row, command=None)
    if not installed:
        return held("the installed build does not record its commit; build and "
                    "install it once by hand with ./build_app.sh --install")
    commit = main_commit(project)
    if commit is None:
        return held(f"git could not read {MAIN_BRANCH} in {project}")
    if commit.startswith(installed):
        # Level with main: edits and other branches in the checkout are in no
        # build until they are on main, so they are no reason to update (§11.2.4).
        note = row.note
        if row.needs_rebuild:
            note = (f"{note} It is level with {MAIN_BRANCH} ({commit[:7]}), which is "
                    f"all Update now builds: uncommitted edits and other branches "
                    f"are in no build until they are committed to {MAIN_BRANCH}.")
        return replace(row, verdict="current", command=None, note=note)
    if _git(project, "merge-base", "--is-ancestor", installed, commit)[0] == 1:
        # Installed from commits main does not have (a branch built by hand):
        # building main would replace it with an older build (review P2-1).
        ahead = _git(project, "merge-base", "--is-ancestor", commit, installed)[0] == 0
        reason = (f"the installed build ({installed}) has commits {MAIN_BRANCH} "
                  f"({commit[:7]}) does not, and Update now builds only "
                  f"{MAIN_BRANCH}, so it would replace it with an older build")
        if ahead:
            return replace(row, verdict="current", command=None,
                           note=f"built from {installed}, ahead of {MAIN_BRANCH}. "
                                f"Update now leaves Lab Hub alone: {reason}.")
        return held(reason)
    note, version = row.note, row.version
    code, head = _git(project, "rev-parse", "HEAD")
    if row.verdict != "behind" or code != 0 or head != commit:
        code, count = _git(project, "rev-list", "--count", f"{installed}..{commit}")
        behind = int(count) if code == 0 and count.isdigit() else 0
        further = (f"{behind} commit{'' if behind == 1 else 's'} further on" if behind
                   else f"at {commit[:7]}")
        note = f"built at {version.text or installed}, but {MAIN_BRANCH} is {further}."
        version = replace(version, behind=behind)
    row = replace(row, verdict="behind", note=note, version=version)
    code, _ = _git(project, "cat-file", "-e", f"{commit}:build_app.sh")
    if code != 0:
        return held(f"{MAIN_BRANCH} ({commit[:7]}) has no build_app.sh")
    return replace(row, command=build_command(project, commit), by_hand=False,
                   forward=False, guide=None,
                   note=f"{note} Update now builds {commit[:7]}.")


# -- staging the build that passed ------------------------------------------
@dataclass(frozen=True)
class Staged:
    bundle: Path
    version: str  # v<major>.<build>, from the bundle's own stamp
    commit: str


def _stamp(bundle: Path) -> dict | None:
    for holder in ("Resources", "Frameworks"):
        try:
            data = json.loads((bundle / "Contents" / holder / "_build_info.json").read_text())
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            return data
    return None


def _no_symlinks(path: Path) -> bool:
    return os.path.realpath(path) == str(path.absolute())


def stage_build(commit: str | None, *, ditto: str = "/usr/bin/ditto") -> Staged:
    """Copy the bundle `build_app.sh` just built and self-tested out of the
    snapshot, if it was built from `commit` (the one Update now recorded), then
    remove the snapshot. The shared checkout is not read: what it holds now
    does not change what is installed. Raises ValueError with the reason."""
    if not commit or not _SHA.fullmatch(commit):
        raise ValueError("the build command is not one Lab Hub made")
    snap, src = snapshot(), built_bundle()
    if not _no_symlinks(src):
        raise ValueError(f"{src} goes through a symlink")
    if not (src / "Contents" / "MacOS" / EXECUTABLE).is_file():
        raise ValueError(f"no new build at {src}")
    code, head = _git(snap, "rev-parse", "HEAD")
    if code != 0 or head != commit:
        raise ValueError(
            f"the build folder is at {head[:7] or 'an unknown commit'}, "
            f"not {commit[:7]}")
    stamp = _stamp(src) or {}
    stamped = str(stamp.get("commit") or "")
    if len(stamped) < 7 or not commit.startswith(stamped):
        raise ValueError(
            f"the new build is from {stamped or 'an unknown commit'}, "
            f"not {commit[:7]}")
    try:
        version = f"v{stamp['major']}.{int(stamp['build']):03d}"
    except (KeyError, TypeError, ValueError):
        version = "the new build"
    staged = staged_bundle()
    staged.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    subprocess.run(["/bin/rm", "-rf", str(staged)], check=False, timeout=120)
    if staged.exists() or staged.is_symlink():
        raise ValueError(f"could not clear {staged}")
    copied = subprocess.run([ditto, str(src), str(staged)], capture_output=True,
                            text=True, timeout=600)
    if copied.returncode != 0:
        raise ValueError(f"could not copy the new build: {copied.stderr.strip()[:200]}")
    # Best effort: the build is staged, and the next Update now clears the
    # snapshot anyway (review P3-3). Checked again, as `ditto` can take minutes
    # (security P3-1).
    try:
        if _no_symlinks(snap):
            subprocess.run(["/bin/rm", "-rf", str(snap)], check=False, timeout=120)
    except (OSError, subprocess.SubprocessError):
        pass
    return Staged(staged, version, stamped)


# -- the helper -------------------------------------------------------------
# bash 3.2 (macOS's own). Positional parameters, nothing interpolated:
#  $1 pid   $2 staged bundle   $3 installed bundle   $4 previous-build path
#  $5 outcome file   $6 version being installed   $7 `open`
#  $8 wait s   $9 late wait s   $10 self-test s
HELPER_SCRIPT = r'''
set -u
umask 077
PATH=/usr/bin:/bin:/usr/sbin:/sbin
pid="$1"; src="$2"; target="$3"; backup="$4"; outcome="$5"; version="$6"
opener="$7"; wait_s="$8"; late_s="$9"; selftest_s="${10}"
staged="$target.updating"
lock="$(dirname "$outcome")/lock"
written=0
swapping=0  # 1 once the installed app may have been touched
say() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*"; }
finish() {
  printf '%s\n%s\n%s\n' "$1" "$2" "$version" > "$outcome"
  written=1
  say "$1: $2"
}
on_exit() {
  if [ "$written" = 0 ] && [ "$swapping" = 1 ]; then
    finish broken "the update stopped part-way; the previous build is at $backup"
  elif [ "$written" = 0 ]; then
    finish not_replaced "the update stopped before anything was replaced"
  fi
  [ "${have_lock:-0}" = 1 ] && rm -rf "$lock"
}
trap on_exit EXIT
# Removes a path completely or says it could not (Finder can drop a .DS_Store
# in mid-walk, so once more before giving up).
gone() {
  rm -rf "$1" 2>/dev/null || rm -rf "$1" 2>/dev/null
  [ ! -e "$1" ] && [ ! -L "$1" ]
}
free() { [ ! -e "$1" ] && [ ! -L "$1" ]; }

for n in "$wait_s" "$late_s" "$selftest_s" "$pid"; do
  case "$n" in ''|*[!0-9]*) finish not_replaced "refused: a bad number"; exit 2 ;; esac
done
case "$target" in */"Lab Hub.app") ;; *) finish not_replaced "refused: $target is not a Lab Hub.app"; exit 2 ;; esac
case "$backup" in */"Lab Hub.app") ;; *) finish not_replaced "refused: $backup is not a Lab Hub.app"; exit 2 ;; esac
case "$src" in */"Lab Hub.app") ;; *) finish not_replaced "refused: $src is not a Lab Hub.app"; exit 2 ;; esac
if [ "$src" = "$target" ] || [ -L "$src" ] || [ -L "$target" ]; then
  finish not_replaced "refused: the new build and the installed app are not two plain bundles"; exit 2
fi
if [ ! -x "$src/Contents/MacOS/Lab Hub" ]; then
  finish not_replaced "the new build at $src has no executable"; exit 1
fi

if mkdir "$lock" 2>/dev/null; then
  have_lock=1
  echo "$$" > "$lock/pid"
else
  other="$(cat "$lock/pid" 2>/dev/null)"
  case "$other" in ''|*[!0-9]*) other="" ;; esac
  if [ -n "$other" ] && kill -0 "$other" 2>/dev/null; then
    finish not_replaced "another update is already running"; exit 1
  fi
  rm -rf "$lock" && mkdir "$lock" && have_lock=1 && echo "$$" > "$lock/pid" || {
    finish not_replaced "could not take the update lock"; exit 1; }
fi

say "waiting for Lab Hub ($pid) to quit"
ticks=0
while kill -0 "$pid" 2>/dev/null; do
  if [ "$ticks" -ge $((wait_s * 4)) ]; then
    finish not_replaced "the old Lab Hub ($pid) did not quit within ${wait_s}s; nothing was replaced"
    # It was quitting: if it does go, start it again rather than leave none.
    late=0
    while kill -0 "$pid" 2>/dev/null && [ "$late" -lt $((late_s * 4)) ]; do
      sleep 0.25; late=$((late + 1))
    done
    kill -0 "$pid" 2>/dev/null || "$opener" "$target"
    exit 1
  fi
  sleep 0.25
  ticks=$((ticks + 1))
done

say "copying $src"
if ! gone "$staged"; then
  finish not_replaced "could not clear $staged; the installed app is untouched"
  "$opener" "$target"; exit 1
fi
if ! /usr/bin/ditto "$src" "$staged"; then
  gone "$staged"
  finish not_replaced "could not copy the new build into place; the installed app is untouched"
  "$opener" "$target"; exit 1
fi

mkdir -p "$(dirname "$backup")"
swapping=1
if ! gone "$backup"; then
  gone "$staged"
  finish not_replaced "could not clear the previous build at $backup; the installed app is untouched"
  "$opener" "$target"; exit 1
fi
had_old=0
if [ -e "$target" ]; then
  if ! mv "$target" "$backup" || ! free "$target"; then
    gone "$staged"
    if free "$target" && [ -e "$backup" ]; then mv "$backup" "$target"; fi
    if [ -x "$target/Contents/MacOS/Lab Hub" ]; then
      finish not_replaced "could not move the installed app aside; it is untouched"
      "$opener" "$target"
    else
      finish broken "could not move the installed app aside; the previous build is at $backup"
    fi
    exit 1
  fi
  had_old=1
fi

restore() {
  # The new build failed: do not keep it staged (best effort; the next
  # Update now clears it anyway). Then put the previous build back, only onto
  # a path that is now free.
  gone "$src" || say "could not remove the failed build at $src"
  if [ "$had_old" = 1 ] && gone "$target" && mv "$backup" "$target" \
     && [ -x "$target/Contents/MacOS/Lab Hub" ]; then
    finish rolled_back "$1; the previous build is back"
    "$opener" "$target"
  elif [ "$had_old" = 1 ]; then
    finish broken "$1, and the previous build could not be put back; it is at $backup"
  else
    gone "$target"
    finish broken "$1, and there was no previous build to put back"
  fi
}

if ! mv "$staged" "$target"; then
  gone "$staged"
  restore "could not move the new build into place"
  exit 1
fi

say "self-testing $target"
"$target/Contents/MacOS/Lab Hub" --selftest &
test_pid=$!
ticks=0
while kill -0 "$test_pid" 2>/dev/null; do
  if [ "$ticks" -ge $((selftest_s * 4)) ]; then
    kill -9 "$test_pid" 2>/dev/null
    say "the self-test did not finish within ${selftest_s}s"
    break
  fi
  sleep 0.25
  ticks=$((ticks + 1))
done
if wait "$test_pid"; then
  touch "$target"
  gone "$src"
  finish ok "installed and self-tested"
  "$opener" "$target"
else
  restore "the installed copy failed its self-test"
  exit 1
fi
'''


@dataclass(frozen=True)
class HelperPaths:
    pid: int
    src: Path
    target: Path
    backup: Path
    log: Path
    outcome: Path
    version: str = ""


def helper_paths(staged: Staged, *, running: object = _UNSET,
                 pid: int | None = None) -> HelperPaths:
    """Every value the helper gets, checked. Raises ValueError with the reason."""
    bundle = running_bundle() if running is _UNSET else running
    target = installed_target()
    if bundle is None:
        raise ValueError("Lab Hub runs from source, so there is no bundle to replace")
    if not _same(bundle, target):
        raise ValueError(f"this copy runs from {bundle}, not {target}")
    src = staged.bundle
    if src != staged_bundle() or not _no_symlinks(src):
        raise ValueError(f"the new build is not the staged copy at {staged_bundle()}")
    if _same(src, target):
        raise ValueError("the new build and the installed app are the same folder")
    if not (src / "Contents" / "MacOS" / EXECUTABLE).is_file():
        raise ValueError(f"no new build at {src}")
    return HelperPaths(
        pid=os.getpid() if pid is None else pid,
        src=src, target=target,
        backup=UPDATE_DIR / "previous" / APP_BUNDLE,
        log=UPDATE_DIR / "update.log",
        outcome=UPDATE_DIR / "outcome",
        version=staged.version,
    )


def helper_env() -> dict[str, str]:
    """A fixed environment: no BASH_ENV, no exported functions, no API keys."""
    env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"}
    for name in ("HOME", "USER", "LOGNAME", "LANG", "TMPDIR"):
        if os.environ.get(name):
            env[name] = os.environ[name]
    return env


def start_helper(paths: HelperPaths, env: dict[str, str] | None = None) -> subprocess.Popen:
    """Start the helper in a session of its own, so it outlives Lab Hub."""
    paths.log.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    for stale in (paths.outcome, paths.outcome.with_name("outcome.seen")):
        try:
            stale.unlink()
        except FileNotFoundError:
            pass
    fd = os.open(paths.log, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as log:
        return subprocess.Popen(
            ["/bin/bash", "-c", HELPER_SCRIPT, "lab-hub-update",
             str(paths.pid), str(paths.src), str(paths.target), str(paths.backup),
             str(paths.outcome), paths.version, OPEN,
             str(WAIT_S), str(LATE_WAIT_S), str(SELFTEST_S)],
            cwd="/", stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            close_fds=True, start_new_session=True,
            env=env if env is not None else helper_env(),
        )


# -- after the restart ------------------------------------------------------
OUTCOMES = ("ok", "rolled_back", "not_replaced", "broken")


@dataclass(frozen=True)
class Outcome:
    token: str
    message: str
    log: Path
    version: str = ""  # the version it tried to install

    @property
    def ok(self) -> bool:
        return self.token == "ok"


def read_outcome(update_dir: Path | None = None) -> Outcome | None:
    """The last update's outcome, once: the file is renamed after reading.
    Anything unreadable means no notice."""
    where = update_dir or UPDATE_DIR
    path = where / "outcome"
    try:
        if not path.is_file() or path.is_symlink():
            return None
        with path.open("rb") as handle:
            raw = handle.read(OUTCOME_MAX_BYTES)
    except OSError:
        return None
    try:
        path.replace(where / "outcome.seen")
    except OSError:
        pass
    lines = raw.decode("utf-8", errors="replace").splitlines()
    if not lines or lines[0].strip() not in OUTCOMES:
        return None
    message = lines[1].strip()[:300] if len(lines) > 1 else ""
    version = lines[2].strip()[:40] if len(lines) > 2 else ""
    return Outcome(lines[0].strip(), message, where / "update.log", version)


def notice(outcome: Outcome, running_version: str) -> str:
    if outcome.ok:
        return f"Lab Hub updated to {running_version}."
    tried = outcome.version or "the new build"
    return (f"The update to {tried} did not install ({outcome.message}); you are "
            f"on {running_version}. Log: {outcome.log}")
