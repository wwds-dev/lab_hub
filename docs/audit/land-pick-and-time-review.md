# Review: land-pick-and-time (Build, uncommitted)

Reviewer: code-reviewer (read-only subagent), 2026-11-18. Saved by the orchestrator. No P0/P1.

## P2
- **P2-1** Unticked card name not dimmed (`ui/land_confirm.py` `_toggled`): the stylesheet's `QWidget` colour beats the disabled palette. **Fixed**: the name switches to object name `hint` while left out. Test: `test_land_confirm::test_a_left_out_name_takes_the_hint_style_and_gets_it_back`.
- **P2-2** No test for a nothing-to-land plan with a partial choice (`ui/apps_tab.py` `_land_planned`, `or (p.nothing and ids)`). **Fixed** (test only): `test_land_ui::test_a_partial_choice_keeps_the_nothing_to_land_rows_in_plan_order`.

## P3
- **P3-1** "Earlier" line uses commas; the spec text uses " · ". **Kept, for the owner:** commas inside a run, " · " between runs; the spec's " · " everywhere makes three runs one undivided chain. Spec §9 records it.
- **P3-2** A stopped row keeps tone warn and counts as "needs you"; §8.2 said tone muted. **Fixed** (tone muted; the count is unchanged): `test_progress::test_a_stopped_row_is_muted_not_amber`.
- **P3-3** Month names follow the system locale after `QApplication` sets it. **Fixed** (`progress.MONTHS`): `test_progress::test_month_names_stay_english_whatever_the_locale`.
- **P3-4** A Land all with nothing to do was logged as a 0-repo run. **Fixed** (`LandWindow.finish` records only when a repo ran): `test_progress_window::test_a_land_where_nothing_ran_is_not_logged`.
- **P3-5** Folding cards leaves blank space (`_sync` does not refit). **Fixed** (`_refit`): `test_land_confirm::test_folding_cards_gives_their_room_back`.
- **P3-6** Land all narrowed to one repo with no actions opens no window. **Fixed** (decided on the plans before the choice): `test_land_ui::test_land_all_narrowed_to_one_repo_still_opens_the_window`.
- **P3-7** Opened rows keyed by repo name; duplicate names open together. **Fixed** (by index): `test_progress_window::test_two_rows_with_the_same_name_open_one_at_a_time`.
- **P3-8** Header toggles on any left-button release, even dragged off. **Fixed** (release must be inside): `test_land_confirm::test_a_press_dragged_off_the_header_does_not_toggle`.
- **P3-9** No end-to-end test from the real dialog's `chosen()` to `lander.run`. **Fixed** (test): `test_land_ui::test_the_real_dialog_choice_is_what_runs_and_what_is_disclosed`.

Confirmed correct: the disclosure matches what runs; left-out repos neither run nor stick; no double run record; status words stay bare for Ask Claude; Check builds' `Row.took` untouched; ClaudeBox replace and opener signals safe; run log never raises; names plain text; no existing assertion weakened.
