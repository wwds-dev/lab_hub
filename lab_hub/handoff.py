"""Ask Claude: hand the rows Lab Hub could not clear to a Claude Code session.

Check builds and Land end with rows only a person (or a session the person
watches) can clear. This module turns those rows, exactly as the window shows
them, into one prompt per repo and opens `claude` in Terminal in that repo's
folder. No Qt here; the dialog is `ui.handoff_dialog`.

Spec: `docs/specs/claude-handoff.md`. ADR 0004.

Boundaries (ADR 0004):
- The prompt holds only what the window shows (row text, paths, commands) and
  the names and pids of processes running in the checkout. No repo file is read.
- Repo text never becomes shell syntax: it reaches `claude` only through
  `"$(cat -- <file>)"`; every other value in the line is `shlex.quote`d.
- Every session runs in `manual` permission mode with a settings file that asks
  before push, merge, tag and install, and denies the sign-off commands.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import repo_tidy as rt

# Statuses that mean "Lab Hub stopped here" (spec §1). Icons `needs` and
# `failed` cover "Needs you" and a failed rebuild; the rest are named.
STATUSES = frozenset({"Needs you", "Not now", "Cannot check", "Not rebuilt"})
ICONS = frozenset({"needs", "failed"})
# Review's "Out of date" rows wear the `needs` icon but are Update now's job.
NOT_YET = frozenset({"Out of date"})

DONE_WORDS = '"Up to date", "Landed" or "Nothing to land"'

# Spec §4.2, word for word. Also appended to the session's system prompt.
LIMITS = """\
Hard limits for this session (set by Lab Hub; the owner approved them):
1. Never sign or record a legal or tax sign-off. Never run `legal_gate.py sign`, never edit `docs/legal/signoff.jsonl`, never record an approval for the owner (`record_approval.py`).
2. Never accept anything on the owner's behalf: a gate, a contract, terms, a client's acceptance.
3. Never push, merge into the default branch, tag a release, or install, unless the owner says yes in this session for that step.
4. Work only in this repo's checkout and its own worktrees. Never another repo's.
5. Do not run Lab Hub's Update now or Land, and do not run `build_app.sh` while another build is running.
6. Anything only the owner can do goes into a short list for the owner at the end. Do not attempt it: a legal or tax sign-off, a password, a payment, an App Store or notarisation login, a choice the spec leaves to the owner."""

# Per-session permission rules (ADR 0004 §3): `ask` beats an allow rule in the
# owner's own settings; `deny` cannot be overridden from inside the session.
SETTINGS = {
    "permissions": {
        "ask": [
            "Bash(git push:*)",
            "Bash(git merge:*)",
            "Bash(git tag:*)",
            "Bash(*build_app.sh*--install*)",
            "Bash(*install*.sh*)",
        ],
        "deny": [
            "Bash(*legal_gate.py sign*)",
            "Bash(*record_approval.py*)",
            "Edit(**/docs/legal/signoff.jsonl)",
            "Write(**/docs/legal/signoff.jsonl)",
        ],
    }
}

FOLDER = "claude-handoff"
_STAMP = re.compile(r"^\d{8}T\d{6}Z-\d+$")
KEEP_SECONDS = 24 * 3600


@dataclass(frozen=True)
class Item:
    """One row, in the window's own words."""
    name: str
    status: str
    reason: str = ""
    detail: str = ""
    command: str = ""

    @property
    def line(self) -> str:
        words = [self.status + "."] + [t for t in (self.reason, self.detail) if t]
        return f"{self.name}: " + " ".join(words)


@dataclass(frozen=True)
class Handoff:
    """Everything for one repo's session."""
    repo: str  # the checkout folder's name
    path: Path  # the repo's top level: the session's working folder
    items: tuple[Item, ...]


@dataclass(frozen=True)
class Context:
    """What else runs in the repo's checkout and worktrees at the click."""
    claude: tuple[str, ...] = ()  # "claude (pid 12) in <folder>"
    others: tuple[str, ...] = ()
    known: bool = True  # False when lsof could not tell

    @property
    def lines(self) -> tuple[str, ...]:
        return (*self.claude, *self.others)


def qualifies(row) -> bool:
    """A window row Lab Hub could not clear (spec §1, §4.1)."""
    status = getattr(row, "status", "")
    if status in NOT_YET:
        return False
    return (getattr(row, "icon", "") in ICONS or status in STATUSES
            or "archived" in status)


def top_level(path: Path) -> Path:
    """The git top level of `path`, or `path` itself when git cannot say."""
    rc, out, _ = rt.git(path, "rev-parse", "--show-toplevel")
    return Path(out) if rc == 0 and out else path


def collect(rows, paths: dict[str, Path | None],
            commands: dict[str, str] | None = None,
            top=top_level) -> tuple[list[Handoff], list[str]]:
    """Group the qualifying rows by repo. Returns the hand-offs, in first-seen
    order, and the names of rows with no folder (not sent)."""
    commands = commands or {}
    groups: dict[Path, list[Item]] = {}
    unplaced: list[str] = []
    for row in rows:
        if not qualifies(row):
            continue
        path = paths.get(row.name)
        if path is None or not Path(path).is_dir():
            unplaced.append(row.name)
            continue
        root = Path(top(Path(path))).resolve()
        groups.setdefault(root, []).append(Item(
            row.name, row.status, row.reason, row.detail, commands.get(row.name, "")))
    return [Handoff(root.name, root, tuple(items)) for root, items in groups.items()], unplaced


def worktrees(path: Path) -> list[Path]:
    """The repo's checkout and every worktree git knows of."""
    rc, out, _ = rt.git(path, "worktree", "list", "--porcelain")
    found = [path]
    if rc == 0:
        found += [Path(line[9:]) for line in out.splitlines() if line.startswith("worktree ")]
    return list(dict.fromkeys(p.resolve() for p in found))


def _inside(cwd: Path, folders: list[Path]) -> Path | None:
    try:
        here = cwd.resolve()
    except OSError:
        return None
    best = None
    for folder in folders:
        if here == folder or folder in here.parents:
            if best is None or len(folder.parts) > len(best.parts):
                best = folder  # the innermost worktree it is in
    return best


def context(handoff: Handoff, listing, trees=worktrees, me: int | None = None) -> Context:
    """Processes whose current folder is in the repo or one of its worktrees.
    `listing` is `land_resolve.cwd_listing()`: None when lsof could not tell."""
    if listing is None:
        return Context(known=False)
    me = os.getpid() if me is None else me
    folders = trees(handoff.path)
    claude, others = [], []
    for name, pid, cwd in listing:
        if str(pid) == str(me):
            continue
        folder = _inside(Path(cwd), folders)
        if folder is None:
            continue
        where = "." if folder == handoff.path else os.path.relpath(folder, handoff.path)
        line = f"{name} (pid {pid}) in {where}"
        (claude if name == "claude" else others).append(line)
    return Context(tuple(dict.fromkeys(claude)), tuple(dict.fromkeys(others)))


def prompt(handoff: Handoff, ctx: Context, window: str, when: datetime | None = None) -> str:
    """The session's first message (spec §2.5)."""
    when = when or datetime.now()
    out = [
        f"Lab Hub's {window} window could not clear these rows. Resolve them in this repo.",
        "",
        f"Repo: {handoff.repo}",
        f"Folder: {handoff.path}",
        f"Shown by Lab Hub on {when:%Y-%m-%d %H:%M}:",
    ]
    for item in handoff.items:
        out.append(f"- {item.line}")
        if item.command:
            out.append(f"  Command Lab Hub shows for it: {item.command}")
    out.append("")
    if not ctx.known:
        out.append("Lab Hub could not tell what else is running in this repo (lsof failed). "
                   "Check before you build, switch branches or commit.")
    elif ctx.lines:
        out.append("Also running in this repo's checkout and worktrees right now:")
        out.extend(f"- {line}" for line in ctx.lines)
        out.append("Do not build, switch branches or commit in a folder another process is "
                   "using without asking the owner first.")
    else:
        out.append("Nothing else was running in this repo's checkout or worktrees "
                   "when Lab Hub opened this session.")
    out += [
        "",
        f"Done looks like: the owner presses Refresh in Lab Hub and every row above reads "
        f"{DONE_WORDS}.",
        "",
        LIMITS,
        "",
        "End with two short lists: what you did, and what only the owner can do.",
    ]
    return "\n".join(out)


def command_line(claude: str, handoff: Handoff, folder: Path) -> str:
    """The one line the `.command` file runs. Repo text reaches `claude` only
    through `$(cat …)`; every other value is quoted (ADR 0004 §2)."""
    q = shlex.quote
    return (f"cd -- {q(str(handoff.path))} && {q(claude)} --permission-mode manual "
            f"--settings {q(str(folder / 'settings.json'))} "
            f"--append-system-prompt \"$(cat -- {q(str(folder / 'limits.md'))})\" "
            f"-n {q('Lab Hub: ' + handoff.repo)} "
            f"\"$(cat -- {q(str(folder / 'prompt.md'))})\"")


def _write(path: Path, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)


def _prune(base: Path, now: float) -> None:
    """Remove launch folders older than a day: only names Lab Hub makes."""
    for old in base.iterdir():
        try:
            if (_STAMP.match(old.name) and not old.is_symlink() and old.is_dir()
                    and now - old.stat().st_mtime > KEEP_SECONDS):
                shutil.rmtree(old)
        except OSError:
            pass  # a folder that cannot go stays; the next launch tries again


def _new_folder(base: Path, now: datetime) -> Path:
    stamp = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for n in range(1, 1000):
        folder = base / f"{stamp}-{n}"
        try:
            os.mkdir(folder, 0o700)
            return folder
        except FileExistsError:
            continue
    raise OSError(f"no free launch folder under {base}")


@dataclass
class Launcher:
    """Writes one launch folder and opens Terminal on it. `runner` is
    `launcher.control.run_in_terminal` (tests pass a fake)."""
    runner: object
    support: Path
    clock: object = time.time
    opened: list[Path] = field(default_factory=list)

    def launch(self, claude: str, handoff: Handoff, text: str) -> Path:
        base = self.support / FOLDER
        if base.is_symlink():
            raise OSError(f"{base} is a link; not writing launch files there")
        base.mkdir(mode=0o700, parents=True, exist_ok=True)
        base.chmod(0o700)
        now = self.clock()
        _prune(base, now)
        folder = _new_folder(base, datetime.fromtimestamp(now, timezone.utc))
        _write(folder / "prompt.md", text)
        _write(folder / "limits.md", LIMITS)
        _write(folder / "settings.json", json.dumps(SETTINGS, indent=2))
        self.runner([command_line(claude, handoff, folder)], directory=folder)
        self.opened.append(folder)
        return folder
