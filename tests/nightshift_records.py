"""Nightshift state folders built in the tests, to schema version 1.

Field names and shapes follow Foundry's `docs/nightshift-audit-schema.md`; nothing here is
copied from a real run.
"""

from __future__ import annotations

import json
from pathlib import Path

WINDOW = {"recheck": "01:55", "start": "02:00", "end": "07:00", "startup_min": 5}

MEMORY_SHORT = {
    "model": "test-model", "file_gb": 13.0, "cache_gb": 1.5, "buffer_gb": 2.0, "need_gb": 16.5,
    "context": 16384, "available_gb": 6.5, "free_pct": 50, "compressor_gb": 7.81, "swap_used_gb": 2.04,
    "short_gb": 10.0, "close": [["Big App", 4.4], ["Browser", 2.0]], "close_enough": True, "ok": False,
    "why": "6.5 GB free, 16.5 GB needed",
}
MEMORY_OK = {**MEMORY_SHORT, "available_gb": 30.0, "short_gb": 0, "close": [], "ok": True, "why": "enough"}


def foundry(root: Path) -> Path:
    """A lab root with a Foundry folder that has Nightshift."""
    f = root / "foundry"
    (f / "tools").mkdir(parents=True)
    (f / "tools" / "nightshift.py").write_text("# fake\n")
    return f


def state(f: Path) -> Path:
    s = f / "local-drafts" / "nightshift"
    s.mkdir(parents=True, exist_ok=True)
    return s


def write(path: Path, obj) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(obj if isinstance(obj, str) else json.dumps(obj), encoding="utf-8")
    return path


def run_record(run_id: str, state_: str = "finished", tasks=("t1",), **extra) -> dict:
    return {
        "schema_version": 1, "run_id": run_id, "state": state_, "dry_run": run_id.endswith("-dry"),
        "armed_at": None, "started": None, "finished": None, "window": WINDOW, "tasks": list(tasks),
        "prestart": None, "recheck": None, "abort": None, "models": [], "results": [], "checks": None,
        **extra,
    }


def task_record(run_id: str, task_id: str, status: str = "done", **extra) -> dict:
    return {
        "schema_version": 1, "run_id": run_id, "task_id": task_id, "app": "sonar", "task_type": "logic",
        "title": f"Task {task_id}", "status": status, "status_reason": "ok",
        "branch": f"nightshift/{run_id}/{task_id}", "worktree": None, "base_sha": "a" * 40,
        "commit_sha": "b" * 40 if status == "done" else None, "started": "2026-11-24T02:00:00+00:00",
        "finished": "2026-11-24T02:20:00+00:00", "seconds": 1200, "estimate_min": 20,
        "settings": {"model": "test-model", "quant": "Q3_K_M", "bits": 3, "lossy_quant": True, "format": "gguf",
                     "context": 16384, "context_fill_max": 0.6, "overflow_policy": "stop", "temperature": 0.2,
                     "seed": 7, "max_output_tokens": 6000, "reviewer": None, "sandbox": True},
        "prediction": {"score": 70, "band": "Check", "armable": True, "reasons": ["r"], "hints": [],
                       "lossy_quant": True},
        "result": {"score": 80, "band": "High", "hard_gate": True, "reasons": ["tests pass"]},
        "gap": 10, "attempts": [], "retries": 1,
        "gates": {"baseline_green": True, "tests_pass": True, "lint_clean": None, "types_clean": None,
                  "diff_ok": True, "tests_intact": True, "review": None},
        "diff": {"files": 1, "lines_added": 3, "lines_deleted": 1, "cap_files": 8, "cap_lines": 300},
        "review": None, "verdict": None, "files": {},
        **extra,
    }


def add_task(s: Path, run_id: str, task_id: str, files: dict[str, str] | None = None, **extra) -> Path:
    folder = s / "runs" / run_id / task_id
    names = {}
    for name, text in (files or {}).items():
        write(folder / name, text)
        names[Path(name).stem] = name  # as Foundry's write_task lists them
    rec = task_record(run_id, task_id, **{"files": names, **extra})
    return write(folder / "record.json", rec)


def task_spec(s: Path, task_id: str, approved: str = "true", **fields) -> Path:
    body = {"app": '"sonar"', "type": '"logic"', "title": f'"Spec {task_id}"', "estimate_min": "20",
            "approved": approved, **fields}
    return write(s / "tasks" / f"{task_id}.toml", "".join(f"{k} = {v}\n" for k, v in body.items()))


def gate(ok: bool = True) -> dict:
    return {
        "ok": ok, "blockers": [] if ok else ["memory: short"], "warnings": ["task t1: predicted Check (70)"],
        "memory": MEMORY_OK if ok else MEMORY_SHORT,
        "load": {"ok": True, "total_min": 20, "window_min": 295, "why": "1 task(s), 20 min estimated"},
        "predictions": {"t1": {"score": 70, "band": "Check", "armable": True, "reasons": ["no lint"],
                               "hints": ["add lint"], "lossy_quant": True}},
        "models": {"t1": "test-model"}, "sandbox": True,
    }
