"""The duration history behind "time left" (spec progress-windows §8.4, §8.12).

It is a cache: anything wrong with the file reads as no history, never a crash,
and the next good save replaces it. Names are keys, never paths.
"""

from __future__ import annotations

import json
import os
import stat

import pytest

from lab_hub import config, durations


def test_round_trip_and_median(tmp_path):
    file = tmp_path / "d.json"
    for value in (10, 30, 20):
        assert durations.record("repo:SONAR", "merge", value, path=file)
    history = durations.load(path=file)
    assert history == {"repo:SONAR": {"merge": [10.0, 30.0, 20.0]}}
    assert durations.estimate(history, "repo:SONAR", "merge") == 20.0
    assert durations.estimate(history, "repo:SONAR", "push") is None
    assert durations.estimate(history, "repo:other", "merge") is None


@pytest.mark.parametrize("samples, median", [
    ([4], 4), ([4, 8], 6), ([1, 9, 5], 5), ([1, 2, 3, 100], 2.5), ([5, 1, 4, 2, 3], 3),
])
def test_the_estimate_is_the_median_of_one_to_five(tmp_path, samples, median):
    file = tmp_path / "d.json"
    for value in samples:
        durations.record("app:x", "build", value, path=file)
    assert durations.estimate(durations.load(path=file), "app:x", "build") == median


def test_a_sixth_sample_drops_the_oldest(tmp_path):
    file = tmp_path / "d.json"
    for value in (1, 2, 3, 4, 5, 6):
        durations.record("app:x", "build", value, path=file)
    assert durations.load(path=file)["app:x"]["build"] == [2.0, 3.0, 4.0, 5.0, 6.0]


@pytest.mark.parametrize("content", [
    b"",
    b"{not json",
    b"\xff\xfe\x00",
    json.dumps({"version": 2, "subjects": {"repo:a": {"merge": [1]}}}).encode(),
    json.dumps([1, 2, 3]).encode(),
    json.dumps({"version": 1, "subjects": []}).encode(),
    json.dumps({"version": "1", "subjects": {"repo:a": {"merge": [1]}}}).encode(),
])
def test_a_broken_file_is_no_history_not_a_crash(tmp_path, content):
    file = tmp_path / "d.json"
    file.write_bytes(content)
    assert durations.load(path=file) == {}


def test_a_missing_file_is_no_history(tmp_path):
    assert durations.load(path=tmp_path / "nope.json") == {}


def test_bad_samples_and_unknown_kinds_are_dropped_on_load(tmp_path):
    file = tmp_path / "d.json"
    file.write_text(json.dumps({"version": 1, "subjects": {
        "repo:a": {"merge": ["3", None, True, -1, 0, 21601, 5, 2.5],
                   "rm -rf": [1], "push": "7"},
        "repo:b": "not an object",
        "repo:c": {"merge": ["x"]},
    }}))
    # NaN is not valid JSON for most writers, but Python's own reader takes it.
    raw = file.read_text().replace("2.5", "NaN")
    file.write_text(raw)
    assert durations.load(path=file) == {"repo:a": {"merge": [5.0]}}


def test_an_oversized_file_is_treated_as_empty(tmp_path):
    file = tmp_path / "d.json"
    good = {"version": 1, "subjects": {"repo:a": {"merge": [1]}}}
    text = json.dumps(good)
    file.write_text(text + " " * (300 * 1024))
    assert durations.load(path=file) == {}


@pytest.mark.parametrize("seconds", [0, -1, float("nan"), float("inf"), 21601, "5", True])
def test_record_refuses_a_bad_sample(tmp_path, seconds):
    file = tmp_path / "d.json"
    assert durations.record("app:x", "build", seconds, path=file) is False
    assert not file.exists()


def test_record_refuses_an_unknown_kind(tmp_path):
    file = tmp_path / "d.json"
    assert durations.record("app:x", "../../etc", 3, path=file) is False
    assert not file.exists()


def test_the_cap_is_six_hours_inclusive(tmp_path):
    file = tmp_path / "d.json"
    assert durations.record("app:x", "build", 21600, path=file)
    assert durations.load(path=file)["app:x"]["build"] == [21600.0]


def test_a_subject_is_sanitised_and_stays_a_key(tmp_path):
    assert durations.subject("repo", "SON\x1bAR​\n  x") == "repo:SONAR x"
    long = durations.subject("repo", "a" * 500)
    assert long == "repo:" + "a" * 120
    key = durations.subject("repo", "../x")
    file = tmp_path / "sub" / "d.json"
    assert durations.record(key, "merge", 1, path=file)
    assert sorted(p.name for p in file.parent.iterdir()) == ["d.json"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["sub"]
    assert durations.load(path=file) == {"repo:../x": {"merge": [1.0]}}


def test_the_201st_subject_evicts_the_oldest(tmp_path):
    file = tmp_path / "d.json"
    history = {f"repo:{n}": {"merge": [1.0]} for n in range(200)}
    assert durations.save(history, path=file)
    durations.record("repo:0", "merge", 2, path=file)  # recorded again: now the newest
    durations.record("repo:new", "merge", 3, path=file)
    loaded = durations.load(path=file)
    assert len(loaded) == 200
    assert "repo:1" not in loaded  # the oldest untouched one went
    assert "repo:0" in loaded and "repo:new" in loaded
    assert list(loaded)[-1] == "repo:new"


def test_save_leaves_no_temp_file_and_is_private(tmp_path):
    file = tmp_path / "d.json"
    assert durations.record("app:x", "build", 3, path=file)
    assert [p.name for p in tmp_path.iterdir()] == ["d.json"]
    assert stat.S_IMODE(os.stat(file).st_mode) == 0o600


def test_a_save_that_fails_returns_false_and_cleans_up(tmp_path, monkeypatch):
    file = tmp_path / "d.json"

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(durations.os, "replace", boom)
    assert durations.record("app:x", "build", 3, path=file) is False
    assert list(tmp_path.iterdir()) == []


def test_a_broken_file_is_replaced_by_the_next_good_save(tmp_path):
    file = tmp_path / "d.json"
    file.write_text("{oops")
    assert durations.record("app:x", "build", 3, path=file)
    assert durations.load(path=file) == {"app:x": {"build": [3.0]}}


_DEEP = b"[" * 200_000
_DEEP_IN_SUBJECTS = b'{"version":1,"subjects":{"repo:a":' + b"[" * 200_000 + b"}}"
_HUGE_INT = b'{"version":1,"subjects":{"repo:a":{"merge":[1' + b"0" * 309 + b"]}}}"


@pytest.mark.parametrize("content", [_DEEP, _DEEP_IN_SUBJECTS, _HUGE_INT],
                         ids=["deep-list", "deep-in-subjects", "int-over-float"])
def test_a_hostile_file_is_no_history_and_the_next_save_replaces_it(tmp_path, content):
    """Review P2-3 / Secure P2-1: these raised RecursionError and OverflowError
    out of load() and record(), so Check builds opened nothing until the file
    was deleted by hand."""
    file = tmp_path / "d.json"
    file.write_bytes(content)
    assert durations.load(path=file) == {}
    assert durations.record("repo:b", "merge", 2.0, path=file) is True
    assert durations.load(path=file) == {"repo:b": {"merge": [2.0]}}


def test_a_huge_integer_sample_is_dropped_not_raised(tmp_path):
    file = tmp_path / "d.json"
    file.write_bytes(b'{"version":1,"subjects":{"repo:a":{"merge":[3, 1' + b"0" * 400
                     + b"]}}}")
    assert durations.load(path=file) == {"repo:a": {"merge": [3.0]}}


def test_a_fifo_at_the_path_is_not_read_and_does_not_hang(tmp_path):
    """Secure P3-2: read_text() on a FIFO blocked the GUI thread for good."""
    import threading

    file = tmp_path / "d.json"
    os.mkfifo(file)
    got = []
    worker = threading.Thread(target=lambda: got.append(durations.load(path=file)),
                              daemon=True)
    worker.start()
    worker.join(3)
    if worker.is_alive():  # unblock the reader so the thread can end
        os.close(os.open(file, os.O_WRONLY | os.O_NONBLOCK))
    assert got == [{}]
    # Not even a FIFO holding a good history is read: only a regular file is.
    holder = os.open(file, os.O_RDONLY | os.O_NONBLOCK)  # keeps the data in the pipe
    try:
        writer = os.open(file, os.O_WRONLY | os.O_NONBLOCK)
        os.write(writer, json.dumps({"version": 1, "subjects": {
            "repo:a": {"merge": [1]}}}).encode())
        os.close(writer)
        assert durations.load(path=file) == {}
    finally:
        os.close(holder)
    assert durations.record("app:x", "build", 3, path=file)
    assert durations.load(path=file) == {"app:x": {"build": [3.0]}}


def test_a_symlink_or_a_directory_at_the_path_is_not_read(tmp_path):
    target = tmp_path / "elsewhere.json"
    target.write_text(json.dumps({"version": 1, "subjects": {"repo:a": {"merge": [1]}}}))
    link = tmp_path / "d.json"
    link.symlink_to(target)
    assert durations.load(path=link) == {}
    folder = tmp_path / "dir.json"
    folder.mkdir()
    assert durations.load(path=folder) == {}


def test_load_keeps_only_the_last_five_samples_of_a_hand_edited_file(tmp_path):
    file = tmp_path / "d.json"
    file.write_text(json.dumps({"version": 1, "subjects": {
        "repo:a": {"merge": [1, 2, 3, 4, 5, 6, 7]}}}))
    assert durations.load(path=file) == {"repo:a": {"merge": [3.0, 4.0, 5.0, 6.0, 7.0]}}


def test_load_of_a_hand_edited_file_keeps_the_newest_two_hundred(tmp_path):
    file = tmp_path / "d.json"
    file.write_text(json.dumps({"version": 1, "subjects": {
        f"repo:{n}": {"merge": [1]} for n in range(205)}}))
    loaded = durations.load(path=file)
    assert len(loaded) == 200
    assert list(loaded)[0] == "repo:5" and list(loaded)[-1] == "repo:204"


def test_record_writes_at_most_two_hundred_subjects(tmp_path):
    file = tmp_path / "d.json"
    assert durations.save({f"repo:{n}": {"merge": [1.0]} for n in range(200)}, path=file)
    durations.record("repo:new", "merge", 3, path=file)
    on_disk = json.loads(file.read_text())["subjects"]
    assert len(on_disk) == 200 and "repo:0" not in on_disk


def test_the_path_follows_the_support_dir(isolated_config):
    assert durations.path() == isolated_config / "durations.json"
    assert durations.record("app:x", "build", 3)
    assert (config.SUPPORT_DIR / "durations.json").exists()


# ------------------------------------------- the Land run log (ADR 0005)
from datetime import datetime  # noqa: E402


def test_run_log_round_trip_keeps_the_last_ten(tmp_path):
    file = tmp_path / "land-runs.json"
    for i in range(12):
        assert durations.record_run(datetime(2026, 11, 18, 14, i), 6, 5, 860.5 + i,
                                    i == 11, path=file)
    runs = durations.load_runs(path=file)
    assert len(runs) == 10 and runs[0].at == datetime(2026, 11, 18, 14, 2)
    assert runs[-1] == durations.Run(datetime(2026, 11, 18, 14, 11), 6, 5, 871.5, True)
    assert not list(tmp_path.glob(".*.tmp"))
    assert oct(file.stat().st_mode & 0o777) == "0o600"


def test_the_run_log_follows_the_support_dir():
    assert durations.runs_path() == config.SUPPORT_DIR / "land-runs.json"
    assert durations.load_runs() == []
    assert durations.record_run(datetime(2026, 11, 18, 9, 0), 1, 1, 41)
    assert len(durations.load_runs()) == 1
    assert durations.load() == {}  # the step history is a different file, untouched


@pytest.mark.parametrize("bad", [
    {"at": "2026-11-18T14:09:33", "repos": 1, "landed": 1, "seconds": 5},
    {"at": "yesterday", "repos": 1, "landed": 1, "seconds": 5},
    {"at": 20261118, "repos": 1, "landed": 1, "seconds": 5},
    {"at": "2026-11-18T14:09", "repos": -1, "landed": 0, "seconds": 5},
    {"at": "2026-11-18T14:09", "repos": 501, "landed": 0, "seconds": 5},
    {"at": "2026-11-18T14:09", "repos": True, "landed": 0, "seconds": 5},
    {"at": "2026-11-18T14:09", "repos": 1, "landed": 1.5, "seconds": 5},
    {"at": "2026-11-18T14:09", "repos": 1, "landed": 1, "seconds": 0},
    {"at": "2026-11-18T14:09", "repos": 1, "landed": 1, "seconds": "5"},
    {"at": "2026-11-18T14:09", "repos": 1, "landed": 1, "seconds": 1e9},
    {"at": "2026-11-18T14:09", "repos": 1, "landed": 1, "seconds": 5, "stopped": "no"},
    ["2026-11-18T14:09", 1, 1, 5],
])
def test_a_bad_run_entry_is_dropped_and_the_good_ones_kept(tmp_path, bad):
    file = tmp_path / "land-runs.json"
    good = {"at": "2026-11-18T14:09", "repos": 2, "landed": 3, "seconds": 5}
    file.write_text(json.dumps({"version": 1, "runs": [bad, good]}))
    runs = durations.load_runs(path=file)
    assert runs == [durations.Run(datetime(2026, 11, 18, 14, 9), 2, 2, 5.0)]  # landed <= repos


@pytest.mark.parametrize("text", ["", "{", "[]", '{"version": 2, "runs": []}',
                                  '{"version": 1, "runs": {}}', '{"version": 1}',
                                  "[" * 100000, '{"version": 1, "runs": [' + "1," * 40000 + "1]}"])
def test_a_hostile_run_log_reads_as_no_runs_and_the_next_record_replaces_it(tmp_path, text):
    file = tmp_path / "land-runs.json"
    file.write_text(text)
    assert durations.load_runs(path=file) == []
    assert durations.record_run(datetime(2026, 11, 18, 9, 0), 1, 0, 3, path=file)
    assert len(durations.load_runs(path=file)) == 1


def test_a_symlink_or_fifo_run_log_is_not_read(tmp_path):
    target = tmp_path / "real.json"
    target.write_text(json.dumps({"version": 1, "runs": [
        {"at": "2026-11-18T14:09", "repos": 1, "landed": 1, "seconds": 5}]}))
    link = tmp_path / "land-runs.json"
    link.symlink_to(target)
    assert durations.load_runs(path=link) == []
    fifo = tmp_path / "fifo.json"
    os.mkfifo(fifo)
    assert durations.load_runs(path=fifo) == []


def test_record_run_refuses_bad_values_and_a_failed_save_says_false(tmp_path, monkeypatch):
    file = tmp_path / "land-runs.json"
    assert not durations.record_run(datetime(2026, 11, 18), 1, 1, 0, path=file)
    assert not durations.record_run(datetime(2026, 11, 18), -1, 0, 5, path=file)
    assert not file.exists()
    monkeypatch.setattr(durations.os, "replace", lambda *a: (_ for _ in ()).throw(OSError()))
    assert not durations.record_run(datetime(2026, 11, 18), 1, 1, 5, path=file)
    assert not file.exists() and not list(tmp_path.glob(".*.tmp"))


# --- verify follow-up (docs/audit/land-pick-and-time-qa.md G7) ---------------
def _good_run(i: int = 0) -> dict:
    return {"at": f"2026-11-18T14:{i:02d}", "repos": 2, "landed": 2, "seconds": 30 + i,
            "stopped": False}


def _runs_file(tmp_path, data) -> object:
    file = tmp_path / "runs.json"
    file.write_text(json.dumps(data), encoding="utf-8")
    return file


def test_a_valid_run_log_over_the_64_kib_cap_reads_as_no_runs(tmp_path):
    runs = [dict(_good_run(), pad="x" * 70_000)]  # well-formed JSON, valid entry, 70 KiB
    file = _runs_file(tmp_path, {"version": durations.VERSION, "runs": runs})
    assert 64 * 1024 < file.stat().st_size < durations.MAX_BYTES
    assert durations.load_runs(path=file) == []
    small = _runs_file(tmp_path, {"version": durations.VERSION, "runs": [_good_run()]})
    assert len(durations.load_runs(path=small)) == 1


def test_a_run_log_of_another_version_reads_as_no_runs_even_with_good_runs(tmp_path):
    file = _runs_file(tmp_path, {"version": durations.VERSION + 1, "runs": [_good_run()]})
    assert durations.load_runs(path=file) == []


def test_a_hand_edited_run_log_keeps_its_last_ten(tmp_path):
    file = _runs_file(tmp_path, {"version": durations.VERSION,
                                 "runs": [_good_run(i) for i in range(12)]})
    runs = durations.load_runs(path=file)
    assert [r.seconds for r in runs] == [float(30 + i) for i in range(2, 12)]


def test_the_repo_count_limit_is_500_inclusive(tmp_path):
    def with_repos(n):
        entry = dict(_good_run(), repos=n, landed=0)
        return _runs_file(tmp_path, {"version": durations.VERSION, "runs": [entry]})

    assert [r.repos for r in durations.load_runs(path=with_repos(500))] == [500]
    assert durations.load_runs(path=with_repos(501)) == []
