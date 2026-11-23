"""The Nightshift page: rendering the states and running commands through a fake CLI."""

from __future__ import annotations

import json
import sys
import time

import pytest
from PySide6.QtCore import QCoreApplication, Qt

from lab_hub import config
from lab_hub import nightshift as ns
from ui.nightshift_tab import NightshiftTab, gate_html, task_row, tonight_html

from . import nightshift_records as rec

FAKE_CLI = """\
import json, pathlib, sys
log = pathlib.Path(__file__).with_name("calls.jsonl")
with log.open("a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
print("fake nightshift", *sys.argv[1:])
print("cwd", pathlib.Path.cwd().name)
if sys.argv[1:2] == ["dry-run"]:
    import time
    time.sleep(30)
sys.exit(3 if sys.argv[1:2] == ["arm"] else 0)
"""


def wait_for(predicate, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    raise AssertionError("timed out")


@pytest.fixture
def lab(tmp_path):
    f = rec.foundry(tmp_path)
    (f / "tools" / "nightshift.py").write_text(FAKE_CLI)
    return tmp_path


@pytest.fixture
def page(qapp, lab):
    settings = config.Settings(lab_root=str(lab))
    tab = NightshiftTab(settings)
    tab.python_exe = sys.executable
    tab.confirm = lambda title, text: True
    tab.opened = []
    tab.open_file = tab.opened.append
    yield tab
    tab.shutdown()
    tab.deleteLater()


def test_hidden_page_does_not_read(qapp, lab):
    tab = NightshiftTab(config.Settings(lab_root=str(lab)))
    tab.refresh()
    assert tab._reader is None
    tab.shutdown()


def load(tab):
    tab.snapshot = None
    tab.read_now()
    wait_for(lambda: tab._reader is None and tab.snapshot is not None)


def calls(lab):
    path = lab / "foundry" / "tools" / "calls.jsonl"
    return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []


def test_no_foundry_folder(qapp, tmp_path):
    tab = NightshiftTab(config.Settings(lab_root=str(tmp_path)))
    load(tab)
    assert "No Foundry folder" in tab.where.text()
    assert not tab.dry_button.isEnabled() and not tab.disarm_button.isEnabled()
    assert tab.run_command("disarm") is False
    tab.shutdown()


def test_no_state_folder_yet(page):
    load(page)
    assert "written nothing yet" in page.where.text()
    assert page.dry_button.isEnabled()
    assert page.runs_table.rowCount() == 0


def test_nothing_armed_shows_the_latest_gate(page, lab):
    s = rec.state(lab / "foundry")
    rid = "20261123-201345-dry"
    rec.write(s / "runs" / rid / "run.json", rec.run_record(
        rid, "cancelled", tasks=["dry-docstring"], prestart={"memory": rec.MEMORY_SHORT},
        checks=[{"name": "memory is enough", "ok": False, "detail": "short"}]))
    load(page)
    text = page.tonight.text()
    assert "Nothing armed" in text and rid in text and "Big App" in text and "short by 10 GB" in text
    assert "compressed 7.8 GB" in text and "swap 2 GB" in text
    assert page.runs_table.item(0, 1).text() == "cancelled"
    assert "FAIL: memory is enough" in page.run_detail.text()
    assert page.run_tasks.rowCount() == 0
    assert not page.morning_button.isEnabled()


def test_armed_run(page, lab):
    s = rec.state(lab / "foundry")
    rid = "20261124-020000"
    rec.write(s / "armed.json", {"run_id": rid, "armed_at": "2026-11-23T21:00:00+00:00"})
    rec.write(s / "runs" / rid / "run.json", rec.run_record(rid, "armed", prestart=rec.gate(True)))
    (s / "STOP_AFTER_TASK").write_text("")
    load(page)
    text = page.tonight.text()
    assert f"Armed:</b> run {rid}" in text
    assert "02:00 to 07:00" in text and "Gate: passed" in text
    assert "predicted Check 70" in text and "lossy quant" in text and "Fix: add lint" in text
    assert "Warnings" in text and "stop after the running task" in text


def test_unreadable_armed_run(page, lab):
    s = rec.state(lab / "foundry")
    rid = "20261124-020000"
    rec.write(s / "armed.json", {"run_id": rid})
    rec.write(s / "runs" / rid / "run.json", {**rec.run_record(rid), "schema_version": 2})
    load(page)
    assert "unreadable" in page.tonight.text() and "schema_version 2" in page.tonight.text()
    assert page.runs_table.item(0, 1).text() == "unreadable"


def test_html_is_escaped():
    g = rec.gate(False)
    g["blockers"] = ["<script>x</script>"]
    assert "<script>" not in gate_html(g) and "&lt;script&gt;" in gate_html(g)


def test_gate_with_missing_fields_shows_dashes():
    out = gate_html({"memory": {"ok": None}})
    assert "Memory: unknown" in out and "—" in out


def test_tonight_without_runs():
    snap = ns.Snapshot(None, None, exists=True)
    assert "Nothing armed" in tonight_html(snap)


def test_finished_run_tasks_files_and_verdict(page, lab):
    s = rec.state(lab / "foundry")
    rid = "20261124-020000"
    rec.write(s / "runs" / rid / "run.json", rec.run_record(
        rid, tasks=["t1", "t2"], abort={"rule": "overrun", "scope": "task", "why": "2x estimate"}))
    rec.write(s / "runs" / rid / "MORNING.md", "# Morning\n")
    rec.add_task(s, rid, "t1", files={"diff.patch": "+x\n", "review.md": "PASS\n"})
    bad = rec.task_record(rid, "t2")
    bad["schema_version"] = "one"
    rec.write(s / "runs" / rid / "t2" / "record.json", bad)
    load(page)
    assert "overrun: 2x estimate" in page.run_detail.text()
    row = [page.run_tasks.item(0, c).text() for c in range(page.run_tasks.columnCount())]
    assert row[:9] == ["t1", "done", "High 80", "Check 70", "10", "1", "test-model", "Q3_K_M (lossy)",
                       f"nightshift/{rid}/t1"]
    assert page.run_tasks.item(1, 1).text() == "unreadable"
    page.morning_button.click()
    assert page.opened == [s / "runs" / rid / "MORNING.md"]
    page.select_task("t1")
    assert page.file_buttons["diff.patch"].isEnabled() and not page.file_buttons["tests.log"].isEnabled()
    page.file_buttons["review.md"].click()
    assert page.opened[-1] == (s / "runs" / rid / "t1" / "review.md").resolve()
    assert page.accept_button.isEnabled()
    page.note.setText("looks good")
    page.accept_button.click()
    wait_for(lambda: not page.is_running())
    assert calls(lab)[-1] == ["verdict", rid, "t1", "accept", "--note=looks good"]
    assert page.last_exit == 0 and page.note.text() == ""


def test_dry_run_tasks_take_no_verdict(page, lab):
    s = rec.state(lab / "foundry")
    rid = "20261124-020000-dry"
    rec.write(s / "runs" / rid / "run.json", rec.run_record(rid))
    rec.add_task(s, rid, "t1")
    load(page)
    page.select_task("t1")
    assert not page.accept_button.isEnabled()


def test_tasks_tick_and_plan_and_arm(page, lab):
    s = rec.state(lab / "foundry")
    rec.task_spec(s, "alpha")
    rec.task_spec(s, "beta", approved="false")
    rec.write(s / "tasks" / "gamma.toml", "= broken")
    load(page)
    assert page.tasks_table.item(1, 6).text() == "no"
    assert "unreadable" in page.tasks_table.item(2, 2).text()
    assert not page.plan_button.isEnabled()
    page.tick("beta", "alpha")
    assert page.ticked() == ["alpha", "beta"]
    page.plan_button.click()
    wait_for(lambda: not page.is_running())
    assert calls(lab)[-1] == ["plan", "alpha", "beta"]
    out = page.output.toPlainText()
    assert out.startswith("$ nightshift.py plan alpha beta") and "cwd foundry" in out and "exit 0" in out
    page.arm_button.click()
    wait_for(lambda: not page.is_running())
    assert calls(lab)[-1] == ["arm", "alpha", "beta"]
    assert page.exit_label.text() == "exit 3"
    # Ticks survive a refresh.
    load(page)
    assert page.ticked() == ["alpha", "beta"]


def test_confirmation_declined_runs_nothing(page, lab):
    rec.state(lab / "foundry")
    load(page)
    page.confirm = lambda title, text: False
    page.disarm_button.click()
    page.stop_now_button.click()
    assert not page.is_running() and calls(lab) == []


@pytest.mark.parametrize("button, want", [
    ("disarm_button", ["disarm"]), ("stop_after_button", ["stop", "--after"]),
    ("stop_now_button", ["stop", "--now"]), ("stop_clear_button", ["stop", "--clear"]),
])
def test_command_buttons(page, lab, button, want):
    rec.state(lab / "foundry")
    load(page)
    getattr(page, button).click()
    wait_for(lambda: not page.is_running())
    assert calls(lab) == [want]


def test_cancel_kills_the_child_and_shutdown_waits(page, lab):
    rec.state(lab / "foundry")
    load(page)
    page.dry_button.click()
    assert page.is_running() and page.busy_reason()
    assert not page.dry_button.isEnabled() and page.cancel_button.isEnabled()
    wait_for(lambda: "fake nightshift dry-run" in page.output.toPlainText())
    page.cancel_command()
    wait_for(lambda: not page.is_running())
    assert "(cancelled)" in page.exit_label.text()


def test_shutdown_with_a_command_running(qapp, lab):
    rec.state(lab / "foundry")
    tab = NightshiftTab(config.Settings(lab_root=str(lab)))
    tab.python_exe = sys.executable
    load(tab)
    assert tab.run_command("dry-run")
    worker = tab.worker
    tab.shutdown()
    assert worker.isFinished()


def test_refused_command_is_not_run(page, lab):
    rec.state(lab / "foundry")
    load(page)
    assert page.run_command("run") is False
    assert "Not run" in page.exit_label.text() and calls(lab) == []


def test_page_writes_nothing_in_the_state_folder(page, lab):
    s = rec.state(lab / "foundry")
    rid = "20261124-020000"
    rec.write(s / "runs" / rid / "run.json", rec.run_record(rid))
    rec.add_task(s, rid, "t1", files={"diff.patch": "+x"})
    rec.task_spec(s, "a")
    before = {p: p.read_bytes() for p in s.rglob("*") if p.is_file()}
    load(page)
    page.tick("a")
    page.select_task("t1")
    load(page)
    assert {p: p.read_bytes() for p in s.rglob("*") if p.is_file()} == before


def test_task_row_of_unreadable_record(tmp_path):
    row = task_row(ns.Unreadable(tmp_path / "t9" / "record.json", "no schema_version"))
    assert row[:3] == ["t9", "unreadable", "no schema_version"]


def test_reachable_from_tools(window):
    tile = next(t for t in window.tools_overview.tool_tiles if t.name.text() == "Nightshift")
    tile.open_requested.emit()
    assert window.tools_tabs.currentWidget() is window.nightshift_tab
    window.tools_tabs.setCurrentWidget(window.tools_overview)


@pytest.mark.parametrize("state_, status", [("finished", "failed"), ("finished", "skipped"), ("running", "done")])
def test_verdict_only_for_a_done_task_of_a_night_that_is_over(page, lab, state_, status):
    s = rec.state(lab / "foundry")
    rid = "20261124-020000"
    rec.write(s / "runs" / rid / "run.json", rec.run_record(rid, state_))
    rec.add_task(s, rid, "t1", status=status)
    load(page)
    page.select_task("t1")
    assert not page.accept_button.isEnabled() and not page.reject_button.isEnabled()


def test_a_running_night_is_shown_as_running(page, lab):
    s = rec.state(lab / "foundry")
    rid = "20261124-020000"
    rec.write(s / "runs" / rid / "run.json", rec.run_record(rid, "running", started="2026-11-24T02:00:00+00:00",
                                                            prestart=rec.gate(True)))
    load(page)
    assert "Running now:</b> run 20261124-020000" in page.tonight.text()
    assert "Nothing armed" not in page.tonight.text()


def test_track_rule_text_follows_the_settings(page, lab):
    rec.state(lab / "foundry")
    (lab / "foundry" / "tools" / "nightshift.toml").write_text("[track]\nwindow = 6\nallowed = 4\ndaytime_below = 3\n")
    load(page)
    assert "last 6 results" in page.track_rule.text() and "4 or more" in page.track_rule.text()


def test_cancel_sends_sigint_first(page, lab):
    (lab / "foundry" / "tools" / "nightshift.py").write_text(
        "import sys, time\nprint('started', flush=True)\n"
        "try:\n    time.sleep(30)\nexcept KeyboardInterrupt:\n    print('cleaned up', flush=True)\n    sys.exit(130)\n")
    rec.state(lab / "foundry")
    load(page)
    page.dry_button.click()
    wait_for(lambda: "started" in page.output.toPlainText())
    page.cancel_command()
    wait_for(lambda: not page.is_running())
    assert "cleaned up" in page.output.toPlainText() and page.last_exit == 130

