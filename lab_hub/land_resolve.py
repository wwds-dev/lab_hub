"""Land leaves nothing open: the steps that resolve what Land used to leave.

Spec `docs/specs/land-resolve-all.md`, ADR 0001. `land.land()` runs these around
`repo_tidy`'s plan:

- `link_target()` / `repair_link()` (4.1): an app path that git records as a
  symlink but that was checked out as a text file.
- `prep()` / `apply_step()` (4.2–4.4): untracked files are scanned and either
  committed or moved to quarantine; a detached HEAD with work is put on a
  rescue branch; a main checkout on a feature branch is committed and switched
  to the default branch.
- `verdict()` / `archive()` (4.6): a branch that still did not land gets a
  Claude Code verdict, and is kept as a local tag `archive/<branch>/<date>`
  when it is archived. `archives()` / `restore()` serve Review branches.

Every git call goes through `repo_tidy.git` (no prompts, no inherited GIT_*),
every change is logged before it is made, and nothing is deleted: a
quarantined file is moved, an archived branch is tagged first.
"""

from __future__ import annotations

import fnmatch
import json
import os
import posixpath
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import repo_tidy as rt

QUARANTINE_ROOT = Path.home() / "Documents" / "lab" / ".quarantine"
MAX_BYTES = 10 * 1024 * 1024
SCAN_TIMEOUT = 120
# Secrets by name (spec 4.2): quarantined without a scan. Matched on the file
# name, case-insensitively.
SECRET_NAMES = (
    ".env", ".env.*", ".envrc", "*.pem", "*.key", "*.p12", "*.pfx", "id_rsa*", "id_dsa*",
    "id_ecdsa*", "id_ed25519*", "*credentials*", "*.keychain*", ".netrc", ".pypirc",
    ".npmrc", "*.tfvars", "*.kdbx", "*.jks", "*.keystore", "*.ppk",
)
# Binary files gitleaks reads well enough to trust a clean result (security
# P1-1): images. Any other binary (archives, databases, .gz) is quarantined.
IMAGE_MAGIC = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF87a", b"GIF89a", b"\x00\x00\x01\x00")
# Lab Hub's own gitleaks config: the default rules, never a repo's own file.
GITLEAKS_CONFIG = "[extend]\nuseDefault = true\n"
# A link checked out as a file is followed only to a folder under here (security P2-3).
LINK_ROOT = Path.home() / "Documents" / "lab"
SAFE_NAMES = (".env.example", ".env.sample", ".env.template")
ARCHIVE_PREFIX = "archive/"
KEPT_PREFIX = "refs/lab-hub/kept/"  # branches the owner restored: not archived again
TRIAGE_BUDGET_USD = 0.50
TRIAGE_TOOLS = "Read,Grep,Glob"
MAX_DIFF_BYTES = 200_000
RESCUE_PREFIX = "lab-hub/rescue-"


def _now() -> datetime:
    return datetime.now()


# ----------------------------------------------------------------------
# 4.1 A link checked out as a text file
# ----------------------------------------------------------------------
def _enclosing_repo(path: Path) -> Path | None:
    rc, top, _ = rt.git(path.parent, "rev-parse", "--show-toplevel")
    return Path(top) if rc == 0 and top else None


def link_target(path: Path) -> Path | None:
    """The folder a git symlink points at, when `path` is that symlink checked
    out as a plain file (`core.symlinks=false`); else None."""
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4096:
        return None
    top = _enclosing_repo(path)
    if top is None:
        return None
    rel = os.path.relpath(path, top)
    rc, out, _ = rt.git(top, "ls-files", "-s", "--", f":(literal){rel}")
    if rc != 0 or not out.startswith("120000 "):
        return None
    # Only the link git records, not a local edit of the file (security P2-3).
    rc, blob, _ = rt.git(top, "rev-parse", f"HEAD:{rel}")
    rc2, local, _ = rt.git(top, "hash-object", "--", rel)
    if rc != 0 or rc2 != 0 or blob != local:
        return None
    text = path.read_text(errors="replace").strip()
    if not text or "\n" in text or "\0" in text:
        return None
    target = (path.parent / text).resolve()
    try:
        inside = target.is_relative_to(LINK_ROOT.resolve())
    except OSError:
        inside = False
    return target if inside and target.is_dir() else None


def repair_link(path: Path, log: Path | None = None) -> bool:
    """Turn the text file back into the symlink git records, only when its text
    is exactly git's blob, so nothing local is overwritten."""
    top = _enclosing_repo(path)
    if top is None:
        return False
    rel = os.path.relpath(path, top)
    rc, blob, _ = rt.git(top, "rev-parse", f"HEAD:{rel}")
    rc2, local, _ = rt.git(top, "hash-object", "--", rel)
    if rc != 0 or rc2 != 0 or blob != local:
        return False
    rc, _, err = rt.git(top, "-c", "core.symlinks=true", "checkout", "--", f":(literal){rel}")
    if rc == 0:
        rt._log(f"RELINKED {path} as the symlink git records", log)
    return rc == 0 and path.is_symlink()


# ----------------------------------------------------------------------
# 4.2 Untracked files
# ----------------------------------------------------------------------
def untracked(path: Path) -> list[str] | None:
    """Untracked, not-ignored paths in a worktree (a nested repo ends in "/");
    None when git cannot tell."""
    rc, out, _ = rt.git(path, "ls-files", "--others", "--exclude-standard", "--directory",
                        "--no-empty-directory", "-z", strip=False)
    if rc != 0:
        return None
    found = []
    for entry in out.split("\0"):
        if not entry:
            continue
        if entry.endswith("/") and not (path / entry / ".git").exists():
            # A plain folder: list its files one by one.
            rc, sub, _ = rt.git(path, "ls-files", "--others", "--exclude-standard", "-z",
                                "--", f":(literal){entry}", strip=False)
            found += [e for e in sub.split("\0") if e] if rc == 0 else [entry]
        else:
            found.append(entry)
    return found


def secret_by_name(rel: str) -> bool:
    name = rel.rstrip("/").rsplit("/", 1)[-1].lower()
    if name in SAFE_NAMES:
        return False
    return any(fnmatch.fnmatchcase(name, pat) for pat in SECRET_NAMES)


@dataclass(frozen=True)
class Sorted:
    commit: tuple[str, ...] = ()
    quarantine: tuple[tuple[str, str], ...] = ()  # (path, why)
    ignore: tuple[str, ...] = ()  # nested repos: their own repo, ignored here
    error: str = ""
    blobs: tuple[tuple[str, str], ...] = ()  # (path, git blob id of the bytes scanned)
    links: tuple[str, ...] = ()  # links Land never commits (§3.1): ignored in place


def gitleaks_exe() -> str | None:
    return shutil.which("gitleaks", path=rt._SEARCH_PATH)


def _scan_env() -> dict[str, str]:
    # A repo, a shell or a host must not hand gitleaks another config.
    return {k: v for k, v in rt._env().items() if not k.startswith("GITLEAKS")}


def _run_gitleaks(args: list[str], tmp: Path) -> tuple[list[dict], str]:
    """Run gitleaks with Lab Hub's own config, no ignore file and no allow
    comments, from an empty folder; its JSON findings, or an error."""
    exe = gitleaks_exe()
    if exe is None:
        return [], "gitleaks is not installed (brew install gitleaks)"
    config = tmp / "gitleaks.toml"
    config.write_text(GITLEAKS_CONFIG)
    empty = tmp / "no-ignore"
    empty.mkdir()
    report = tmp / "report.json"
    try:
        r = subprocess.run(
            [exe, *args, "--config", str(config), "--gitleaks-ignore-path", str(empty),
             "--no-banner", "--redact", "--ignore-gitleaks-allow", "--log-level", "error",
             "--exit-code", "0", "--report-format", "json", "--report-path", str(report)],
            capture_output=True, text=True, timeout=SCAN_TIMEOUT, env=_scan_env(),
            cwd=empty, start_new_session=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return [], f"gitleaks failed: {exc}"
    if r.returncode != 0:
        return [], f"gitleaks failed: {(r.stderr or r.stdout).strip()[:200]}"
    try:
        findings = json.loads(report.read_text() or "[]")
    except (OSError, ValueError) as exc:
        return [], f"gitleaks gave no readable report: {exc}"
    if not isinstance(findings, list):
        return [], "gitleaks gave no readable report"
    return [f for f in findings if isinstance(f, dict)], ""


def scan(worktree: Path, paths: list[str]) -> tuple[dict[str, str], dict[str, str], str]:
    """gitleaks findings by path: ({path: rule id}, {path: blob id}, error).

    Each file is copied as `<n>/f` into an empty temporary folder: a neutral
    name, so gitleaks' path allowlist (lockfiles, images) cannot skip it, and no
    repo file can act as its config or ignore list. Archives are opened. A
    finding Lab Hub cannot place is an error (fail closed). The blob ids of the
    bytes scanned let the commit refuse a file that changed since."""
    if not paths:
        return {}, {}, ""
    with tempfile.TemporaryDirectory(prefix="lab-hub-scan-") as tmp:
        src = Path(tmp) / "src"
        where: dict[str, str] = {}
        copies: list[str] = []
        for i, rel in enumerate(paths):
            dest = src / str(i) / "f"
            dest.parent.mkdir(parents=True)
            source = worktree / rel
            try:
                if source.is_symlink():
                    dest.write_bytes(os.fsencode(os.readlink(source)))
                elif source.is_file():
                    shutil.copyfile(source, dest)
                else:
                    return {}, {}, f"{rel} is not a regular file"
            except OSError as exc:
                return {}, {}, f"could not read {rel} to scan it: {exc}"
            where[str(dest.resolve())] = rel
            copies.append(str(dest))
        # Hashed as `git add` will store them: the repo's filters for that path
        # (line endings, LFS), none for a link.
        blobs: dict[str, str] = {}
        for rel, copy in zip(paths, copies):
            how = (["--no-filters"] if (worktree / rel).is_symlink()
                   else [f"--path={rel}"])
            rc, out, err = rt.git(worktree, "hash-object", *how, "--", copy)
            if rc != 0 or not out:
                return {}, {}, f"could not hash {rel} as scanned: {err}"
            blobs[rel] = out
        findings, error = _run_gitleaks(["dir", str(src), "--max-archive-depth", "4"], Path(tmp))
        if error:
            return {}, {}, error
        hits: dict[str, str] = {}
        for item in findings:
            name = str(item.get("File", "")).split("!", 1)[0]  # "x.zip!inner/.env"
            try:
                rel = where.get(str(Path(name).resolve()))
            except OSError:
                rel = None
            if rel is None:
                return {}, {}, "gitleaks reported a finding Lab Hub cannot place; nothing committed"
            hits.setdefault(rel, str(item.get("RuleID", "secret")))
        return hits, blobs, ""


def is_unreadable_binary(path: Path) -> bool:
    """Binary, and not an image: gitleaks cannot be trusted to have read it."""
    try:
        with path.open("rb") as fh:
            head = fh.read(8192)
    except OSError:
        return False
    return b"\0" in head and not head.startswith(IMAGE_MAGIC)


def outgoing_findings(repo: Path, default: str) -> tuple[list[str], str]:
    """Secrets in the commits a push of `default` would publish (security
    P1-2): ["<file> (<rule>) in <commit>"], or an error."""
    with tempfile.TemporaryDirectory(prefix="lab-hub-push-scan-") as tmp:
        findings, error = _run_gitleaks(
            ["git", str(repo), "--log-opts", f"refs/remotes/origin/{default}..refs/heads/{default}"],
            Path(tmp))
    if error:
        return [], error
    return [f"{item.get('File', '?')} ({item.get('RuleID', 'secret')}) in "
            f"{str(item.get('Commit', ''))[:8]}" for item in findings], ""


def sort_untracked(worktree: Path) -> Sorted:
    paths = untracked(worktree)
    if paths is None:
        return Sorted(error="git cannot list its untracked files")
    commit, quarantine, ignore, to_scan, links = [], [], [], [], []
    for rel in paths:
        if rel.endswith("/"):
            ignore.append(rel)
        elif never_commit_link(worktree, rel):
            links.append(rel)
        elif secret_by_name(rel):
            quarantine.append((rel, "a secret by its name"))
        elif _size(worktree / rel) > MAX_BYTES:
            quarantine.append((rel, f"over {MAX_BYTES // (1024 * 1024)} MB"))
        elif not (worktree / rel).is_symlink() and is_unreadable_binary(worktree / rel):
            quarantine.append((rel, "a binary file the secret scan cannot read"))
        else:
            to_scan.append(rel)
    hits, blobs, error = scan(worktree, to_scan)
    if error:
        return Sorted(error=error)
    for rel in to_scan:
        if rel in hits:
            quarantine.append((rel, f"gitleaks: {hits[rel]}"))
        else:
            commit.append(rel)
    return Sorted(tuple(commit), tuple(quarantine), tuple(ignore),
                  blobs=tuple((r, blobs[r]) for r in commit), links=tuple(links))


def never_commit_link(worktree: Path, rel: str) -> bool:
    """A symlink Land must never commit (spec land-update-gaps §3.1):
    - it points at a folder, or the ignore rules would ignore its name if it
      were one. `.venv/` does not match a link, so SONAR's agent worktree
      committed its `.venv` link, and the main checkout that took it lost its
      virtualenv;
    - its text is absolute or it leads out of the worktree (owner decision
      §10.2 B): what it points at can become a folder after Land checks, and
      its text names a private path such as `/Users/<name>/.ssh/...`."""
    path = worktree / rel
    if not path.is_symlink():
        return False
    try:
        text = os.readlink(path)
        if path.is_dir() or text.endswith("/") or os.path.isabs(text):
            return True
        if not (path.parent / text).resolve().is_relative_to(worktree.resolve()):
            return True
    except (OSError, RuntimeError):  # RuntimeError: a link loop on older Pythons
        return True  # cannot tell: never commit it
    return ignored_as_folder(worktree, rel)


def ignored_as_folder(worktree: Path, rel: str) -> bool:
    """Would `rel` be ignored if it were a folder? git will not check a path
    behind a symlink, so ask about it in an empty copy of the folders that
    holds only their `.gitignore` files (the git dir still adds
    `info/exclude` and `core.excludesFile`). True when git cannot tell."""
    rc, git_dir, _ = rt.git(worktree, "rev-parse", "--absolute-git-dir")
    if rc != 0 or not git_dir:
        return True
    parts = Path(rel).parts
    try:
        root = worktree.resolve()
    except OSError:
        return True
    with tempfile.TemporaryDirectory(prefix="lab-hub-ignore-") as tmp:
        mirror = Path(tmp)
        try:
            for depth in range(len(parts)):
                src = worktree.joinpath(*parts[:depth], ".gitignore")
                # git does not follow a .gitignore that is a link either, and a
                # folder swapped for a link since the listing is not followed
                # out of the worktree (security P3-3).
                if (src.is_file() and not src.is_symlink()
                        and src.resolve().is_relative_to(root)):
                    dest = mirror.joinpath(*parts[:depth], ".gitignore")
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(src, dest)
        except OSError:
            return True
        # "./": a name starting with ":" is not read as pathspec magic (review
        # P3-1, security P3-1).
        rc, _, err = rt.git(mirror, f"--git-dir={git_dir}", f"--work-tree={mirror}",
                            "check-ignore", "--no-index", "-q", "--", f"./{rel}/")
    # 0: ignored; 1 with nothing said: not ignored. A git that could not run or
    # timed out also comes back as 1, with the error: cannot tell (review P3-2).
    return not (rc == 1 and not err)


# ----------------------------------------------------------------------
# A link a branch already contains (spec land-folder-link-guard)
# ----------------------------------------------------------------------
LINK_MODE = "120000"
# The start of a merge's link stop; `claude_resolve.blocker_kind` keys on it.
LINK_STOPS = ("it adds a link at ", "it may add a link")
_OID = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")


def incoming_links(checkout: Path, old: str, new: str) -> list[tuple[str, str]] | None:
    """(path, blob) for every path that is a symlink in `new` and was not the
    same symlink in `old` (commits or trees); None when git cannot tell."""
    rc, out, _ = rt.git(checkout, "diff-tree", "-r", "-z", "--no-renames", "--no-abbrev",
                        old, new, strip=False)
    if rc != 0:
        return None
    parts = out.split("\0")
    if parts and parts[-1] == "":
        parts.pop()
    if len(parts) % 2:
        return None
    found = []
    for meta, rel in zip(parts[::2], parts[1::2]):
        fields = meta.lstrip(":").split()
        if len(fields) != 5 or not rel:
            return None
        if fields[1] == LINK_MODE:
            found.append((rel, fields[3]))
    return found


def _tracked(checkout: Path, rel: str) -> bool | None:
    rc, out, _ = rt.git(checkout, "ls-files", "-z", "--", f":(literal){rel}", strip=False)
    if rc != 0:
        return None
    return rel in out.split("\0")


def link_problem(checkout: Path, rel: str, blob: str) -> str:
    """Why the link `rel` (its text in `blob`) must not reach `checkout`, or ""
    (spec land-folder-link-guard §3.2). Its target is judged on the text only:
    it need not exist yet. A link to a folder inside the repo passes (§2.3)."""
    parts = Path(rel).parts
    try:
        for depth in range(1, len(parts)):
            if checkout.joinpath(*parts[:depth]).is_symlink():
                return "behind a link in this checkout"
        path = checkout / rel
        if path.is_dir() and not path.is_symlink():
            return "where this checkout has a real folder"
        if os.path.lexists(path):
            tracked = _tracked(checkout, rel)
            if tracked is None:
                return "that git cannot check"
            if not tracked:
                return "where this checkout has a file git does not track"
    except OSError:
        return "that git cannot check"
    if ignored_as_folder(checkout, rel):
        return "a name ignored as a folder here"
    rc, text, _ = rt.git(checkout, "cat-file", "blob", blob, strip=False)
    if rc != 0:
        return "that git cannot check"
    if not text or "\n" in text or "\0" in text:
        return "whose target git cannot read"
    if os.path.isabs(text):
        return "whose target is an absolute path"
    if text.endswith("/"):
        return "whose target ends in /"
    target = posixpath.normpath(posixpath.join(posixpath.dirname(rel), text))
    if target == ".." or target.startswith("../"):
        return "whose target is outside the repo"
    return ""


def _shown(rel: str) -> str:
    """A branch's path, safe to show: no control characters, at most 120 long."""
    text = re.sub(r"[\x00-\x1f\x7f]", "?", rel)
    return text if len(text) <= 120 else text[:119] + "…"


def link_stop(checkout: Path, old: str, new: str, who: str = "it",
              fix_in: str = "the branch") -> str:
    """The stop when moving `checkout` from `old` to `new` would bring a link
    that §3.2 refuses, or "" when there is none."""
    links = incoming_links(checkout, old, new)
    if links is None:
        return f"{who} may add a link that git cannot check: Land again, or land it by hand"
    bad = [(rel, why) for rel, blob in links if (why := link_problem(checkout, rel, blob))]
    if not bad:
        return ""
    rel, why = bad[0]
    text = f"{who} adds a link at {_shown(rel)} {why}"
    others = [_shown(r) for r, _ in bad[1:]]
    if others:
        text += f"; also at {', '.join(others[:2])}"
        if len(others) > 2:
            text += f" and {len(others) - 2} more"
    return f"{text}: remove the link from {fix_in}, then Land again"


def merge_link_stop(repo: Path, default: str, branch: str) -> str:
    """`link_stop` for merging `branch` into `default` in the main checkout,
    judged on the merge result git would write (with or without conflicts)."""
    trees = rt.worktrees(repo)
    rc, out, _ = rt.git(repo, "merge-tree", "--write-tree",
                        f"refs/heads/{default}", f"refs/heads/{branch}")
    tree = out.splitlines()[0].strip() if out else ""
    if not trees or rc not in (0, 1) or not _OID.fullmatch(tree):
        return "it may add a link that git cannot check: Land again, or land it by hand"
    return link_stop(trees[0].path, f"refs/heads/{default}", tree)


def _size(path: Path) -> int:
    try:
        return path.lstat().st_size
    except OSError:
        return 0


_GLOB = re.compile(r"([*?\[\]\\])")


def ignore_line(rel: str) -> str:
    """A .gitignore line matching exactly this path from the repo root."""
    line = "/" + _GLOB.sub(r"\\\1", rel)
    if line.endswith(" "):
        line = line[:-1] + "\\ "
    return line


def quarantine_dir(repo_name: str, when: datetime | None = None,
                   root: Path | None = None) -> Path:
    when = when or _now()
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", repo_name) or "repo"
    return (root or QUARANTINE_ROOT) / safe / when.strftime("%Y-%m-%d")


def _private_dirs(folder: Path, root: Path) -> None:
    """Make `folder` and every folder from `root` down to it, owner-only."""
    folder.mkdir(parents=True, exist_ok=True)
    if not folder.is_relative_to(root):
        os.chmod(folder, 0o700)
        return
    for part in [folder, *folder.parents]:
        os.chmod(part, 0o700)
        if part == root:
            break


def _free(dest: Path) -> Path:
    """`dest`, or `dest.2`, `dest.3`… when that name is taken."""
    stem, n = dest.name, 2
    while dest.exists() or dest.is_symlink():
        dest = dest.with_name(f"{stem}.{n}")
        n += 1
    return dest


def _move(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.rename(src, dest)
    except OSError:
        shutil.move(str(src), str(dest))


# ----------------------------------------------------------------------
# Prep steps (4.2–4.4)
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class Step:
    repo_name: str
    repo: Path
    kind: str  # rescue | untracked | switch
    target: str  # the worktree path
    detail: str = ""  # untracked: what goes where; switch: the branch it was on
    files: tuple[str, ...] = ()  # untracked, switch: the files that may be committed
    quarantine: tuple[tuple[str, str], ...] = ()
    ignored: tuple[str, ...] = ()  # nested repos, only added to .gitignore
    links: tuple[str, ...] = ()  # links Land never commits, only added to .gitignore

    @property
    def label(self) -> str:
        if self.kind == "rescue":
            return (f"{self.repo_name}: Put the detached HEAD in {self.target} on a new "
                    f"branch {RESCUE_PREFIX}… — {self.detail}")
        if self.kind == "switch":
            return (f"{self.repo_name}: Commit open work on {self.detail} and switch the "
                    f"checkout to the default branch")
        parts = []
        if self.files:
            # Every file, not "and N more": this list is what the owner checks (spec §7).
            parts.append(f"commit {len(self.files)} untracked file"
                         f"{'s' if len(self.files) != 1 else ''}: " + ", ".join(self.files))
        if self.quarantine:
            parts.append("move to quarantine and ignore: " + ", ".join(
                f"{p} ({why})" for p, why in self.quarantine))
        if self.ignored:
            parts.append("ignore nested repos: " + ", ".join(self.ignored))
        if self.links:
            parts.append("ignore links to folders or outside the repo (never committed): "
                         + ", ".join(self.links))
        return f"{self.repo_name}: In {self.target}, " + "; ".join(parts or ["nothing"])


@dataclass(frozen=True)
class Stop:
    """A hard stop (spec 4.7): Land cannot resolve this; one action clears it."""
    repo_name: str
    target: str
    reason: str
    processes: tuple[str, ...] = ()  # every "cmd (pid N)" in the worktree, for Details

    @property
    def label(self) -> str:
        return f"{self.repo_name}: {self.target} — {self.reason}"


# The one action each known stop asks for: the reason ends with ": <action>".
# Only these are split off for the confirmation (spec land-confirm-dialog §8);
# any other reason is shown whole, never cut at a colon inside a path or error.
STOP_ACTIONS = (
    "close that terminal or session, then Land again",
    "finish or abort it in Terminal",
    "resolve them in Terminal",
    "set origin/HEAD",
    "fix the app's path",
)


def in_own_tree(wt: rt.Worktree, trees: list[rt.Worktree], busy) -> bool:
    """A process has its current folder in this worktree itself, not in another
    worktree nested inside it (agent worktrees live under the main checkout's
    `.claude/worktrees/`). Fails closed like `repo_tidy.in_use`."""
    if busy is None:
        return True
    try:
        target = wt.path.resolve()
        nested = [t.path.resolve() for t in trees
                  if t.path != wt.path and t.path.resolve().is_relative_to(target)]
    except OSError:
        return True
    for cwd in busy:
        try:
            cwd = cwd.resolve()
        except OSError:
            continue
        if cwd.is_relative_to(target) and not any(cwd.is_relative_to(n) for n in nested):
            return True
    return False


def _worktree_stop(repo: Path, wt: rt.Worktree, busy) -> str:
    return _worktree_stop_full(repo, wt, busy)[0]


def _worktree_stop_full(repo: Path, wt: rt.Worktree, busy,
                        listing=None) -> tuple[str, tuple[str, ...]]:
    """The stop's reason ("" when none) and, for a busy worktree, every process in it.
    `listing` returns one shared `lsof` reading (security review P3-3)."""
    paused = rt.paused_operation(wt.path)
    if paused:
        return f"{paused} is in progress: finish or abort it in Terminal", ()
    if rt.has_conflicts(wt.path):
        return "it has unresolved conflicts: resolve them in Terminal", ()
    if busy is None:
        return "could not check whether a process is running in it (lsof failed)", ()
    if in_own_tree(wt, rt.worktrees(repo), busy):
        found = processes_in(wt, rt.worktrees(repo), listing() if listing else None)
        who = _first(found)
        return (f"a process is running in it{f' ({who})' if who else ''}: close that "
                "terminal or session, then Land again"), tuple(found)
    return "", ()


def _first(found: list[str], limit: int = 3) -> str:
    more = f" and {len(found) - limit} more" if len(found) > limit else ""
    return ", ".join(found[:limit]) + more


def who_is_in(wt: rt.Worktree, trees: list[rt.Worktree], limit: int = 3) -> str:
    """"claude (pid 4712), zsh (pid 15934)" for processes whose current folder
    is this worktree (not one nested in it); "" when lsof cannot tell."""
    return _first(processes_in(wt, trees), limit)


LSOF_TIMEOUT = 10  # seconds; planning waits on it (security review P3-3)
NAME_MAX = 40  # a process names itself: cut it for display (security review P3-1)


def _shown_name(cmd: str) -> str:
    """A process's own name, safe to show: no control characters, at most NAME_MAX."""
    clean = "".join(ch if ch.isprintable() else "?" for ch in cmd)
    return clean if len(clean) <= NAME_MAX else clean[:NAME_MAX - 1] + "…"


def cwd_listing() -> list[tuple[str, str, Path]] | None:
    """(name, pid, current folder) of every process, from one `lsof` run;
    None when lsof cannot tell."""
    lsof = shutil.which("lsof", path=rt._SEARCH_PATH)
    if lsof is None:
        return None
    try:
        r = subprocess.run([lsof, "-n", "-P", "-d", "cwd", "-F", "pcn"], capture_output=True,
                           text=True, timeout=LSOF_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    listing, pid, cmd = [], "", ""
    for line in r.stdout.splitlines():
        tag, value = line[:1], line[1:]
        if tag == "p":
            pid = value
        elif tag == "c":
            cmd = _shown_name(value)
        elif tag == "n" and value.startswith("/"):
            listing.append((cmd, pid, Path(value)))
    return listing


def processes_in(wt: rt.Worktree, trees: list[rt.Worktree],
                 listing: list[tuple[str, str, Path]] | None = None) -> list[str]:
    """Every "cmd (pid N)" whose current folder is this worktree (not one
    nested in it), in lsof's order; [] when lsof cannot tell."""
    if listing is None:
        listing = cwd_listing() or []
    found = [f"{cmd} (pid {pid})" for cmd, pid, cwd in listing
             if in_own_tree(wt, trees, (cwd,))]
    return list(dict.fromkeys(found))


def _rescue_needed(repo: Path, wt: rt.Worktree) -> bool:
    if wt.branch or not wt.path.exists():
        return False
    if not rt.is_clean(wt.path):
        return True
    # A clean detached HEAD whose commit no branch holds is open work too,
    # unless an archive tag holds it (Land detached it there: review P1-1).
    rc, out, _ = rt.git(repo, "branch", "--contains", wt.head, "--format=%(refname:short)")
    if rc != 0 or out.strip():
        return False
    rc, tags, _ = rt.git(repo, "tag", "--contains", wt.head, "--list", f"{ARCHIVE_PREFIX}*")
    return not (rc == 0 and tags.strip())


def prep(name: str, repo: Path, busy) -> tuple[list[Step], list[Stop]]:
    """The prep steps one repo needs now, and its hard stops."""
    steps: list[Step] = []
    stops: list[Stop] = []
    default = rt.default_branch(repo)
    if default is None:
        return steps, [Stop(name, str(repo), "no default branch found: set origin/HEAD")]
    seen: list = []

    def listing():  # one lsof run for every busy worktree of this repo, only when needed
        if not seen:
            seen.append(cwd_listing() or [])
        return seen[0]

    for wt in rt.worktrees(repo):
        if not wt.path.exists():
            continue
        open_work = _rescue_needed(repo, wt) or not rt.is_clean(wt.path) or (
            wt.main and rt.current_branch(wt.path) != default)
        if not open_work:
            continue
        stop, who = _worktree_stop_full(repo, wt, busy, listing)
        if stop:
            stops.append(Stop(name, str(wt.path), stop, who))
            continue
        if _rescue_needed(repo, wt):
            steps.append(Step(name, repo, "rescue", str(wt.path),
                              f"at {wt.head[:8]}, work no branch holds"))
        sort = sort_untracked(wt.path)
        if sort.error:
            stops.append(Stop(name, str(wt.path), sort.error))
            continue
        if sort.commit or sort.quarantine or sort.ignore or sort.links:
            steps.append(Step(name, repo, "untracked", str(wt.path), files=sort.commit,
                              quarantine=sort.quarantine, ignored=sort.ignore,
                              links=sort.links))
        if wt.main and rt.current_branch(wt.path) != default:
            steps.append(Step(name, repo, "switch", str(wt.path),
                              rt.current_branch(wt.path) or "a detached HEAD",
                              files=sort.commit))
    return steps, stops


def _commit_all_tracked(path: Path, message: str) -> tuple[int, str]:
    if rt.tracked_clean(path):
        return 0, ""
    rc, _, err = rt.git(path, "add", "--update")
    if rc == 0:
        rc, _, err = rt.git(path, "commit", "--quiet", "-m", message)
    return rc, err


def apply_step(step: Step, log: Path | None = None, busy="fresh",
               quarantine_root: Path | None = None) -> tuple[bool, str]:
    """Re-check, then run one prep step: (done, what happened)."""
    if busy == "fresh":
        busy = rt.busy_dirs()
    wt = rt._find_worktree(step.repo, step.target)
    if wt is None:
        return False, "skipped — the worktree is gone"
    stop = _worktree_stop(step.repo, wt, busy)
    if stop:
        return False, f"skipped — {stop}"
    path = wt.path
    stamp = f"{_now():%Y-%m-%d %H:%M}"
    if step.kind == "rescue":
        if wt.branch:
            return True, f"already on {wt.branch}"
        name = f"{RESCUE_PREFIX}{_now():%Y%m%d}-{wt.head[:8]}"
        rc, _, err = rt.git(path, "switch", "--quiet", "-c", name)
        if rc != 0:
            return False, f"failed — {err}"
        rt._log(f"RESCUED detached HEAD {wt.head} in {path} onto branch {name}", log)
        rc, err = _commit_all_tracked(path, f"Lab Hub: commit open work, {stamp}")
        if rc != 0:
            return False, f"failed — {err}"
        return True, f"on new branch {name}"
    if step.kind == "untracked":
        return _apply_untracked(step, path, log, quarantine_root, stamp)
    if step.kind == "switch":
        default = rt.default_branch(step.repo)
        if default is None:
            return False, "failed — no default branch found"
        sort = sort_untracked(path)
        if sort.error:
            return False, f"skipped — {sort.error}"
        if sort.commit or sort.quarantine or sort.links:
            ok, msg = _apply_untracked(Step(step.repo_name, step.repo, "untracked", step.target,
                                            files=step.files, quarantine=sort.quarantine,
                                            links=sort.links),
                                       path, log, quarantine_root, stamp)
            if not ok:
                return ok, msg
        if not rt.current_branch(path):
            ok, msg = apply_step(Step(step.repo_name, step.repo, "rescue", step.target),
                                 log, busy, quarantine_root)
            if not ok:
                return ok, msg
        was = rt.current_branch(path)
        if was == default:
            return True, f"already on {default}"
        rc, err = _commit_all_tracked(path, f"Lab Hub: commit open work, {stamp}")
        if rc != 0:
            return False, f"failed — could not commit the open work on {was}: {err}"
        # git would replace an ignored real folder with a link (land-folder-link-guard).
        why = link_stop(path, "HEAD", f"refs/heads/{default}", who=default, fix_in=default)
        if why:
            rt._log(f"NOT SWITCHED checkout {path} from {was} to {default}: {why}", log)
            return False, f"failed — {why}"
        rc, _, err = rt.git(path, "switch", "--quiet", default)
        if rc != 0:
            return False, f"failed — could not switch to {default}: {err}"
        rt._log(f"SWITCHED checkout {path} from {was} to {default}", log)
        return True, f"switched from {was} to {default}; {was} lands as a branch"
    return False, f"unknown step {step.kind}"


def _apply_untracked(step: Step, path: Path, log: Path | None,
                     quarantine_root: Path | None, stamp: str) -> tuple[bool, str]:
    # Before anything moves: a commit needs a branch (review P2-1).
    if not rt.current_branch(path):
        return False, "skipped — it is on a detached HEAD"
    # Fresh look: a file may have appeared, changed or gone since the preview.
    # Only files the preview listed are committed (review P2-3); a new one waits
    # for the next Land. Secrets found now are quarantined either way.
    sort = sort_untracked(path)
    if sort.error:
        return False, f"skipped — {sort.error}"
    allowed = set(step.files)
    commit = [p for p in sort.commit if p in allowed]
    blobs = {p: b for p, b in sort.blobs if p in allowed}
    lines = []
    dest_dir = quarantine_dir(step.repo_name, root=quarantine_root)
    for rel, why in sort.quarantine:
        try:
            _private_dirs(dest_dir, quarantine_root or QUARANTINE_ROOT)
            (dest_dir / rel).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            dest = _free(dest_dir / rel)
        except OSError as exc:
            return False, f"failed — could not prepare the quarantine folder: {exc}"
        if not rt._log(f"QUARANTINE {path / rel} -> {dest} ({why})", log):
            return False, "skipped — could not write the log"
        try:
            _move(path / rel, dest)
        except OSError as exc:
            return False, f"failed — could not move {rel} to quarantine: {exc}"
        if "\n" not in rel and "\r" not in rel:  # never a forged line (security P2-2)
            lines.append(ignore_line(rel))
    for rel in sort.ignore:
        if "\n" in rel or "\r" in rel:
            return False, "skipped — a nested repo has a line break in its name: rename it"
        lines.append(ignore_line(rel.rstrip("/")) + "/")
        rt._log(f"IGNORED nested repo {path / rel}", log)
    for rel in sort.links:
        if "\n" in rel or "\r" in rel:
            return False, "skipped — a link has a line break in its name: rename it"
        # No trailing "/": a folder pattern does not match a link (spec land-update-gaps §3.1).
        lines.append(ignore_line(rel))
        rt._log(f"IGNORED link {path / rel} (to a folder or outside the repo)", log)
    add = list(commit)
    if lines:
        gi = path / ".gitignore"
        if gi.is_symlink() or (gi.exists() and not gi.is_file()):
            return False, "skipped — its .gitignore is not a regular file"
        try:
            before = gi.read_text() if gi.exists() else ""
            with gi.open("a") as fh:
                if before and not before.endswith("\n"):
                    fh.write("\n")
                fh.write("# Lab Hub: moved to quarantine, a nested repo or a link, "
                         f"{stamp}\n" + "\n".join(lines) + "\n")
        except OSError as exc:
            return False, f"failed — could not update .gitignore: {exc}"
        add.append(".gitignore")
    if not add:
        return True, "nothing left to commit"
    rc, _, err = rt.git(path, "add", "--", *[f":(literal){p}" for p in add])
    if rc == 0:
        changed = _staged_differs(path, blobs)
        if changed:
            rt.git(path, "reset", "--quiet", "--", *[f":(literal){p}" for p in add])
            return False, (f"skipped — {changed} changed after the secret scan; nothing "
                           "committed (Land again)")
        rc, _, err = rt.git(path, "commit", "--quiet", "-m",
                            f"Lab Hub: add untracked files, {stamp}")
    if rc != 0:
        return False, f"failed — {err}"
    rt._log(f"COMMITTED {len(commit)} untracked file(s) in {path}; "
            f"{len(sort.quarantine)} quarantined", log)
    done = f"{len(commit)} committed"
    if sort.quarantine:
        done += f", {len(sort.quarantine)} moved to {dest_dir}"
    if sort.links:
        done += (f", {len(sort.links)} link{'s' if len(sort.links) != 1 else ''} ignored "
                 f"({', '.join(sort.links)})")
    return True, done


def _staged_differs(path: Path, blobs: dict[str, str]) -> str:
    """The first file whose staged blob is not the one scanned, or whose mode is
    not a plain file or link (security P2-1); "" when all match."""
    if not blobs:
        return ""
    rc, out, _ = rt.git(path, "ls-files", "-s", "-z", "--",
                        *[f":(literal){p}" for p in blobs], strip=False)
    if rc != 0:
        return "the index"
    staged: dict[str, tuple[str, str]] = {}
    for entry in out.split("\0"):
        if not entry:
            continue
        meta, _, name = entry.partition("\t")
        mode, blob, _stage = meta.split(" ")
        staged[name] = (mode, blob)
    for rel, blob in blobs.items():
        mode, got = staged.get(rel, ("", ""))
        if got != blob or mode not in ("100644", "100755", "120000"):
            return rel
    if set(staged) - set(blobs):
        return sorted(set(staged) - set(blobs))[0]
    return ""


# ----------------------------------------------------------------------
# 4.6 Branches that did not land: verdict and archive
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class Verdict:
    land: bool
    reason: str
    cost: float = 0.0
    ok: bool = True  # False: Claude could not be asked; `reason` says why


_VERDICT = re.compile(r"^`?VERDICT:\s*(land|archive)\b[\s:—-]*(.*?)`?\s*$", re.IGNORECASE)


def parse_verdict(text: str) -> tuple[str, str] | None:
    for line in reversed(text.strip().splitlines()):
        m = _VERDICT.match(line.strip())
        if m:
            return m.group(1).lower(), m.group(2).strip()
    return None


def triage_prompt(info: rt.BranchInfo, worktree_note: str, why_not: str,
                  copies: int = 0) -> str:
    copied = (f" {copies} of those commits already appear in `{info.default}` as copies "
              "(matched by patch)." if copies else "")
    return (
        f"You are deciding what to do with git branch `{info.branch}` of repo "
        f"`{info.repo_name}`. It has {info.ahead} commit(s) that `{info.default}` does not "
        f"have; its last commit is from {info.date}.{copied} {worktree_note}\n"
        f"Lab Hub could not land it automatically: {why_not}\n\n"
        "This folder holds `log.txt` (its commits), `stat.txt` (files changed) and "
        "`diff.txt` (the diff against the default branch, possibly cut). Read them. "
        "Decide whether the branch is still useful work that belongs in "
        f"`{info.default}` (land) or stale, superseded, experimental or abandoned "
        "(archive). Archived branches are kept as a tag and can be restored.\n"
        "Do not change any file. End your reply with exactly one line:\n"
        "VERDICT: land — <one sentence why>\n"
        "or\n"
        "VERDICT: archive — <one sentence why>"
    )


def verdict(info: rt.BranchInfo, exe: str, why_not: str, stop=None,
            progress=None) -> Verdict:
    """Ask Claude Code, read-only, in a folder holding only the branch's log and diff."""
    from . import claude_resolve as cr

    repo, base, head = info.repo, f"refs/heads/{info.default}", f"refs/heads/{info.branch}"
    _, log_text, _ = rt.git(repo, "log", "--max-count=50", "--format=%h %cs %s",
                            f"{base}..{head}")
    _, stat, _ = rt.git(repo, "diff", "--stat", f"{base}...{head}")
    _, diff, _ = rt.git(repo, "diff", f"{base}...{head}", strip=False, timeout=60)
    if len(diff.encode()) > MAX_DIFF_BYTES:
        diff = diff.encode()[:MAX_DIFF_BYTES].decode(errors="ignore") + "\n[diff cut here]\n"
    note = (f"It is checked out in worktree {info.worktree}." if info.worktree
            else "It has no worktree.")
    rc, cherry, _ = rt.git(repo, "cherry", base, head)
    copies = sum(1 for ln in cherry.splitlines() if ln.startswith("- ")) if rc == 0 else 0
    with tempfile.TemporaryDirectory(prefix="lab-hub-triage-") as tmp:
        folder = Path(tmp)
        (folder / "log.txt").write_text(log_text)
        (folder / "stat.txt").write_text(stat)
        (folder / "diff.txt").write_text(diff)
        result = cr.run_claude(exe, triage_prompt(info, note, why_not, copies), folder,
                               TRIAGE_BUDGET_USD, stop or cr.Stopper(),
                               progress or (lambda _m: None), tools=TRIAGE_TOOLS)
    if not result.ok:
        return Verdict(False, result.reason, result.cost, ok=False)
    parsed = parse_verdict(result.text)
    if parsed is None:
        return Verdict(False, "Claude gave no VERDICT line", result.cost, ok=False)
    kind, why = parsed
    return Verdict(kind == "land", cr._flat(why or kind, 200), result.cost)


def archive_tag(repo: Path, branch: str, when: datetime | None = None) -> str:
    base = f"{ARCHIVE_PREFIX}{branch}/{(when or _now()):%Y-%m-%d}"
    name, n = base, 2
    while rt.git(repo, "rev-parse", "--verify", "--quiet", f"refs/tags/{name}")[0] == 0:
        name = f"{base}-{n}"
        n += 1
    return name


def archive(info: rt.BranchInfo, reason: str, log: Path | None = None,
            busy="fresh", now: float | None = None) -> tuple[bool, str]:
    """Keep the branch as a local tag, then delete it; its worktree is removed
    when the removal guards allow, else detached at the same commit."""
    repo, branch = info.repo, info.branch
    if branch == info.default:
        return False, "the default branch is never archived"
    sha = rt.tip(repo, branch)
    if not sha:
        return False, "the branch is gone"
    if sha != info.sha:
        return False, "the branch has moved since it was looked at"
    if busy == "fresh":
        busy = rt.busy_dirs()
    wt = next((w for w in rt.worktrees(repo) if w.branch == branch), None)
    if wt is not None:
        if wt.main:
            return False, "it is checked out in the repo's own checkout"
        if wt.path.exists():
            stop = _worktree_stop(repo, wt, busy)
            if stop:
                return False, f"its worktree {wt.path}: {stop}"
            if not rt.is_clean(wt.path):
                return False, f"its worktree {wt.path} has uncommitted or untracked files"
    tag = archive_tag(repo, branch)
    if not rt._log(f"ARCHIVING branch {branch} at {sha} in {repo} as tag {tag} ({reason}); "
                   f"restore: git -C {repo} branch {branch} {tag}^{{commit}}", log):
        return False, "could not write the log"
    rc, _, err = rt.git(repo, "tag", "-a", "-m", f"Lab Hub archive: {reason}", tag, sha)
    if rc != 0:
        return False, f"could not tag it: {err}"
    if wt is not None and wt.path.exists():
        if not rt.worktree_blocker(repo, wt, busy, now):
            rc, _, err = rt.git(repo, "worktree", "remove", "--", str(wt.path))
            if rc == 0:
                rt._log(f"REMOVED worktree {wt.path} of {repo} (branch archived)", log)
        else:
            rc, _, err = rt.git(wt.path, "switch", "--quiet", "--detach", sha)
            if rc == 0:
                rt._log(f"DETACHED worktree {wt.path} at {sha} (branch archived)", log)
        if rc != 0:
            return False, f"tagged {tag}, but its worktree could not be freed: {err}"
    rc, _, err = rt.git(repo, "update-ref", "-d", f"refs/heads/{branch}", sha)
    if rc != 0:
        return False, f"tagged {tag}, but the branch could not be deleted: {err}"
    rt._log(f"ARCHIVED {branch} as {tag} in {repo}", log)
    return True, f"archived as tag {tag}"


@dataclass(frozen=True)
class Archived:
    repo_name: str
    repo: Path
    tag: str
    sha: str
    date: str
    reason: str

    @property
    def branch(self) -> str:
        """The branch name the tag was made from."""
        rest = self.tag.removeprefix(ARCHIVE_PREFIX)
        return rest.rsplit("/", 1)[0] if "/" in rest else rest


def archives(repos: list[tuple[str, Path]]) -> list[Archived]:
    rows = []
    for name, repo in repos:
        if not (repo / ".git").exists():
            continue
        rc, out, _ = rt.git(repo, "for-each-ref", "--sort=-creatordate",
                            "--format=%(refname:lstrip=2)%00%(*objectname)%00"
                            "%(creatordate:short)%00%(contents:subject)",
                            f"refs/tags/{ARCHIVE_PREFIX}")
        if rc != 0:
            continue
        for line in out.splitlines():
            parts = line.split("\0")
            if len(parts) != 4 or not parts[1]:
                continue
            tag, sha, date, subject = parts
            rows.append(Archived(name, repo, tag, sha, date,
                                 subject.removeprefix("Lab Hub archive: ")))
    return rows


def restore(item: Archived, log: Path | None = None) -> tuple[bool, str]:
    """Recreate the branch from its archive tag, then drop the tag."""
    repo, branch = item.repo, item.branch
    if rt.tip(repo, branch):
        return False, f"a branch {branch} exists already"
    rc, sha, _ = rt.git(repo, "rev-parse", "--verify", "--quiet", f"refs/tags/{item.tag}^{{commit}}")
    if rc != 0 or sha != item.sha:
        return False, "the archive tag has changed since the list was made; refresh first"
    rc, _, err = rt.git(repo, "branch", "--", branch, sha)
    if rc != 0:
        return False, f"failed — {err}"
    # The owner chose to keep it: Land leaves it alone while it stays at this
    # commit (review P2-5); new commits on it bring it back into Land.
    rt.git(repo, "update-ref", f"{KEPT_PREFIX}{branch}", sha)
    rt.git(repo, "tag", "-d", item.tag)
    rt._log(f"RESTORED branch {branch} at {sha} in {repo} from {item.tag}", log)
    return True, f"restored branch {branch}"


def kept(info: rt.BranchInfo) -> bool:
    """The owner restored this branch and it has not moved since."""
    rc, sha, _ = rt.git(info.repo, "rev-parse", "--verify", "--quiet",
                        f"{KEPT_PREFIX}{info.branch}")
    return rc == 0 and sha == info.sha


def unlanded(repo: Path, name: str = "") -> list[rt.BranchInfo]:
    """Branches not landed, without the ones the owner restored and kept."""
    return [b for b in rt.unlanded([(name, repo)]) if not kept(b)]


# ----------------------------------------------------------------------
# What is still open (the honest end of a Land)
# ----------------------------------------------------------------------
def open_items(repo: Path) -> list[str]:
    """Everything a tile's badge would still count, in words; [] when none."""
    items = []
    default = rt.default_branch(repo)
    if default is None:
        return ["no default branch found"]
    trees = rt.worktrees(repo)
    if trees and rt.current_branch(trees[0].path) != default:
        items.append(f"the checkout is not on {default}")
    for wt in trees:
        if wt.path.exists() and not rt.is_clean(wt.path):
            items.append(f"{wt.path} has uncommitted or untracked files")
    n = len(unlanded(repo))
    if n:
        items.append(f"{n} branch{'es' if n != 1 else ''} not landed")
    counts = rt.ahead_behind(repo) if trees else None
    if counts and (counts[0] or counts[1]):
        items.append(f"{default} is {counts[0]} ahead, {counts[1]} behind origin")
    return items
