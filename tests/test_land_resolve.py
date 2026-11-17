"""Land leaves nothing open: real temporary git repos, real gitleaks, no git mocks.

Spec `docs/specs/land-resolve-all.md`. Claude Code is outside git: its verdict
is replaced with a fixed answer (`land_resolve.verdict`), and a merge Claude
would resolve is replaced through `repo_tidy.apply` for that one action, as in
`test_land.py`.
"""

from __future__ import annotations

import os
import stat
import time

import pytest

from lab_hub import land, land_resolve as lr, repo_tidy

from .test_repo_tidy import OLD, add_worktree, commit, lab, make_branch, sh  # noqa: F401

needs_gitleaks = pytest.mark.skipif(lr.gitleaks_exe() is None, reason="gitleaks not installed")
# Not real credentials: shapes gitleaks' default rules match.
# Assembled at run time, so this file itself never matches a secret scanner
# (Land's own pre-push scan would refuse to push lab_hub otherwise).
GITHUB_PAT = "ghp" + "_" + "8Zq3rT5vW1xY7bN2mK4pL6sD9fG0hJ3kQ5wE"
AWS_KEY = "AKIA" + "Q2XKZ7RMPLWE3TNV"


@pytest.fixture
def quarantine(tmp_path, monkeypatch):
    root = tmp_path / "quarantine"
    monkeypatch.setattr(lr, "QUARANTINE_ROOT", root)
    return root


def plan_for(repo, claude=None, busy=(), now=OLD):
    return land.make_plan("repo", repo, claude=claude, busy=busy, now=now)


def run(plan, tmp_path, busy=(), now=OLD, **kw):
    return land.land(plan, log=tmp_path / "land.log", busy=busy, now=now, **kw)


def fixed_verdict(monkeypatch, land_it: bool, reason="stale experiment", ok=True):
    asked = []

    def verdict(info, exe, why, stop=None, progress=None):
        asked.append((info.branch, why))
        return lr.Verdict(land_it, reason, 0.01, ok=ok)

    monkeypatch.setattr(lr, "verdict", verdict)
    return asked


def quarantined_files(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


# ------------------------------------------------------------ 4.2 untracked
@needs_gitleaks
def test_untracked_files_are_committed_and_secrets_go_to_quarantine(lab, tmp_path, quarantine):
    (lab / "notes.md").write_text("plain notes\n")
    (lab / "docs").mkdir()
    (lab / "docs" / "model_use.jsonl").write_text('{"model": "sonnet"}\n')
    (lab / "settings.py").write_text(f'TOKEN = "{GITHUB_PAT}"\n')
    (lab / ".env").write_text("A=1\n")
    (lab / ".env.example").write_text("A=\n")
    plan = plan_for(lab)
    assert "commit 3 untracked files after a secret scan" in plan.sentence
    assert "move 2 files to quarantine" in plan.sentence
    result = run(plan, tmp_path)
    assert result.state == "landed", result
    assert result.quarantined == 2 and "2 files quarantined" in result.line
    tracked = sh(lab, "ls-files").splitlines()
    assert {"notes.md", "docs/model_use.jsonl", ".env.example", ".gitignore"} <= set(tracked)
    assert "settings.py" not in tracked and ".env" not in tracked
    # Nothing lost: moved, not deleted, and owner-only.
    moved = quarantined_files(quarantine)
    assert any(m.endswith("settings.py") for m in moved) and any(m.endswith(".env") for m in moved)
    day = next(p for p in quarantine.rglob("*") if p.is_dir() and p.parent.parent == quarantine)
    for folder in (quarantine, day.parent, day):
        assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    ignore = (lab / ".gitignore").read_text()
    assert "/settings.py" in ignore and "/.env" in ignore
    assert repo_tidy.is_clean(lab) and repo_tidy.ahead_behind(lab) == (0, 0)  # pushed
    log = (tmp_path / "land.log").read_text()
    assert "QUARANTINE" in log and GITHUB_PAT not in log  # the secret is never logged
    assert sh(lab, "log", "--all", "-p").count(GITHUB_PAT) == 0  # never committed


@needs_gitleaks
def test_a_gitleaks_allow_comment_does_not_hide_a_secret(lab, tmp_path, quarantine):
    (lab / "keys.txt").write_text(f'key = "{AWS_KEY}"  # gitleaks:allow\n')
    run(plan_for(lab), tmp_path)
    assert "keys.txt" not in sh(lab, "ls-files")
    assert any(m.endswith("keys.txt") for m in quarantined_files(quarantine))


@needs_gitleaks
def test_a_repo_cannot_switch_the_scan_off_with_its_own_gitleaks_config(lab, tmp_path, quarantine):
    (lab / ".gitleaks.toml").write_text('[allowlist]\npaths = [".*"]\n')
    (lab / ".gitleaksignore").write_text("*\n")
    (lab / "app.py").write_text(f'T = "{GITHUB_PAT}"\n')
    run(plan_for(lab), tmp_path)
    assert "app.py" not in sh(lab, "ls-files")
    assert any(m.endswith("app.py") for m in quarantined_files(quarantine))


def test_without_gitleaks_nothing_is_committed_and_it_is_a_hard_stop(lab, tmp_path, quarantine,
                                                                       monkeypatch):
    monkeypatch.setattr(lr, "gitleaks_exe", lambda: None)
    (lab / "notes.md").write_text("x")
    head = sh(lab, "rev-parse", "HEAD")
    result = run(plan_for(lab), tmp_path)
    assert result.state == "not_landed" and "gitleaks is not installed" in result.reason
    assert sh(lab, "rev-parse", "HEAD") == head and (lab / "notes.md").exists()


def test_big_files_and_secret_names_are_quarantined_without_a_scan(lab, monkeypatch):
    monkeypatch.setattr(lr, "MAX_BYTES", 10)
    monkeypatch.setattr(lr, "scan", lambda wt, paths: ({}, {p: "0" * 40 for p in paths}, ""))
    (lab / "big.bin").write_text("x" * 11)
    (lab / "id_ed25519").write_text("k")
    (lab / "server.PEM").write_text("k")
    (lab / "ok.txt").write_text("k")
    sorted_ = lr.sort_untracked(lab)
    assert sorted_.commit == ("ok.txt",)
    assert {p for p, _ in sorted_.quarantine} == {"big.bin", "id_ed25519", "server.PEM"}


@pytest.mark.parametrize("name, secret", [
    (".env", True), (".env.local", True), (".env.example", False), ("a/b/id_rsa.pub", True),
    ("aws_credentials.json", True), ("notes.md", False), ("key.py", False), ("x.key", True),
])
def test_secret_by_name(name, secret):
    assert lr.secret_by_name(name) is secret


@pytest.mark.parametrize("rel, line", [
    ("a.txt", "/a.txt"), ("d/[x]*?.txt", "/d/\\[x\\]\\*\\?.txt"), ("#a", "/#a"), ("!b", "/!b"),
])
def test_ignore_line_matches_exactly_that_path(rel, line):
    assert lr.ignore_line(rel) == line


def test_an_ignore_line_ignores_only_its_own_file(lab):
    (lab / "[ab].txt").write_text("x")
    (lab / "b.txt").write_text("x")  # matched by the glob [ab].txt, not by the escaped line
    (lab / ".gitignore").write_text(lr.ignore_line("[ab].txt") + "\n")
    assert sorted(lr.untracked(lab)) == [".gitignore", "b.txt"]


# ------------------------------------------------------------ 4.3 checkout on a branch
def test_a_checkout_on_a_feature_branch_is_committed_switched_and_landed(lab, tmp_path,
                                                                           quarantine):
    sh(lab, "checkout", "-q", "-b", "claude/redesign")
    commit(lab, "r.txt")
    (lab / "a.txt").write_text("edited, not committed")
    plan = plan_for(lab)
    assert "switch the checkout from claude/redesign back to the default branch" in plan.sentence
    result = run(plan, tmp_path)
    assert result.state == "landed", result
    assert repo_tidy.current_branch(lab) == "main"
    assert (lab / "r.txt").exists() and (lab / "a.txt").read_text() == "edited, not committed"
    assert "claude/redesign" not in repo_tidy.local_branches(lab)
    assert repo_tidy.ahead_behind(lab) == (0, 0) and lr.open_items(lab) == []


def test_a_process_in_the_checkout_is_a_hard_stop_and_nothing_switches(lab, tmp_path,
                                                                        quarantine):
    sh(lab, "checkout", "-q", "-b", "wip")
    commit(lab, "w.txt")
    result = run(plan_for(lab, busy=(lab,)), tmp_path, busy=(lab,))
    assert result.state == "not_landed" and "a process is running in it" in result.reason
    assert repo_tidy.current_branch(lab) == "wip"


def test_a_process_in_a_nested_agent_worktree_does_not_block_the_main_checkout(lab, tmp_path,
                                                                              quarantine):
    make_branch(lab, "agent", "g.txt")
    wt = add_worktree(lab, "agent", lab / ".claude" / "worktrees" / "agent")
    (lab / ".gitignore").write_text("/.claude/\n")
    (lab / "loose.md").write_text("x")
    busy = (wt,)  # a session works in the agent worktree, nobody in the checkout
    steps, stops = lr.prep("repo", lab, busy)
    assert not [s for s in stops if s.target == str(lab)]
    assert any(s.kind == "untracked" and s.target == str(lab) for s in steps)
    assert lr.in_own_tree(repo_tidy.worktrees(lab)[1], repo_tidy.worktrees(lab), busy)


def test_a_paused_rebase_is_a_hard_stop(lab, tmp_path, quarantine):
    gitdir = lab / ".git"
    (gitdir / "rebase-merge").mkdir()
    (lab / "a.txt").write_text("y")
    result = run(plan_for(lab), tmp_path)
    assert result.state == "not_landed" and "a rebase is in progress" in result.reason


# ------------------------------------------------------------ 4.4 detached HEAD
def test_a_detached_worktree_with_changes_is_rescued_and_landed(lab, tmp_path, quarantine):
    make_branch(lab, "base", "b.txt")
    wt = tmp_path / "wt"
    sh(lab, "worktree", "add", "-q", "--detach", str(wt), "base")
    (wt / "b.txt").write_text("changed while detached")
    result = run(plan_for(lab), tmp_path)
    assert result.state == "landed", result
    assert (lab / "b.txt").read_text() == "changed while detached"
    log = (tmp_path / "land.log").read_text()
    assert "RESCUED detached HEAD" in log
    assert lr.open_items(lab) == []


# ------------------------------------------------------------ 4.5 recent agent worktrees
def test_a_recent_agent_worktree_is_committed_in_and_merged(lab, tmp_path, quarantine):
    make_branch(lab, "agent", "g.txt")
    wt = add_worktree(lab, "agent", lab / ".claude" / "worktrees" / "agent")
    (lab / ".gitignore").write_text("/.claude/\n")
    sh(lab, "add", ".gitignore")
    sh(lab, "commit", "-qm", "ignore agent worktrees")
    sh(lab, "push", "-q")
    (wt / "g.txt").write_text("more work")
    (wt / "new.txt").write_text("new file")
    now = time.time()  # the worktree was just used
    result = run(plan_for(lab, now=now), tmp_path, now=now)
    assert result.state == "landed", result
    assert (lab / "new.txt").exists() and (lab / "g.txt").read_text() == "more work"
    assert wt.exists()  # removal still keeps the 24-hour rule
    assert lr.open_items(lab) == []


# ------------------------------------------------------------ 4.1 a link checked out as a file
@pytest.fixture
def link_root(tmp_path, monkeypatch):
    monkeypatch.setattr(lr, "LINK_ROOT", tmp_path)
    return tmp_path


def test_a_symlink_checked_out_as_a_file_is_followed_and_repaired(lab, tmp_path, quarantine,
                                                                    link_root):
    site = tmp_path / "site"
    sh(tmp_path, "init", "-q", "-b", "main", str(site))
    host = tmp_path / "host"
    sh(tmp_path, "init", "-q", "-b", "main", str(host))
    sh(host, "config", "user.name", "t")
    sh(host, "config", "user.email", "t@t")
    os.symlink("../site", host / "website")
    sh(host, "add", "website")
    sh(host, "commit", "-qm", "link")
    sh(host, "config", "core.symlinks", "false")
    (host / "website").unlink()
    sh(host, "checkout", "--", "website")
    assert (host / "website").is_file() and not (host / "website").is_symlink()
    assert lr.link_target(host / "website") == site.resolve()
    plan = land.make_plan("host/website", host / "website", claude=None, busy=(), now=OLD)
    assert plan.path == site.resolve() and plan.relinked == str(host / "website")
    assert "not a git checkout" not in plan.detail
    assert lr.repair_link(host / "website")
    assert (host / "website").is_symlink() and sh(host, "status", "--porcelain") == ""


def test_a_local_edit_to_the_link_file_is_never_overwritten(tmp_path):
    host = tmp_path / "host"
    (tmp_path / "site").mkdir()
    sh(tmp_path, "init", "-q", "-b", "main", str(host))
    os.symlink("../site", host / "website")
    sh(host, "add", "website")
    sh(host, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "link")
    (host / "website").unlink()
    (host / "website").write_text("../elsewhere")
    assert not lr.repair_link(host / "website")
    assert (host / "website").read_text() == "../elsewhere"


def test_a_path_that_is_no_repo_and_no_link_is_a_hard_stop(tmp_path):
    result = land.land(land.make_plan("x", tmp_path / "nope", claude=None, busy=(), now=OLD),
                       busy=(), now=OLD)
    assert result.state == "not_landed" and "not a git checkout" in result.reason


# ------------------------------------------------------------ 4.6 triage and archive
def conflicting(lab, name="feat"):
    make_branch(lab, name, "a.txt", "theirs")
    commit(lab, "a.txt", "ours")
    sh(lab, "push", "-q", "origin", "main")
    return repo_tidy.tip(lab, name)


def test_a_branch_claude_calls_stale_is_archived_as_a_tag_and_can_be_restored(
        lab, tmp_path, quarantine, monkeypatch):
    sha = conflicting(lab, "claude/old-idea")
    asked = fixed_verdict(monkeypatch, land_it=False)
    result = run(plan_for(lab, claude="/bin/false"), tmp_path)
    assert result.state == "landed" and result.archived == 1, result
    assert result.line == "Landed · 1 branch archived"
    assert asked and asked[0][0] == "claude/old-idea" and "conflicts" in asked[0][1]
    assert "claude/old-idea" not in repo_tidy.local_branches(lab)
    [item] = lr.archives([("repo", lab)])
    assert item.sha == sha and item.branch == "claude/old-idea"
    assert item.tag.startswith("archive/claude/old-idea/") and item.reason == "stale experiment"
    assert sh(lab, "ls-remote", "--tags", "origin") == ""  # never pushed
    assert lr.open_items(lab) == []
    ok, _ = lr.restore(item, tmp_path / "land.log")
    assert ok and repo_tidy.tip(lab, "claude/old-idea") == sha
    assert lr.archives([("repo", lab)]) == []


def test_a_branch_claude_would_land_but_that_fails_is_archived_with_why(
        lab, tmp_path, quarantine, monkeypatch):
    conflicting(lab)
    fixed_verdict(monkeypatch, land_it=True, reason="useful fix")
    real = repo_tidy.apply
    attempts = []

    def apply(action, *a, **kw):
        if action.kind == "claude_merge":
            attempts.append(action.target)
            return False, "not landed — the tests fail after the merge"
        return real(action, *a, **kw)

    monkeypatch.setattr(repo_tidy, "apply", apply)
    monkeypatch.setattr("lab_hub.claude_resolve.test_command",
                        lambda repo: type("C", (), {"display": "true", "note": "",
                                                    "source": "default"})())
    monkeypatch.setattr("lab_hub.claude_resolve.conflicted_files", lambda *a: ["a.txt"])
    monkeypatch.setattr("lab_hub.claude_resolve.timeout_note", lambda repo: "")
    result = run(plan_for(lab, claude="/bin/false"), tmp_path)
    assert attempts == ["feat"]  # tried once, never paid for twice at the same tip
    assert result.state == "landed" and result.archived == 1, result
    [item] = lr.archives([("repo", lab)])
    assert "could not be landed" in item.reason and "useful fix" in item.reason


def test_when_claude_cannot_decide_the_branch_is_untouched_and_it_is_a_hard_stop(
        lab, tmp_path, quarantine, monkeypatch):
    conflicting(lab)
    fixed_verdict(monkeypatch, land_it=False, reason="Claude Code failed: not signed in", ok=False)
    result = run(plan_for(lab, claude="/bin/false"), tmp_path)
    assert result.state == "not_landed" and "could not decide" in result.reason
    assert "feat" in repo_tidy.local_branches(lab) and lr.archives([("repo", lab)]) == []


def test_archive_refuses_a_branch_that_moved(lab, tmp_path):
    conflicting(lab)
    [info] = repo_tidy.unlanded([("repo", lab)])
    sh(lab, "checkout", "-q", "feat")
    commit(lab, "later.txt")
    sh(lab, "checkout", "-q", "main")
    ok, msg = lr.archive(info, "stale", tmp_path / "log", busy=())
    assert not ok and "moved" in msg and "feat" in repo_tidy.local_branches(lab)


def test_an_archived_branch_in_a_recent_worktree_is_detached_not_removed(lab, tmp_path):
    conflicting(lab)
    wt = add_worktree(lab, "feat", lab / ".claude" / "worktrees" / "feat")
    [info] = repo_tidy.unlanded([("repo", lab)])
    ok, msg = lr.archive(info, "stale", tmp_path / "log", busy=(), now=time.time())
    assert ok, msg
    assert wt.exists() and repo_tidy.current_branch(wt) == ""
    assert sh(wt, "rev-parse", "HEAD") == info.sha


def test_archive_tags_never_collide(lab):
    conflicting(lab)
    first = lr.archive_tag(lab, "feat")
    sh(lab, "tag", first, "HEAD")
    assert lr.archive_tag(lab, "feat") == first + "-2"


@pytest.mark.parametrize("text, expected", [
    ("thinking…\nVERDICT: land — still needed", ("land", "still needed")),
    ("VERDICT: archive: superseded by #12", ("archive", "superseded by #12")),
    ("`VERDICT: ARCHIVE — old`", ("archive", "old")),
    ("I think land.\nNo verdict here", None),
])
def test_parse_verdict(text, expected):
    assert lr.parse_verdict(text) == expected


def test_the_triage_run_is_read_only_and_sees_only_the_diff_folder(lab, monkeypatch):
    from lab_hub import claude_resolve as cr

    conflicting(lab)
    [info] = repo_tidy.unlanded([("repo", lab)])
    seen = {}

    def fake(exe, prompt, cwd, budget, stop, progress, tools=cr.TOOLS):
        seen.update(tools=tools, files=sorted(p.name for p in cwd.iterdir()), budget=budget,
                    diff=(cwd / "diff.txt").read_text())
        return cr.ClaudeResult(True, "ok", 0.02, 1, "VERDICT: archive — stale")

    monkeypatch.setattr(cr, "run_claude", fake)
    v = lr.verdict(info, "/bin/claude", "it conflicts")
    assert v.ok and not v.land and v.reason == "stale"
    assert seen["tools"] == "Read,Grep,Glob" and "Edit" not in seen["tools"]
    assert seen["files"] == ["diff.txt", "log.txt", "stat.txt"]
    assert seen["budget"] == lr.TRIAGE_BUDGET_USD and "theirs" in seen["diff"]
    assert "--tools" in (argv := cr.claude_argv("c", "p", 1.0, lr.TRIAGE_TOOLS))
    assert argv[argv.index("--tools") + 1] == "Read,Grep,Glob"


# ------------------------------------------------------------ the whole thing
@needs_gitleaks
def test_a_lab_with_every_kind_of_open_item_ends_with_nothing_open(lab, tmp_path, quarantine,
                                                                     monkeypatch):
    fixed_verdict(monkeypatch, land_it=False)
    conflicting(lab, "old")  # cannot land: archived
    make_branch(lab, "clean", "c.txt")  # merges
    wt = tmp_path / "agent"
    add_worktree(lab, "clean", wt)
    (wt / "log.jsonl").write_text("{}\n")  # untracked in a worktree
    (wt / "secret.env").write_text(f"T={GITHUB_PAT}\n")
    sh(lab, "checkout", "-q", "-b", "side")  # checkout on a side branch
    commit(lab, "s.txt")
    (lab / "loose.md").write_text("loose")
    result = run(plan_for(lab, claude="/bin/false"), tmp_path)
    assert result.state == "landed", result
    assert lr.open_items(lab) == []
    assert repo_tidy.local_branches(lab) == ["main"]
    for name in ("c.txt", "s.txt", "loose.md", "log.jsonl"):
        assert (lab / name).exists(), name
    assert any(m.endswith("secret.env") for m in quarantined_files(quarantine))
    assert repo_tidy.ahead_behind(lab) == (0, 0)  # pushed after triage (QA q)


# ------------------------------------------------------------ security review fixes
def link_host(tmp_path, target: str):
    host = tmp_path / "host"
    sh(tmp_path, "init", "-q", "-b", "main", str(host))
    os.symlink(target, host / "website")
    sh(host, "add", "website")
    sh(host, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "link")
    sh(host, "config", "core.symlinks", "false")
    (host / "website").unlink()
    sh(host, "checkout", "--", "website")
    return host


def test_a_link_outside_the_lab_or_edited_locally_is_not_followed(tmp_path, monkeypatch):
    (tmp_path / "lab" / "site").mkdir(parents=True)
    (tmp_path / "outside").mkdir()
    monkeypatch.setattr(lr, "LINK_ROOT", tmp_path / "lab")
    host = link_host(tmp_path, "../outside")
    assert lr.link_target(host / "website") is None  # P2-3: outside the lab
    (host / "website").write_text("../lab/site")  # a local edit, not git's link
    assert lr.link_target(host / "website") is None


@needs_gitleaks
@pytest.mark.parametrize("name", ["package-lock.json", "photo.png"])
def test_gitleaks_path_allowlist_cannot_skip_a_file(lab, tmp_path, quarantine, name):
    head = b"\x89PNG\r\n\x1a\n\0\0" if name.endswith(".png") else b""
    (lab / name).write_bytes(head + f'"token": "{GITHUB_PAT}"\n'.encode())
    run(plan_for(lab), tmp_path)
    assert name not in sh(lab, "ls-files")
    assert any(m.endswith(name) for m in quarantined_files(quarantine))


def test_a_binary_the_scan_cannot_read_is_quarantined(lab, monkeypatch):
    monkeypatch.setattr(lr, "scan", lambda wt, paths: ({}, {p: "0" * 40 for p in paths}, ""))
    (lab / "app.sqlite").write_bytes(b"SQLite format 3\0" + b"\0" * 100)
    (lab / "backup.zip").write_bytes(b"PK\x03\x04\0\0" + b"x" * 50)
    (lab / "pic.png").write_bytes(b"\x89PNG\r\n\x1a\n\0\0")
    sorted_ = lr.sort_untracked(lab)
    assert {p for p, _ in sorted_.quarantine} == {"app.sqlite", "backup.zip"}
    assert sorted_.commit == ("pic.png",)


@needs_gitleaks
def test_a_finding_lab_hub_cannot_place_fails_closed(lab, monkeypatch):
    monkeypatch.setattr(lr, "_run_gitleaks",
                        lambda args, tmp: ([{"File": "/elsewhere/x", "RuleID": "r"}], ""))
    (lab / "n.txt").write_text("x")
    assert "cannot place" in lr.sort_untracked(lab).error


@needs_gitleaks
def test_a_file_changed_after_the_scan_is_not_committed(lab, tmp_path, quarantine, monkeypatch):
    (lab / "notes.md").write_text("clean\n")
    real = lr.sort_untracked
    calls = []

    def then_change(wt):
        result = real(wt)
        calls.append(wt)
        if len(calls) == 3:  # preview, prep, then the scan right before `git add`
            (wt / "notes.md").write_text(f"T={GITHUB_PAT}\n")
        return result

    monkeypatch.setattr(lr, "sort_untracked", then_change)
    head = sh(lab, "rev-parse", "HEAD")
    result = run(plan_for(lab), tmp_path)
    assert result.state == "not_landed" and "changed after the secret scan" in result.reason
    assert sh(lab, "rev-parse", "HEAD") == head and sh(lab, "diff", "--cached") == ""


def test_a_name_with_a_line_break_never_writes_a_gitignore_line(lab, tmp_path, quarantine,
                                                                 monkeypatch):
    monkeypatch.setattr(lr, "scan", lambda wt, paths: ({}, {}, ""))
    (lab / "credentials\n!config.json").write_text("k")
    ok, _ = lr.apply_step(lr.Step("repo", lab, "untracked", str(lab)), tmp_path / "log", busy=())
    assert ok
    gi = lab / ".gitignore"
    assert not gi.exists() or "!config.json" not in gi.read_text()
    assert not (lab / "credentials\n!config.json").exists()  # moved to quarantine


def test_a_symlinked_gitignore_is_never_written_through(lab, tmp_path, quarantine, monkeypatch):
    monkeypatch.setattr(lr, "scan", lambda wt, paths: ({}, {}, ""))
    outside = tmp_path / "outside.txt"
    outside.write_text("keep\n")
    os.symlink(outside, lab / ".gitignore")
    sh(lab, "add", ".gitignore")
    sh(lab, "commit", "-qm", "link")
    (lab / ".env").write_text("A=1")
    ok, msg = lr.apply_step(lr.Step("repo", lab, "untracked", str(lab)), tmp_path / "log", busy=())
    assert not ok and "not a regular file" in msg
    assert outside.read_text() == "keep\n"


@needs_gitleaks
def test_a_secret_in_a_tracked_edit_is_never_pushed(lab, tmp_path, quarantine):
    (lab / "a.txt").write_text(f'TOKEN = "{GITHUB_PAT}"\n')  # a tracked file, not untracked
    result = run(plan_for(lab), tmp_path)
    assert result.state == "not_landed" and "gitleaks found a secret" in result.reason
    assert GITHUB_PAT not in sh(tmp_path / "origin.git", "log", "--all", "-p")


@needs_gitleaks
def test_archive_tags_are_never_pushed_even_with_follow_tags(lab, tmp_path, quarantine,
                                                             monkeypatch):
    sh(lab, "config", "push.followTags", "true")
    sh(lab, "tag", "-a", "-m", "x", "archive/old/2026-11-17", "HEAD")
    commit(lab, "more.txt")
    result = run(plan_for(lab), tmp_path)
    assert result.state == "landed", result
    assert sh(lab, "ls-remote", "--tags", "origin") == ""


# ------------------------------------------------------------ QA gaps and review fixes
@needs_gitleaks
def test_a_file_that_appears_after_the_preview_is_not_committed_and_land_says_not_landed(
        lab, tmp_path, quarantine):
    (lab / "shown.md").write_text("listed in the preview")
    plan = plan_for(lab)
    (lab / "late.md").write_text("appeared after the confirmation")
    result = run(plan, tmp_path)
    tracked = sh(lab, "ls-files")
    assert "shown.md" in tracked and "late.md" not in tracked  # review P2-3
    # Nothing stopped Land, but something is still open: never "Landed" (QA f).
    assert result.state == "not_landed" and "untracked" in result.reason


def fake_gitleaks(tmp_path, monkeypatch, body: str) -> None:
    exe = tmp_path / "gitleaks"
    exe.write_text("#!/bin/sh\n" + body + "\n")
    exe.chmod(0o755)
    monkeypatch.setattr(lr, "gitleaks_exe", lambda: str(exe))


@pytest.mark.parametrize("body, why", [
    ("echo boom >&2; exit 2", "gitleaks failed"),  # QA k
    ('for a; do last="$p"; p="$a"; done; echo "not json" > "$p"; exit 0', "no readable report"),
])
def test_gitleaks_failing_is_a_hard_stop_and_nothing_is_committed(lab, tmp_path, quarantine,
                                                                   monkeypatch, body, why):
    fake_gitleaks(tmp_path, monkeypatch, body)
    (lab / "notes.md").write_text("x")
    head = sh(lab, "rev-parse", "HEAD")
    result = run(plan_for(lab), tmp_path)
    assert result.state == "not_landed" and why in result.reason
    assert sh(lab, "rev-parse", "HEAD") == head and (lab / "notes.md").exists()


def test_a_reply_without_a_verdict_line_never_archives(lab, monkeypatch):
    from lab_hub import claude_resolve as cr

    conflicting(lab)
    [info] = repo_tidy.unlanded([("repo", lab)])
    monkeypatch.setattr(cr, "run_claude", lambda *a, **k: cr.ClaudeResult(
        True, "ok", 0.01, 1, "I would archive this, probably."))
    v = lr.verdict(info, "/bin/claude", "it conflicts")
    assert not v.ok and "no VERDICT" in v.reason  # QA m


def test_apply_step_rechecks_its_guard(lab, tmp_path, quarantine):
    (lab / "loose.md").write_text("x")
    steps, _ = lr.prep("repo", lab, ())
    [step] = steps
    ok, msg = lr.apply_step(step, tmp_path / "log", busy=(lab,))  # QA n
    assert not ok and "a process is running" in msg
    assert "loose.md" not in sh(lab, "ls-files")


def test_a_clean_detached_head_on_no_branch_is_rescued(lab, tmp_path):
    wt = tmp_path / "wt"
    sh(lab, "worktree", "add", "-q", "--detach", str(wt), "main")
    commit(wt, "orphan.txt")  # clean afterwards, but no branch holds it
    steps, _ = lr.prep("repo", lab, ())
    assert [s.kind for s in steps] == ["rescue"]  # QA o
    assert "put 1 detached HEAD on a rescue branch" in plan_for(lab).sentence  # measure 5


def test_archive_refuses_a_branch_whose_worktree_has_work(lab, tmp_path):
    conflicting(lab)
    wt = add_worktree(lab, "feat", tmp_path / "wt")
    (wt / "wip.txt").write_text("unsaved")
    [info] = repo_tidy.unlanded([("repo", lab)])
    ok, msg = lr.archive(info, "stale", tmp_path / "log", busy=())
    assert not ok and "uncommitted or untracked" in msg  # QA p
    assert "feat" in repo_tidy.local_branches(lab) and lr.archives([("repo", lab)]) == []


def test_open_items_counts_unpushed_and_behind(lab, tmp_path):
    assert lr.open_items(lab) == []
    commit(lab, "ahead.txt")
    assert any("1 ahead" in item for item in lr.open_items(lab))  # QA r


def test_restore_refuses_a_tag_that_moved(lab, tmp_path):
    conflicting(lab)
    [info] = repo_tidy.unlanded([("repo", lab)])
    assert lr.archive(info, "stale", tmp_path / "log", busy=())[0]
    [item] = lr.archives([("repo", lab)])
    sh(lab, "tag", "-f", "-a", "-m", "moved", item.tag, "main")
    ok, msg = lr.restore(item)
    assert not ok and "changed" in msg and not repo_tidy.tip(lab, "feat")  # QA t


def test_the_notice_prices_every_branch_that_may_reach_claude(lab, monkeypatch):
    from lab_hub import claude_resolve as cr

    conflicting(lab)
    plan = plan_for(lab, claude="/bin/false")
    notice = plan.claude_notice
    assert "archive/<branch>/<date>" in notice and "never pushed" in notice  # measure 5
    assert plan.with_claude == 0 or "will be sent" in notice
    blocked = land.LandPlan("r", lab, (), (), "/bin/claude", unlanded=3)
    text = blocked.claude_notice
    assert "up to 3 branches may be sent" in text  # review P1-2
    assert f"${3 * cr.BUDGET_USD:.0f} in total" in text


def test_an_archived_branch_does_not_come_back_on_the_next_land(lab, tmp_path, quarantine,
                                                                monkeypatch):
    conflicting(lab)
    wt = add_worktree(lab, "feat", lab / ".claude" / "worktrees" / "feat")
    (lab / ".gitignore").write_text("/.claude/\n")
    sh(lab, "add", ".gitignore")
    sh(lab, "commit", "-qm", "ignore")
    sh(lab, "push", "-q")
    asked = fixed_verdict(monkeypatch, land_it=False)
    now = time.time()  # recent: the worktree is detached, not removed
    first = run(plan_for(lab, claude="/bin/false", now=now), tmp_path, now=now)
    assert first.state == "landed" and first.archived == 1, first
    assert repo_tidy.current_branch(wt) == ""
    second = run(plan_for(lab, claude="/bin/false", now=now), tmp_path, now=now)
    assert second.state in ("nothing", "landed") and second.archived == 0  # review P1-1
    assert len(asked) == 1 and len(lr.archives([("repo", lab)])) == 1


def test_a_restored_branch_is_kept_and_not_archived_again(lab, tmp_path, quarantine,
                                                          monkeypatch):
    conflicting(lab)
    asked = fixed_verdict(monkeypatch, land_it=False)
    run(plan_for(lab, claude="/bin/false"), tmp_path)
    [item] = lr.archives([("repo", lab)])
    assert lr.restore(item)[0]
    again = run(plan_for(lab, claude="/bin/false"), tmp_path)
    assert len(asked) == 1 and "feat" in repo_tidy.local_branches(lab)  # review P2-5
    assert again.state in ("nothing", "landed") and lr.open_items(lab) == []


def test_a_refused_push_is_tried_once_per_land(lab, tmp_path, quarantine, monkeypatch):
    calls = []
    monkeypatch.setattr(lr, "outgoing_findings",
                        lambda repo, d: calls.append(d) or (["x.py (rule) in abc"], ""))
    make_branch(lab, "feat", "f.txt")
    result = run(plan_for(lab), tmp_path)
    assert result.state == "not_landed" and "gitleaks found a secret" in result.reason
    assert len(calls) == 1  # review P2-6


def test_who_is_in_names_the_process(lab):
    import subprocess

    proc = subprocess.Popen(["sleep", "30"], cwd=lab)
    try:
        trees = repo_tidy.worktrees(lab)
        deadline = time.time() + 5
        who = ""
        while time.time() < deadline and "sleep" not in who:
            who = lr.who_is_in(trees[0], trees)
        assert f"sleep (pid {proc.pid})" in who  # review P2-4
    finally:
        proc.kill()


def test_a_branch_landed_on_claudes_verdict_is_pushed(lab, tmp_path, quarantine, monkeypatch):
    # QA run 2, survivor q: the last round pushes what triage landed.
    make_branch(lab, "feat", "f.txt")
    monkeypatch.setattr(land, "ROUNDS", 0)  # nothing merges before triage
    fixed_verdict(monkeypatch, land_it=True, reason="still needed")
    result = run(plan_for(lab, claude="/bin/false"), tmp_path)
    assert result.state == "landed", result
    assert (lab / "f.txt").exists() and repo_tidy.ahead_behind(lab) == (0, 0)
    assert any("landed on Claude's verdict" in n for n in result.notes)


def test_each_prep_step_says_what_it_will_do():
    from pathlib import Path

    rescue = lr.Step("r", Path("/x"), "rescue", "/x/wt", "at 1234abcd, work no branch holds")
    switch = lr.Step("r", Path("/x"), "switch", "/x", "claude/side")
    loose = lr.Step("r", Path("/x"), "untracked", "/x", files=("a.md",),
                    quarantine=((".env", "a secret by its name"),), ignored=("sub/",))
    assert "on a new branch lab-hub/rescue-" in rescue.label
    assert "Commit open work on claude/side and switch the checkout" in switch.label
    assert loose.label == ("r: In /x, commit 1 untracked file: a.md; move to quarantine and "
                           "ignore: .env (a secret by its name); ignore nested repos: sub/")


def test_one_lsof_run_serves_every_busy_worktree_of_a_repo(lab, monkeypatch):
    """Security review P3-3 (land-confirm-dialog): one reading per repo plan, not per stop."""
    make_branch(lab, "agent", "g.txt")
    wt = add_worktree(lab, "agent", lab / ".claude" / "worktrees" / "agent")
    (lab / ".gitignore").write_text("/.claude/\n")
    (wt / "loose.md").write_text("x")
    sh(lab, "checkout", "-q", "-b", "wip")
    commit(lab, "w.txt")
    calls = []
    fake = [("zsh", "1", lab), ("claude", "2", wt)]
    monkeypatch.setattr(lr, "cwd_listing", lambda: calls.append(1) or fake)
    _, stops = lr.prep("repo", lab, (lab, wt))
    by_target = {s.target: s.processes for s in stops}
    assert by_target == {str(lab): ("zsh (pid 1)",), str(wt): ("claude (pid 2)",)}
    assert len(calls) == 1


def test_a_process_name_is_made_safe_to_show():
    """Security review P3-1 (land-confirm-dialog)."""
    assert lr._shown_name("zsh") == "zsh"
    assert lr._shown_name("evil\nnext\x1b[31m") == "evil?next?[31m"
    long = lr._shown_name("x" * 100)
    assert len(long) == lr.NAME_MAX and long.endswith("…")
