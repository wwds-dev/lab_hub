"""Resolve what is safe (commit, clean up, sync), and list the rest for review.

Spec: `docs/specs/repo-tidy.md`. Check repos (`hygiene.py`) only reports; this
module is the one place Lab Hub changes a repo, and only on the owner's click:

- `plan()` reads git and proposes actions that lose nothing: delete a branch
  whose changes are already in the default branch, remove a clean worktree on
  such a branch, fast-forward a clean default branch that is only behind, push
  one that is only ahead. Everything else is a `Skip` with its reason.
- `apply()` re-checks the action's guard right before running it, because
  agent sessions share these repos and the state can move between preview and
  click. A guard that no longer holds skips the action; nothing is forced.
- `unlanded()` lists the branches with real unlanded work, and
  `delete_branch()` / `remove_worktree()` act on one the owner picked.

Every change is appended to `repo-tidy.log` in Lab Hub's support folder; a
deleted branch is logged with its tip SHA so `git branch <name> <sha>` brings
it back. Nothing here rebases, force-pushes or touches a remote branch. A
branch that merges cleanly is merged (section 10); one that conflicts can be
handed to Claude Code (`claude_resolve`, section 11).

All functions block on git; the UI runs them on a worker thread.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

GIT_TIMEOUT = 30
NETWORK_TIMEOUT = 90
# A worktree an agent session made and used recently may belong to a session
# that is idle right now, with no process inside it for `lsof` to see (A2).
RECENT_HOURS = 24
AGENT_WORKTREES = Path(".claude") / "worktrees"
# A file changed this recently may belong to a session that is still working,
# with no process inside the worktree for `lsof` to see: a session opened in
# the lab root edits active/<app> from outside it, and the main checkout was
# never tested at all (audit H1, spec land-live-session-guard). 0 turns the
# rule off (the test suite's default, tests/conftest.py).
QUIET_MINUTES = 15
SETTLING_MAX_FILES = 2000
# A frozen app has a minimal PATH.
_SEARCH_PATH = "/usr/bin:/usr/sbin:/opt/homebrew/bin:/usr/local/bin"


def log_path() -> Path:
    from .config import SUPPORT_DIR

    return SUPPORT_DIR / "repo-tidy.log"


# ----------------------------------------------------------------------
# git plumbing
# ----------------------------------------------------------------------
def _git_exe() -> str:
    return shutil.which("git", path=_SEARCH_PATH) or "git"


_DROP_ENV = ("GIT_", "DYLD_", "PYTHON", "QT_")


def _env() -> dict[str, str]:
    """os.environ without anything that would point git at another repo
    (GIT_DIR, GIT_WORK_TREE, GIT_INDEX_FILE, GIT_CONFIG_*) or load other code,
    and with every credential prompt shut off."""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(_DROP_ENV) and k not in ("SSH_ASKPASS",)}
    env.update(GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0",
               GCM_INTERACTIVE="never", GIT_SSH_COMMAND="ssh -oBatchMode=yes")
    return env


def git(repo: Path, *args: str, timeout: int = GIT_TIMEOUT,
        strip: bool = True) -> tuple[int, str, str]:
    """Run git in `repo`: (returncode, stdout, stderr). Never raises, never prompts."""
    try:
        r = subprocess.run(
            [_git_exe(), "-C", str(repo), *args],
            capture_output=True, text=True, timeout=timeout, env=_env(),
            start_new_session=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, "", str(exc)
    out = r.stdout.strip() if strip else r.stdout
    return r.returncode, out, r.stderr.strip()


def default_branch(repo: Path) -> str | None:
    rc, out, _ = git(repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if rc == 0 and out.startswith("origin/"):
        return out.removeprefix("origin/")
    for name in ("main", "master"):
        if git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}")[0] == 0:
            return name
    return None


@dataclass(frozen=True)
class Worktree:
    path: Path
    branch: str  # "" when detached
    head: str
    locked: bool
    main: bool  # the repo's own checkout, never removed


def worktrees(repo: Path) -> list[Worktree]:
    # -z: a path containing a newline cannot spoof another entry.
    rc, out, _ = git(repo, "worktree", "list", "--porcelain", "-z", strip=False)
    if rc != 0:
        return []
    found: list[Worktree] = []
    for block in out.split("\0\0"):
        fields: dict[str, str] = {}
        for line in block.split("\0"):
            if not line:
                continue
            key, _, value = line.partition(" ")
            fields[key] = value
        if "worktree" not in fields or "bare" in fields:
            continue
        found.append(Worktree(
            path=Path(fields["worktree"]),
            branch=fields.get("branch", "").removeprefix("refs/heads/"),
            head=fields.get("HEAD", ""),
            locked="locked" in fields,
            main=not found,
        ))
    return found


def tip(repo: Path, branch: str) -> str:
    rc, out, _ = git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")
    return out if rc == 0 else ""


def local_branches(repo: Path) -> list[str]:
    rc, out, _ = git(repo, "for-each-ref", "--format=%(refname:lstrip=2)", "refs/heads")
    return out.splitlines() if rc == 0 else []


def is_landed_by_tree(repo: Path, default: str, branch: str) -> bool:
    """Merging `branch` into `default` would give the default branch's own tree:
    true for an ancestor, and for work that landed another way (a squash-merged
    pull request). A conflict or an error is "no"."""
    rc, base, _ = git(repo, "rev-parse", "--verify", "--quiet",
                      f"refs/heads/{default}^{{tree}}")
    if rc != 0 or not base:
        return False
    rc, out, _ = git(repo, "merge-tree", "--write-tree",
                     f"refs/heads/{default}", f"refs/heads/{branch}")
    return rc == 0 and out.splitlines()[:1] == [base]


def applied_copies(repo: Path, default: str, branch: str) -> int:
    """How many commits `branch` has that `default` does not, when every one of
    them is already in `default` as a rebased or cherry-picked copy; else 0.

    `git cherry` matches by patch-id, so this does not prove main still holds
    that work (a later commit may have changed it): the plan says so. It skips
    merge commits, so a branch containing one is refused, not guessed at.
    """
    rc, merges, _ = git(repo, "rev-list", "--merges", "--count",
                        f"refs/heads/{default}..refs/heads/{branch}")
    if rc != 0 or merges != "0":
        return 0
    rc, out, _ = git(repo, "cherry", f"refs/heads/{default}", f"refs/heads/{branch}")
    lines = out.splitlines() if rc == 0 else []
    if not lines or any(not line.startswith("- ") for line in lines):
        return 0
    return len(lines)


def is_landed(repo: Path, default: str, branch: str) -> bool:
    """Every change on `branch` is already in `default`: by tree (see
    `is_landed_by_tree`) or as copies of its commits (`applied_copies`)."""
    return (is_landed_by_tree(repo, default, branch)
            or applied_copies(repo, default, branch) > 0)


def landed_reason(repo: Path, default: str, branch: str) -> str:
    """Why `branch` counts as landed, in words for the preview and the log;
    "" when it does not count as landed."""
    if is_landed_by_tree(repo, default, branch):
        return f"its changes are already in {default}"
    n = applied_copies(repo, default, branch)
    if not n:
        return ""
    # Files the branch changed since it forked that still differ from the
    # default branch's tip: main may have changed, reverted or rewritten them.
    rc1, mine, _ = git(repo, "diff", "--name-only", f"refs/heads/{default}...refs/heads/{branch}")
    rc2, tips, _ = git(repo, "diff", "--name-only", f"refs/heads/{default}", f"refs/heads/{branch}")
    k = len(set(mine.splitlines()) & set(tips.splitlines())) if rc1 == 0 and rc2 == 0 else 0
    text = (f"every commit ({n}) is already in {default} as a copy (matched by "
            f"patch; later edits on {default} are not compared)")
    if k:
        text += (f"; {k} file{'s' if k != 1 else ''} the branch changed differ from "
                 f"{default} now: {default} may have changed, reverted or rewritten that work")
    return text


def contains(repo: Path, default: str, commit: str) -> bool:
    """`commit` is in the default branch's history."""
    if not commit:
        return False
    rc, _, _ = git(repo, "merge-base", "--is-ancestor", commit, f"refs/heads/{default}")
    return rc == 0


def is_clean(path: Path) -> bool:
    """No staged, unstaged or untracked changes (ignored files do not count)."""
    rc, out, _ = git(path, "status", "--porcelain")
    return rc == 0 and not out


# Ignored files git would delete with the worktree that can be rebuilt; any
# other ignored file (.env, data/, docs/legal/) blocks removal.
REGENERABLE = frozenset({
    ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", ".next", "build", "dist", "dist.noindex",
    ".DS_Store", ".coverage", "htmlcov", ".tox",
})


def ignored_files(path: Path) -> list[str] | None:
    """Ignored files and folders in a worktree that are not REGENERABLE.

    `git worktree remove` deletes ignored files without asking. None when git
    cannot tell (treated as a blocker).
    """
    rc, out, _ = git(path, "ls-files", "--others", "--ignored", "--exclude-standard",
                     "--directory", "-z", strip=False)
    if rc != 0:
        return None
    keep = []
    for entry in out.split("\0"):
        parts = [p for p in entry.split("/") if p]
        if parts and not any(p in REGENERABLE or p.endswith(".pyc") for p in parts):
            keep.append(entry)
    return keep


def paused_operation(path: Path) -> str:
    """A rebase, merge, cherry-pick or bisect in progress, or ""."""
    rc, gitdir, _ = git(path, "rev-parse", "--absolute-git-dir")
    if rc != 0 or not gitdir:
        return "git cannot read it"
    g = Path(gitdir)
    for marker, name in (("rebase-merge", "a rebase"), ("rebase-apply", "a rebase"),
                         ("MERGE_HEAD", "a merge"), ("CHERRY_PICK_HEAD", "a cherry-pick"),
                         ("REVERT_HEAD", "a revert"), ("BISECT_LOG", "a bisect")):
        if (g / marker).exists():
            return name
    return ""


def changed_tracked(path: Path) -> int:
    """Tracked files with staged or unstaged changes."""
    rc, out, _ = git(path, "status", "--porcelain", "--untracked-files=no")
    return len(out.splitlines()) if rc == 0 else 0


def untracked_count(path: Path) -> int:
    rc, out, _ = git(path, "ls-files", "--others", "--exclude-standard")
    return len(out.splitlines()) if rc == 0 else 0


def has_conflicts(path: Path) -> bool:
    rc, out, _ = git(path, "diff", "--name-only", "--diff-filter=U")
    return rc != 0 or bool(out)


def _open_files(path: Path) -> list[str] | None:
    """Every file git reports as changed or untracked in this worktree, or
    None when git cannot tell. A rename counts under its new name."""
    rc, out, _ = git(path, "status", "--porcelain=v1", "-z", "--untracked-files=all",
                     strip=False)
    if rc != 0:
        return None
    files: list[str] = []
    fields = out.split("\0")
    i = 0
    while i < len(fields):
        entry = fields[i]
        i += 1
        if len(entry) < 4:
            continue
        files.append(entry[3:])
        if "R" in entry[:2] or "C" in entry[:2]:
            # The name it was renamed or copied from follows, for a staged
            # rename (first letter) and for an intent-to-add one (second).
            i += 1
    return files


def _changed_at(root: Path, rel: str) -> tuple[float, bool] | None:
    """When this file last changed, and whether that is a folder's time: its
    own time, or for a deleted file the time of the nearest folder that still
    exists (a delete updates it). None when that cannot be read."""
    target = root / rel
    by_folder = False
    while True:
        try:
            return target.lstat().st_mtime, by_folder
        except FileNotFoundError:
            if target == root:
                return None
            target = target.parent
            by_folder = True
        except OSError:
            return None


# When Lab Hub itself last wrote into a worktree. Land's untracked step moves
# files to quarantine and may create a .gitignore, and both change a folder's
# time. A deleted file is timed by its folder, so without this Land would read
# its own write as a session's and stop itself (review 2026-11-20).
_OWN_WRITES: dict[str, float] = {}


def _own_key(path: Path) -> str:
    try:
        return str(path.resolve())
    except OSError:
        return str(path)


def note_own_write(path: Path) -> None:
    """Lab Hub has just finished writing in this worktree."""
    _OWN_WRITES[_own_key(path)] = time.time()


def settling(path: Path, now: float | None = None) -> str:
    """Why this worktree's open work must be left alone for now, or "".

    Open work is every file git reports as changed or untracked. While the
    newest of them changed less than QUIET_MINUTES ago, a session may still be
    writing here, whether or not a process sits inside the worktree. Fails
    closed: when git cannot list the files, when there are more than
    SETTLING_MAX_FILES, or when a file's time cannot be read, the answer is a
    reason, never "".
    """
    if QUIET_MINUTES <= 0:
        return ""
    files = _open_files(path)
    if files is None:
        return "could not list its changed files"
    if not files:
        return ""
    if len(files) > SETTLING_MAX_FILES:
        return (f"it has more than {SETTLING_MAX_FILES} changed files, too many to check "
                "when they last changed: commit them yourself")
    now = time.time() if now is None else now
    own_write = _OWN_WRITES.get(_own_key(path))
    newest, newest_at = "", 0.0
    for rel in files:
        found = _changed_at(path, rel)
        if found is None:
            return f"could not read when {rel} last changed"
        at, by_folder = found
        if by_folder and own_write is not None and at <= own_write:
            continue  # the folder last changed by Lab Hub's own write, not a session's
        if not newest or at > newest_at:
            newest, newest_at = rel, at
    if not newest:
        return ""
    if newest_at - now > 60:
        return (f"{newest} is dated in the future, so nobody can tell when it changed: "
                "check the clock, or commit it yourself")
    age = max(0.0, now - newest_at)
    quiet = QUIET_MINUTES * 60
    if age >= quiet:
        return ""
    minutes = int(age // 60)
    ago = ("less than a minute ago" if minutes == 0
           else f"{minutes} minute{'s' if minutes != 1 else ''} ago")
    left = max(1, -int(-(quiet - age) // 60))
    return (f"{newest} changed {ago}: a session may still be working here. Try again in "
            f"{left} minute{'s' if left != 1 else ''}, or commit it yourself")


def commit_blocker(repo: Path, wt: Worktree, busy: tuple[Path, ...] | None,
                   now: float | None = None, land_mode: bool = False) -> str:
    """Why tracked changes in this worktree must not be committed, or "".
    `land_mode` (Land, spec land-resolve-all 4.5): a commit deletes nothing, so
    a recently used agent worktree is committed in too."""
    if not wt.path.exists():
        return "its folder is missing"
    if not current_branch(wt.path):
        return "it is on a detached HEAD"
    paused = paused_operation(wt.path)
    if paused:
        return f"{paused} is in progress"
    if has_conflicts(wt.path):
        return "it has unresolved conflicts"
    if not wt.main:
        # A linked worktree is usually an agent's: leave one that is in use
        # or was used recently to the session that owns it.
        if busy is None:
            return "could not check whether a process is running in it"
        if in_use(wt.path, busy):
            return "a process is running in it"
        if not land_mode and recent_agent_worktree(repo, wt.path, now):
            return f"an agent worktree used in the last {RECENT_HOURS} hours"
    # The main checkout too: a session elsewhere may be editing it right now.
    return settling(wt.path, now)


def merges_cleanly(repo: Path, default: str, branch: str) -> bool:
    rc, _, _ = git(repo, "merge-tree", "--write-tree",
                   f"refs/heads/{default}", f"refs/heads/{branch}")
    return rc == 0


def merge_target_blocker(repo: Path, default: str, after_commit: bool = False) -> str:
    """Why nothing may be merged into the default branch now, or ""."""
    trees = worktrees(repo)
    if not trees:
        return "git cannot list its checkout"
    main = trees[0]
    branch = current_branch(main.path)
    if branch != default:
        return f"the checkout is on {branch or 'a detached HEAD'}, not {default}"
    paused = paused_operation(main.path)
    if paused:
        return f"{paused} is in progress in the checkout"
    if has_conflicts(main.path):
        return "the checkout has unresolved conflicts"
    if not after_commit and not tracked_clean(main.path):
        return "the checkout has uncommitted changes"
    counts = ahead_behind(repo)
    if counts is not None and counts[1]:
        return f"{default} is {counts[1]} behind origin: pull it first"
    return ""


def merge_source_blocker(repo: Path, wt: Worktree | None,
                         busy: tuple[Path, ...] | None, now: float | None = None,
                         land_mode: bool = False) -> str:
    """Why a branch's worktree says its work is not finished, or "".
    `land_mode` (Land): a merge reads commits only, so a process in the
    worktree or its recent use does not stop it."""
    if wt is None:
        return ""
    if not wt.path.exists():
        return ""
    if not is_clean(wt.path):
        return "its worktree has uncommitted or untracked files"
    paused = paused_operation(wt.path)
    if paused:
        return f"{paused} is in progress in its worktree"
    if land_mode:
        return ""
    if busy is None:
        return "could not check whether a process is running in its worktree"
    if in_use(wt.path, busy):
        return "a process is running in its worktree"
    if recent_agent_worktree(repo, wt.path, now):
        return f"its agent worktree was used in the last {RECENT_HOURS} hours"
    return ""


def tracked_clean(path: Path) -> bool:
    rc, out, _ = git(path, "status", "--porcelain", "--untracked-files=no")
    return rc == 0 and not out


def upstream(repo: Path) -> str:
    rc, out, _ = git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    return out if rc == 0 else ""


def ahead_behind(repo: Path) -> tuple[int, int] | None:
    """(ahead, behind) of HEAD against its upstream, as of the last fetch."""
    rc, out, _ = git(repo, "rev-list", "--left-right", "--count", "HEAD...@{upstream}")
    if rc != 0:
        return None
    try:
        ahead, behind = (int(n) for n in out.split())
    except ValueError:
        return None
    return ahead, behind


def current_branch(path: Path) -> str:
    rc, out, _ = git(path, "symbolic-ref", "--short", "-q", "HEAD")
    return out if rc == 0 else ""


# ----------------------------------------------------------------------
# Is anything using a worktree?
# ----------------------------------------------------------------------

def busy_dirs() -> tuple[Path, ...] | None:
    """The current directory of every process we can see (`lsof -d cwd`).

    None when lsof is missing or fails: then nobody can say a worktree is
    unused, and `in_use` answers yes (fail closed).
    """
    lsof = shutil.which("lsof", path=_SEARCH_PATH)
    if lsof is None:
        return None
    try:
        r = subprocess.run([lsof, "-n", "-P", "-d", "cwd", "-F", "n"],
                           capture_output=True, text=True, timeout=GIT_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    dirs = tuple(Path(line[1:]) for line in r.stdout.splitlines()
                 if line.startswith("n/"))
    # lsof exits 1 when some processes cannot be read; an empty list as well
    # means it saw nothing at all, which is not believable.
    return dirs or None


def in_use(path: Path, busy: tuple[Path, ...] | None) -> bool:
    if busy is None:
        return True
    try:
        target = path.resolve()
    except OSError:
        return True
    for cwd in busy:
        try:
            cwd = cwd.resolve()
        except OSError:
            continue
        if cwd == target or target in cwd.parents:
            return True
    return False


def last_touched(repo: Path, wt: Path) -> float:
    """Newest time git or a file system change touched this worktree."""
    stamps = []
    candidates = [wt, wt / ".git"]
    rc, gitdir, _ = git(wt, "rev-parse", "--absolute-git-dir")
    if rc == 0 and gitdir:
        g = Path(gitdir)
        candidates += [g, g / "HEAD", g / "index", g / "logs" / "HEAD"]
    for p in candidates:
        try:
            stamps.append(p.stat().st_mtime)
        except OSError:
            pass
    return max(stamps, default=0.0)


def recent_agent_worktree(repo: Path, wt: Path, now: float | None = None) -> bool:
    """Under `.claude/worktrees/` and touched in the last RECENT_HOURS (A2)."""
    try:
        wt.resolve().relative_to((repo / AGENT_WORKTREES).resolve())
    except (ValueError, OSError):
        return False
    now = time.time() if now is None else now
    return now - last_touched(repo, wt) < RECENT_HOURS * 3600


def worktree_blocker(repo: Path, wt: Worktree, busy: tuple[Path, ...] | None,
                     now: float | None = None) -> str:
    """Why this worktree must not be removed, or "" when it may be."""
    if wt.main:
        return "it is the repo's own checkout"
    if wt.locked:
        return "it is locked"
    if not wt.path.exists():
        return "its folder is missing (git worktree prune clears it)"
    if not is_clean(wt.path):
        return "it has uncommitted or untracked files"
    paused = paused_operation(wt.path)
    if paused:
        return f"{paused} is in progress in it"
    ignored = ignored_files(wt.path)
    if ignored is None:
        return "git cannot list its ignored files"
    if ignored:
        names = ", ".join(ignored[:3]) + (f" and {len(ignored) - 3} more" if len(ignored) > 3 else "")
        return f"it holds ignored files that removing it would delete: {names}"
    if busy is None:
        return "could not check whether a process is running in it"
    if in_use(wt.path, busy):
        return "a process is running in it"
    if recent_agent_worktree(repo, wt.path, now):
        return f"an agent worktree used in the last {RECENT_HOURS} hours"
    return ""


# ----------------------------------------------------------------------
# Resolve: plan and apply
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class Action:
    repo_name: str
    repo: Path
    kind: str  # commit | merge | claude_merge | delete_branch | remove_worktree | pull | push
    target: str  # branch name, or worktree path
    reason: str
    sha: str = ""  # a branch's tip when planned: deleted only if unchanged
    branch: str = ""  # commit: the branch the worktree was on when planned
    detail: str = ""  # claude_merge: the test command shown in the preview
    land_mode: bool = False  # planned by Land: its guards (spec land-resolve-all 4.5)

    @property
    def label(self) -> str:
        verb = {
            "commit": f"Commit in {self.target} (on {self.branch})",
            "merge": f"Merge {self.target} into {self.branch}",
            "claude_merge": f"Resolve conflicts with Claude: {self.target} into {self.branch}",
            "delete_branch": f"Delete branch {self.target}",
            "remove_worktree": f"Remove worktree {self.target}",
            "pull": f"Pull {self.target} (fast-forward)",
            "push": f"Push {self.target}",
        }[self.kind]
        return f"{self.repo_name}: {verb} — {self.reason}"


@dataclass(frozen=True)
class Skip:
    repo_name: str
    target: str
    reason: str

    @property
    def label(self) -> str:
        return f"{self.repo_name}: {self.target} — {self.reason}"


@dataclass(frozen=True)
class Plan:
    actions: tuple[Action, ...] = ()
    skipped: tuple[Skip, ...] = ()


def plan_repo(name: str, repo: Path, busy: tuple[Path, ...] | None = (),
              now: float | None = None,
              claude: str | None = None,
              claude_why: str = "Claude Code not found",
              land_mode: bool = False) -> tuple[list[Action], list[Skip]]:
    """`claude`: the Claude Code executable, or None to leave conflicting
    branches for a person (section 11), saying `claude_why`. `land_mode`: Land
    plans it, which resolves untracked files itself and uses its guards."""
    actions: list[Action] = []
    skips: list[Skip] = []
    default = default_branch(repo)
    if default is None:
        return actions, [Skip(name, str(repo), "no default branch found")]
    trees = worktrees(repo)
    by_branch = {wt.branch: wt for wt in trees if wt.branch}

    # Open work: commit tracked changes; never add untracked files.
    main_committed = False
    for wt in trees:
        changed = changed_tracked(wt.path) if wt.path.exists() else 0
        loose = untracked_count(wt.path) if wt.path.exists() else 0
        if loose and not land_mode:
            skips.append(Skip(name, str(wt.path),
                              f"{loose} untracked file{'s' if loose != 1 else ''} — "
                              "add them yourself if they belong in git"))
        if not changed:
            continue
        blocker = commit_blocker(repo, wt, busy, now, land_mode)
        if blocker:
            skips.append(Skip(name, str(wt.path),
                              f"{changed} changed file{'s' if changed != 1 else ''} not "
                              f"committed: {blocker}"))
            continue
        branch = current_branch(wt.path)
        actions.append(Action(name, repo, "commit", str(wt.path),
                              f"{changed} changed tracked file{'s' if changed != 1 else ''}",
                              branch=branch, land_mode=land_mode))
        main_committed = main_committed or (wt.main and branch == default)

    # Unlanded branches that merge into the default branch with no conflicts
    # (owner's choice, spec section 10). Conflicting ones are left for a
    # person: Review branches -> Open in Terminal.
    merged_any = False
    committed = {a.branch for a in actions if a.kind == "commit"}
    target = merge_target_blocker(repo, default, after_commit=main_committed)
    for branch in local_branches(repo):
        if branch == default or is_landed(repo, default, branch):
            continue
        wt = by_branch.get(branch)
        if wt is not None and wt.main:
            continue  # the checkout itself is on it; target says why
        if target:
            skips.append(Skip(name, branch, f"not merged: {target}"))
            continue
        if branch in committed:
            skips.append(Skip(name, branch, "not merged: its open work is committed in "
                                            "this run; the next Resolve can merge it"))
            continue
        source = merge_source_blocker(repo, wt, busy, now, land_mode)
        if source:
            skips.append(Skip(name, branch, f"not merged: {source}"))
            continue
        links = _merge_link_stop(repo, default, f"refs/heads/{branch}")
        if links:
            skips.append(Skip(name, branch, f"not merged: {links}"))
            continue
        rc, count, _ = git(repo, "rev-list", "--count",
                           f"refs/heads/{default}..refs/heads/{branch}")
        n = int(count) if rc == 0 and count.isdigit() else 0
        commits = f"{n} commit{'s' if n != 1 else ''}"
        sha = tip(repo, branch)
        if not merges_cleanly(repo, default, branch):
            reason = _claude_blocker(repo, claude, claude_why)
            if reason:
                skips.append(Skip(name, branch, f"not merged: it conflicts with {default} — "
                                                f"{reason}"))
                continue
            from .claude_resolve import conflicted_files, test_command, timeout_note

            cmd = test_command(repo)
            files = conflicted_files(repo, default, branch)
            k = len(files)
            note = f"; {cmd.note}" if cmd and cmd.note else ""
            limit = timeout_note(repo)
            note += f"; {limit}" if limit else ""
            actions.append(Action(
                name, repo, "claude_merge", branch,
                f"{commits}, conflicts in {k} file{'s' if k != 1 else ''}; "
                f"tests ({cmd.source}): {cmd.display}{note}",
                sha, branch=default, detail=cmd.display, land_mode=land_mode))
        else:
            actions.append(Action(name, repo, "merge", branch, f"{commits}, no conflicts",
                                  sha, branch=default, land_mode=land_mode))
        merged_any = True
        # Once merged it has landed: tidy its worktree and the branch too.
        if wt is not None:
            if worktree_blocker(repo, wt, busy, now):
                continue
            actions.append(Action(name, repo, "remove_worktree", str(wt.path),
                                  f"its branch {branch} is merged above"))
        actions.append(Action(name, repo, "delete_branch", branch,
                              f"merged into {default} above", sha))

    # Landed branches, and the worktrees that hold them.
    for branch in local_branches(repo):
        if branch == default:
            continue
        reason = landed_reason(repo, default, branch)
        if not reason:
            continue
        sha = tip(repo, branch)
        wt = by_branch.get(branch)
        if wt is not None:
            blocker = worktree_blocker(repo, wt, busy, now)
            if blocker:
                skips.append(Skip(name, branch,
                                  f"landed, but its worktree {wt.path} stays: {blocker}"))
                continue
            actions.append(Action(name, repo, "remove_worktree", str(wt.path),
                                  f"clean, and its branch {branch} is landed"))
        actions.append(Action(name, repo, "delete_branch", branch,
                              reason, sha))

    # Detached worktrees whose commit is already in the default branch.
    for wt in trees:
        if wt.main or wt.branch or not contains(repo, default, wt.head):
            continue
        blocker = worktree_blocker(repo, wt, busy, now)
        if blocker:
            skips.append(Skip(name, str(wt.path), blocker))
        else:
            actions.append(Action(name, repo, "remove_worktree", str(wt.path),
                                  f"clean, detached at a commit already in {default}"))

    # Sync the default branch, only when nothing can be lost or merged.
    changed = main_committed or merged_any
    reason = sync_blocker(repo, default, after_commit=changed)
    if reason:
        skips.append(Skip(name, default, reason))
    elif changed:
        actions.append(Action(name, repo, "push", default,
                              "after the commit or merges above", land_mode=land_mode))
    else:
        ahead, behind = ahead_behind(repo) or (0, 0)
        if behind:
            actions.append(Action(name, repo, "pull", default,
                                  f"{behind} commit{'s' if behind != 1 else ''} behind, nothing local"))
        elif ahead:
            actions.append(Action(name, repo, "push", default,
                                  f"{ahead} commit{'s' if ahead != 1 else ''} not on the remote",
                                  land_mode=land_mode))
    return actions, skips


def _merge_link_stop(repo: Path, default: str, rev: str) -> str:
    """A link (or file) the merge of `rev` would bring over a real folder
    (land-folder-link-guard)."""
    from .land_resolve import merge_link_stop

    return merge_link_stop(repo, default, rev)


def _pull_link_stop(repo: Path, default: str, rev: str = "") -> str:
    """The same for a pull, judged on `rev` (the last-fetched origin/<default>
    when not given)."""
    from .land_resolve import link_stop

    trees = worktrees(repo)
    if not trees:
        return "git cannot list its checkout"
    return link_stop(trees[0].path, "HEAD", rev or f"refs/remotes/origin/{default}",
                     who=f"origin/{default}", fix_in=f"{default} on the remote")


def _claude_blocker(repo: Path, claude: str | None, why: str) -> str:
    """Why a conflicting branch cannot go to Claude, or ""."""
    if claude is None:
        return f"land it by hand (Review branches → Open in Terminal); {why}"
    from .claude_resolve import test_command

    if test_command(repo) is None:
        return ("land it by hand (Review branches → Open in Terminal); no test command "
                "found in docs/foundry/app-context.md")
    return ""


def sync_blocker(repo: Path, default: str, after_commit: bool = False) -> str:
    """Why the default branch must not be pulled or pushed, or "" when one of
    the two may run (it is only behind, or only ahead, with nothing local).

    `after_commit`: a commit of the checkout's open work is planned first, so
    uncommitted changes and being level do not stop the push that follows it.
    """
    trees = worktrees(repo)
    if not trees:
        return "git cannot list its checkout"
    branch = current_branch(trees[0].path)
    if branch != default:
        return f"the checkout is on {branch or 'a detached HEAD'}, not {default}"
    if upstream(repo) != f"origin/{default}":
        return f"{default} does not track origin/{default}"
    counts = ahead_behind(repo)
    if counts is None:
        return "no upstream to pull from or push to"
    ahead, behind = counts
    if ahead and behind:
        return f"diverged: {ahead} unpushed, {behind} behind"
    if after_commit:
        if behind:
            return f"{behind} behind with local changes: committing would diverge it, so not pushed"
        return f"{paused_operation(trees[0].path)} is in progress" if paused_operation(trees[0].path) else ""
    if not tracked_clean(trees[0].path):
        return "has uncommitted changes that are not committed first"
    if not ahead and not behind:
        return "level with origin"
    if paused_operation(trees[0].path):
        return f"{paused_operation(trees[0].path)} is in progress"
    return ""


def plan(repos: list[tuple[str, Path]], now: float | None = None,
         claude: str | None | bool = True, claude_why: str = "Claude Code not found") -> Plan:
    """`claude`: True finds Claude Code itself (and checks it is signed in); a
    path uses that one; None leaves conflicting branches for a person."""
    if claude is True:
        from .claude_resolve import availability

        claude, claude_why = availability()
    busy = busy_dirs()
    actions: list[Action] = []
    skips: list[Skip] = []
    for name, repo in repos:
        if not repo.is_absolute() or not (repo / ".git").exists():
            skips.append(Skip(name, str(repo), "not a git checkout"))
            continue
        a, s = plan_repo(name, repo, busy, now, claude or None, claude_why)
        actions += a
        skips += [x for x in s if x.reason != "level with origin"]
    return Plan(tuple(actions), tuple(skips))


def _log(line: str, log: Path | None) -> bool:
    """Append one line; False when it could not be written. Newlines in git's
    output are flattened so a remote's message cannot forge a log line."""
    log = log or log_path()
    text = " ".join(line.splitlines())
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(log, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a") as fh:
            fh.write(f"{datetime.now().isoformat(timespec='seconds')} {text}\n")
        return True
    except OSError:
        return False


BACKUP_PREFIX = "refs/lab-hub-tidy/"


def _delete_branch_at(repo: Path, branch: str, sha: str, log: Path | None,
                      what: str) -> tuple[bool, str]:
    """Delete `branch` only if it still points at `sha`.

    The log line goes first and a failed write stops the delete, so every
    deleted branch can be found again. A backup ref keeps its commits from
    git's garbage collection; `git branch <name> <sha>` restores it, and
    `git update-ref -d refs/lab-hub-tidy/<sha>` lets them go for good.
    """
    restore = f"git -C {repo} branch {branch} {sha}"
    if not _log(f"DELETING {what} {branch} at {sha} in {repo} (restore: {restore})", log):
        return False, f"not deleted — could not write the log at {log or log_path()}"
    rc, _, err = git(repo, "update-ref", f"{BACKUP_PREFIX}{sha}", sha)
    if rc != 0:
        _log(f"FAILED backup ref for {branch} in {repo}: {err}", log)
        return False, f"not deleted — could not keep a backup ref: {err}"
    rc, _, err = git(repo, "update-ref", "-d", f"refs/heads/{branch}", sha)
    if rc != 0:
        _log(f"FAILED delete {branch} in {repo}: {err}", log)
        return False, f"failed — {err or 'the branch moved'}"
    return True, f"deleted; restore with: {restore}"


def _find_worktree(repo: Path, path: str) -> Worktree | None:
    want = Path(path)
    for wt in worktrees(repo):
        if wt.path == want:
            return wt
    return None


def check(action: Action, busy: tuple[Path, ...] | None = (),
          now: float | None = None) -> str:
    """Why `action` may no longer run, or "" when its guard still holds."""
    repo = action.repo
    default = default_branch(repo)
    if default is None:
        return "no default branch found"
    if action.kind == "commit":
        wt = _find_worktree(repo, action.target)
        if wt is None:
            return "the worktree is gone"
        if current_branch(wt.path) != action.branch:
            return f"it is no longer on {action.branch}"
        blocker = commit_blocker(repo, wt, busy, now, action.land_mode)
        if blocker:
            return blocker
        if not changed_tracked(wt.path):
            return "nothing to commit any more"
        return ""
    if action.kind in ("merge", "claude_merge"):
        branch = action.target
        if tip(repo, branch) != action.sha:
            return "the branch has moved since the preview"
        if is_landed(repo, default, branch):
            return f"it is already in {default}"
        reason = merge_target_blocker(repo, default)
        if reason:
            return reason
        wt = next((w for w in worktrees(repo) if w.branch == branch), None)
        reason = merge_source_blocker(repo, wt, busy, now, action.land_mode)
        if reason:
            return reason
        if action.kind == "merge" and not merges_cleanly(repo, default, branch):
            return f"it now conflicts with {default}"
        reason = _merge_link_stop(repo, default, action.sha)  # what apply merges (security P3-1)
        if reason:
            return reason
        if action.kind == "claude_merge":
            from .claude_resolve import test_command

            cmd = test_command(repo)
            if cmd is None or cmd.display != action.detail:
                return "its test command changed since the preview"
        return ""
    if action.kind == "delete_branch":
        branch = action.target
        if branch == default:
            return "it is the default branch"
        current = tip(repo, branch)
        if not current:
            return "the branch is gone"
        if current != action.sha:
            return "the branch has moved since the preview"
        if any(wt.branch == branch for wt in worktrees(repo)):
            return "it is checked out in a worktree"
        if not is_landed(repo, default, branch):
            return f"its changes are no longer all in {default}"
        return ""
    if action.kind == "remove_worktree":
        wt = _find_worktree(repo, action.target)
        if wt is None:
            return "the worktree is gone"
        blocker = worktree_blocker(repo, wt, busy, now)
        if blocker:
            return blocker
        if wt.branch and not is_landed(repo, default, wt.branch):
            return f"its branch is no longer landed in {default}"
        if not wt.branch and not contains(repo, default, wt.head):
            return f"its commit is not in {default}"
        return ""
    if action.kind == "push":
        rc, _, err = git(repo, "fetch", "--quiet", "origin", timeout=NETWORK_TIMEOUT)
        if rc != 0:
            return f"could not fetch: {err or 'git fetch failed'}"
    if action.kind not in ("pull", "push"):
        return f"unknown action {action.kind}"
    reason = sync_blocker(repo, default)
    if reason:
        return reason
    ahead, behind = ahead_behind(repo) or (0, 0)
    if action.kind == "pull" and ahead:
        return "it has local commits now"
    if action.kind == "push" and behind:
        return f"the remote has {behind} new commit(s); pull first"
    if action.kind == "push" and not ahead:
        return "nothing to push any more"
    return ""


def apply(action: Action, log: Path | None = None,
          busy: tuple[Path, ...] | None | str = "fresh",
          now: float | None = None, *, claude: str | None = None,
          progress=None, stop=None) -> tuple[bool, str]:
    """Re-check, then run one action: (done, what happened).

    A worktree removal takes a fresh `lsof` snapshot unless `busy` is given
    (tests pass one): an earlier snapshot can be minutes old by now.
    `claude`, `progress` and `stop` serve a claude_merge (section 11).
    """
    if busy == "fresh":
        busy = busy_dirs() if action.kind in ("remove_worktree", "commit", "merge",
                                              "claude_merge") else ()
    if stop is not None and stop.stopped:
        _log(f"SKIP {action.repo} {action.kind} {action.target}: stopped", log)
        return False, "skipped — stopped"
    reason = check(action, busy, now)  # type: ignore[arg-type]
    if reason:
        _log(f"SKIP {action.repo} {action.kind} {action.target}: {reason}", log)
        return False, f"skipped — {reason}"
    repo = action.repo
    if action.kind == "claude_merge":
        default = action.branch
        if merges_cleanly(repo, default, action.target):
            # It merges cleanly now: the plain merge path, no Claude.
            return apply(Action(action.repo_name, repo, "merge", action.target,
                                action.reason, action.sha, branch=default,
                                land_mode=action.land_mode),
                         log, busy, now)
        from . import claude_resolve as cr

        exe = claude or cr.find_claude()
        if exe is None:
            return False, "skipped — Claude Code not found"
        cmd = cr.test_command(repo)
        if cmd is None or cmd.display != action.detail:
            return False, "skipped — its test command changed since the preview"
        outcome = cr.resolve(repo, default, action.target, action.sha, cmd, exe, log,
                             stop or cr.Stopper(), progress or (lambda _m: None))
        if outcome.landed:
            return True, outcome.message
        return False, f"not landed — {outcome.message}"
    if action.kind == "delete_branch":
        ok, message = _delete_branch_at(repo, action.target, action.sha, log, "landed branch")
        return ok, "done" if ok else message
    if action.kind == "merge":
        main = worktrees(repo)[0].path
        rc, _, err = git(main, "merge", "--no-ff", "--quiet", "-m",
                         f"Lab Hub: merge {action.target}", action.sha)
        if rc != 0:
            git(main, "merge", "--abort")
        else:
            _log(f"MERGED {action.target} at {action.sha} into {action.branch} in {repo}", log)
    elif action.kind == "commit":
        path = Path(action.target)
        rc, _, err = git(path, "add", "--update")
        if rc == 0:
            message = f"Lab Hub: commit open work, {datetime.now():%Y-%m-%d %H:%M}"
            rc, _, err = git(path, "commit", "--quiet", "-m", message)
        if rc == 0:
            _log(f"COMMITTED tracked changes in {path} on {action.branch}", log)
    elif action.kind == "remove_worktree":
        rc, _, err = git(repo, "worktree", "remove", "--", action.target)
        if rc == 0:
            _log(f"REMOVED worktree {action.target} of {repo}", log)
    elif action.kind == "pull":
        # A pull, with the link check between fetch and update
        # (land-folder-link-guard §8.4): git would replace an ignored real
        # folder with a link the remote brings.
        remote = f"refs/remotes/origin/{action.target}"
        rc, _, err = git(repo, "fetch", "--quiet", "origin",
                         f"+refs/heads/{action.target}:{remote}", timeout=NETWORK_TIMEOUT)
        if rc == 0:
            # One exact commit is checked and moved to (security P3-1).
            rc, oid, err = git(repo, "rev-parse", "--verify", "--quiet", f"{remote}^{{commit}}")
        if rc == 0:
            why = _pull_link_stop(repo, action.target, oid)
            if why:
                _log(f"NOT PULLED {action.target} in {repo}: {why}", log)
                return False, f"not pulled — {why}"
            rc, _, err = git(repo, "merge", "--ff-only", "--quiet", oid)
        if rc == 0:
            _log(f"PULLED {action.target} in {repo}", log)
    else:  # push
        if action.land_mode:
            # Land commits and merges work nobody reviewed: no secret may leave
            # with it (spec land-resolve-all §2.4, security P1-2).
            from .land_resolve import outgoing_findings

            found, error = outgoing_findings(repo, action.target)
            if error or found:
                why = error or ("gitleaks found a secret in the commits to push: "
                                + "; ".join(found[:3])
                                + "; remove it from those commits, then Land again")
                _log(f"NOT PUSHED {action.target} in {repo}: {why}", log)
                return False, f"not pushed — {why}"
        rc, _, err = git(repo, "push", "--quiet", "--no-follow-tags", "origin",
                         f"refs/heads/{action.target}:refs/heads/{action.target}",
                         timeout=NETWORK_TIMEOUT)
        if rc == 0:
            _log(f"PUSHED {action.target} in {repo}", log)
    if rc != 0:
        _log(f"FAILED {action.repo} {action.kind} {action.target}: {err}", log)
        return False, f"failed — {err or 'git exited with an error'}"
    return True, "done"


# ----------------------------------------------------------------------
# Review branches
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class BranchInfo:
    repo_name: str
    repo: Path
    branch: str
    default: str
    sha: str
    ahead: int
    date: str
    subject: str
    worktree: str  # path, or "" when it has none

    @property
    def location(self) -> Path:
        return Path(self.worktree) if self.worktree else self.repo


def unlanded(repos: list[tuple[str, Path]]) -> list[BranchInfo]:
    """Branches with changes not yet in their repo's default branch."""
    rows: list[BranchInfo] = []
    for name, repo in repos:
        if not (repo / ".git").exists():
            continue
        default = default_branch(repo)
        if default is None:
            continue
        by_branch = {wt.branch: wt for wt in worktrees(repo) if wt.branch}
        for branch in local_branches(repo):
            if branch == default or is_landed(repo, default, branch):
                continue
            rc, count, _ = git(repo, "rev-list", "--count",
                               f"refs/heads/{default}..refs/heads/{branch}")
            rc2, meta, _ = git(repo, "log", "-1", "--format=%cs%x00%s", f"refs/heads/{branch}")
            date, _, subject = meta.partition("\x00")
            wt = by_branch.get(branch)
            rows.append(BranchInfo(
                name, repo, branch, default, tip(repo, branch),
                int(count) if rc == 0 and count.isdigit() else 0,
                date, subject, str(wt.path) if wt else "",
            ))
    return rows


def commit_subjects(info: BranchInfo, limit: int = 5) -> list[str]:
    rc, out, _ = git(info.repo, "log", f"--max-count={limit}", "--format=%h %s",
                     f"refs/heads/{info.default}..refs/heads/{info.branch}")
    return out.splitlines() if rc == 0 else []


def delete_branch(info: BranchInfo, log: Path | None = None) -> tuple[bool, str]:
    """Delete an unlanded branch the owner confirmed: only if it has not moved
    and is not checked out anywhere. Logged with its tip for restoring."""
    repo, branch = info.repo, info.branch
    if branch == info.default:
        return False, "the default branch is never deleted"
    current = tip(repo, branch)
    if not current:
        return False, "the branch is gone"
    if current != info.sha:
        return False, "the branch has moved since the list was made; refresh first"
    if any(wt.branch == branch for wt in worktrees(repo)):
        return False, "it is checked out in a worktree; remove the worktree first"
    return _delete_branch_at(repo, branch, info.sha, log,
                             f"unlanded branch ({info.ahead} commits)")


def worktree_status(info: BranchInfo, busy: tuple[Path, ...] | None | str = "fresh",
                    now: float | None = None) -> str:
    """"" when the branch's worktree may be removed, else why not."""
    if not info.worktree:
        return "no worktree"
    wt = _find_worktree(info.repo, info.worktree)
    if wt is None:
        return "the worktree is gone"
    if busy == "fresh":
        busy = busy_dirs()
    blocker = worktree_blocker(info.repo, wt, busy, now)
    # The recent-agent rule protects Resolve; a deliberate removal may
    # override it after a warning, so it is not a blocker here.
    if blocker.startswith("an agent worktree"):
        return ""
    return blocker


def remove_worktree(info: BranchInfo, log: Path | None = None,
                    busy: tuple[Path, ...] | None | str = "fresh") -> tuple[bool, str]:
    """Remove a branch's clean worktree; the branch and its commits stay."""
    reason = worktree_status(info, busy)
    if reason:
        return False, reason
    rc, _, err = git(info.repo, "worktree", "remove", "--", info.worktree)
    if rc != 0:
        _log(f"FAILED remove worktree {info.worktree} of {info.repo}: {err}", log)
        return False, f"failed — {err}"
    _log(f"REMOVED worktree {info.worktree} of {info.repo} (branch {info.branch} kept)", log)
    return True, "removed; the branch is kept"
