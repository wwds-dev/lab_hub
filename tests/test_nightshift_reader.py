"""The Nightshift readers and the command allowlist (spec nightshift-panel)."""

from __future__ import annotations

import json

import pytest

from lab_hub import nightshift as ns

from . import nightshift_records as rec


@pytest.fixture
def foundry(tmp_path):
    return rec.foundry(tmp_path)


def test_locate_needs_the_nightshift_script(tmp_path):
    assert ns.locate(tmp_path) is None
    (tmp_path / "foundry").mkdir()
    assert ns.locate(tmp_path) is None
    f = rec.foundry(tmp_path / "other")
    assert ns.locate(tmp_path / "other") == f


def test_no_foundry_and_no_state_folder(foundry):
    assert ns.read_state(None) == ns.Snapshot(None, None)
    snap = ns.read_state(foundry)
    assert snap.exists is False and snap.state == foundry / "local-drafts" / "nightshift"


def test_empty_state_folder(foundry):
    rec.state(foundry)
    snap = ns.read_state(foundry)
    assert snap.exists and snap.armed is None and snap.runs == () and snap.tasks == ()
    assert snap.track == () and snap.notices == () and snap.stops == ()


def test_armed_run_with_its_gate(foundry):
    s = rec.state(foundry)
    rec.write(s / "armed.json", {"run_id": "20261124-020000", "armed_at": "2026-11-23T21:00:00+00:00"})
    rec.write(s / "runs" / "20261124-020000" / "run.json",
              rec.run_record("20261124-020000", "armed", prestart=rec.gate(True)))
    snap = ns.read_state(foundry)
    assert snap.armed["run_id"] == "20261124-020000"
    assert isinstance(snap.armed_run, ns.Run)
    assert snap.armed_run.get("prestart")["predictions"]["t1"]["band"] == "Check"


def test_armed_json_with_a_bad_run_id_is_unreadable(foundry):
    s = rec.state(foundry)
    rec.write(s / "armed.json", {"run_id": "../../etc"})
    snap = ns.read_state(foundry)
    assert isinstance(snap.armed, ns.Unreadable) and snap.armed_run is None


def test_armed_but_run_record_missing_is_unreadable(foundry):
    s = rec.state(foundry)
    rec.write(s / "armed.json", {"run_id": "20261124-020000", "armed_at": None})
    snap = ns.read_state(foundry)
    assert isinstance(snap.armed_run, ns.Unreadable)
    assert "cannot read" in snap.armed_run.reason


def test_cancelled_dry_run_with_only_a_memory_check(foundry):
    s = rec.state(foundry)
    rid = "20261123-201345-dry"
    rec.write(s / "runs" / rid / "run.json", rec.run_record(
        rid, "cancelled", tasks=["dry-docstring"], prestart={"memory": rec.MEMORY_SHORT},
        checks=[{"name": "memory is enough", "ok": False, "detail": "short"}]))
    (run,) = ns.read_state(foundry).runs
    assert isinstance(run, ns.Run) and run.tasks == () and run.morning is None
    assert run.get("prestart") == {"memory": rec.MEMORY_SHORT}


@pytest.mark.parametrize("version", [2, 0, "1", None, True])
def test_refused_or_unknown_schema_version_is_unreadable(foundry, version):
    s = rec.state(foundry)
    run = rec.run_record("20261124-020000")
    run["schema_version"] = version
    rec.write(s / "runs" / "20261124-020000" / "run.json", run)
    (got,) = ns.read_state(foundry).runs
    assert isinstance(got, ns.Unreadable) and "schema_version" in got.reason


def test_missing_schema_version_is_unreadable(foundry):
    s = rec.state(foundry)
    run = rec.run_record("20261124-020000")
    del run["schema_version"]
    rec.write(s / "runs" / "20261124-020000" / "run.json", run)
    (got,) = ns.read_state(foundry).runs
    assert isinstance(got, ns.Unreadable) and got.reason == "no schema_version"


@pytest.mark.parametrize("text, reason", [("{not json", "not valid JSON"), ("[1, 2]", "not a JSON object")])
def test_broken_run_json_is_unreadable(foundry, text, reason):
    s = rec.state(foundry)
    rec.write(s / "runs" / "20261124-020000" / "run.json", text)
    (got,) = ns.read_state(foundry).runs
    assert isinstance(got, ns.Unreadable) and reason in got.reason


def test_unknown_run_state_is_unreadable(foundry):
    s = rec.state(foundry)
    rec.write(s / "runs" / "20261124-020000" / "run.json", rec.run_record("20261124-020000", "exploded"))
    (got,) = ns.read_state(foundry).runs
    assert isinstance(got, ns.Unreadable) and "exploded" in got.reason


def test_finished_run_with_task_records_files_and_morning(foundry):
    s = rec.state(foundry)
    rid = "20261124-020000"
    rec.write(s / "runs" / rid / "run.json", rec.run_record(rid, tasks=["t2", "t1"]))
    rec.write(s / "runs" / rid / "MORNING.md", "# Morning\n")
    rec.add_task(s, rid, "t1", files={"diff.patch": "+x\n", "tests.log": "ok\n"})
    rec.add_task(s, rid, "t2", status="failed")
    bad = rec.task_record(rid, "t3")
    bad["schema_version"] = 99
    rec.write(s / "runs" / rid / "t3" / "record.json", bad)
    (run,) = ns.read_state(foundry).runs
    assert run.morning == s / "runs" / rid / "MORNING.md"
    # Ticked order first, then the rest.
    assert [t.get("task_id") if isinstance(t, ns.TaskRecord) else t.path.parent.name for t in run.tasks] == [
        "t2", "t1", "t3"]
    t1 = run.tasks[1]
    assert set(t1.files) == {"diff.patch", "tests.log"}
    assert isinstance(run.tasks[2], ns.Unreadable) and "99" in run.tasks[2].reason


def test_record_files_outside_the_task_folder_are_ignored(foundry):
    s = rec.state(foundry)
    rid = "20261124-020000"
    rec.write(s / "runs" / rid / "run.json", rec.run_record(rid))
    rec.write(s / "secret.txt", "no")
    path = rec.add_task(s, rid, "t1")
    data = json.loads(path.read_text())
    data["files"] = {"diff.patch": "../../../secret.txt", "tests.log": "missing.log"}
    path.write_text(json.dumps(data))
    (run,) = ns.read_state(foundry).runs
    assert run.tasks[0].files == {}


def test_dry_runs_do_not_push_real_runs_off(foundry):
    s = rec.state(foundry)
    rec.write(s / "runs" / "20261120-020000" / "run.json", rec.run_record("20261120-020000"))
    for i in range(5):
        rid = f"2026112{3 + i // 3}-0{i}0000-dry"
        rec.write(s / "runs" / rid / "run.json", rec.run_record(rid))
    runs = ns.read_state(foundry, max_runs=3, max_dry_runs=2).runs
    assert [r.run_id for r in runs][-1] == "20261120-020000" and len(runs) == 3


def test_runs_newest_first_and_capped(foundry):
    s = rec.state(foundry)
    for i in range(5):
        rid = f"2026112{i}-020000"
        rec.write(s / "runs" / rid / "run.json", rec.run_record(rid))
    runs = ns.read_state(foundry, max_runs=3).runs
    assert [r.run_id for r in runs] == ["20261124-020000", "20261123-020000", "20261122-020000"]


def test_task_specs(foundry):
    s = rec.state(foundry)
    rec.task_spec(s, "a")
    rec.task_spec(s, "b", approved='"yes"', estimate_min='"20"')
    rec.write(s / "tasks" / "c.toml", "this is = = not toml")
    rec.task_spec(s, "d", app='""', repo='"/x/y"')
    a, b, c, d = ns.read_state(foundry).tasks
    assert a == ns.TaskSpec("a", "Spec a", "logic", "sonar", 20, True)
    assert b.approved is False and b.estimate_min is None  # only `approved = true` counts
    assert isinstance(c, ns.Unreadable) and "TOML" in c.reason
    assert d.app == "repo /x/y"


def test_stop_files(foundry):
    s = rec.state(foundry)
    (s / "STOP_NOW").write_text("")
    assert ns.read_state(foundry).stops == ("STOP_NOW",)


def test_notices_newest_first_and_bad_lines_counted(foundry):
    s = rec.state(foundry)
    lines = [json.dumps({"ts": "1", "kind": "info", "run_id": None, "message": "first"}), "oops",
             json.dumps({"ts": "2", "kind": "cancelled", "run_id": "r", "message": "second"}), "[]"]
    rec.write(s / "notices.jsonl", "\n".join(lines) + "\n")
    snap = ns.read_state(foundry)
    assert [n.message for n in snap.notices] == ["second", "first"]
    assert snap.notices_unreadable == 2


def _track(rid, verdict, gap=0, task_type="logic", task_id="t"):
    return {"run_id": rid, "task_id": task_id, "task_type": task_type, "verdict": verdict, "gap": gap}


def test_track_merges_owner_verdicts_and_summarises(foundry):
    s = rec.state(foundry)
    lines = [_track(f"r{i}", None, gap=i) for i in range(10)]
    lines += [{"run_id": f"r{i}", "task_id": "t", "task_type": "logic", "verdict": "accept",
               "verdict_by": "owner"} for i in range(7)]
    lines += [{"run_id": f"r{i}", "task_id": "t", "task_type": "logic", "verdict": "reject"} for i in range(7, 10)]
    lines.append(_track("x", "reject", task_type="docs"))
    rec.write(s / "track.jsonl", "\n".join(json.dumps(x) for x in lines) + "\nbroken\n")
    snap = ns.read_state(foundry)
    by = {t["task_type"]: t for t in snap.track}
    assert by["logic"]["status"] == ns.ALLOWED and by["logic"]["accepted"] == 7 and by["logic"]["total"] == 10
    assert by["logic"]["mean_gap"] == 4.5
    assert by["docs"]["status"] == ns.BUILDING
    assert snap.track_unreadable == 1


@pytest.mark.parametrize("accepted, status", [(7, "allowed"), (6, "watch"), (5, "watch"), (4, "daytime_only")])
def test_track_rule(accepted, status):
    history = [_track(str(i), "accept" if i < accepted else "reject", task_id=str(i)) for i in range(10)]
    assert ns.track_status(history, "logic")["status"] == status


def test_track_rules_out_early():
    # 6 rejects of 6: even 4 more accepts cannot reach 5.
    history = [_track(str(i), "reject", task_id=str(i)) for i in range(6)]
    assert ns.track_status(history, "logic")["status"] == ns.DAYTIME


def test_track_settings_from_the_toml(foundry):
    (foundry / "tools" / "nightshift.toml").write_text("[track]\nwindow = 4\nallowed = 3\ndaytime_below = true\n")
    assert ns.track_settings(foundry) == {"window": 4, "allowed": 3, "daytime_below": 5}
    assert ns.track_settings(None) == ns.TRACK_DEFAULTS


# --- commands -------------------------------------------------------------------------------------
@pytest.mark.parametrize("sub, args, note, want", [
    ("plan", ("a", "b"), "", ["plan", "a", "b"]),
    ("arm", ("a",), "", ["arm", "a"]),
    ("disarm", (), "", ["disarm"]),
    ("dry-run", (), "", ["dry-run"]),
    ("stop", ("--after",), "", ["stop", "--after"]),
    ("stop", ("--now",), "", ["stop", "--now"]),
    ("stop", ("--clear",), "", ["stop", "--clear"]),
    ("verdict", ("20261124-020000", "t1", "accept"), "", ["verdict", "20261124-020000", "t1", "accept"]),
    ("verdict", ("r", "t1", "reject"), "-looks like a flag", ["verdict", "r", "t1", "reject", "--note=-looks like a flag"]),
])
def test_allowed_commands(sub, args, note, want):
    assert ns.command_args(sub, *args, note=note) == want


@pytest.mark.parametrize("sub, args", [
    ("run", ()), ("recheck", ()), ("status", ()), ("launchctl", ("load",)), ("rm", ("-rf",)),
    ("plan", ()), ("arm", ("--all",)), ("arm", ("../x",)), ("plan", ("a b",)),
    ("disarm", ("x",)), ("dry-run", ("--model", "m")), ("stop", ()), ("stop", ("--now", "--after")),
    ("verdict", ("r", "t", "maybe")), ("verdict", ("r", "--x", "accept")), ("verdict", ("r", "t")),
])
def test_everything_else_is_refused(sub, args):
    with pytest.raises(ns.Refused):
        ns.command_args(sub, *args)


def test_command_runs_the_foundry_script(foundry):
    argv = ns.command(foundry, "disarm", python_exe="/x/python3")
    assert argv == ["/x/python3", str(foundry / "tools" / "nightshift.py"), "disarm"]


def test_reading_writes_nothing(foundry):
    s = rec.state(foundry)
    rid = "20261124-020000"
    rec.write(s / "runs" / rid / "run.json", rec.run_record(rid))
    rec.add_task(s, rid, "t1", files={"diff.patch": "+x"})
    rec.task_spec(s, "a")
    before = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in s.rglob("*") if p.is_file()}
    ns.read_state(foundry)
    after = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in s.rglob("*") if p.is_file()}
    assert before == after
