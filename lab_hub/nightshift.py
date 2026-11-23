"""Nightshift, read-only: what Foundry's Nightshift has written, and the owner commands.

Nightshift (Foundry, `docs/nightshift.md`) keeps all its state under
`<foundry>/local-drafts/nightshift/`. The contract for reading it is Foundry's
`docs/nightshift-audit-schema.md`, schema version 1 (spec `nightshift-panel`).

Rules this module keeps:

* It never writes anything there. Every change goes through `tools/nightshift.py`, and
  `command()` builds only the owner commands the panel offers; `run`, `recheck` and
  anything else are refused.
* A record that does not parse, or whose `schema_version` is not 1, is `Unreadable`
  with the reason. No field is guessed; a missing optional field reads as None.
* No Qt: the page runs `read_state` on a worker thread and only renders the result.

`track_status` and `merge_track` are copies of Foundry's `nightshift_quality.track_status`
and `nightshift_audit.read_track`; `tests/test_nightshift_drift.py` holds them in step.
"""

from __future__ import annotations

import json
import re
import shutil
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA_VERSION = 1
RUN_STATES = ("armed", "cancelled", "running", "finished", "aborted")
TASK_STATUSES = ("done", "failed", "skipped", "aborted")
STOP_FILES = ("STOP_AFTER_TASK", "STOP_NOW")
TASK_FILES = ("diff.patch", "tests.log", "review.md")
MAX_RUNS = 30  # real runs shown
MAX_DRY_RUNS = 10  # dry runs shown besides, so a day of dry runs cannot push real ones off

TRACK_DEFAULTS = {"window": 10, "allowed": 7, "daytime_below": 5}
ALLOWED, BUILDING, WATCH, DAYTIME = "allowed", "building", "watch", "daytime_only"

_SEARCH_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin"
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


# --- where ---------------------------------------------------------------------------------------
def locate(lab_root: Path) -> Path | None:
    """The Foundry folder under the lab root, or None when it has no Nightshift."""
    foundry = Path(lab_root) / "foundry"
    return foundry if (foundry / "tools" / "nightshift.py").is_file() else None


def state_dir(foundry: Path) -> Path:
    return foundry / "local-drafts" / "nightshift"


# --- records -------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Unreadable:
    path: Path
    reason: str


@dataclass(frozen=True)
class TaskRecord:
    path: Path
    data: dict
    files: dict[str, Path]  # file name (`diff.patch`) -> existing file, from the record's `files`

    def get(self, key: str, default=None):
        return self.data.get(key, default)


@dataclass(frozen=True)
class Run:
    path: Path
    data: dict
    tasks: tuple[TaskRecord | Unreadable, ...] = ()
    morning: Path | None = None

    @property
    def run_id(self) -> str:
        return self.data["run_id"]

    def get(self, key: str, default=None):
        return self.data.get(key, default)


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    title: str | None
    task_type: str | None
    app: str | None
    estimate_min: float | None
    approved: bool


@dataclass(frozen=True)
class Notice:
    ts: str | None
    kind: str | None
    run_id: str | None
    message: str | None


@dataclass(frozen=True)
class Snapshot:
    foundry: Path | None
    state: Path | None
    exists: bool = False
    armed: dict | Unreadable | None = None
    armed_run: Run | Unreadable | None = None
    stops: tuple[str, ...] = ()
    tasks: tuple[TaskSpec | Unreadable, ...] = ()
    runs: tuple[Run | Unreadable, ...] = ()
    track: tuple[dict, ...] = ()
    track_cfg: dict = field(default_factory=lambda: dict(TRACK_DEFAULTS))
    track_unreadable: int = 0
    notices: tuple[Notice, ...] = ()
    notices_unreadable: int = 0
    errors: tuple[str, ...] = field(default=())


def _load_json(path: Path) -> dict | Unreadable:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        return Unreadable(path, f"cannot read: {error.strerror or error}")
    except ValueError as error:
        return Unreadable(path, f"not valid JSON: {error}")
    if not isinstance(data, dict):
        return Unreadable(path, "not a JSON object")
    return data


def _schema_error(data: dict) -> str | None:
    version = data.get("schema_version")
    if "schema_version" not in data:
        return "no schema_version"
    if isinstance(version, bool) or not isinstance(version, int):
        return f"schema_version is not a number: {version!r}"
    if version != SCHEMA_VERSION:
        return f"schema_version {version} is not supported (this Lab Hub reads {SCHEMA_VERSION})"
    return None


def read_task_record(path: Path) -> TaskRecord | Unreadable:
    data = _load_json(path)
    if isinstance(data, Unreadable):
        return data
    problem = _schema_error(data)
    if problem is None and not isinstance(data.get("task_id"), str):
        problem = "no task_id"
    if problem is None and data.get("status") not in TASK_STATUSES:
        problem = f"unknown status {data.get('status')!r}"
    if problem:
        return Unreadable(path, problem)
    files: dict[str, Path] = {}
    listed = data.get("files")
    if isinstance(listed, dict):
        # Foundry lists each file under its stem (`"diff": "diff.patch"`); the panel looks
        # them up by the file's own name, which is what the schema names.
        for rel in listed.values():
            if not isinstance(rel, str) or not rel:
                continue
            candidate = (path.parent / rel).resolve()
            # Only files inside the task folder; a record cannot point the panel elsewhere.
            if candidate.is_relative_to(path.parent.resolve()) and candidate.is_file():
                files[candidate.name] = candidate
    return TaskRecord(path, data, files)


def read_run(run_path: Path) -> Run | Unreadable:
    path = run_path / "run.json"
    data = _load_json(path)
    if isinstance(data, Unreadable):
        return data
    problem = _schema_error(data)
    if problem is None and not isinstance(data.get("run_id"), str):
        problem = "no run_id"
    if problem is None and data.get("state") not in RUN_STATES:
        problem = f"unknown state {data.get('state')!r}"
    if problem:
        return Unreadable(path, problem)
    ticked = data.get("tasks") if isinstance(data.get("tasks"), list) else []
    folders = sorted(p for p in run_path.iterdir() if (p / "record.json").is_file())
    order = {t: i for i, t in enumerate(ticked) if isinstance(t, str)}
    folders.sort(key=lambda p: (order.get(p.name, len(order)), p.name))
    tasks = tuple(read_task_record(p / "record.json") for p in folders)
    morning = run_path / "MORNING.md"
    return Run(run_path, data, tasks, morning if morning.is_file() else None)


def _str(value) -> str | None:
    return value if isinstance(value, str) else None


def read_task_spec(path: Path) -> TaskSpec | Unreadable:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        return Unreadable(path, f"cannot read: {error.strerror or error}")
    except tomllib.TOMLDecodeError as error:
        return Unreadable(path, f"not valid TOML: {error}")
    estimate = data.get("estimate_min")
    app = _str(data.get("app")) or (f"repo {data['repo']}" if isinstance(data.get("repo"), str) else None)
    return TaskSpec(
        task_id=path.stem,
        title=_str(data.get("title")),
        task_type=_str(data.get("type")),
        app=app,
        estimate_min=estimate if isinstance(estimate, (int, float)) and not isinstance(estimate, bool) else None,
        # Approved only when it says exactly `approved = true`.
        approved=data.get("approved") is True,
    )


def _read_jsonl(path: Path) -> tuple[list[dict], int]:
    """Lines that are JSON objects, and how many were not."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return [], 0
    out, bad = [], 0
    for line in lines:
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            bad += 1
            continue
        if isinstance(entry, dict):
            out.append(entry)
        else:
            bad += 1
    return out, bad


# --- track record (copied from Foundry; drift-tested) ----------------------------------------------
def merge_track(entries: list[dict]) -> list[dict]:
    """One entry per (run, task), oldest first; a later line (the owner's verdict) wins.
    Copy of `nightshift_audit.read_track` after the file is read."""
    by: dict[tuple, dict] = {}
    for e in entries:
        by[(e.get("run_id"), e.get("task_id"))] = {**by.get((e.get("run_id"), e.get("task_id")), {}), **e}
    return list(by.values())


def track_status(history: list[dict], task_type: str, cfg: dict | None = None) -> dict:
    """Copy of `nightshift_quality.track_status`; `cfg` is the `[track]` table."""
    t = {**TRACK_DEFAULTS, **(cfg or {})}
    judged = [e for e in history if e.get("task_type") == task_type and e.get("verdict") in ("accept", "reject")]
    last = judged[-t["window"]:]
    accepted, total = sum(1 for e in last if e["verdict"] == "accept"), len(last)
    if total < t["window"]:
        status = DAYTIME if accepted + (t["window"] - total) < t["daytime_below"] else BUILDING
    elif accepted >= t["allowed"]:
        status = ALLOWED
    elif accepted < t["daytime_below"]:
        status = DAYTIME
    else:
        status = WATCH
    gaps = [e["gap"] for e in last if isinstance(e.get("gap"), (int, float))]
    return {"task_type": task_type, "status": status, "accepted": accepted, "total": total,
            "window": t["window"], "mean_gap": round(sum(gaps) / len(gaps), 1) if gaps else None}


def track_settings(foundry: Path | None) -> dict:
    """`[track]` from `tools/nightshift.toml`, integers only; defaults when absent."""
    if foundry is None:
        return dict(TRACK_DEFAULTS)
    try:
        table = tomllib.loads((foundry / "tools" / "nightshift.toml").read_text(encoding="utf-8")).get("track")
    except (OSError, tomllib.TOMLDecodeError):
        return dict(TRACK_DEFAULTS)
    out = dict(TRACK_DEFAULTS)
    if isinstance(table, dict):
        for key in TRACK_DEFAULTS:
            value = table.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                out[key] = value
    return out


def track_summary(entries: list[dict], cfg: dict | None = None) -> tuple[dict, ...]:
    history = merge_track(entries)
    types = sorted({e["task_type"] for e in history if isinstance(e.get("task_type"), str)})
    return tuple(track_status(history, t, cfg) for t in types)


# --- the whole picture ----------------------------------------------------------------------------
def read_state(foundry: Path | None, max_runs: int = MAX_RUNS, max_dry_runs: int = MAX_DRY_RUNS) -> Snapshot:
    """Everything the panel shows. Reads only; safe to call on a worker thread."""
    if foundry is None:
        return Snapshot(None, None)
    state = state_dir(foundry)
    if not state.is_dir():
        return Snapshot(foundry, state, exists=False)

    armed: dict | Unreadable | None = None
    armed_run: Run | Unreadable | None = None
    armed_path = state / "armed.json"
    if armed_path.exists():
        armed = _load_json(armed_path)
        if isinstance(armed, dict):
            run_id = armed.get("run_id")
            if not isinstance(run_id, str) or not _ID.match(run_id):
                armed = Unreadable(armed_path, f"run_id is not a run id: {run_id!r}")
            else:
                armed_run = read_run(state / "runs" / run_id)

    tasks_dir = state / "tasks"
    tasks = tuple(read_task_spec(p) for p in sorted(tasks_dir.glob("*.toml"))) if tasks_dir.is_dir() else ()

    runs_dir = state / "runs"
    all_dirs = sorted((p for p in runs_dir.iterdir() if p.is_dir()), reverse=True) if runs_dir.is_dir() else []
    real = [p for p in all_dirs if not p.name.endswith("-dry")][:max_runs]
    dry = [p for p in all_dirs if p.name.endswith("-dry")][:max_dry_runs]
    run_dirs = sorted(real + dry, reverse=True)
    runs = tuple(read_run(p) for p in run_dirs)

    track_lines, track_bad = _read_jsonl(state / "track.jsonl")
    notice_lines, notices_bad = _read_jsonl(state / "notices.jsonl")
    track_cfg = track_settings(foundry)
    notices = tuple(
        Notice(_str(n.get("ts")), _str(n.get("kind")), _str(n.get("run_id")), _str(n.get("message")))
        for n in reversed(notice_lines)
    )
    return Snapshot(
        foundry=foundry,
        state=state,
        exists=True,
        armed=armed,
        armed_run=armed_run,
        stops=tuple(name for name in STOP_FILES if (state / name).exists()),
        tasks=tasks,
        runs=runs,
        track=track_summary(track_lines, track_cfg),
        track_cfg=track_cfg,
        track_unreadable=track_bad,
        notices=notices,
        notices_unreadable=notices_bad,
    )


# --- commands -------------------------------------------------------------------------------------
class Refused(ValueError):
    """A command the panel must never run."""


STOP_FLAGS = ("--after", "--now", "--clear")
VERDICTS = ("accept", "reject")


def _ids(values, what: str) -> list[str]:
    values = list(values)
    if not values:
        raise Refused(f"{what}: tick at least one task")
    for v in values:
        if not isinstance(v, str) or not _ID.match(v):
            raise Refused(f"{what}: not a task id: {v!r}")
    return values


def command_args(sub: str, *args: str, note: str = "") -> list[str]:
    """The arguments after `tools/nightshift.py` for an owner command, or Refused.

    Only these: plan, arm, disarm, stop, verdict, dry-run. Never run, recheck, status
    (read from the files instead) or anything else."""
    if sub in ("plan", "arm"):
        return [sub, *_ids(args, sub)]
    if sub == "disarm" and not args:
        return ["disarm"]
    if sub == "dry-run" and not args:
        return ["dry-run"]
    if sub == "stop" and len(args) == 1 and args[0] in STOP_FLAGS:
        return ["stop", args[0]]
    if sub == "verdict" and len(args) == 3 and args[2] in VERDICTS:
        run_id, task_id = _ids(args[:2], "verdict")
        out = ["verdict", run_id, task_id, args[2]]
        if note:
            # `--note=` keeps a note that starts with "-" from being read as an option.
            out.append(f"--note={note}")
        return out
    raise Refused(f"not an owner command the panel runs: {' '.join([sub, *args])}")


def python() -> str | None:
    """A python3 from the usual places (a GUI app's PATH is short)."""
    return shutil.which("python3", path=_SEARCH_PATH)


def command(foundry: Path, sub: str, *args: str, note: str = "", python_exe: str | None = None) -> list[str]:
    """The full argv, run with cwd `foundry`."""
    exe = python_exe or python()
    if exe is None:
        raise Refused("no python3 found in /opt/homebrew/bin, /usr/local/bin or /usr/bin")
    return [exe, str(foundry / "tools" / "nightshift.py"), *command_args(sub, *args, note=note)]
