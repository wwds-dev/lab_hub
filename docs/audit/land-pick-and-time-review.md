# Review: land-pick-and-time (Build, uncommitted)

Reviewer: code-reviewer (read-only subagent), 2026-11-18. Saved by the orchestrator. No P0/P1.

## P2
- **P2-1** Unticked card name not dimmed (`ui/land_confirm.py` `_toggled`): the stylesheet's `QWidget` colour beats the disabled palette. **Fixed**: the name switches to object name `hint` while left out. Test still checks only `isEnabled()` (not the rendered colour): open.
- **P2-2** No test for a nothing-to-land plan with a partial choice (`ui/apps_tab.py` `_land_planned`, `or (p.nothing and ids)`). **Open.**

## P3
- **P3-1** "Earlier" line uses commas; the spec text uses " · ". Open (match spec or owner approves commas).
- **P3-2** A stopped row keeps tone warn and counts as "needs you"; §8.2 said tone muted. Open.
- **P3-3** Month names follow the system locale after `QApplication` sets it. Open (fixed English month names).
- **P3-4** A Land all with nothing to do was logged as a 0-repo run. **Fixed** (`LandWindow.finish` records only when a repo ran). No test yet.
- **P3-5** Folding cards leaves blank space (`_sync` does not refit). Open.
- **P3-6** Land all narrowed to one repo with no actions opens no window. Open.
- **P3-7** Opened rows keyed by repo name; duplicate names open together. Open.
- **P3-8** Header toggles on any left-button release, even dragged off. Open.
- **P3-9** No end-to-end test from the real dialog's `chosen()` to `lander.run`. Open.

Confirmed correct: the disclosure matches what runs; left-out repos neither run nor stick; no double run record; status words stay bare for Ask Claude; Check builds' `Row.took` untouched; ClaudeBox replace and opener signals safe; run log never raises; names plain text; no existing assertion weakened.
