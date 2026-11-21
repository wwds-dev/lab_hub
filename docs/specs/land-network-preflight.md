# Spec: Land checks the network before it starts any slow work

Status: **Define, waiting for the owner's approval (2026-11-21).**
In-flight check (`session_start.py --inflight`, 2026-11-21): no spec or worktree touches a network check in Land. The `land-*` specs in flight (`land-live-session-guard`, `land-update-gaps`, `land-pick-and-time`, …) touch other parts of `land.py`; Build must be rebased on them and must not edit their code paths beyond the one call below.

## 1. Problem and evidence
The owner, 2026-11-21 01:05: "it took 50 minutes to tell me that it failed?"
- Landing 9 repos, imprint ran its merge, a Claude conflict resolution and the full test suite (about 50 minutes) before its push step reported `could not fetch: … Failed to connect to github.com port 443 after 1036 ms`.
- The only network call is `git fetch` in the push guard (`repo_tidy.py:999-1002`, and the pull path at `repo_tidy.py:1088`). It runs last, so an outage that was already there at the start is found after all the slow work.
- GitHub answered again minutes later (`git ls-remote origin main` succeeded), so this was a short outage. The merge was done locally; nothing was lost except 50 minutes of not knowing.

## 2. User and success measure
User: the owner, pressing Land.
1. **No network at the start:** each repo that has an `origin` and has work to do stops in seconds, before prep, merge, Claude or tests, with one plain sentence: "cannot reach origin (no network?): nothing was started". Its row shows as needing attention, not as a failure of the repo's code.
2. **Network fine:** behaviour and timing unchanged apart from at most one quick `ls-remote` per repo (about 1 s).
3. **Repos with no `origin`, or with nothing to land:** no check, no change.
Measured by tests: a fake `origin` that refuses connections makes `land()` return `not_landed` with the sentence above and run no prep, merge, Claude or test step; a reachable `origin` runs the plan as before; a repo with no `origin` is not checked.

## 3. Scope and open questions
- **In:** one preflight per repo at the start of `land()`; the message; tests.
- **Not changed:** the late `could not fetch` guard in the push step stays (the network can drop mid-run).
- **Decision for the owner:** if the network is down for *all* repos, each repo fails on its own in about 15 s (one timeout each, at most 9 × 15 s ≈ 2 min). A shared answer ("the first repo failed: stop all") would be faster but changes how the run loop treats repos. Proposed: keep per-repo, simple; say so if you want the shared stop.
- **Decision for the owner:** a repo whose branches could merge locally without the network is also stopped. Proposed: yes, because the push at the end needs the network anyway and a half-landed repo is worse than a waiting one.

## 4. Design
`land()` runs `repo_tidy.git(path, "ls-remote", "--exit-code", "--heads", "origin", default, timeout=PREFLIGHT_TIMEOUT)` (new constant, 15 s) right after the `plan.nothing` and missing-`.git` returns and before `_Run.prep()`. Skipped when the repo has no `origin` remote. On failure it returns `LandResult(name, "not_landed", "cannot reach origin (no network?): nothing was started")` and logs git's own error line to the Land log. The claim is released by the existing `finally`. No new state, threads or boundaries; no ADR. The sentence goes through `plain_reason`; no new UI element, so no Design phase beyond the wording above.

## 5. Phases
Define (this, GATE: user-visible message), Build, Review, Verify, Document (CHANGELOG, README Land section if it lists failure messages). Skipped: Case, Architect (no state/concurrency/boundary), Secure (adds one read-only `git ls-remote` of the owner's own remotes; no secrets, input or file writes; Build notes this in the review), Comply and Launch (tier `public`, no new claim or data), Release (owner's call).
