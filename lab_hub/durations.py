"""How long each step took last time, so a progress window can say how long is left.

Spec: `docs/specs/progress-windows.md` §8.4; ADR 0001. One small JSON file,
`~/Library/Application Support/Lab Hub/durations.json`:

    {"version": 1,
     "subjects": {"repo:SONAR": {"merge": [2.1, 1.9]},
                  "app:sonar":  {"build": [61.2], "rebuild": [88.0]}}}

It is a cache, not a record. Anything wrong with it (missing, unreadable, not
JSON, another version, the wrong types, too big) reads as "no history", and the
window says "Estimating…" rather than guessing. The next good save replaces it.

Names are data and only ever JSON keys: never a path part. Written only on the
GUI thread, by load-update-save through a same-directory temp file and
`os.replace`, so a crash mid-write leaves the old file whole.
"""

from __future__ import annotations

import json
import math
import os
import re
import stat
import statistics
import tempfile
import unicodedata
from pathlib import Path

from . import config

VERSION = 1
KEEP = 5  # samples per (subject, kind); the estimate is their median
MAX_SUBJECTS = 200
MAX_BYTES = 256 * 1024
MAX_SECONDS = 6 * 60 * 60
MAX_NAME = 120

# The seven Land step kinds (`repo_tidy.Action.kind`) and the build stages.
LAND_KINDS = ("commit", "merge", "claude_merge", "pull", "push", "delete_branch",
              "remove_worktree")
BUILD_KINDS = ("build", "package", "install", "verify", "rebuild")
KINDS = frozenset(LAND_KINDS + BUILD_KINDS)

History = dict[str, dict[str, list[float]]]


def path() -> Path:
    """Read at call time, so tests that move `config.SUPPORT_DIR` move this too."""
    return config.SUPPORT_DIR / "durations.json"


def _default() -> Path:
    # The functions below take a `path=` keyword, which hides `path()` inside them.
    return path()


def subject(prefix: str, name: str) -> str:
    """`repo:<name>` or `app:<key>`, with control and format characters removed,
    whitespace collapsed and the name cut to 120 characters."""
    text = "".join(ch for ch in str(name) if not unicodedata.category(ch).startswith("C"))
    text = re.sub(r"\s+", " ", text).strip()[:MAX_NAME]
    return f"{prefix}:{text}"


def _sample(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        value = float(value)
    except (OverflowError, ValueError):  # an integer too big for a float
        return None
    if not math.isfinite(value) or not 0 < value <= MAX_SECONDS:
        return None
    return value


def _read(file: Path) -> bytes | None:
    """The file's bytes if it is a regular file of at most MAX_BYTES, else None.

    Opened without following a symlink and without blocking, then checked on
    the open descriptor: a FIFO, a device or a directory at the path is not
    read (a FIFO would hang the GUI thread), and a file that grows between the
    check and the read is still refused."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(file, flags)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES:
            return None
        chunks, size = [], 0
        while size <= MAX_BYTES:
            chunk = os.read(fd, MAX_BYTES + 1 - size)
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        return None if size > MAX_BYTES else b"".join(chunks)
    finally:
        os.close(fd)


def load(*, path: Path | None = None) -> History:
    """The history, or an empty one. Never raises, whatever is in the file."""
    file = path or _default()
    try:
        return _parse(file)
    except Exception:  # noqa: BLE001 - a cache: deep nesting, huge numbers, anything
        return {}


def _parse(file: Path) -> History:
    try:
        raw = _read(file)
    except OSError:
        return {}
    if raw is None:
        return {}
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict) or data.get("version") != VERSION:
        return {}
    subjects = data.get("subjects")
    if not isinstance(subjects, dict):
        return {}
    history: History = {}
    for name, kinds in subjects.items():
        if not isinstance(name, str) or not isinstance(kinds, dict):
            continue
        clean: dict[str, list[float]] = {}
        for kind, samples in kinds.items():
            if kind not in KINDS or not isinstance(samples, list):
                continue
            good = [s for s in (_sample(v) for v in samples) if s is not None]
            if good:
                clean[kind] = good[-KEEP:]
        if clean:
            history[name] = clean
    # Oldest first, as saved; a hand-edited file over the cap keeps the newest.
    return dict(list(history.items())[-MAX_SUBJECTS:])


def estimate(history: History, subject_key: str, kind: str) -> float | None:
    """The median of what is recorded, or None: no history means no guess."""
    samples = history.get(subject_key, {}).get(kind)
    return statistics.median(samples) if samples else None


def save(history: History, *, path: Path | None = None) -> bool:
    """Write atomically. False (and nothing changed on disk) if it could not."""
    file = path or _default()
    tmp = None
    try:
        file.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=file.parent, prefix=".durations.", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"version": VERSION, "subjects": history}, handle,
                      separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, file)
        tmp = None
        return True
    except OSError:
        return False
    finally:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def record(subject_key: str, kind: str, seconds: float, *,
           path: Path | None = None) -> bool:
    """Add one finished step's duration. Re-reads the file first, so two pages
    writing in turn never lose each other's samples. False if refused or unsaved."""
    value = _sample(seconds)
    if kind not in KINDS or value is None:
        return False
    history = load(path=path)
    kinds = history.pop(subject_key, {})  # re-inserted last: the newest subject
    kinds[kind] = (kinds.get(kind, []) + [value])[-KEEP:]
    history[subject_key] = kinds
    while len(history) > MAX_SUBJECTS:
        history.pop(next(iter(history)))
    return save(history, path=path)
