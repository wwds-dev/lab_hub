# Spec: status rows on app tiles instead of one yellow line

Needs: define (owner approval of this spec)

Status: Phase Define (`product-manager`), drafted 2026-11-23 in `lab_hub`. Nothing built.
In-flight check (`session_start.py --inflight`, 2026-11-23): no spec owns the tile's version
or badge text. `land-from-tiles` (document done) owns the Land button and the outcome line;
this spec changes only the Land button's label (a count), never its behaviour. `tile-resolve`
is superseded.

## 1. Problem and evidence
The owner (2026-11-23, screenshot of the Apps page): "i dont like how the info in the yellow
font is shown." Today one tile can carry three different facts in the same yellow:
- the version line with a suffix: `v2.447+g96b469c · 3 behind` (`ui/apps_tab.py`
  `refresh_version`, restyled `stateWarn` when stale), and `-dirty` inside the marker;
- the hygiene badge: `1 branch · 2 worktrees to land` (`refresh_hygiene`, `stateWarn`).
They read as one warning. "behind" and "-dirty" are jargon, the version ID turns yellow, and
a tile with nothing to do looks the same as one that was never checked.

The owner approved the direction from a mockup in this session ("much better. build it").

## 2. User and success measure
User: the owner, on the Apps page.
1. The version line is always the neutral hint style and holds only the ID
   (`v2.447+g96b469c`): no "· N behind", no `-dirty` suffix (test).
2. Under it, a status block shows one row per fact, each with a leading symbol and plain words:
   - stale build: "Installed build is N commits old" (1: "1 commit old"; count unknown:
     "Installed build is older than its source"), with a **Check builds** link that opens the
     page's existing Check builds report;
   - work to land: the existing badge words, as "1 branch · 2 worktrees waiting to land";
   - dirty source: "Uncommitted changes in source" when the installed build was made from a
     dirty checkout (`found.dirty`);
   - "repo not readable" stays as its own row, in the bad style.
   Tests assert the rows for a stale + dirty + landing fixture, and for each fact alone.
3. Only the symbol carries the colour (accent for update, warning for land and uncommitted,
   bad for unreadable); the words stay in the secondary text colour (test reads the style
   names, screenshot shows it).
4. When the version is known, not stale, and the hygiene report has a row for the repo that
   needs nothing, the block shows one row "Up to date, nothing to land" with a success symbol.
   When there is no evidence (no report row, or version unknown), the block is empty: the tile
   never claims "up to date" without evidence (test).
5. The Land button reads "Land (N)" where N is the number of things the badge counts; plain
   "Land" when it cannot count; "Landing…" while running, as today (test).
6. Lab Hub's own tile (`OwnCard`) follows the same rule: its "behind" moves out of the version
   line into a status row (test).
7. Tooltips keep today's full wording (they hold the detail the rows shorten).
8. Screenshot of the real Apps page in light and dark after the change, tiles still aligned.

## 3. Scope
- `ui/apps_tab.py`: `AppCard` gets a status block (QVBoxLayout of row widgets) replacing the
  stale suffix and the hygiene label; `OwnCard` uses it for "behind"; Land label count.
- `lab_hub/hygiene.py`: a `land_count` property next to `badge` (sum of the counted items).
- `ui/theme.py`: styles for the symbol colours if the existing `stateOk/Warn/Bad` do not fit.
- Tests next to the existing apps-tab tests; README line if it describes the tile; CHANGELOG.

## 4. Non-goals
- No per-tile Update or rebuild action: the link opens the existing all-apps Check builds.
- No change to what Land, Check builds or the hygiene report do or count.
- The app path and the background-service line stay where they are (the mockup moved the
  service line; left for a follow-up so the reserved-height alignment is not reopened here).

## 5. Design notes (`ux-designer`)
Symbols are text glyphs so they need no icon assets: ↓ update, ⇄ land, ✎ uncommitted,
✕ unreadable, ✓ up to date. Rows are 13 px, 2 px apart, inside the tile's existing `meta`
layout under the version. Sentence case, no terminal punctuation.

## 6. Architecture (`architect`)
No new state, threads or files: rows are rebuilt from the same `launcher.version` result and
`hygiene.RepoRow` the tile already reads, on the same calls (`refresh_version`,
`refresh_hygiene`). No gate needed.
