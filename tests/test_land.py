"""Land: one repo's work in one go, on real temporary git repos (no git mocks).

Spec `docs/specs/land-from-tiles.md`. Claude Code and a repo's own test run are
outside git, so the "tests fail on the default branch" and "Claude could not
resolve it" outcomes come from replacing `repo_tidy.apply`'s answer for that one
action; everything else runs real git.
"""

from __future__ import annotations

import pytest

from lab_hub import land, repo_tidy

from .test_repo_tidy import OLD, commit, lab, make_branch, sh, squash_land  # noqa: F401 (fixture)


def plan_for(repo, claude=None):
    return land.make_plan("repo", repo, claude=claude, busy=(), now=OLD)


def run(plan, tmp_path, **kw):
    return land.land(plan, log=tmp_path / "land.log", busy=(), now=OLD, **kw)


# ---------------------------------------------------------------- the sentence
def test_the_sentence_says_what_will_happen_in_plain_words(lab):
    make_branch(lab, "feat", "f.txt")
    squash_land(lab, "old", "o.txt")
    text = plan_for(lab).sentence
    assert text.startswith("repo: ")
    assert "merge 1 branch into main" in text
    assert "push main to origin" in text
    assert "delete 2 landed branches" in text
    assert "Claude" not in text


def test_an_empty_plan_says_why_instead_of_listing_nothing(lab):
    plan = plan_for(lab)
    assert plan.nothing and "nothing" in plan.sentence.lower()


def _claude_plan(*targets):
    from pathlib import Path

    actions = tuple(repo_tidy.Action("sonar", Path("/x"), "claude_merge", t, "conflicts",
                                     branch="master", detail="pytest -q") for t in targets)
    return land.LandPlan("sonar", Path("/x"), actions, (), "/bin/claude")


def test_conflicts_handed_to_claude_are_named_with_cost_total_and_test_command():
    from lab_hub import claude_resolve

    plan = _claude_plan("a", "b")
    assert plan.with_claude == 2
    assert plan.sentence == "sonar: merge 2 branches into master (2 with Claude Code resolving conflicts)."
    notice = plan.claude_notice
    assert "sent to Claude Code" in notice and "Anthropic" in notice
    assert f"${2 * claude_resolve.BUDGET_USD:.0f} in total" in notice
    assert "pytest -q" in notice
    assert land.LandPlan("r", plan.path).claude_notice == ""


def test_the_sentence_names_every_push_and_the_detail_names_the_path(lab):
    from pathlib import Path

    acts = tuple(repo_tidy.Action("r", Path("/x"), "push", t, "ahead") for t in ("main", "dev"))
    plan = land.LandPlan("r", Path("/x"), acts)
    assert plan.sentence == "r: push main, dev to origin."
    assert plan.detail.startswith("r is /x")


# ---------------------------------------------------------------- success
def test_land_merges_pushes_and_tidies_then_says_landed(lab, tmp_path):
    make_branch(lab, "feat", "f.txt")
    squash_land(lab, "old", "o.txt")
    result = run(plan_for(lab), tmp_path)
    assert result.state == "landed" and result.landed
    assert result.line == "Landed"
    assert result.failed == 0 and result.done >= 3
    assert (lab / "f.txt").exists()
    assert repo_tidy.local_branches(lab) == ["main"]
    assert repo_tidy.ahead_behind(lab) == (0, 0)


def test_nothing_to_land_says_so(lab, tmp_path):
    result = run(plan_for(lab), tmp_path)
    assert result.state == "nothing" and result.line == "Nothing to land"


def test_a_conflict_land_cannot_take_is_reported_and_counted_for_the_owner(lab, tmp_path):
    make_branch(lab, "feat", "a.txt", "theirs")
    commit(lab, "a.txt", "ours")
    sh(lab, "push", "-q", "origin", "main")
    result = run(plan_for(lab, claude=None), tmp_path)
    assert result.state == "not_landed" and result.remaining == 1
    assert "conflict" in result.reason.lower()
    assert result.line.startswith("Not landed: ")
    assert "feat" in repo_tidy.local_branches(lab)  # nothing was forced


def test_landed_with_a_branch_left_for_the_owner_says_so():
    result = land.LandResult("repo", "landed", remaining=2)
    assert result.line == "Landed · 2 branches need your decision"
    assert land.LandResult("repo", "landed", remaining=1).line == "Landed · 1 branch needs your decision"


# ---------------------------------------------------------------- failure
def test_a_failed_step_is_reported_in_one_sentence_and_the_rest_still_run(lab, tmp_path, monkeypatch):
    make_branch(lab, "feat", "f.txt")
    squash_land(lab, "old", "o.txt")
    real = repo_tidy.apply
    seen = []

    def apply(action, *a, **kw):
        seen.append(action.kind)
        if action.kind == "merge":
            return False, ("not landed — no Claude run: the tests don't pass on master itself "
                           "in a temporary copy (they fail): re as _core # noqa: E402\n"
                           "sonar/core.py:29: in <module>\n"
                           "ImportError: cannot import name 'macro' from 'sonar'")
        return real(action, *a, **kw)

    monkeypatch.setattr(repo_tidy, "apply", apply)
    result = run(plan_for(lab), tmp_path)
    assert result.state == "not_landed" and result.failed >= 1
    assert result.reason.startswith("no Claude run: the tests don't pass on master itself")
    assert "cannot import name 'macro'" in result.reason
    assert "not landed" not in result.reason and "\n" not in result.reason
    assert result.line.startswith("Not landed: ")
    assert "push" in seen and "delete_branch" in seen  # it carried on past the merge


def test_a_diverged_repo_is_not_landed_with_the_reason(lab, tmp_path):
    other = tmp_path / "other"
    sh(tmp_path, "clone", "-q", str(tmp_path / "origin.git"), str(other))
    sh(other, "config", "user.name", "t")
    sh(other, "config", "user.email", "t@t")
    commit(other, "theirs.txt")
    sh(other, "push", "-q", "origin", "main")
    commit(lab, "mine.txt")
    sh(lab, "fetch", "-q", "origin")
    result = run(plan_for(lab), tmp_path)
    assert result.state == "not_landed"
    assert "diverged" in result.reason.lower() and "\n" not in result.reason
    assert repo_tidy.ahead_behind(lab) == (1, 1)  # never forced, never merged


def test_a_repo_already_landing_is_refused(lab, tmp_path):
    assert land.claim(lab)
    try:
        result = run(plan_for(lab), tmp_path)
        assert result.state == "not_landed" and "already being landed" in result.reason
    finally:
        land.release(lab)
    assert not land.landing(lab)


def test_the_claim_is_released_after_a_crash(lab, tmp_path, monkeypatch):
    make_branch(lab, "feat", "f.txt")
    monkeypatch.setattr(repo_tidy, "apply", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    result = run(plan_for(lab), tmp_path)
    assert result.state == "not_landed" and "boom" in result.reason
    assert not land.landing(lab)


def test_stop_skips_the_rest_and_says_it_was_stopped(lab, tmp_path):
    from lab_hub import claude_resolve

    make_branch(lab, "feat", "f.txt")
    stopper = claude_resolve.Stopper()
    stopper.stop()
    result = run(plan_for(lab), tmp_path, stop=stopper)
    assert result.state == "not_landed" and "stopped" in result.reason
    assert not (lab / "f.txt").exists()


def test_a_path_that_is_not_a_repo_is_not_landed(tmp_path):
    plan = land.make_plan("x", tmp_path / "nope", claude=None, busy=(), now=OLD)
    result = land.land(plan, busy=(), now=OLD)
    assert result.state == "not_landed" and "not a git checkout" in result.reason


# ---------------------------------------------------------------- plain_reason
@pytest.mark.parametrize("message, expected", [
    ("not landed — the tests fail", "the tests fail"),
    ("skipped — its changes are no longer all in main", "its changes are no longer all in main"),
    ("failed — fatal: unable to access", "fatal: unable to access"),
    ("", "it did not finish and gave no reason"),
    ("first line\nmore\nValueError: bad thing", "first line: ValueError: bad thing"),
    # pytest's own summary must not be mistaken for the cause
    ("not landed — the tests fail\nsonar/core.py:29: in <module>\n"
     "ImportError: cannot import name 'macro' from 'sonar'\n"
     "=========== 1 error in 0.12s ===========",
     "the tests fail: ImportError: cannot import name 'macro' from 'sonar'"),
])
def test_plain_reason(message, expected):
    assert land.plain_reason(message) == expected


def test_plain_reason_is_cut_to_one_tile_line():
    assert len(land.plain_reason("x" * 1000)) <= land.MAX_REASON
