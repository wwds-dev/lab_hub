"""Land one repo's work in one go: plan, say it in a sentence, run it, say how it went.

Spec: `docs/specs/land-from-tiles.md`, extended by `land-resolve-all.md`
(Land leaves nothing open: `land_resolve` prepares the repo first and decides
the branches that still did not land). This is the front end of `repo_tidy`: the
planning, the guards and every git command stay there (a guard is re-checked
right before each action; nothing is forced, rewritten or force-pushed). What
this module adds is what a person needs around them:

- `make_plan()` reads git for one repo and `LandPlan.sentence` says what Land
  will do in plain words, for the one confirmation.
- `land()` runs the plan, carries on past a failed step, and returns a
  `LandResult` whose `reason` is one plain sentence, never a progress log.
- A repo is claimed while it lands, so two windows (or Land all and a tile)
  can never land the same repo at once.

Everything here blocks on git; the UI runs it on a worker thread.
"""

from __future__ import annotations

import dataclasses
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import claude_resolve, land_resolve, repo_tidy

# What a person can read on a tile line. A longer reason is cut, never wrapped
# into a paragraph; the full text is in the log and the Details.
MAX_REASON = 180

_PREFIX = re.compile(r"^(?:not landed|not done|skipped|failed)\s*[—-]\s*", re.IGNORECASE)
# A real exception line ("ImportError: cannot import name ..."), not a pytest
# summary such as "=== 1 error in 0.12s ===" (case-sensitive, needs the colon).
_ERROR_LINE = re.compile(r"\b[A-Z]\w*(?:Error|Exception):\s.*")


def plain_reason(message: str) -> str:
    """One readable sentence from a step's outcome message.

    `repo_tidy` and `claude_resolve` report in the voice of a log ("not landed
    — no Claude run: the tests don't pass on master itself in a temporary copy
    (they fail): <pytest output>"). A tile needs the cause: the first line
    without its status prefix, and the last error line if the output has one.
    """
    text = (message or "").strip()
    if not text:
        return "it did not finish and gave no reason"
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    first = _PREFIX.sub("", lines[0])
    error = ""
    for line in reversed(lines):
        found = _ERROR_LINE.search(line)
        if found:
            error = found.group(0).strip()
            break
    if error and error not in first:
        first = f"{first.rstrip(' .:')}: {error}"
    first = re.sub(r"\s+", " ", first)
    if len(first) > MAX_REASON:
        first = first[: MAX_REASON - 1].rstrip() + "…"
    return first


# ----------------------------------------------------------------------
# One repo at a time
# ----------------------------------------------------------------------
_ACTIVE: set[str] = set()
_LOCK = threading.Lock()


def _key(path: Path) -> str:
    try:
        return str(path.resolve())
    except OSError:
        return str(path)


def claim(path: Path) -> bool:
    """True if nothing else is landing this repo; the caller must `release` it."""
    with _LOCK:
        key = _key(path)
        if key in _ACTIVE:
            return False
        _ACTIVE.add(key)
        return True


def release(path: Path) -> None:
    with _LOCK:
        _ACTIVE.discard(_key(path))


def landing(path: Path) -> bool:
    with _LOCK:
        return _key(path) in _ACTIVE


# ----------------------------------------------------------------------
# The plan, in words
# ----------------------------------------------------------------------
def _n(count: int, one: str, many: str | None = None) -> str:
    return f"{count} {one if count == 1 else (many or one + 's')}"


@dataclass(frozen=True)
class LandPlan:
    name: str
    path: Path
    actions: tuple[repo_tidy.Action, ...] = ()
    skipped: tuple[repo_tidy.Skip, ...] = ()
    claude: str | None = None  # the Claude Code binary, when conflicts can be handed to it
    prep: tuple[land_resolve.Step, ...] = ()  # run first (spec land-resolve-all 4.1-4.4)
    stops: tuple[land_resolve.Stop, ...] = ()  # hard stops found while looking (4.7)
    unlanded: int = 0  # branches not landed and not in `actions`: merged later or decided by Claude (4.6)
    claude_why: str = ""  # why there is no Claude Code, when `claude` is None
    relinked: str = ""  # the app path, when it was a link checked out as a file (4.1)

    @property
    def with_claude(self) -> int:
        return sum(1 for a in self.actions if a.kind == "claude_merge")

    @property
    def nothing(self) -> bool:
        return not (self.actions or self.prep or self.stops or self.unlanded)

    @property
    def sentence(self) -> str:
        """What Land will do, for the one confirmation."""
        if self.nothing:
            why = self.skipped[0].reason if self.skipped else "nothing is waiting"
            return f"{self.name}: nothing Land can do on its own ({why})."
        by: dict[str, list[repo_tidy.Action]] = {}
        for action in self.actions:
            by.setdefault(action.kind, []).append(action)
        parts = []
        steps: dict[str, list[land_resolve.Step]] = {}
        for step in self.prep:
            steps.setdefault(step.kind, []).append(step)
        if "rescue" in steps:
            parts.append(f"put {_n(len(steps['rescue']), 'detached HEAD')} on a rescue branch")
        files = sum(len(s.files) for s in steps.get("untracked", ()))
        held = sum(len(s.quarantine) for s in steps.get("untracked", ()))
        if files:
            parts.append(f"commit {_n(files, 'untracked file')} after a secret scan")
        if held:
            parts.append(f"move {_n(held, 'file')} to quarantine")
        links = sum(len(s.links) for s in steps.get("untracked", ()))
        if links:
            parts.append(f"ignore {_n(links, 'link')} to a folder without committing it")
        if "switch" in steps:
            parts.append("switch the checkout from " + ", ".join(s.detail for s in steps["switch"])
                         + " back to the default branch")
        if "commit" in by:
            parts.append(f"commit open changes in {_n(len(by['commit']), 'worktree')}")
        merges = len(by.get("merge", ())) + len(by.get("claude_merge", ()))
        if merges:
            target = (by.get("merge") or by["claude_merge"])[0].branch
            text = f"merge {_n(merges, 'branch', 'branches')} into {target}"
            if self.with_claude:
                text += f" ({self.with_claude} with Claude Code resolving conflicts)"
            parts.append(text)
        if "pull" in by:
            parts.append("pull " + ", ".join(dict.fromkeys(a.target for a in by["pull"])))
        if "push" in by:
            parts.append("push " + ", ".join(dict.fromkeys(a.target for a in by["push"]))
                         + " to origin")
        if "delete_branch" in by:
            parts.append(f"delete {_n(len(by['delete_branch']), 'landed branch', 'landed branches')}")
        if "remove_worktree" in by:
            parts.append(f"remove {_n(len(by['remove_worktree']), 'clean worktree')}")
        if self.unlanded:
            parts.append(f"then merge the {_n(self.unlanded, 'other branch', 'other branches')} "
                         "not landed yet where they can; Claude Code decides for any that "
                         "still cannot land: land it or archive it as a tag")
        if self.stops:
            parts.append(f"stop at {_n(len(self.stops), 'thing')} only you can clear: "
                         + "; ".join(s.label for s in self.stops))
        return f"{self.name}: " + ", ".join(parts) + "."

    @property
    def claude_notice(self) -> str:
        """The disclosure the old Resolve dialog gave, kept: it is a real data flow."""
        from . import claude_resolve

        triage = ""
        if self.unlanded:
            triage = (f"A branch that still does not land is sent to Claude Code read-only "
                      f"(its log and diff, at most ${land_resolve.TRIAGE_BUDGET_USD:.2f} each, "
                      f"${self.unlanded * land_resolve.TRIAGE_BUDGET_USD:.2f} for "
                      f"{_n(self.unlanded, 'branch', 'branches')} at most). An archived branch "
                      "is kept as a local tag archive/<branch>/<date>, never pushed, and can "
                      "be restored from Review branches.")
        # Branches blocked now only by untracked files or the checkout may need a
        # Claude merge once prep has run: priced as such (review P1-2).
        later = self.unlanded if self.claude else 0
        n = self.with_claude + later
        if not n:
            return triage
        cap = claude_resolve.BUDGET_USD
        tests = sorted({a.detail for a in self.actions if a.kind == "claude_merge" and a.detail})
        who = (f"{_n(n, 'branch', 'branches')} will be sent" if not later else
               f"up to {_n(n, 'branch', 'branches')} may be sent "
               f"({self.with_claude} known to conflict now)")
        return (
            f"{who} to "
            f"Claude Code (model {claude_resolve.MODEL}, at most ${cap:.0f} each, "
            f"${n * cap:.0f} in total). Code from "
            "this repo goes to Anthropic, as in any Claude Code session. Lab Hub runs the "
            f"repo's tests itself ({'; '.join(tests) or 'its test command'}); a merge that "
            "passes them lands and is pushed without review. A branch that fails is "
            "archived as a tag, never lost."
        ) + (f"\n\n{triage}" if triage else "")

    @property
    def detail(self) -> str:
        lines = [f"{self.name} is {self.path}"]
        if self.relinked:
            lines.append(f"({self.relinked} is a link to it, checked out as a file; "
                         "Land restores the link)")
        lines += [""] + [s.label for s in self.prep] + [a.label for a in self.actions]
        if self.stops:
            lines += ["", "Only you can clear:"] + [s.label for s in self.stops]
        if self.skipped:
            lines += ["", "Left alone:"] + [s.label for s in self.skipped]
        return "\n".join(lines)


def make_plan(name: str, path: Path, *, claude: str | None | bool = True,
              busy="fresh", now: float | None = None) -> LandPlan:
    """Read git for one repo. `claude`: True finds Claude Code, a path uses that
    one, None leaves conflicting branches for a person. Tests pass `busy`/`now`."""
    why = "Claude Code not found"
    if claude is True:
        from .claude_resolve import availability

        claude, why = availability()
    relinked = ""
    if path.is_absolute() and not (path / ".git").exists():
        target = land_resolve.link_target(path)
        if target is not None and (target / ".git").exists():
            relinked, path = str(path), target
    if not path.is_absolute() or not (path / ".git").exists():
        return LandPlan(name, path, (), (repo_tidy.Skip(name, str(path), "not a git checkout"),),
                        stops=(land_resolve.Stop(name, str(path), "not a git checkout, nor a "
                                                 "link to one: fix the app's path"),))
    if busy == "fresh":
        busy = repo_tidy.busy_dirs()
    prep, stops = land_resolve.prep(name, path, busy)
    actions, skips = repo_tidy.plan_repo(name, path, busy, now, claude or None, why,
                                         land_mode=True)
    skips = [s for s in skips if s.reason != "level with origin"]
    merging = {a.target for a in actions if a.kind in ("merge", "claude_merge")}
    open_branches = land_resolve.unlanded(path, name)
    unlanded = len([b for b in open_branches if b.branch not in merging])
    # A branch the owner restored and kept is not Land's business (review P2-5).
    kept = ({b.branch for b in repo_tidy.unlanded([(name, path)])}
            - {b.branch for b in open_branches})
    skips = [s for s in skips if s.target not in kept]
    return LandPlan(name, path, tuple(actions), tuple(skips), claude or None,
                    tuple(prep), tuple(stops), unlanded, "" if claude else why, relinked)


# ----------------------------------------------------------------------
# Running it
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class LandResult:
    name: str
    state: str  # landed | not_landed | nothing
    reason: str = ""  # one sentence; set whenever state is not "landed"
    done: int = 0
    failed: int = 0
    remaining: int = 0  # branches still not landed at the end (0 unless something stopped it)
    notes: tuple[str, ...] = field(default_factory=tuple)
    archived: int = 0  # branches kept as archive tags in this run
    quarantined: int = 0  # files moved to quarantine in this run

    @property
    def landed(self) -> bool:
        return self.state == "landed"

    @property
    def line(self) -> str:
        """The tile's one-line outcome."""
        if self.state == "landed":
            extra = []
            if self.archived:
                extra.append(f"{_n(self.archived, 'branch', 'branches')} archived")
            if self.quarantined:
                extra.append(f"{_n(self.quarantined, 'file')} quarantined")
            return "Landed" + (" · " + " · ".join(extra) if extra else "")
        if self.state == "nothing":
            return "Nothing to land"
        return f"Not landed: {self.reason}"


def _remaining(plan: LandPlan) -> int:
    """Branches with work not in the default branch."""
    try:
        return len(land_resolve.unlanded(plan.path, plan.name))
    except Exception:  # noqa: BLE001 - the count is a courtesy
        return 0


@dataclass(frozen=True)
class StepEvent:
    """One step starting or ending, in structured form, for a progress window.

    Spec `progress-windows` §8.3. Sent beside the text lines (which stay exactly
    as they are) at the start and end of every step Land runs. Plain values
    only, so it crosses the worker boundary as it is.
    """

    repo: str  # LandPlan.name: display data, never used as a path
    index: int  # 0-based: its place in plan.prep + plan.actions, or count + n for
    #              the n-th step Land added after planning (a later round, an archive)
    count: int  # len(plan.prep) + len(plan.actions)
    kind: str  # Action.kind as planned
    phase: str  # "start" | "end"
    at: float  # clock() when sent, seconds, monotonic
    started: float = 0.0  # end only: the matching start's `at`
    outcome: str = ""  # end only: "done" | "failed" | "skipped"
    label: str = ""  # Action.label, the same text as the progress line


def step_outcome(ok: bool, message: str) -> str:
    """done, skipped (a guard re-checked, or Stop) or failed. Stop during a
    Claude Code merge says "not landed — stopped" (`repo_tidy.apply`): skipped,
    not a failure."""
    if ok:
        return "done"
    text = (message or "").strip().lower()
    if text.startswith("skipped") or text == "not landed — stopped":
        return "skipped"
    return "failed"


MERGES = ("merge", "claude_merge")
ROUNDS = 3


class _Run:
    """One Land of one repo: counts, the first failure, and the log."""

    def __init__(self, plan: LandPlan, say, stop, log, busy, now,
                 tell=lambda _e: None, clock=time.monotonic) -> None:
        self.plan, self.say, self.stop, self.log = plan, say, stop, log
        self.busy, self.now = busy, now
        self.tell, self.clock = tell, clock
        planned = [(s.kind, s.label) for s in plan.prep] + [(a.kind, a.label)
                                                            for a in plan.actions]
        self.count = len(planned)
        self.slots: dict[tuple[str, str], list[int]] = {}  # (kind, label) -> unused indexes
        for index, key in enumerate(planned):
            self.slots.setdefault(key, []).append(index)
        self.added = 0  # steps run that were not in the plan
        self.done = self.failed = self.archived = self.quarantined = 0
        self.first_failure = ""
        self.stops: list[land_resolve.Stop] = []
        self.tried: dict[tuple[str, str], str] = {}  # (branch, sha) -> why it did not land
        self.notes: list[str] = []  # branches Claude chose to land (security P2-4)
        self.push_failed: set[str] = set()  # not pushed in this run: not retried (review P2-6)
        # (branch, sha) -> (kind, default, message): a merge that stopped for a
        # reason only a person can clear; never triaged or archived (land-fast §3)
        self.blocked: dict[tuple[str, str], tuple[str, str, str]] = {}
        self.blocker_stops: list[land_resolve.Stop] = []
        self.kept = {b.branch for b in repo_tidy.unlanded([(plan.name, plan.path)])
                     if land_resolve.kept(b)}  # restored by the owner: left alone

    @property
    def stopped(self) -> bool:
        return self.stop is not None and self.stop.stopped

    def _busy(self):
        return repo_tidy.busy_dirs() if self.busy == "fresh" else self.busy

    def _index(self, kind: str, label: str) -> int:
        """The planned step this one is (first unused match), else a new index
        after the plan, so a progress window can add it (spec progress-windows)."""
        free = self.slots.get((kind, label))
        if free:
            return free.pop(0)
        self.added += 1
        return self.count + self.added - 1

    def step(self, kind: str, label: str, apply) -> tuple[bool, str]:
        """Run one step, telling a progress window when it starts and ends."""
        index = self._index(kind, label)
        started = self.clock()
        self.tell(StepEvent(self.plan.name, index, self.count, kind, "start", started,
                            label=label))
        try:
            ok, message = apply()
        except Exception as exc:  # noqa: BLE001 - one failure must not hide the rest
            ok, message = False, f"failed — {type(exc).__name__}: {exc}"
        self.tell(StepEvent(self.plan.name, index, self.count, kind, "end", self.clock(),
                            started, step_outcome(ok, message), label))
        return ok, message

    def outcome(self, ok: bool, message: str) -> None:
        if ok:
            self.done += 1
            self.say(f"  → done: {message}")
        else:
            self.failed += 1
            self.first_failure = self.first_failure or plain_reason(message)
            self.say(f"  → not done: {message}")

    def prep(self) -> None:
        plan = self.plan
        steps, stops = land_resolve.prep(plan.name, plan.path, self._busy())
        self.stops += stops
        # Commit only what the confirmation listed (review P2-3).
        shown = {s.target: set(s.files) for s in plan.prep if s.kind in ("untracked", "switch")}
        steps = [dataclasses.replace(s, files=tuple(f for f in s.files
                                                    if f in shown.get(s.target, set())))
                 for s in steps]
        for step in steps:
            if self.stopped:
                return
            self.say(step.label)
            ok, message = self.step(step.kind, step.label, lambda step=step:
                                    land_resolve.apply_step(step, self.log, self._busy()))
            if ok and step.kind == "untracked":
                self.quarantined += len(step.quarantine)
            if not ok:
                self.stops.append(land_resolve.Stop(plan.name, step.target, plain_reason(message)))
            self.outcome(ok, message)

    def actions(self, first: tuple[repo_tidy.Action, ...] | None = None) -> int:
        """Plan (or take `first`) and apply; how many actions ran."""
        plan = self.plan
        if first is None:
            actions, _ = repo_tidy.plan_repo(plan.name, plan.path, self._busy(), self.now,
                                             plan.claude, plan.claude_why or "Claude Code not found",
                                             land_mode=True)
        else:
            actions = list(first)
        actions = [a for a in actions
                   if not (a.kind in MERGES and ((a.target, a.sha) in self.tried
                                                 or a.target in self.kept))
                   and not (a.kind == "push" and a.target in self.push_failed)]
        ran = 0
        for action in actions:
            if self.stopped:
                self.outcome(False, "skipped — stopped")
                break
            self.say(action.label)
            ok, message = self.step(action.kind, action.label, lambda action=action:
                                    repo_tidy.apply(action, self.log, self.busy, self.now,
                                                    claude=plan.claude, progress=self.say,
                                                    stop=self.stop))
            ran += 1
            # A plain merge that an earlier merge turned into a conflict is not
            # "tried": the next round plans a Claude merge for it (land-fast §3.5).
            conflicts_now = (action.kind == "merge"
                             and message.startswith("skipped — it now conflicts"))
            if action.kind in MERGES and not ok and not conflicts_now:
                self.tried[(action.target, action.sha)] = plain_reason(message)
                kind = claude_resolve.blocker_kind(message)
                if kind:
                    self.blocked[(action.target, action.sha)] = (kind, action.branch, message)
            elif action.kind in MERGES and ok:
                self.tried[(action.target, action.sha)] = ""
            if action.kind == "push" and not ok:
                self.push_failed.add(action.target)
            self.outcome(ok, message)
        return ran

    def blockers(self) -> None:
        """One stop for a default branch whose own tests fail (naming the
        branches waiting on it), one per branch with a protected-file conflict."""
        plan = self.plan
        self.stops = [s for s in self.stops if s not in self.blocker_stops]
        self.blocker_stops = []
        waiting: dict[str, list[str]] = {}
        why: dict[str, str] = {}
        for (branch, _sha), (kind, default, message) in self.blocked.items():
            if kind == "base":
                waiting.setdefault(default, []).append(branch)
                why.setdefault(default, message)
            else:
                self.blocker_stops.append(land_resolve.Stop(plan.name, branch,
                                                            plain_reason(message)))
        for default, branches in waiting.items():
            found = _ERROR_LINE.findall(why[default])
            detail = f" ({found[-1].strip()[:120]})" if found else ""
            self.blocker_stops.insert(0, land_resolve.Stop(
                plan.name, default,
                f"fix {default}'s own tests, then Land again: they fail in a clean copy"
                f"{detail}; waiting: {', '.join(sorted(branches))}"))
        self.stops = self.blocker_stops + self.stops

    def triage(self) -> None:
        plan = self.plan
        left = [b for b in land_resolve.unlanded(plan.path, plan.name)
                if (b.branch, b.sha) not in self.blocked]
        if not left or self.stopped:
            return
        if plan.claude is None:
            self.stops.append(land_resolve.Stop(
                plan.name, str(plan.path),
                f"{_n(len(left), 'branch', 'branches')} not landed and "
                f"{plan.claude_why or 'Claude Code not found'}: install or sign in to "
                "Claude Code, then Land again"))
            return
        _, skips = repo_tidy.plan_repo(plan.name, plan.path, self._busy(), self.now,
                                       plan.claude, plan.claude_why, land_mode=True)
        why_by_branch = {s.target: s.reason for s in skips}
        for info in left:
            if self.stopped:
                return
            why = (self.tried.get((info.branch, info.sha))
                   or why_by_branch.get(info.branch, "").removeprefix("not merged: ")
                   or "no merge path was found")
            self.say(f"{plan.name}: Ask Claude Code about {info.branch} — {why}")
            try:
                v = land_resolve.verdict(info, plan.claude, why, self.stop, self.say)
            except Exception as exc:  # noqa: BLE001
                v = land_resolve.Verdict(False, f"{type(exc).__name__}: {exc}", ok=False)
            if not v.ok:
                self.stops.append(land_resolve.Stop(
                    plan.name, info.branch,
                    f"Claude Code could not decide ({plain_reason(v.reason)}): Land again, "
                    "or decide in Review branches"))
                continue
            if v.land and self._land_one(info):
                self.notes.append(f"{plan.name}: {info.branch} — landed on Claude's verdict: "
                                  f"{v.reason}")
                continue
            if (info.branch, info.sha) in self.blocked:
                continue  # a stop only a person can clear, never an archive (§5.3)
            reason = (v.reason if not v.land
                      else f"could not be landed ({why}); Claude: {v.reason}")
            label = f"{plan.name}: Archive {info.branch} — {reason}"
            self.say(label)
            ok, message = self.step("archive", label, lambda info=info, reason=reason:
                                    land_resolve.archive(info, reason, self.log,
                                                         self._busy(), self.now))
            if ok:
                self.archived += 1
            else:
                self.stops.append(land_resolve.Stop(plan.name, info.branch,
                                                    f"not archived: {message}"))
            self.outcome(ok, message)

    def retry_busy(self) -> None:
        """Spec 4.5: a worktree busy at the start is tried once more at the end."""
        busy = [s for s in self.stops if s.reason.startswith("a process is running")]
        if not busy or self.stopped:
            return
        others = [s for s in self.stops if s not in busy]
        self.stops = []
        self.say(f"{self.plan.name}: trying the busy worktrees again")
        self.prep()
        self.stops += others  # a stop found now is the more basic reason: it goes first
        if self.actions():
            self.actions()

    def _land_one(self, info: repo_tidy.BranchInfo) -> bool:
        """Claude says land: try its merge once more if it was not tried at this tip."""
        if (info.branch, info.sha) in self.tried:
            return False
        actions, _ = repo_tidy.plan_repo(self.plan.name, self.plan.path, self._busy(), self.now,
                                         self.plan.claude, self.plan.claude_why, land_mode=True)
        mine = [a for a in actions if a.kind in MERGES and a.target == info.branch]
        if not mine:
            return False
        self.actions(tuple(mine))
        return self.tried.get((info.branch, info.sha)) == ""


def land(plan: LandPlan, *, progress=None, stop=None, log: Path | None = None,
         busy="fresh", now: float | None = None, events=None,
         clock=time.monotonic) -> LandResult:
    """Run the plan. Never raises; a failed step does not stop the ones after it
    (each re-checks its own guard), and the result says why in one sentence.

    Order (spec land-resolve-all §4, ADR 0001): prep steps; up to ROUNDS rounds
    of plan-and-apply (a branch committed in one round merges in the next);
    Claude's verdict on each branch still not landed; a last round for the
    push. "Landed" only when nothing is left open.
    `events`, if given, gets a `StepEvent` at the start and end of each step."""
    say = progress or (lambda _line: None)

    def tell(event: StepEvent) -> None:
        if events is None:
            return
        try:
            events(event)
        except Exception:  # noqa: BLE001 - a window must never stop a Land
            pass
    if not claim(plan.path):
        return LandResult(plan.name, "not_landed", "it is already being landed")
    try:
        claude_resolve.forget_base_failures(plan.path)  # each Land tests a failing tip once
        if plan.relinked:  # 4.1: restore the link even when nothing else is open
            land_resolve.repair_link(Path(plan.relinked), log)
        if plan.nothing:
            if plan.skipped:
                return LandResult(plan.name, "not_landed", plain_reason(plan.skipped[0].reason),
                                  remaining=_remaining(plan),
                                  notes=tuple(s.label for s in plan.skipped))
            return LandResult(plan.name, "nothing")
        if plan.stops and not (plan.path / ".git").exists():
            return LandResult(plan.name, "not_landed", plain_reason(plan.stops[0].reason),
                              notes=tuple(s.label for s in plan.stops))
        run = _Run(plan, say, stop, log, busy, now, tell, clock)
        run.prep()
        first = None if plan.prep or plan.relinked else plan.actions
        for _ in range(ROUNDS):
            if run.stopped or not run.actions(first):
                break
            first = None
        if not run.stopped:
            run.blockers()
            run.triage()
            run.actions()  # the push, and tidying what triage freed
            run.retry_busy()
            run.blockers()  # merges after triage can stop for a person too (review P2)
        remaining = _remaining(plan)
        left = land_resolve.open_items(plan.path)
        notes = tuple(s.label for s in run.stops) + tuple(run.notes)
        counts = dict(done=run.done, failed=run.failed, remaining=remaining, notes=notes,
                      archived=run.archived, quarantined=run.quarantined)
        if run.stopped:
            return LandResult(plan.name, "not_landed", "it was stopped", **counts)
        if run.stops or left:
            reason = run.stops[0].reason if run.stops else run.first_failure or left[0]
            if run.first_failure and remaining and not run.archived:
                reason = run.first_failure
            if run.stops and run.stops[0] in run.blocker_stops:
                reason = run.stops[0].reason
            return LandResult(plan.name, "not_landed", plain_reason(reason), **counts)
        return LandResult(plan.name, "landed", "", **counts)
    finally:
        release(plan.path)
