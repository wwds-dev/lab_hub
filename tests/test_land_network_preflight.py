"""Land checks that `origin` answers before it starts any slow work.

Spec `docs/specs/land-network-preflight.md`. Real temporary git repos; an
unreachable origin is a remote URL that points at nothing, which git refuses at
once. The calls to git are recorded by wrapping `repo_tidy.git`, which delegates
to the real one.
"""

from __future__ import annotations

import dataclasses

from lab_hub import land, repo_tidy

from .test_land import plan_for, run
from .test_repo_tidy import lab, make_branch, sh, squash_land  # noqa: F401 (fixture)

SENTENCE = "cannot reach origin (no network?): no merge or test was started"


def record_git(monkeypatch):
    calls: list[tuple[tuple, dict]] = []
    real = repo_tidy.git

    def spy(repo, *args, **kw):
        calls.append((args, kw))
        return real(repo, *args, **kw)

    monkeypatch.setattr(repo_tidy, "git", spy)
    return calls


def preflights(calls):
    return [(a, kw) for a, kw in calls if a and a[0] == "ls-remote"]


def break_origin(repo, tmp_path):
    sh(repo, "remote", "set-url", "origin", str(tmp_path / "gone.git"))


def test_an_unreachable_origin_stops_the_repo_before_any_step(lab, tmp_path, monkeypatch):
    make_branch(lab, "feat", "f.txt")
    squash_land(lab, "old", "o.txt")
    plan = plan_for(lab)
    assert not plan.nothing
    break_origin(lab, tmp_path)
    events = []
    result = run(plan, tmp_path, events=events.append)
    assert result.state == "not_landed" and result.reason == SENTENCE
    assert events == []  # no prep, merge, Claude or test step started
    assert not (lab / "f.txt").exists()  # nothing was merged
    assert "feat" in repo_tidy.local_branches(lab)  # nothing was deleted
    assert result.line == f"Not landed: {SENTENCE}"


def test_the_claim_is_released_after_the_stop(lab, tmp_path):
    make_branch(lab, "feat", "f.txt")
    plan = plan_for(lab)
    good = lab.parent / "origin.git"
    break_origin(lab, tmp_path)
    assert run(plan, tmp_path).reason == SENTENCE
    assert not land.landing(lab)
    sh(lab, "remote", "set-url", "origin", str(good))
    assert run(plan_for(lab), tmp_path).state == "landed"


def test_a_reachable_origin_is_asked_once_with_a_short_timeout_and_land_runs(
        lab, tmp_path, monkeypatch):
    make_branch(lab, "feat", "f.txt")
    squash_land(lab, "old", "o.txt")
    plan = plan_for(lab)
    calls = record_git(monkeypatch)
    result = run(plan, tmp_path)
    assert result.state == "landed"
    asked = preflights(calls)
    assert len(asked) == 1
    args, kw = asked[0]
    assert kw["timeout"] == land.PREFLIGHT_TIMEOUT and land.PREFLIGHT_TIMEOUT <= 15
    assert args[-2:] == ("origin", "main")
    # the check comes before the first step's git work
    assert calls.index(asked[0]) < next(i for i, (a, _) in enumerate(calls)
                                        if a and a[0] in ("merge", "commit", "push"))


def test_a_repo_with_nothing_to_land_is_not_checked(lab, tmp_path, monkeypatch):
    plan = plan_for(lab)
    calls = record_git(monkeypatch)
    assert run(plan, tmp_path).state == "nothing"
    assert preflights(calls) == []


def test_a_repo_without_origin_is_not_checked(lab, tmp_path, monkeypatch):
    make_branch(lab, "feat", "f.txt")
    plan = plan_for(lab)
    sh(lab, "remote", "remove", "origin")
    calls = record_git(monkeypatch)
    result = run(plan, tmp_path)
    assert preflights(calls) == []
    assert SENTENCE not in result.reason


def test_the_log_keeps_gits_own_error_line(lab, tmp_path):
    make_branch(lab, "feat", "f.txt")
    plan = plan_for(lab)
    break_origin(lab, tmp_path)
    run(plan, tmp_path)
    log = (tmp_path / "land.log").read_text()
    assert "ls-remote" in log and "gone.git" in log


def test_the_stop_comes_before_prep_moves_anything(lab, tmp_path):
    # An untracked file that blocks a merge is quarantined by a prep step; with
    # no network that must not happen (a mutation that checked after prep survived).
    make_branch(lab, "feat", "f.txt")
    (lab / "f.txt").write_text("mine")
    plan = plan_for(lab)
    assert plan.prep, "the fixture must give Land a prep step"
    break_origin(lab, tmp_path)
    events = []
    result = run(plan, tmp_path, events=events.append)
    assert result.reason == SENTENCE and events == []
    assert (lab / "f.txt").read_text() == "mine"


def test_a_timeout_gets_the_same_sentence_and_the_log_line(lab, tmp_path, monkeypatch):
    make_branch(lab, "feat", "f.txt")
    plan = plan_for(lab)
    real = repo_tidy.git

    def hang(repo, *args, **kw):
        if args and args[0] == "ls-remote":
            return 1, "", "timed out after 15 seconds"
        return real(repo, *args, **kw)

    monkeypatch.setattr(repo_tidy, "git", hang)
    events = []
    result = run(plan, tmp_path, events=events.append)
    assert result.reason == SENTENCE and events == []
    assert "timed out after 15 seconds" in (tmp_path / "land.log").read_text()


def test_a_stop_pressed_before_the_check_says_stopped_and_asks_nothing(
        lab, tmp_path, monkeypatch):
    from lab_hub import claude_resolve

    make_branch(lab, "feat", "f.txt")
    plan = plan_for(lab)
    stopper = claude_resolve.Stopper()
    stopper.stop()
    calls = record_git(monkeypatch)
    result = run(plan, tmp_path, stop=stopper)
    assert result.reason == "it was stopped" and preflights(calls) == []


def test_the_stop_keeps_the_blockers_a_person_must_clear(lab, tmp_path):
    from lab_hub import land_resolve

    make_branch(lab, "feat", "f.txt")
    plan = plan_for(lab)
    stop = land_resolve.Stop("repo", "x", "a blocker only a person can clear")
    plan = dataclasses.replace(plan, stops=(stop,))
    break_origin(lab, tmp_path)
    result = run(plan, tmp_path)
    assert result.reason == SENTENCE and stop.label in result.notes


def test_an_unknown_default_branch_sends_no_empty_ref(lab, tmp_path, monkeypatch):
    make_branch(lab, "feat", "f.txt")
    plan = plan_for(lab)
    monkeypatch.setattr(repo_tidy, "default_branch", lambda repo: None)
    calls = record_git(monkeypatch)
    run(plan, tmp_path)
    (args, _), = preflights(calls)
    assert args == ("ls-remote", "--heads", "origin")
