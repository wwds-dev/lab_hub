# Review: tile-check-build (code-reviewer, independent, 2026-11-24)

0 P0, 1 P1, 2 P2, 2 P3; all fixed the same day.
- P1-1 Lab Hub's own tile with `self_status` raising opened an empty window headed "All 0 apps are the newest build": now a message box with the error and no window (test added).
- P2-1 the button showed on launchable tiles with no install and no checkout, against spec §2.5 and the README: now hidden when readiness is "missing" (tests added).
- P2-2 the landing disable ignored the per-repo claim from another card or page: now also checks `land.landing(row.path)` and re-syncs on `refresh_hygiene` (test added).
- P3-1 tests did not drive the real `clicked(bool)` connection: a test now clicks the page button; the page-level test mocks `self_status`.
- P3-2 the `scope`/`own_only` conditional was hard to read: now an explicit `if/elif/else`.
Not run by the reviewer: the full suite, the running app. Verify (qa-engineer) not run; the author mutation-checked five mutants (scope ignores `only`, own_only dropped, button for all, no disable while landing, `*_checked` removed), all killed. Full suite: see the commit.
