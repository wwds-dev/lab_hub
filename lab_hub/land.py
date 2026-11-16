"""Land one repo's work in one go: plan, say it in a sentence, run it, say how it went.

Spec: `docs/specs/land-from-tiles.md`. This is the front end of `repo_tidy`: the
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

import re
import threading
from dataclasses import dataclass, field
from pathlib import Path

from . import repo_tidy

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

    @property
    def with_claude(self) -> int:
        return sum(1 for a in self.actions if a.kind == "claude_merge")

    @property
    def nothing(self) -> bool:
        return not self.actions

    @property
    def sentence(self) -> str:
        """What Land will do, for the one confirmation."""
        if not self.actions:
            why = self.skipped[0].reason if self.skipped else "nothing is waiting"
            return f"{self.name}: nothing Land can do on its own ({why})."
        by: dict[str, list[repo_tidy.Action]] = {}
        for action in self.actions:
            by.setdefault(action.kind, []).append(action)
        parts = []
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
        return f"{self.name}: " + ", ".join(parts) + "."

    @property
    def claude_notice(self) -> str:
        """The disclosure the old Resolve dialog gave, kept: it is a real data flow."""
        if not self.with_claude:
            return ""
        from . import claude_resolve

        cap = claude_resolve.BUDGET_USD
        tests = sorted({a.detail for a in self.actions if a.kind == "claude_merge" and a.detail})
        return (
            f"{self.with_claude} branch{'es' if self.with_claude != 1 else ''} will be sent to "
            f"Claude Code (model {claude_resolve.MODEL}, at most ${cap:.0f} each, "
            f"${self.with_claude * cap:.0f} in total). Code from "
            "this repo goes to Anthropic, as in any Claude Code session. Lab Hub runs the "
            f"repo's tests itself ({'; '.join(tests) or 'its test command'}); a merge that "
            "passes them lands and is pushed without review. A branch that fails stays "
            "exactly as it is."
        )

    @property
    def detail(self) -> str:
        lines = [f"{self.name} is {self.path}", ""] + [a.label for a in self.actions]
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
    if not path.is_absolute() or not (path / ".git").exists():
        return LandPlan(name, path, (), (repo_tidy.Skip(name, str(path), "not a git checkout"),))
    if busy == "fresh":
        busy = repo_tidy.busy_dirs()
    actions, skips = repo_tidy.plan_repo(name, path, busy, now, claude or None, why)
    skips = [s for s in skips if s.reason != "level with origin"]
    return LandPlan(name, path, tuple(actions), tuple(skips), claude or None)


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
    remaining: int = 0  # branches with unlanded work that Land left for the owner
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def landed(self) -> bool:
        return self.state == "landed"

    @property
    def line(self) -> str:
        """The tile's one-line outcome."""
        if self.state == "landed":
            tail = (f" · {_n(self.remaining, 'branch', 'branches')} "
                    f"need{'s' if self.remaining == 1 else ''} your decision"
                    if self.remaining else "")
            return f"Landed{tail}"
        if self.state == "nothing":
            return "Nothing to land"
        return f"Not landed: {self.reason}"


def _remaining(plan: LandPlan) -> int:
    """Branches with unlanded work that Land left for the owner to decide."""
    try:
        return len(repo_tidy.unlanded([(plan.name, plan.path)]))
    except Exception:  # noqa: BLE001 - the count is a courtesy
        return 0


def land(plan: LandPlan, *, progress=None, stop=None, log: Path | None = None,
         busy="fresh", now: float | None = None) -> LandResult:
    """Run the plan. Never raises; a failed step does not stop the ones after it
    (each re-checks its own guard), and the result says why in one sentence."""
    say = progress or (lambda _line: None)
    if not claim(plan.path):
        return LandResult(plan.name, "not_landed", "it is already being landed")
    try:
        if plan.nothing:
            if plan.skipped:
                return LandResult(plan.name, "not_landed", plain_reason(plan.skipped[0].reason),
                                  remaining=_remaining(plan),
                                  notes=tuple(s.label for s in plan.skipped))
            return LandResult(plan.name, "nothing")
        done = failed = 0
        first_failure = ""
        for action in plan.actions:
            say(action.label)
            try:
                ok, message = repo_tidy.apply(
                    action, log, busy, now, claude=plan.claude, progress=say, stop=stop)
            except Exception as exc:  # noqa: BLE001 - one failure must not hide the rest
                ok, message = False, f"failed — {type(exc).__name__}: {exc}"
            if ok:
                done += 1
                say(f"  → done: {message}")
            else:
                failed += 1
                first_failure = first_failure or plain_reason(message)
                say(f"  → not done: {message}")
        remaining = _remaining(plan)
        notes = tuple(s.label for s in plan.skipped)
        if failed:
            return LandResult(plan.name, "not_landed", first_failure, done, failed,
                              remaining, notes)
        return LandResult(plan.name, "landed", "", done, 0, remaining, notes)
    finally:
        release(plan.path)
