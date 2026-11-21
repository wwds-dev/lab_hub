# Review: land-network-preflight (2026-11-21)

Reviewer: `code-reviewer` (read-only, independent of the author). Saved by the orchestrator because the reviewer had no write tool. No P0, no P1.

| # | Sev | Finding | Outcome |
|---|---|---|---|
| 1 | P2 | Stop was ignored by the preflight (up to 15 s, wrong reason) | Fixed: `land()` returns "it was stopped" before the check; test added |
| 2 | P2 | Tests never exercised the timeout, unknown default branch, stop or stops-only paths | Fixed: four tests added |
| 3 | P3 | "nothing was started" over-claims when `repair_link` ran first | Fixed: sentence is now "no merge or test was started" |
| 4 | P3 | Failed result dropped the plan's hard-stop notes | Fixed: `notes` kept; test added |
| 5 | P3 | Offline cleanup/prep-only plans are now blocked too | Not changed. The owner approved "local merges also wait"; cleanup-only is not named. Open for the owner (TODO) |
| 6 | P3 | One sentence for every `ls-remote` failure (dead or renamed remote blocks every Land, no override) | Not changed. Git's error is in the Land log; open for the owner (TODO) |
| 7 | P3 | Empty ref sent when the default branch is unknown | Fixed: ref added only when known; test added |

Not verified by the reviewer: the multi-repo loop and the row display in the UI; the full suite.
