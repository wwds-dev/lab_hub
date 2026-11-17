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
