"""Is the work committed, pushed and merged? Read from git_autosync's report.

git_autosync backs work up; `git_autosync/scripts/hygiene.py` says whether it
has *landed*. Its hourly run writes `hygiene.json` beside it. Lab Hub only reads
that file (cheap, safe on the UI thread) and, on "Check repos", runs the same
script again without a fetch. Nothing here runs git, and nothing changes a repo.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

REPORT_NAME = "hygiene.json"
SCRIPT_REL = Path("git_autosync") / "scripts" / "hygiene.py"
# A frozen app has a minimal PATH; python3 lives in one of these.
_SEARCH_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin"
STALE_AFTER_HOURS = 6


_SHORT = (
    (re.compile(r"^(\d+) branch(?:es)? not merged"), "branch", "branches"),
    (re.compile(r"^(\d+) worktrees? with uncommitted"), "worktree", "worktrees"),
    (re.compile(r"^(\d+) uncommitted files?"), "file", "files"),
    (re.compile(r"^(?:diverged: )?(\d+) unpushed"), "unpushed commit", "unpushed commits"),
    (re.compile(r"(?:^|, )(\d+) behind"), "commit behind", "commits behind"),
)


def _short(problem: str) -> str:
    """Counts for the tile: "6 branches not merged into master" -> "6 branches";
    "" for a line git_autosync words differently (counted as an item)."""
    parts = []
    for pattern, one, many in _SHORT:
        m = pattern.search(problem)
        if m:
            n = int(m.group(1))
            parts.append(f"{n} {one if n == 1 else many}")
    return " · ".join(parts)


@dataclass(frozen=True)
class RepoRow:
    name: str
    path: Path
    branch: str = ""
    problems: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    error: str = ""

    @property
    def needs_attention(self) -> bool:
        return bool(self.problems or self.error)

    @property
    def badge(self) -> str:
        """Short text for a tile: how many things are left to land."""
        if self.error:
            return "repo not readable"
        parts = [s for s in (_short(p) for p in self.problems) if s]
        unknown = sum(1 for p in self.problems if not _short(p))
        if unknown:
            parts.append(f"{unknown} item{'s' if unknown != 1 else ''}")
        return " · ".join(parts) + " to land" if parts else ""

    @property
    def detail(self) -> str:
        return self.error or "; ".join(self.problems)


@dataclass(frozen=True)
class Report:
    generated: str = ""
    fetched: bool = False
    rows: tuple[RepoRow, ...] = field(default_factory=tuple)

    @property
    def attention(self) -> tuple[RepoRow, ...]:
        return tuple(r for r in self.rows if r.needs_attention)

    def for_project(self, lab_root: Path, project: str) -> RepoRow | None:
        """The row for the checkout `lab_root/project`, if autosync tracks it."""
        try:
            want = (lab_root / project).resolve()
        except OSError:
            return None
        for row in self.rows:
            if row.path == want:
                return row
        return None

    def age_hours(self, now: datetime | None = None) -> float | None:
        try:
            then = datetime.fromisoformat(self.generated)
        except ValueError:
            return None
        now = now or datetime.now(then.tzinfo)
        return max(0.0, (now - then).total_seconds() / 3600)

    @property
    def stale(self) -> bool:
        age = self.age_hours()
        return age is None or age > STALE_AFTER_HOURS


def report_path(lab_root: Path) -> Path:
    return lab_root / "git_autosync" / REPORT_NAME


def script_path(lab_root: Path) -> Path:
    return lab_root / SCRIPT_REL


def load(lab_root: Path) -> Report | None:
    """The last report, or None when there is none or it cannot be read."""
    try:
        data = json.loads(report_path(lab_root).read_text())
        rows = []
        for raw in data["repos"]:
            rows.append(RepoRow(
                name=str(raw["name"]),
                path=Path(raw["path"]),
                branch=str(raw.get("branch", "")),
                problems=tuple(str(p) for p in raw.get("problems", ())),
                notes=tuple(str(n) for n in raw.get("notes", ())),
                error=str(raw.get("error", "")),
            ))
        return Report(
            generated=str(data.get("generated", "")),
            fetched=bool(data.get("fetched", False)),
            rows=tuple(rows),
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None


def command(lab_root: Path) -> list[str] | None:
    """The argv that rewrites the report from the repos as they are now.

    No `--fetch`: a button press must not wait on the network. None when the
    script or a python3 to run it is missing.
    """
    script = script_path(lab_root)
    python = shutil.which("python3", path=_SEARCH_PATH)
    if python is None or not script.is_file():
        return None
    return [python, str(script), "--lab-root", str(lab_root.parent),
            "--out", str(report_path(lab_root))]
