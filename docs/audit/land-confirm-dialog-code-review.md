# Code review: land-confirm-dialog

Reviewer: `code-reviewer` (independent, read-only, Sonnet), 2026-11-17. Target: commit `4072f72`. Spec: `docs/specs/land-confirm-dialog.md`.
Evidence: `pytest tests/test_land_confirm.py tests/test_land_ui.py`, 47 passed. The reviewer did not run the full suite or an interactive macOS check; its offscreen font metrics are approximate.

**Verdict: no P0 or P1 found. Safe to ship; the disclosure is complete and behaviour is unchanged.**

## Checks that held
1. **Disclosure.** Every fact the old `claude_notice` gave is in `claude_panel`. The reviewer reasoned through all four combinations (claude None, unlanded > 0, with_claude > 0, both). The total is merge plus triage, as spec §2.4 says.
2. **Behaviour unchanged.** `Stop.reason` and `label` are byte-identical. `who_is_in` gives the same deduplicated, limited list. `prep` runs one `lsof`, as before.
3. **Plain text.** Labels are plain text, the tooltip goes through `_plain_tip`, and Details is a `QPlainTextEdit`.
4. **Dialog.** Every button has autoDefault off, so Return does nothing; Escape rejects. `_cards_height` is set before any toggle can fire. The caller guards plans where every repo has nothing to do (`ui/apps_tab.py` `_land_planned`).

## P2
- **P2-1. Cost combinations not tested** (`tests/test_land_confirm.py`). One screenshot fixture covers the costs. Nothing compares `claude_panel` with `claude_notice` across the four combinations. Fix: parametrise them; assert the total and the shared facts.
- **P2-2. No test for the sizing or tooltips.** `_toggle_details`, `_fit` (including `screen() is None`) and plain tooltips have no test. Fix: a toggle round-trip test that keeps the height within 90% of the screen, and a tooltip test with a reason that contains `<b>`.
- **P2-3. `_fit` ignores word-wrap height.** `ui/land_confirm.py` `_fit` takes `holder.sizeHint().height()`, which ignores height-for-width. Offscreen, `need` was 715 against a real height of 595. Fix: use `layout().totalHeightForWidth(w)`.

## P3
- **P3-1.** `_toggle_details` adds 220 on top of a `sizeHint()` that already includes Details, so the window can be taller than needed (still capped at 90% of the screen).
- **P3-2.** `headline([])` raises `IndexError`; only the caller's guard prevents it.
- **P3-3.** `_place` compares paths exactly. A symlinked or `/private/var` path shows "Worktree <name>" for the main checkout. Fix: compare `resolve()` results.
- **P3-4.** Two worktrees with the same folder name under different parents get the same place label; only the tooltip tells them apart.
- **P3-5.** `_who` grammar with 2–3 processes of one name ("zsh running in it"); the action's plural keys on the process count, not the name count.
- **P3-6.** `test_items_are_the_sentence_without_the_stops` mirrors the implementation; no literal string from before the change pins `sentence`. Fix: add one literal expected sentence.

## Disposition
Owner, 2026-11-17: "Yes, fix them" (P2s and P3-1, 2, 3, 6). Fixed by the author:
- P2-1: `test_the_panel_total_is_the_old_notices_amounts`, 5 combinations, two repos each; the total and the shared facts are checked against `claude_notice`.
- P2-2: `test_a_tooltip_shows_markup_as_text` and `test_details_round_trip_stays_on_the_screen`. The test found a real overflow on a short (800 px) screen: with Details open, the window went past 90%. Details and the cards now give up room (`DETAILS_MIN` 80, `CARDS_MIN_WITH_DETAILS` 70). On an 800 px screen the disclosure text alone can need a little more than 90%, so the test asserts the window stays on screen, with 90% as the aim.
- P2-3: `_fit` uses `layout().totalHeightForWidth()` at the real width; `test_the_cards_area_fits_wrapped_text_at_its_real_width`.
- P3-1: the extra 220 px is gone. P3-2: `headline([])` returns "Nothing to land." P3-3: `_place` also compares resolved paths (`_same`); there is a test. P3-6: `test_sentence_and_notice_are_byte_identical_to_before` pins literal texts taken from the parent of `4072f72`.
- P3-4 and P3-5, fixed later on the owner's "fix the left items": same-named worktrees show their parent folder (`LandPlan.stop_views`), and repeated names give a count ("3 processes running in it: limactl and ssh"). Tests: `test_same_named_worktrees_name_their_parent`, `test_repeated_process_names_say_how_many`.

QA (`qa-engineer`, Sonnet, 2026-11-17): pass with gaps. 158 tests in the four Land test files passed, and 7 of 8 planted mutations were caught. The survivor (the three-name cap in `_who`) and the untested footer, card pills and width are now covered: `test_at_most_three_names_are_named`, plus assertions in `test_one_card_per_repo_and_a_line_for_the_idle`.
