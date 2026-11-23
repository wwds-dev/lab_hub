"""`lab_hub.nightshift.track_status` and `merge_track` are copies of Foundry's
`nightshift_quality.track_status` and `nightshift_audit.read_track`. This runs both on the
same histories when a Foundry checkout sits beside Lab Hub, and skips otherwise.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

from lab_hub import nightshift as ns


def _foundry_tools() -> Path | None:
    candidates = []
    if os.environ.get("LAB_ROOT"):
        candidates.append(Path(os.environ["LAB_ROOT"]) / "foundry")
    candidates += [parent / "foundry" for parent in Path(__file__).resolve().parents]
    for f in candidates:
        if (f / "tools" / "nightshift_quality.py").is_file() and (f / "tools" / "nightshift_audit.py").is_file():
            return f / "tools"
    return None


TOOLS = _foundry_tools()
pytestmark = pytest.mark.skipif(TOOLS is None, reason="no Foundry checkout beside Lab Hub")


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"_drift_{name}", TOOLS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up while it loads
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


def _histories():
    yield []
    for accepted in range(11):
        yield [{"task_type": "logic", "verdict": "accept" if i < accepted else "reject", "gap": i - 3}
               for i in range(10)]
    for n in range(10):
        yield [{"task_type": "logic", "verdict": "reject"}] * n + [{"task_type": "logic", "verdict": None}]
    yield [{"task_type": "docs", "verdict": "accept", "gap": 2.5}] * 12 + [{"task_type": "logic", "verdict": "reject"}]


def test_track_status_matches_foundry():
    quality = _load("nightshift_quality")
    for history in _histories():
        for task_type in ("logic", "docs"):
            assert ns.track_status(history, task_type) == quality.track_status(history, task_type)
            cfg = {"window": 4, "allowed": 3, "daytime_below": 2}
            assert ns.track_status(history, task_type, cfg) == quality.track_status(history, task_type,
                                                                                    {"track": cfg})


def test_merge_track_matches_foundry(tmp_path):
    audit = _load("nightshift_audit")
    entries = [
        {"run_id": "r1", "task_id": "a", "task_type": "logic", "verdict": None, "gap": 1},
        {"run_id": "r1", "task_id": "b", "task_type": "docs", "verdict": "reject"},
        {"run_id": "r1", "task_id": "a", "verdict": "accept", "verdict_by": "owner"},
        {"run_id": "r2", "task_id": "a", "task_type": "logic", "verdict": None},
    ]
    (tmp_path / "track.jsonl").write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    assert ns.merge_track(entries) == audit.read_track(tmp_path)


def test_a_record_written_by_foundry_reads_here(tmp_path):
    """Foundry's own writer, into a scratch state folder: the panel finds its files by name."""
    audit = _load("nightshift_audit")
    from tests import nightshift_records as rec

    record = rec.task_record("20261124-020000", "t1")
    record["files"] = {}
    path = audit.write_task(record, {"diff.patch": "+x\n", "tests.log": "ok\n", "review.md": "PASS\n"},
                            state=tmp_path)
    got = ns.read_task_record(path)
    assert isinstance(got, ns.TaskRecord)
    assert set(ns.TASK_FILES) <= set(got.files)

