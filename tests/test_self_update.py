"""Lab Hub updates itself (spec docs/specs/self-update.md, ADR 0003, ADR 0006).

The helper is the real bash script, run against fixture bundles in tmp_path:
nothing here touches /Applications or the real support folder, and `open` is
a shim (the `OPEN` constant) that records what it was asked to open.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from lab_hub import launcher, progress, self_update


# -- fixtures -----------------------------------------------------------------
def _bundle(where: Path, marker: str, selftest: str = "exit 0", commit: str = "") -> Path:
    """A fake `Lab Hub.app` whose executable runs `selftest` for --selftest."""
    app = where / "Lab Hub.app"
    macos = app / "Contents" / "MacOS"
    macos.mkdir(parents=True)
    exe = macos / "Lab Hub"
    exe.write_text(f"#!/bin/sh\n{selftest}\n")
    exe.chmod(0o755)
    (app / "Contents" / "marker").write_text(marker)
    if commit:
        resources = app / "Contents" / "Resources"
        resources.mkdir()
        (resources / "_build_info.json").write_text(
            json.dumps({"major": "2", "build": 180, "commit": commit}))
    return app


def _marker(app: Path) -> str:
    return (app / "Contents" / "marker").read_text()


@pytest.fixture
def lab(tmp_path, monkeypatch):
    applications = tmp_path / "Applications"
    applications.mkdir()
    update = tmp_path / "support" / "update"
    opened = tmp_path / "opened"
    shim = tmp_path / "open-shim"
    shim.write_text(f'#!/bin/sh\necho "$@" >> {opened}\n')
    shim.chmod(0o755)
    monkeypatch.setattr(self_update, "APPLICATIONS", applications)
    monkeypatch.setattr(self_update, "UPDATE_DIR", update)
    monkeypatch.setattr(self_update, "OPEN", str(shim))
    monkeypatch.setattr(self_update, "WAIT_S", 2)
    monkeypatch.setattr(self_update, "LATE_WAIT_S", 3)
    monkeypatch.setattr(self_update, "SELFTEST_S", 2)
    target = _bundle(applications, "old")
    return {"target": target, "opened": opened, "update": update}


def _stage(lab, marker: str = "new", selftest: str = "exit 0") -> self_update.Staged:
    """A build already copied out of the checkout, as `stage_build` leaves it."""
    staged = self_update.staged_bundle()
    staged.parent.mkdir(parents=True, exist_ok=True)
    _bundle(staged.parent, marker, selftest)
    return self_update.Staged(staged, "v2.180", "abc1234")


def _orphan(seconds: int) -> int:
    """A process that is not our child, so the system reaps it when it ends
    (as it does Lab Hub); a child of ours would linger as a zombie."""
    out = subprocess.run(["/bin/sh", "-c", f"/bin/sleep {seconds} >/dev/null 2>&1 & echo $!"],
                         capture_output=True, text=True, check=True)
    return int(out.stdout.strip())


def _gone_pid() -> int:
    proc = subprocess.Popen(["/usr/bin/true"])
    proc.wait()
    return proc.pid


def _run(lab, staged, pid: int | None = None) -> self_update.HelperPaths:
    paths = self_update.helper_paths(staged, running=lab["target"], pid=pid or _gone_pid())
    self_update.start_helper(paths).wait(timeout=60)
    return paths


def _opened(lab) -> list[str]:
    try:
        return lab["opened"].read_text().splitlines()
    except FileNotFoundError:
        return []


def _outcome(lab) -> self_update.Outcome:
    outcome = self_update.read_outcome(lab["update"])
    assert outcome is not None
    return outcome


def _raw(lab, src, target, backup, pid=None, numbers=("2", "3", "2")) -> str:
    """Run the script directly with hand-made values; returns the outcome token."""
    lab["update"].mkdir(parents=True, exist_ok=True)
    outcome = lab["update"] / "outcome"
    subprocess.run(
        ["/bin/bash", "-c", self_update.HELPER_SCRIPT, "t", str(pid or _gone_pid()),
         str(src), str(target), str(backup), str(outcome), "v2.180",
         self_update.OPEN, *numbers],
        env=self_update.helper_env(), check=False, timeout=60)
    return outcome.read_text().splitlines()[0]


# -- the helper -----------------------------------------------------------------
def test_the_helper_installs_the_new_build_keeps_the_old_and_opens_it(lab):
    staged = _stage(lab)
    paths = _run(lab, staged)
    assert _marker(lab["target"]) == "new"
    assert _marker(paths.backup) == "old"
    assert not staged.bundle.exists()  # the staged copy is cleared
    assert not Path(f"{lab['target']}.updating").exists()
    assert _opened(lab) == [str(lab["target"])]
    outcome = _outcome(lab)
    assert outcome.ok and outcome.version == "v2.180"
    assert "waiting for Lab Hub" in paths.log.read_text()
    assert paths.log.stat().st_mode & 0o777 == 0o600
    assert not (lab["update"] / "lock").exists()


def test_a_build_that_fails_its_installed_selftest_is_rolled_back(lab):
    staged = _stage(lab, selftest="exit 1")
    _run(lab, staged)
    assert _marker(lab["target"]) == "old"
    assert (lab["target"] / "Contents" / "MacOS" / "Lab Hub").is_file()
    assert _opened(lab) == [str(lab["target"])]
    outcome = _outcome(lab)
    assert outcome.token == "rolled_back" and "self-test" in outcome.message
    # The failed build is not kept in staged/ (real-Mac check 2026-11-20, P3).
    assert not staged.bundle.exists()


def test_a_selftest_that_hangs_is_stopped_and_rolled_back(lab):
    _run(lab, _stage(lab, selftest="sleep 30"))
    assert _marker(lab["target"]) == "old"
    assert _outcome(lab).token == "rolled_back"


def test_a_failed_new_build_with_no_previous_build_opens_nothing(lab):
    import shutil

    shutil.rmtree(lab["target"])
    staged = _stage(lab, selftest="exit 1")
    _run(lab, staged)
    assert not lab["target"].exists()
    assert _opened(lab) == []
    assert _outcome(lab).token == "broken"
    assert not staged.bundle.exists()


def test_a_previous_build_that_cannot_be_cleared_means_nothing_is_replaced(lab):
    """Review P1-1 scenario A: the old kept build would have nested the app."""
    stuck = _bundle(lab["update"] / "previous", "older") / "Contents" / "locked"
    stuck.mkdir()
    (stuck / "f").write_text("x")
    stuck.chmod(0o500)
    try:
        _run(lab, _stage(lab))
    finally:
        stuck.chmod(0o700)
    assert _marker(lab["target"]) == "old"
    assert not (lab["target"] / "Lab Hub.app").exists()
    assert _outcome(lab).token == "not_replaced"
    assert _opened(lab) == [str(lab["target"])]


def test_a_failed_build_that_cannot_be_removed_is_reported_broken_not_restored(lab):
    """Review P1-1 scenario B: no false "the previous build is back"."""
    staged = _stage(lab, selftest="exit 1")
    stuck = staged.bundle / "Contents" / "locked"
    stuck.mkdir()
    (stuck / "f").write_text("x")
    stuck.chmod(0o500)
    try:
        paths = _run(lab, staged)
    finally:
        for folder in (stuck, lab["target"] / "Contents" / "locked"):
            if folder.exists():
                folder.chmod(0o700)
    outcome = _outcome(lab)
    assert outcome.token == "broken"
    assert str(paths.backup) in outcome.message
    assert _marker(paths.backup) == "old"  # still there, named in the notice
    assert not (lab["target"] / "Lab Hub.app").exists()
    assert _opened(lab) == []


def test_a_staging_folder_that_cannot_be_cleared_means_nothing_is_replaced(lab):
    """QA N2: a stale `.updating` folder must not be merged into a mixed bundle."""
    stale = Path(f"{lab['target']}.updating")
    stuck = stale / "Contents" / "locked"
    stuck.mkdir(parents=True)
    (stuck / "f").write_text("x")
    stuck.chmod(0o500)
    try:
        _run(lab, _stage(lab))
    finally:
        stuck.chmod(0o700)
    assert _marker(lab["target"]) == "old"
    assert not (stale / "Contents" / "marker").exists()  # nothing copied into it
    assert _outcome(lab).token == "not_replaced"


def _stop_helper_while(lab, staged, pid: int) -> self_update.HelperPaths:
    """Start the helper and stop it with SIGTERM while it waits on `pid`."""
    import signal
    import time

    paths = self_update.helper_paths(staged, running=lab["target"], pid=pid)
    proc = self_update.start_helper(paths)
    deadline = time.monotonic() + 10
    while "waiting for Lab Hub" not in paths.log.read_text() and time.monotonic() < deadline:
        time.sleep(0.05)
    proc.send_signal(signal.SIGTERM)
    proc.wait(timeout=10)
    return paths


def test_a_helper_stopped_before_the_swap_says_nothing_was_replaced(lab):
    """QA N10: the EXIT trap writes an outcome when the script is stopped."""
    alive = subprocess.Popen(["/bin/sleep", "30"])
    try:
        _stop_helper_while(lab, _stage(lab), alive.pid)
    finally:
        alive.kill()
        alive.wait()
    outcome = _outcome(lab)
    assert outcome.token == "not_replaced" and "before anything" in outcome.message
    assert _marker(lab["target"]) == "old"
    assert not (lab["update"] / "lock").exists()


def test_a_helper_stopped_during_the_swap_says_broken_and_names_the_previous_build(lab):
    """The trap's other branch: once the swap began, an early stop is `broken`."""
    lab["update"].mkdir(parents=True, exist_ok=True)
    outcome = lab["update"] / "outcome"
    backup = lab["update"] / "previous" / "Lab Hub.app"
    # The new build's self-test sends SIGTERM to the helper (its parent) mid-swap.
    staged = _stage(lab, selftest='kill -TERM "$PPID"; sleep 5')
    subprocess.run(
        ["/bin/bash", "-c", self_update.HELPER_SCRIPT, "t", str(_gone_pid()),
         str(staged.bundle), str(lab["target"]), str(backup), str(outcome), "v2.180",
         self_update.OPEN, "2", "3", "5"],
        env=self_update.helper_env(), check=False, timeout=60)
    lines = outcome.read_text().splitlines()
    assert lines[0] == "broken" and str(backup) in lines[1]
    assert _marker(backup) == "old"


def test_an_old_lab_hub_that_never_quits_means_nothing_is_replaced(lab):
    alive = subprocess.Popen(["/bin/sleep", "30"])
    try:
        _run(lab, _stage(lab), pid=alive.pid)
    finally:
        alive.kill()
        alive.wait()
    assert _marker(lab["target"]) == "old"
    assert _opened(lab) == []  # the old copy was still the one running
    assert _outcome(lab).token == "not_replaced"


def test_an_old_lab_hub_that_quits_late_is_opened_again(lab):
    _run(lab, _stage(lab), pid=_orphan(3))
    assert _marker(lab["target"]) == "old"
    assert _outcome(lab).token == "not_replaced"
    assert _opened(lab) == [str(lab["target"])]


def test_a_second_helper_is_turned_away_while_one_runs(lab):
    lab["update"].mkdir(parents=True)
    (lab["update"] / "lock").mkdir()
    holder = subprocess.Popen(["/bin/sleep", "30"])
    try:
        (lab["update"] / "lock" / "pid").write_text(str(holder.pid))
        _run(lab, _stage(lab))
    finally:
        holder.kill()
        holder.wait()
    assert _marker(lab["target"]) == "old"
    assert "another update" in _outcome(lab).message


def test_a_stale_lock_is_taken_over(lab):
    lab["update"].mkdir(parents=True)
    (lab["update"] / "lock").mkdir()
    (lab["update"] / "lock" / "pid").write_text(str(_gone_pid()))
    _run(lab, _stage(lab))
    assert _marker(lab["target"]) == "new"


def test_a_second_update_replaces_the_kept_previous_build(lab):
    paths = _run(lab, _stage(lab, "v1"))
    _run(lab, _stage(lab, "v2"))
    assert _marker(lab["target"]) == "v2"
    assert _marker(paths.backup) == "v1"


@pytest.mark.parametrize("which", ["target", "backup", "src"])
def test_the_helper_refuses_a_path_that_is_not_a_lab_hub_app(lab, tmp_path, which):
    src = _stage(lab).bundle
    other = tmp_path / "Other.app"
    other.mkdir()
    values = {"src": src, "target": lab["target"],
              "backup": lab["update"] / "previous" / "Lab Hub.app"}
    values[which] = other
    assert _raw(lab, values["src"], values["target"], values["backup"]) == "not_replaced"
    assert _marker(lab["target"]) == "old" and not any(other.iterdir())
    assert _opened(lab) == []


def test_the_helper_refuses_a_symlinked_or_identical_new_build(lab, tmp_path):
    backup = lab["update"] / "previous" / "Lab Hub.app"
    assert _raw(lab, lab["target"], lab["target"], backup) == "not_replaced"
    link_parent = tmp_path / "link"
    link_parent.mkdir()
    (link_parent / "Lab Hub.app").symlink_to(lab["target"])
    assert _raw(lab, link_parent / "Lab Hub.app", lab["target"], backup) == "not_replaced"
    assert _marker(lab["target"]) == "old"


def test_the_helper_refuses_a_new_build_with_no_executable(lab):
    src = self_update.staged_bundle()
    (src / "Contents" / "MacOS").mkdir(parents=True)
    backup = lab["update"] / "previous" / "Lab Hub.app"
    assert _raw(lab, src, lab["target"], backup) == "not_replaced"
    assert _marker(lab["target"]) == "old"


def test_the_helper_refuses_numbers_that_are_not_numbers(lab, tmp_path):
    backup = lab["update"] / "previous" / "Lab Hub.app"
    src = _stage(lab).bundle
    token = _raw(lab, src, lab["target"], backup,
                 numbers=(f"PATH[$(touch {tmp_path}/pwned)0]", "3", "2"))
    assert token == "not_replaced"
    assert _marker(lab["target"]) == "old" and not (tmp_path / "pwned").exists()


def test_the_helper_takes_its_values_as_parameters_never_in_its_text():
    assert "$1" in self_update.HELPER_SCRIPT and "${10}" in self_update.HELPER_SCRIPT
    stripped = self_update.HELPER_SCRIPT.replace("${", "").replace("() {", "")
    assert "{" not in stripped.replace("|| {", "")


def test_the_helper_gets_a_fixed_environment(monkeypatch):
    monkeypatch.setenv("BASH_ENV", "/tmp/x")
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    env = self_update.helper_env()
    assert env["PATH"] == "/usr/bin:/bin:/usr/sbin:/sbin"
    assert "BASH_ENV" not in env and "OPENAI_API_KEY" not in env


# -- the paths Lab Hub hands over ---------------------------------------------
def test_helper_paths_refuse_a_source_run_another_copy_and_a_missing_build(lab, tmp_path):
    staged = self_update.Staged(self_update.staged_bundle(), "v2.180", "abc")
    with pytest.raises(ValueError, match="source"):
        self_update.helper_paths(staged, running=None)
    elsewhere = _bundle(tmp_path / "elsewhere", "x")
    with pytest.raises(ValueError, match="not"):
        self_update.helper_paths(staged, running=elsewhere)
    with pytest.raises(ValueError, match="no new build"):
        self_update.helper_paths(staged, running=lab["target"])


def test_helper_paths_take_only_the_staged_copy(lab, tmp_path):
    other = self_update.Staged(_bundle(tmp_path / "dist.noindex", "x"), "v2.180", "abc")
    with pytest.raises(ValueError, match="staged copy"):
        self_update.helper_paths(other, running=lab["target"])


def test_helper_paths_put_everything_but_the_swap_under_the_update_folder(lab):
    paths = self_update.helper_paths(_stage(lab), running=lab["target"], pid=42)
    assert paths.pid == 42 and paths.target == lab["target"]
    for path in (paths.src, paths.backup, paths.log, paths.outcome):
        assert lab["update"] in path.parents
    assert paths.backup.name == "Lab Hub.app" and paths.version == "v2.180"


def test_the_running_bundle_is_the_app_around_the_executable(tmp_path):
    app = _bundle(tmp_path, "x")
    exe = app / "Contents" / "MacOS" / "Lab Hub"
    assert self_update.running_bundle(str(exe), frozen=True) == app.resolve()
    assert self_update.running_bundle(str(exe), frozen=False) is None


# -- the outcome after the restart --------------------------------------------
def test_the_outcome_is_read_once(tmp_path):
    (tmp_path / "outcome").write_text("ok\ninstalled and self-tested\nv2.180\n")
    first = self_update.read_outcome(tmp_path)
    assert first is not None and first.ok
    assert self_update.read_outcome(tmp_path) is None
    assert "updated to v2.180" in self_update.notice(first, "v2.180")


def test_an_unreadable_outcome_means_no_notice(tmp_path):
    assert self_update.read_outcome(tmp_path) is None
    (tmp_path / "outcome").write_text("surprise\n")
    assert self_update.read_outcome(tmp_path) is None
    os.mkfifo(tmp_path / "outcome")
    assert self_update.read_outcome(tmp_path) is None  # and does not block


def test_a_failed_outcome_names_both_versions_and_the_log(tmp_path):
    (tmp_path / "outcome").write_text("rolled_back\nthe installed copy failed\nv2.180\n")
    text = self_update.notice(self_update.read_outcome(tmp_path), "v2.172")
    assert "update to v2.180 did not install" in text and "on v2.172" in text
    assert str(tmp_path / "update.log") in text


# -- the checkout ---------------------------------------------------------------
def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    (path / "main.py").write_text("")
    (path / ".gitignore").write_text("dist.noindex\n")
    _git(path, "add", "main.py", ".gitignore")
    _git(path, "commit", "-q", "-m", "one")
    return path


FAKE_BUILD = r"""#!/bin/sh
# Stands in for build_app.sh: needs the linked .venv, and builds a bundle whose
# marker is main.py and whose stamp is the commit it was built from.
set -e
. .venv/bin/activate
app="dist.noindex/Lab Hub.app/Contents"
mkdir -p "$app/MacOS" "$app/Resources"
printf '#!/bin/sh\nexit 0\n' > "$app/MacOS/Lab Hub"
chmod +x "$app/MacOS/Lab Hub"
cp main.py "$app/marker"
printf '{"major": "2", "build": %s, "commit": "%s"}' \
  "$(git rev-list --count HEAD)" "$(git rev-parse --short=7 HEAD)" > "$app/Resources/_build_info.json"
"""


@pytest.fixture
def buildable(repo):
    """The fixture repo with a fake build_app.sh committed and a .venv beside it,
    as the shared checkout has one (git-ignored)."""
    (repo / ".gitignore").write_text("dist.noindex\n.venv\n")
    script = repo / "build_app.sh"
    script.write_text(FAKE_BUILD)
    script.chmod(0o755)
    (repo / "main.py").write_text("committed\n")
    _git(repo, "add", ".gitignore", "build_app.sh", "main.py")
    _git(repo, "commit", "-q", "-m", "buildable")
    (repo / ".venv" / "bin").mkdir(parents=True)
    (repo / ".venv" / "bin" / "activate").write_text("VENV_OK=1\n")
    return repo


def _build(project: Path, commit: str, shell: str = "/bin/zsh", env=None) -> None:
    """Runs the command as Rebuild does, through the owner's shell (zsh on macOS)."""
    command = self_update.build_command(project, commit)
    subprocess.run([shell, "-c", command], check=True, timeout=60,
                   capture_output=True, env=env)


def _dirty(repo: Path) -> None:
    (repo / "main.py").write_text("another session's half-done edit\n")


def _move(repo: Path) -> None:
    (repo / "main.py").write_text("a later commit\n")
    _git(repo, "commit", "-q", "-am", "later")


def test_main_commit_is_the_full_sha_of_main_whatever_is_checked_out(repo):
    sha = _git(repo, "rev-parse", "main")
    assert self_update.main_commit(repo) == sha
    _git(repo, "switch", "-q", "-c", "claude/x")
    (repo / "x").write_text("")
    _git(repo, "add", "x")
    _git(repo, "commit", "-q", "-m", "x")
    _dirty(repo)
    assert self_update.main_commit(repo) == sha


def test_main_commit_is_none_without_main_or_git(repo, tmp_path):
    _git(repo, "branch", "-m", "main", "trunk")
    assert self_update.main_commit(repo) is None
    assert self_update.main_commit(tmp_path / "nowhere") is None


def test_update_now_builds_the_recorded_commit_in_a_private_snapshot(lab, buildable):
    """§11.2.1 and §11.2.5: built at the recorded commit, none of the checkout's
    edits in it, the checkout untouched and no worktree registered."""
    commit = self_update.main_commit(buildable)
    worktrees = _git(buildable, "worktree", "list", "--porcelain")
    _dirty(buildable)
    _build(buildable, commit)
    assert self_update.snapshot().parent.parent == lab["update"]
    staged = self_update.stage_build(commit)
    assert _marker(staged.bundle) == "committed\n"
    assert staged.commit == commit[:7] and staged.version.startswith("v2.")
    assert not self_update.snapshot().exists()
    assert not (buildable / self_update.DIST).exists()
    assert (buildable / "main.py").read_text() == "another session's half-done edit\n"
    assert _git(buildable, "worktree", "list", "--porcelain") == worktrees


@pytest.mark.parametrize("change", [_dirty, _move], ids=["dirtied", "moved"])
@pytest.mark.parametrize("when", ["before the build", "after the build"])
def test_the_shared_checkout_changing_never_blocks_or_enters_the_update(
        lab, buildable, change, when):
    """§11.2.2 and §11.2.3: in all four cases the recorded commit is staged."""
    commit = self_update.main_commit(buildable)
    if when == "before the build":
        change(buildable)
    _build(buildable, commit)
    if when == "after the build":
        change(buildable)
    staged = self_update.stage_build(commit)
    assert _marker(staged.bundle) == "committed\n" and staged.commit == commit[:7]


def test_a_new_update_replaces_a_snapshot_left_behind(lab, buildable):
    first = self_update.main_commit(buildable)
    _build(buildable, first)
    _move(buildable)
    second = self_update.main_commit(buildable)
    _build(buildable, second)
    assert _marker(self_update.stage_build(second).bundle) == "a later commit\n"


def test_a_build_from_another_commit_is_not_staged(lab, buildable):
    commit = self_update.main_commit(buildable)
    _build(buildable, commit)
    _move(buildable)
    with pytest.raises(ValueError, match="build folder is at"):
        self_update.stage_build(self_update.main_commit(buildable))
    assert not self_update.staged_bundle().exists()


def test_a_stamp_that_is_not_the_recorded_commit_is_not_staged(lab, buildable):
    commit = self_update.main_commit(buildable)
    _build(buildable, commit)
    stamp = self_update.built_bundle() / "Contents" / "Resources" / "_build_info.json"
    stamp.write_text(json.dumps({"major": "2", "build": 1, "commit": "0000000"}))
    with pytest.raises(ValueError, match="new build is from 0000000"):
        self_update.stage_build(commit)
    stamp.write_text(json.dumps({"major": "2", "build": 1, "commit": ""}))
    with pytest.raises(ValueError, match="unknown commit"):
        self_update.stage_build(commit)
    assert self_update.built_bundle().exists()  # a refusal leaves the snapshot for the log


@pytest.mark.parametrize("shell", ["/bin/zsh", "/bin/bash"])
def test_the_build_runs_in_paths_with_spaces_and_quotes(lab, tmp_path, monkeypatch, shell):
    """The real support folder is "Application Support/Lab Hub" (review P3-2)."""
    monkeypatch.setattr(self_update, "UPDATE_DIR",
                        tmp_path / "Application Support" / "it's Lab Hub" / "update")
    project = tmp_path / "a lab $(touch pwned)" / "lab_hub"
    project.parent.mkdir()
    _git(project.parent, "init", "-q", "-b", "main", project.name)
    (project / ".gitignore").write_text("dist.noindex\n.venv\n")
    (project / "build_app.sh").write_text(FAKE_BUILD)
    (project / "build_app.sh").chmod(0o755)
    (project / "main.py").write_text("committed\n")
    _git(project, "add", ".")
    _git(project, "commit", "-q", "-m", "one")
    (project / ".venv" / "bin").mkdir(parents=True)
    (project / ".venv" / "bin" / "activate").write_text("")
    commit = self_update.main_commit(project)
    _build(project, commit, shell=shell)
    assert _marker(self_update.stage_build(commit).bundle) == "committed\n"
    assert not (tmp_path / "pwned").exists()
    assert (self_update.UPDATE_DIR.stat().st_mode & 0o777) == 0o700


def test_no_global_or_template_hook_runs_while_the_snapshot_is_made(lab, buildable, tmp_path):
    """Review P3-1: the owner's global hooks and template stay out of the build."""
    marker = tmp_path / "hook-ran"
    hooks = tmp_path / "hooks"
    template = tmp_path / "template" / "hooks"
    for folder in (hooks, template):
        folder.mkdir(parents=True)
        for name in ("reference-transaction", "post-checkout", "post-merge"):
            hook = folder / name
            hook.write_text(f"#!/bin/sh\necho {name} >> '{marker}'\n")
            hook.chmod(0o755)
    config = tmp_path / "gitconfig"
    config.write_text(f"[core]\n\thooksPath = {hooks}\n[init]\n\ttemplateDir = {template.parent}\n")
    commit = self_update.main_commit(buildable)
    _build(buildable, commit, env={**os.environ, "GIT_CONFIG_GLOBAL": str(config)})
    assert not marker.exists()
    assert not (self_update.snapshot() / ".git" / "hooks").exists()
    assert self_update.stage_build(commit).commit == commit[:7]


def test_a_symlinked_snapshot_folder_stops_the_build_before_removing_anything(
        lab, buildable, tmp_path):
    """Security P3-1: `rm -rf` must not follow a planted link to another lab_hub."""
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / "lab_hub").mkdir(parents=True)
    (elsewhere / "lab_hub" / "keep").write_text("precious")
    lab["update"].mkdir(parents=True)
    (lab["update"] / "snapshot").symlink_to(elsewhere)
    with pytest.raises(subprocess.CalledProcessError):
        _build(buildable, self_update.main_commit(buildable))
    assert (elsewhere / "lab_hub" / "keep").read_text() == "precious"


@pytest.mark.parametrize("commit", [None, "", "abc1234", "x" * 40])
def test_staging_needs_a_full_recorded_commit(lab, commit):
    with pytest.raises(ValueError, match="not one Lab Hub made"):
        self_update.stage_build(commit)


def test_a_symlinked_snapshot_is_not_staged(lab, buildable, tmp_path):
    commit = self_update.main_commit(buildable)
    _build(buildable, commit)
    elsewhere = tmp_path / "elsewhere"
    self_update.snapshot().rename(elsewhere)
    self_update.snapshot().symlink_to(elsewhere)
    with pytest.raises(ValueError, match="symlink"):
        self_update.stage_build(commit)


def test_a_snapshot_without_a_build_is_not_staged(lab, buildable):
    with pytest.raises(ValueError, match="no new build"):
        self_update.stage_build(self_update.main_commit(buildable))


def test_the_build_command_quotes_every_path_and_takes_only_a_full_sha(lab, tmp_path):
    odd = tmp_path / "it's a $(touch pwned) checkout"
    sha = "a" * 40
    command = self_update.build_command(odd, sha)
    assert command.endswith("&& ./build_app.sh") and "--install" not in command
    assert "core.hooksPath=/dev/null" in command and "worktree" not in command
    assert command.count("'") >= 8  # every path quoted
    for bad in ("abc1234", "A" * 40, sha + "; rm -rf /", ""):
        with pytest.raises(ValueError):
            self_update.build_command(odd, bad)


def test_planned_commit_accepts_only_a_command_lab_hub_made(lab, tmp_path):
    project = tmp_path / "repo"
    sha = "b" * 40
    command = self_update.build_command(project, sha)
    assert self_update.planned_commit(command, project) == sha
    assert self_update.planned_commit(command, tmp_path / "other") is None
    assert self_update.planned_commit(command + " && echo more", project) is None
    assert self_update.planned_commit(command.replace("--detach ", "--detach  "), project) is None
    assert self_update.planned_commit("cd x && ./build_app.sh", project) is None
    assert self_update.planned_commit(None, project) is None


# -- the build-report row -----------------------------------------------------
def _behind(project: Path | None, commit: str = "1234567",
            verdict: str = "behind") -> launcher.BuildStatus:
    return launcher.BuildStatus(
        self_update.SELF, launcher.Version(text="v2.172", commit=commit), verdict,
        "built at v2.172, but the source is 3 commits further on.",
        project / "build_app.sh" if project else None,
        "cd x && ./build_app.sh --install", project=project)


@pytest.fixture
def row_for(monkeypatch, repo, lab):
    """Lab Hub's row over the fixture repo: installed from its first commit,
    `main` one commit (adding build_app.sh) further on."""
    installed = _git(repo, "rev-parse", "--short=7", "HEAD")
    (repo / "build_app.sh").write_text("")
    _git(repo, "add", "build_app.sh")
    _git(repo, "commit", "-q", "-m", "build")

    def make(running, *, verdict_row=None, commit=installed, verdict="behind"):
        row = verdict_row or _behind(repo, commit, verdict)
        monkeypatch.setattr(self_update, "build_status", lambda app, root: row)
        monkeypatch.setattr(self_update, "source_dir", lambda app, root: repo)
        return self_update.self_status(repo.parent, running=running)
    return make


def test_lab_hubs_row_builds_main_in_a_snapshot_without_install_and_restarts(
        row_for, lab, repo):
    row = row_for(lab["target"])
    assert row.restarts and row.runs_in_app
    assert row.command.endswith("&& ./build_app.sh")
    assert "--install" not in row.command
    main = _git(repo, "rev-parse", "main")
    assert self_update.planned_commit(row.command, repo) == main
    assert row.note.startswith("built at v2.172, but the source is 3 commits")
    assert row.note.endswith(f"Update now builds {main[:7]}.")


def test_a_source_run_reads_as_running_the_checkout(row_for):
    row = row_for(None)
    assert row.verdict == "current" and row.command is None
    assert "runs the checkout directly" in row.note


def test_another_copy_offers_no_update(row_for, tmp_path):
    row = row_for(_bundle(tmp_path / "elsewhere", "x"))
    assert row.command is None and "not" in row.note


def test_a_dirty_checkout_no_longer_holds_the_update(row_for, lab, repo):
    """§11.2.2: another session's edits do not stop Lab Hub's row."""
    (repo / "main.py").write_text("x = 1\n")
    row = row_for(lab["target"])
    assert row.runs_in_app
    assert self_update.planned_commit(row.command, repo) == _git(repo, "rev-parse", "main")


def test_uncommitted_edits_alone_are_no_reason_to_update(row_for, lab, repo):
    """§11.2.4: level with main, the checkout's edits are in no build."""
    (repo / "main.py").write_text("x = 1\n")
    level = _git(repo, "rev-parse", "--short=7", "main")
    row = row_for(lab["target"], commit=level, verdict="uncommitted")
    assert row.verdict == "current" and row.command is None and not row.needs_rebuild
    assert "in no build until they are committed to main" in row.note


def test_on_another_branch_the_row_still_builds_main(row_for, lab, repo):
    main = _git(repo, "rev-parse", "main")
    _git(repo, "switch", "-q", "-c", "claude/x")
    (repo / "x").write_text("")
    _git(repo, "add", "x")
    _git(repo, "commit", "-q", "-m", "x")
    row = row_for(lab["target"])
    assert self_update.planned_commit(row.command, repo) == main
    assert "but main is 1 commit further on." in row.note and row.version.behind == 1


def test_level_with_main_while_on_another_branch_is_current(row_for, lab, repo):
    level = _git(repo, "rev-parse", "--short=7", "main")
    _git(repo, "switch", "-q", "-c", "claude/x")
    row = row_for(lab["target"], commit=level)
    assert row.verdict == "current" and row.command is None


def _branch_commit(repo: Path) -> str:
    _git(repo, "switch", "-q", "-c", "claude/feature")
    (repo / "feature").write_text("")
    _git(repo, "add", "feature")
    _git(repo, "commit", "-q", "-m", "feature")
    sha = _git(repo, "rev-parse", "--short=7", "HEAD")
    _git(repo, "switch", "-q", "main")
    return sha


def test_a_build_ahead_of_main_is_not_offered_a_downgrade(row_for, lab, repo):
    """Review P2-1: installed from a branch ahead of main, so main is older."""
    ahead = _branch_commit(repo)
    row = row_for(lab["target"], commit=ahead, verdict="current")
    assert row.verdict == "current" and row.command is None and not row.needs_rebuild
    assert "ahead of main" in row.note and "older build" in row.note


def test_a_build_beside_main_is_held_not_replaced(row_for, lab, repo):
    """Review P2-1: installed from a branch, main moved on separately."""
    beside = _branch_commit(repo)
    (repo / "main.py").write_text("later\n")
    _git(repo, "commit", "-q", "-am", "later on main")
    row = row_for(lab["target"], commit=beside)
    assert row.command is None and row.needs_rebuild
    assert "Update now leaves Lab Hub alone" in row.note and "older build" in row.note


def test_without_main_the_row_says_why_and_offers_nothing(row_for, lab, repo):
    _git(repo, "branch", "-m", "main", "trunk")
    row = row_for(lab["target"])
    assert row.command is None and "could not read main" in row.note


def test_main_without_build_app_sh_offers_nothing(row_for, lab, repo):
    _git(repo, "rm", "-q", "build_app.sh")
    _git(repo, "commit", "-q", "-m", "drop")
    row = row_for(lab["target"])
    assert row.command is None and "has no build_app.sh" in row.note


def test_an_installed_build_without_a_stamp_offers_nothing_and_says_why(row_for, lab):
    row = row_for(lab["target"], commit="")
    assert row.command is None and "does not record its commit" in row.note


def test_an_up_to_date_lab_hub_has_no_command(row_for, lab):
    current = launcher.BuildStatus(self_update.SELF, launcher.Version(text="v2.180"),
                                   "current", "matches its source.", None, "x")
    row = row_for(lab["target"], verdict_row=current)
    assert row.command is None and row.verdict == "current"


def test_the_row_is_computed_from_a_real_stamp_and_checkout(lab, repo, monkeypatch):
    """§2.1 without stubs: an installed stamp one commit behind reads as behind."""
    from lab_hub.launcher import state

    old = _git(repo, "rev-parse", "--short=7", "HEAD")
    (repo / "VERSION").write_text("2\n")
    (repo / "build_app.sh").write_text("")
    _git(repo, "add", "VERSION", "build_app.sh")
    _git(repo, "commit", "-q", "-m", "two")
    resources = lab["target"] / "Contents" / "Resources"
    resources.mkdir()
    (resources / "_build_info.json").write_text(
        json.dumps({"major": "2", "build": 1, "commit": old}))
    monkeypatch.setattr(state, "APPLICATIONS", lab["target"].parent)
    monkeypatch.setattr(self_update, "SELF", replace(self_update.SELF, project=repo.name))
    row = self_update.self_status(repo.parent, running=lab["target"])
    assert row.verdict == "behind" and row.version.behind == 1
    assert row.runs_in_app


# -- the Check builds view --------------------------------------------------------
def _other(command: str) -> launcher.BuildStatus:
    app = launcher.ExternalApp("x", "X", "x", "main.py", "s")
    return launcher.BuildStatus(app, launcher.Version(), "behind", "older.", None, command)


def test_lab_hubs_build_runs_last_and_is_named_as_this_app():
    own = replace(_behind(Path("/q")), command="cd /q && ./build_app.sh", restarts=True)
    view = progress.build_check_view((own, _other("echo x")), scoped=False)
    assert view.commands == ("echo x", "cd /q && ./build_app.sh")
    assert view.restarts == "cd /q && ./build_app.sh"
    assert view.items[0].name == "Lab Hub (this app)"
    assert "restarts" in view.info


def test_a_held_lab_hub_row_is_not_listed_as_missing_a_command():
    own = replace(_behind(Path("/q")), command=None, restarts=True,
                  note="older. Update now leaves Lab Hub alone: dirty.")
    view = progress.build_check_view((own,), scoped=False)
    assert view.restarts is None and not view.commands
    assert view.items[0].category == "held"
    assert view.folders == ()
    assert "No rebuild command" not in view.info
    snapshot = progress.BuildModel(view, history={}).snapshot()
    assert snapshot.rows[0].status == "Not now"


# -- the UI: the held build, the restart, the notice ----------------------------
def _pump_until(predicate, timeout_s=15.0) -> bool:
    import time

    from PySide6.QtWidgets import QApplication

    deadline = time.monotonic() + timeout_s
    while not predicate() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    return predicate()


def _restart_window(tmp_path, command, others=()):
    from ui.progress_window import BuildCheckWindow

    rows = tuple(_other(c) for c in others)
    if command is not None:
        rows += (replace(_behind(Path("/q")), command=command, restarts=True),)
    window = BuildCheckWindow(progress.build_check_view(rows, scoped=False), tmp_path)
    _WINDOWS.append(window)
    return window


_WINDOWS: list = []


@pytest.fixture(autouse=True)
def _drop_windows():
    yield
    import shiboken6

    while _WINDOWS:
        window = _WINDOWS.pop()
        if shiboken6.isValid(window):
            shiboken6.delete(window)


def test_a_held_command_waits_then_runs_and_the_row_says_why(qapp, tmp_path, monkeypatch):
    from ui import rebuild as rebuild_module

    monkeypatch.setattr(rebuild_module, "HOLD_POLL_MS", 20)
    window = _restart_window(tmp_path, "echo built")
    asked, seen = [], []

    def hold(command):
        asked.append(command)
        if len(asked) == 2:
            seen.append(window.model.snapshot().rows[0])
        return "Land is running" if len(asked) < 3 else None

    verified = []
    run = rebuild_module.Rebuild(["echo built"], window, hold=hold,
                                 verify=lambda app, root: verified.append(app))
    window.show()
    assert _pump_until(lambda: run.ended)
    assert run.succeeded and len(asked) == 3
    assert seen[0].status == "Waiting" and seen[0].reason == "Waiting: Land is running"
    text = window.output_text()
    assert text.count("[waiting — Land is running]") == 1 and "built" in text
    row = window.model.snapshot().rows[0]
    assert row.reason == "Built and self-tested; installs when Lab Hub restarts."
    assert verified == []  # /Applications still holds the old build: not read
    assert window.cancel_button.text() == "Close and restart"
    window.close()


def test_every_poll_of_a_wait_counts_as_activity(qapp, tmp_path, monkeypatch):
    from ui import rebuild as rebuild_module

    monkeypatch.setattr(rebuild_module, "HOLD_POLL_MS", 20)
    window = _restart_window(tmp_path, "echo built")
    touched = []
    original = window.model.touch
    monkeypatch.setattr(window.model, "touch", lambda: touched.append(1) or original())
    polls = []
    run = rebuild_module.Rebuild(
        ["echo built"], window,
        hold=lambda c: polls.append(1) or ("busy" if len(polls) < 5 else None))
    window.show()
    assert _pump_until(lambda: run.ended)
    assert len(touched) >= 4
    window.close()


def test_cancel_while_held_starts_nothing_and_clears_the_wait(qapp, tmp_path, monkeypatch):
    from ui import rebuild as rebuild_module

    monkeypatch.setattr(rebuild_module, "HOLD_POLL_MS", 20)
    marker = tmp_path / "ran"
    command = f"touch {marker}"
    window = _restart_window(tmp_path, command)
    run = rebuild_module.Rebuild([command], window, hold=lambda c: "Land is running")
    window.show()
    assert _pump_until(lambda: "waiting" in window.output_text())
    assert window.model.snapshot().rows[0].reason == "Waiting: Land is running"
    run.cancel()
    assert _pump_until(lambda: run.ended)
    assert not run.succeeded and not marker.exists()
    assert "Waiting" not in window.model.snapshot().rows[0].reason
    assert window.cancel_button.text() == "Close"
    window.close()


def test_a_skipped_lab_hub_does_not_fail_the_run(qapp, tmp_path):
    """Review P2-1: the other rebuilds count, and there is no restart."""
    from ui.rebuild import Rebuild, Skipped

    marker = tmp_path / "ran"
    command = f"touch {marker}"
    window = _restart_window(tmp_path, command, others=("echo other",))

    def hold(c):
        if c == command:
            raise Skipped("Lab Hub was not rebuilt: the checkout is on claude/x, not main")
        return None

    run = Rebuild(["echo other", command], window, hold=hold)
    window.show()
    assert _pump_until(lambda: run.ended)
    assert run.succeeded and run.skipped == [command] and not marker.exists()
    window.draw()
    snapshot = window.model.snapshot()
    row = snapshot.rows[-1]
    assert row.status == "Not rebuilt" and "claude/x" in row.reason
    assert window.cancel_button.text() == "Close"
    assert "was not rebuilt" in snapshot.outcome
    window.close()


def test_a_hold_that_breaks_fails_the_run(qapp, tmp_path):
    from ui.rebuild import Rebuild

    window = _restart_window(tmp_path, "echo x")

    def hold(_command):
        raise RuntimeError("git exploded")

    run = Rebuild(["echo x"], window, hold=hold)
    window.show()
    assert _pump_until(lambda: run.ended)
    assert not run.succeeded and "git exploded" in window.output_text()
    window.close()


_TABS: list = []


def _tab(**kwargs):
    """An Apps page, deleted for real at the end of the test (`_drop_tabs`): a
    page left to the garbage collector, with its hygiene QProcess still
    running, crashed a later test's theme repaint."""
    from lab_hub import config
    from ui.apps_tab import AppsTab

    tab = AppsTab(config.Settings(), apps=lambda: (), **kwargs)
    _TABS.append(tab)
    return tab


@pytest.fixture(autouse=True)
def _drop_tabs():
    yield
    import shiboken6

    while _TABS:
        tab = _TABS.pop()
        tab._poll.stop()
        if tab._hygiene_proc is not None:
            tab._hygiene_proc.kill()
            tab._hygiene_proc.waitForFinished(2000)
        shiboken6.delete(tab)


def test_the_apps_tab_hold_waits_for_busy_work_but_not_for_the_checkout(
        qapp, isolated_config, monkeypatch, repo):
    from ui.rebuild import Skipped

    tab = _tab(check_builds=True)
    try:
        hold = tab._hold_for("build lab hub")
        assert tab._hold_for(None) is None
        assert hold("another app") is None
        tab.busy_reasons = lambda: ["Land is running"]
        assert "Land is running" in hold("build lab hub")
        tab.busy_reasons = lambda: []
        monkeypatch.setattr(launcher, "source_dir", lambda app, root: repo)
        assert hold("build lab hub") is None
        # The build is a snapshot of the recorded commit (spec §11): another
        # session's edits or branch no longer skip it.
        (repo / "main.py").write_text("x = 1\n")
        _git(repo, "switch", "-q", "-c", "claude/x")
        assert hold("build lab hub") is None
        monkeypatch.setattr(launcher, "source_dir", lambda app, root: None)
        with pytest.raises(Skipped, match="checkout is gone"):
            hold("build lab hub")
    finally:
        tab._poll.stop()


class _StubLander:
    def __init__(self, busy=False, running=False):
        self.busy, self.running = busy, running


def test_a_page_is_busy_while_land_plans_or_runs(qapp, isolated_config):
    tab = _tab(check_builds=True)
    real = tab.lander
    try:
        tab.lander = _StubLander()
        assert tab._own_busy_reasons() == []
        tab.lander = _StubLander(busy=True)
        assert tab._own_busy_reasons() == ["Land is reading the repos"]
        tab.lander = _StubLander(busy=True, running=True)
        assert tab._own_busy_reasons() == ["Land is running"]
    finally:
        tab.lander = real
        tab._poll.stop()


class _FakeRun:
    succeeded = True
    skipped: list = []
    failed: list = []

    @property
    def ran_to_end(self):
        return self.succeeded

    def __init__(self, commands, window, **hooks):
        self.hooks = hooks

    def exec(self):
        return 0


@pytest.mark.parametrize("succeeded,skipped,expect", [
    (True, [], True), (False, [], False), (True, ["build lab hub"], False)])
def test_the_restart_is_asked_for_only_after_lab_hubs_build_passed(
        qapp, isolated_config, monkeypatch, tmp_path, succeeded, skipped, expect):
    from ui import apps_tab as apps_tab_module

    run = type("Run", (_FakeRun,), {"succeeded": succeeded, "skipped": skipped})
    made = []
    run = type("Run", (run,), {"__init__": lambda self, c, w, **h: (
        _FakeRun.__init__(self, c, w, **h), made.append(self))[0]})
    monkeypatch.setattr(apps_tab_module, "Rebuild", run)
    monkeypatch.setattr(launcher, "source_dir", lambda app, root: tmp_path)
    staged = self_update.Staged(tmp_path, "v2.180", "abc")
    monkeypatch.setattr(self_update, "stage_build", lambda project: staged)
    window = _restart_window(tmp_path, "build lab hub", others=("echo x",))
    tab = _tab(check_builds=True)
    asked = []
    tab.restart_requested.connect(asked.append)
    try:
        tab.run_updates(["echo x", "build lab hub"], window=window)
        # QA N29: Lab Hub's build is held while anything a restart would end runs.
        hold = made[0].hooks["hold"]
        tab.busy_reasons = lambda: ["Land is running"]
        assert "Land is running" in hold("build lab hub")
        assert hold("echo x") is None
    finally:
        tab._poll.stop()
        window.close()
    assert asked == ([staged] if expect else [])


def test_a_build_that_cannot_be_staged_asks_for_no_restart(
        qapp, isolated_config, monkeypatch, tmp_path):
    from ui import apps_tab as apps_tab_module

    monkeypatch.setattr(apps_tab_module, "Rebuild", _FakeRun)
    monkeypatch.setattr(launcher, "source_dir", lambda app, root: tmp_path)

    def refuse(commit):
        raise ValueError("the new build is from 1234567, not abcdef0")

    monkeypatch.setattr(self_update, "stage_build", refuse)
    warned = []
    monkeypatch.setattr(apps_tab_module.QMessageBox, "warning",
                        lambda *a: warned.append(a[2]))
    window = _restart_window(tmp_path, "build lab hub")
    tab = _tab(check_builds=True)
    asked = []
    tab.restart_requested.connect(asked.append)
    try:
        tab.run_updates(["build lab hub"], window=window)
    finally:
        tab._poll.stop()
        window.close()
    assert asked == [] and "1234567" in warned[0]


def test_close_and_restart_stages_the_recorded_commit_after_the_checkout_moved(
        qapp, isolated_config, monkeypatch, lab, buildable):
    """§11.2.3 end to end in the tab: the build command Update now ran carries
    its commit; the checkout dirtied and moved since changes nothing."""
    monkeypatch.setattr(self_update, "UPDATE_DIR", lab["update"])
    monkeypatch.setattr(launcher, "source_dir", lambda app, root: buildable)
    commit = self_update.main_commit(buildable)
    command = self_update.build_command(buildable, commit)
    subprocess.run(["/bin/bash", "-c", command], check=True, timeout=60, capture_output=True)
    _move(buildable)
    _dirty(buildable)
    tab = _tab(check_builds=True)
    asked = []
    tab.restart_requested.connect(asked.append)
    try:
        tab._restart_on(command)
    finally:
        tab._poll.stop()
    assert len(asked) == 1 and asked[0].commit == commit[:7]
    assert _marker(asked[0].bundle) == "committed\n"


def test_close_and_restart_refuses_a_command_lab_hub_did_not_make(
        qapp, isolated_config, monkeypatch, lab, buildable):
    from ui import apps_tab as apps_tab_module

    monkeypatch.setattr(self_update, "UPDATE_DIR", lab["update"])
    monkeypatch.setattr(launcher, "source_dir", lambda app, root: buildable)
    warned = []
    monkeypatch.setattr(apps_tab_module.QMessageBox, "warning",
                        lambda *a: warned.append(a[2]))
    tab = _tab(check_builds=True)
    asked = []
    tab.restart_requested.connect(asked.append)
    try:
        tab._restart_on("cd x && ./build_app.sh")
    finally:
        tab._poll.stop()
    assert asked == [] and "not one Lab Hub made" in warned[0]


def test_a_rebuild_without_lab_hub_asks_for_no_restart(qapp, isolated_config, monkeypatch,
                                                       tmp_path):
    from ui import apps_tab as apps_tab_module

    monkeypatch.setattr(apps_tab_module, "Rebuild", _FakeRun)
    tab = _tab(check_builds=True)
    asked = []
    tab.restart_requested.connect(asked.append)
    window = _restart_window(tmp_path, None, others=("echo x",))
    try:
        tab.run_updates(["echo x"], window=window)
    finally:
        tab._poll.stop()
        window.close()
    assert asked == []


def test_the_launchpad_report_ends_with_lab_hub_and_a_scoped_one_has_none(
        qapp, isolated_config, monkeypatch):
    from ui import apps_tab as apps_tab_module

    seen = []

    class FakeWindow:
        def __init__(self, view, root, parent):
            seen.append(view)
            self.copy_requested = type("S", (), {"connect": lambda *a: None})()
            self.handoff_requested = self.copy_requested  # Ask Claude (claude-handoff)
            self.handoff_paths, self.handoff_commands = {}, {}
            self.choice = None

        def set_handoff_busy(self, busy):
            pass

        def ask(self):
            return None

        def isVisible(self):  # noqa: N802 - Qt name
            return False

        def deleteLater(self):  # noqa: N802 - Qt name
            pass

    monkeypatch.setattr(apps_tab_module, "BuildCheckWindow", FakeWindow)
    monkeypatch.setattr(launcher, "build_report", lambda root, apps=None: ())
    own = replace(_behind(Path("/q")), command="cd /q && ./build_app.sh", restarts=True)
    monkeypatch.setattr(self_update, "self_status", lambda root: own)
    launchpad = _tab(check_builds=True)
    scoped = _tab(check_own_builds=True)
    launchpad.busy_reasons = lambda: ["Land is running"]
    try:
        launchpad.show_build_report()
        scoped.show_build_report()
    finally:
        launchpad._poll.stop()
        scoped._poll.stop()
    assert [i.name for i in seen[0].items] == ["Lab Hub (this app)"]
    assert "Will update after this finishes: Land is running" in seen[0].items[0].note
    assert seen[1].items == ()


@pytest.fixture
def no_quit(monkeypatch):
    """Nothing here may really quit, start a helper or open a modal box."""
    calls = {"quit": [], "started": [], "warned": []}
    monkeypatch.setattr("PySide6.QtWidgets.QApplication.quit",
                        staticmethod(lambda: calls["quit"].append(True)))
    monkeypatch.setattr(self_update, "start_helper", lambda p: calls["started"].append(p))
    monkeypatch.setattr(self_update, "helper_paths", lambda staged: ("paths", staged))
    monkeypatch.setattr("ui.main_window.QMessageBox.warning",
                        lambda *a: calls["warned"].append(a[2]))
    return calls


def test_every_apps_page_asks_the_whole_window_what_is_busy(window):
    for page in window._app_pages():
        assert page.busy_reasons == window.busy_reasons


def test_the_restart_signal_reaches_the_window(window, no_quit):
    window.apps_tab.restart_requested.emit("STAGED")
    assert no_quit["started"] == [("paths", "STAGED")] and no_quit["quit"] == [True]


def test_the_restart_waits_while_any_page_lands(window, no_quit, monkeypatch):
    monkeypatch.setattr(window.backup_sync_tab, "_own_busy_reasons",
                        lambda: ["Land is running"])
    window.restart_for_update("STAGED")
    assert no_quit["started"] == [] and no_quit["quit"] == []
    assert window._restart_timer.isActive()
    assert "Land is running" in window.statusBar().currentMessage()
    monkeypatch.setattr(window.backup_sync_tab, "_own_busy_reasons", lambda: [])
    window._restart_timer.stop()
    window._restart_timer.timeout.emit()
    assert no_quit["started"] == [("paths", "STAGED")] and no_quit["quit"] == [True]


def test_the_restart_waits_for_a_running_tool(window, no_quit, monkeypatch):
    monkeypatch.setattr(window, "_running_panels", lambda: [window.narrator_tab])
    assert window.busy_reasons() == ["Narrator is running"]
    window.restart_for_update("STAGED")
    assert no_quit["started"] == [] and no_quit["quit"] == []
    window._restart_timer.stop()


def test_the_restart_starts_the_helper_then_quits_when_idle(window, no_quit):
    window.restart_for_update("STAGED")
    assert no_quit["started"] == [("paths", "STAGED")] and no_quit["quit"] == [True]
    assert window._quitting


def test_a_restart_that_cannot_start_the_helper_keeps_lab_hub_running(
        window, no_quit, monkeypatch):
    def refuse(staged):
        raise ValueError("no new build at x")

    monkeypatch.setattr(self_update, "helper_paths", refuse)
    window.restart_for_update("STAGED")
    assert no_quit["quit"] == [] and not window._quitting
    assert "no new build" in no_quit["warned"][0]


def test_the_first_start_after_an_update_says_how_it_went(window, fake_tray, monkeypatch):
    window.tray = fake_tray
    monkeypatch.setattr(self_update, "read_outcome",
                        lambda: self_update.Outcome("ok", "installed", Path("/l")))
    window.show_update_outcome()
    assert "Lab Hub updated to" in window.statusBar().currentMessage()
    assert any("Lab Hub updated to" in message for _title, message in fake_tray.notices)


# ------------------------------------------------------------ spec land-update-gaps §3.2
def test_lab_hub_still_builds_and_restarts_after_another_app_failed(qapp, tmp_path):
    from ui.rebuild import Rebuild

    window = _restart_window(tmp_path, "echo built-lab-hub", others=("false",))
    run = Rebuild(["false", "echo built-lab-hub"], window)
    window.show()
    assert _pump_until(lambda: run.ended)
    assert "built-lab-hub" in window.output_text()
    assert run.failed == ["false"] and run.ran_to_end and not run.succeeded
    window.draw()
    outcome = window.header.outcome.text()
    assert outcome.startswith("1 of 2 rebuilds failed:")
    assert "Lab Hub's own build passed: it restarts" in outcome
    assert window.cancel_button.text() == "Close and restart"


def test_a_failed_lab_hub_build_asks_for_no_restart(qapp, tmp_path):
    from ui.rebuild import Rebuild

    window = _restart_window(tmp_path, "false", others=("echo other",))
    run = Rebuild(["echo other", "false"], window)
    window.show()
    assert _pump_until(lambda: run.ended)
    window.draw()
    assert "restarts" not in window.header.outcome.text()
    assert window.cancel_button.text() == "Close"


def test_update_now_restarts_when_only_another_app_failed(
        qapp, isolated_config, monkeypatch, tmp_path):
    from ui import apps_tab as apps_tab_module

    run = type("Run", (_FakeRun,), {"succeeded": False, "ran_to_end": True,
                                     "failed": ["echo x"]})
    monkeypatch.setattr(apps_tab_module, "Rebuild", run)
    monkeypatch.setattr(launcher, "source_dir", lambda app, root: tmp_path)
    staged = self_update.Staged(tmp_path, "v2.180", "abc")
    monkeypatch.setattr(self_update, "stage_build", lambda project: staged)
    window = _restart_window(tmp_path, "build lab hub", others=("echo x",))
    tab = _tab(check_builds=True)
    asked, said = [], []
    tab.restart_requested.connect(asked.append)
    tab.launched.connect(said.append)
    try:
        tab.run_updates(["echo x", "build lab hub"], window=window)
    finally:
        tab._poll.stop()
        window.close()
    assert asked == [staged]
    assert said and "1 failed (" in said[0] and "Lab Hub itself was not rebuilt" not in said[0]


def test_update_now_does_not_restart_when_lab_hubs_own_build_failed(
        qapp, isolated_config, monkeypatch, tmp_path):
    from ui import apps_tab as apps_tab_module

    run = type("Run", (_FakeRun,), {"succeeded": False, "ran_to_end": True,
                                     "failed": ["build lab hub"]})
    monkeypatch.setattr(apps_tab_module, "Rebuild", run)
    # A restart attempt would end in a modal warning: record it instead of hanging.
    warned = []
    monkeypatch.setattr(apps_tab_module.QMessageBox, "warning", lambda *a: warned.append(a))
    monkeypatch.setattr(self_update, "stage_build", lambda project: warned.append("staged"))
    window = _restart_window(tmp_path, "build lab hub", others=("echo x",))
    tab = _tab(check_builds=True)
    asked, said = [], []
    tab.restart_requested.connect(asked.append)
    tab.launched.connect(said.append)
    try:
        tab.run_updates(["echo x", "build lab hub"], window=window)
    finally:
        tab._poll.stop()
        window.close()
    assert asked == [] and warned == []
    assert "Rebuilt and reinstalled 1 app." in said[0] and "Lab Hub itself was not rebuilt" in said[0]


def test_a_skipped_lab_hub_is_not_counted_and_is_named_after_another_failure(qapp, tmp_path):
    # Review P3-3.
    from ui.rebuild import Rebuild, Skipped

    def hold(command):
        if command == "echo lab-hub":
            raise Skipped("the checkout has uncommitted changes")
        return None

    window = _restart_window(tmp_path, "echo lab-hub", others=("false",))
    run = Rebuild(["false", "echo lab-hub"], window, hold=hold)
    window.show()
    assert _pump_until(lambda: run.ended)
    window.draw()
    assert window.header.outcome.text() == (
        "1 of 1 rebuild failed: X. See the live output. "
        "Lab Hub itself was not rebuilt; its row says why.")
    assert window.cancel_button.text() == "Close"


# -- Lab Hub's tile (spec apps-discovery §13.4) -------------------------------------
def test_the_build_row_and_the_tile_use_keys_no_registry_file_may_define():
    from lab_hub.launcher import registry

    assert self_update.SELF.key in registry.RESERVED
    assert self_update.SELF.project in registry.RESERVED
    assert self_update.OWN_TILE.key in registry.RESERVED
    assert self_update.OWN_TILE.project in registry.RESERVED
    assert (self_update.OWN_TILE.key, self_update.OWN_TILE.project) == (
        self_update.SELF.key, self_update.SELF.project)


def test_the_tile_is_the_no_launch_kind_and_is_in_no_registry_group():
    from lab_hub.launcher import registry

    tile = self_update.OWN_TILE

    assert tile.entry is None and not tile.launchable
    assert tile.name == "Lab Hub"
    assert tile.summary == "This app: the launcher for the lab's projects."
    assert tile not in registry.current().suites + registry.current().apps
    assert tile.key not in {a.key for group in registry.current().groups() for a in group}
    assert self_update.SELF.launchable, "the build row still compares the installed bundle"


def test_no_shipped_registry_entry_has_a_reserved_key_or_folder():
    from lab_hub.launcher import registry

    shipped = registry.load(registry.PACKAGE_REGISTRY)

    assert all(a.key not in registry.RESERVED for group in shipped.groups() for a in group)
    assert all(a.project not in registry.RESERVED for group in shipped.groups() for a in group)


def _row(verdict: str, note: str = "n.", behind: int = 0) -> launcher.BuildStatus:
    return launcher.BuildStatus(
        self_update.SELF, launcher.Version(text="v2.172", behind=behind), verdict, note)


@pytest.mark.parametrize("behind, line", [
    (1, "1 commit older than its source"),
    (3, "3 commits older than its source"),
    (0, "older than its source"),
])
def test_the_verdict_line_says_how_far_behind_it_is(behind, line):
    assert self_update.verdict_line(_row("behind", behind=behind)) == line


def test_the_verdict_line_says_up_to_date_for_a_current_build():
    assert self_update.verdict_line(
        _row("current", "built at v2.172 and level with main.")) == "up to date"


def test_the_verdict_line_for_a_run_from_source_is_what_self_status_says(lab, repo):
    row = self_update.self_status(repo.parent, running=None)

    assert row.note.startswith("runs the checkout directly")
    assert self_update.verdict_line(row) == "runs the checkout directly"


@pytest.mark.parametrize("verdict, note", [
    ("unknown", "its release number comes from the bundle."),
    ("missing", "no checkout here, so there is nothing to compare it against."),
    ("uncommitted", "level with the last commit, but the checkout has uncommitted changes."),
])
def test_a_row_that_cannot_be_called_current_or_behind_says_build_statuss_own_words(verdict, note):
    assert self_update.verdict_line(_row(verdict, note)) == note


def test_the_tile_adds_nothing_to_the_check_builds_report(monkeypatch, tmp_path):
    """`build_report` reads the registry, which never holds OWN_TILE; Lab Hub's
    row is appended once, by `self_status`."""
    from lab_hub.launcher import registry

    registry.use(registry.Registry(suites=(
        launcher.ExternalApp("a", "A", "a", "main.py", "s"),
        launcher.ExternalApp("kaila", "Kaila", "kaila", None, "s"),
    )))
    try:
        keys = [row.app.key for row in launcher.build_report(tmp_path)]
    finally:
        registry.use(None)

    assert "lab_hub" not in keys and "kaila" not in keys
