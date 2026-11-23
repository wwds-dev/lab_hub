# Spec: Apps finds new projects and shows Lab Hub itself

Needs: define, design, architect, build, review, verify, secure, docs

Status: **Define approved by the owner 2026-11-21 ("Approve as recommended"): all six §11 recommendations and the §7 wording.** Design (§12) and Architect (§13, ADR 0007) written 2026-11-21, **Architect gate approved by the owner 2026-11-21 ("Approve as recommended": every §14 recommendation, ADR 0007 accepted)**. Next: Build. Written 2026-11-21 from the owner's request of the same day. No code written.
In-flight check (`session_start.py --inflight`, 2026-11-21): none of the 20 unreleased specs covers project discovery or a Lab Hub tile. Touching ones, all compatible:
- `self-update` (§1-§3, Amendment 1) gave Lab Hub a **build row** in Check builds (`self_update.SELF`, `lab_hub/self_update.py:64-71`, comment "Never registered: no tile"). This spec adds a tile and leaves that row and Update now unchanged; Build amends only the comment.
- `land-from-tiles` made the Land button and the "N to land" badge part of every tile; the new tiles reuse them unchanged.
- `tile-resolve` (superseded), `land-blocker-actions`, `land-protected-conflict`, `progress-windows`: other parts of Land and the Land window; no shared code path.
Other worktrees (`blissful-newton-43a5f3`, `intelligent-wright-6029ac`) hold no `apps-discovery` branch (`session_start.py --inflight`).

## 1. Problem and evidence
The owner, 2026-11-21: the Apps section should get new projects automatically or ask whether to add them; Kaila is missing; Lab Hub itself should be a tile, at least one with no launch button.

**How the list is made today.** A tile exists only because someone typed an entry into `lab_hub/lab_hub/apps.toml` (`lab_hub/launcher/registry.py:1-20`, `apps.toml:1-4`: "Add an app here and press Refresh"). Nothing looks at the folders. Five fields are required (`registry.py:107`: key, name, project, entry, summary), so an app with no launch script cannot be listed at all.

**What is on the Apps page versus the lab folder** (`ls /Users/as/Documents/lab/active`, `.git` and `docs/foundry/app-context.md` checked per folder, 2026-11-21):

| Folder | Own repo (`.git` dir) | Foundry app-context | In `apps.toml` | Verdict |
|---|---|---|---|---|
| sentinel, imprint, sonar, provisio, syndustryx, backstage | yes | yes | Apps (suites) | shown |
| backup_manager, git_autosync | yes | yes | Backup and Sync | shown there |
| toolbox/unblock_tracker | yes (submodule) | n/a | Utilities | shown there |
| **kaila** | yes | yes | **no** | **gap** |
| **overseer** | yes | yes | **no** | **gap** |
| **shopfront** | yes | yes | **no** | **gap** |
| lab_hub | yes | yes | no | gap: the owner's second ask |
| foundry | yes | **no** (it is the factory, `foundry/README.md`: "Nothing here belongs to any one app") | no | not an app |
| toolbox | yes | no (container of three submodules; `toolbox/README.md`) | no | not an app |
| imprint-base, imprint-deps | **no: `.git` is a file** (a linked worktree of imprint) | yes (copied) | no | helper checkouts, must be ignored |

**The gap is not cosmetic.** Land all counts repos from git_autosync's report, not from tiles (`ui/apps_tab.py:1151-1153`, `_attention_rows`). That report already tracks kaila, overseer, shopfront and foundry (`git_autosync/hygiene.json`, 23 rows, generated 2026-11-21 02:16 UTC). So today Land all can land Kaila, but no tile shows why: Kaila has one unmerged branch (`lab-hub/rescue-20261121-9f75ef23`, `problems: ["1 branch not merged into main"]`) and Foundry has an uncommitted file, and neither has a place on any page. `Land all (4)` counts rows the owner cannot see.

## 2. User and success measure
User: the owner, opening the Apps page.
1. **New project, one question.** A folder directly under the lab folder that is a project the registry does not know produces exactly one suggestion. Pressing Add gives it a tile on the next refresh with no restart; pressing Not now or Never hides it as in §4.4. Today's expected suggestions: Kaila, Overseer, Shopfront HQ, and nothing for foundry, toolbox, imprint-base, imprint-deps or lab_hub.
2. **No nagging.** A folder the owner dismissed is not suggested again (Never: ever; Not now: for 14 days). Asking costs no git call and no network: file existence checks only.
3. **A project with no launch command gets a real tile**, not an error: name, summary, version and repo state, Land and Ask Claude where they apply, and **no Launch button, no menu-bar entry and no Check builds row**. Kaila is the first such tile.
4. **Lab Hub is a tile**, with the running build, repo state and Land; **no Launch, Bring to front, Stop or Quit**.
Measured by tests (§6). The Kaila tile and the Lab Hub tile get a screenshot before and after on the real Mac at Verify.

## 3. Does adding Kaila make sense? Yes, as a tile with no run button
What a Lab Hub tile needs (`ExternalApp`, `registry.py:44-90`): a project folder, a name and a summary. Everything else is optional or derived: a launch entry (`entry`, today required), a build command, a URL, a service name. There is **no tier field** (grep `tier` in `lab_hub/launcher/`: none); a tier is not needed.
What Kaila supplies today (`kaila/`, read 2026-11-21): folder with `.git`; `README.md` whose first paragraph describes it; `VERSION` (`2`); `docs/foundry/app-context.md` (tier commercial, "No UI: CLI (`python -m kaila`)"); no `main.py`, no bundle, no build script ("Build / package: none", `app-context.md` Commands).
What the tile would give the owner, with no launch command: the repo state Land already sees (unmerged branch above), a Land button, Ask Claude, Open in Terminal, and the version line. That is the part of Lab Hub Kaila can use now. A Launch button would have nothing to start: do not invent one. When Kaila gets a window or a build script, one line in the registry adds the button.
**Recommendation: add Kaila** (and decide Overseer and Shopfront HQ at the prompt; each is the same case: Overseer is pre-build, Shopfront has a dashboard but no single entry script).

## 4. Decisions in this spec (recommendation first; the owner changes any of them)

### 4.1 How a project is detected
A folder is a **candidate** when all hold, checked by file existence only:
- it is a direct child of the lab folder (`config.resolved_lab_root()`), so worktrees under `.claude/worktrees` and nested repos are never scanned;
- its name does not start with `.` or `_`, and it is a real directory inside the lab folder (a symlink pointing elsewhere is skipped);
- `<folder>/.git` is a **directory** (a `.git` file marks a linked worktree: imprint-base, imprint-deps);
- `<folder>/docs/foundry/app-context.md` exists (Foundry's marker for "an app"; excludes foundry and toolbox, and every folder that is not a project);
- it is not already registered: no entry in any group of the registry has the same resolved `project` path, and no entry's project lies inside it; not `lab_hub` itself (its tile is §5); not dismissed (§4.4).
Alternative considered: scanning for `AGENTS.md` alone. Foundry has one and so would toolbox's future members; the app-context marker is the one that separates apps from tooling. Alternative considered: reading `foundry/apps.md` (Foundry's list of installed apps). It is Foundry-owned and may lag; the folder is the truth Lab Hub already reads for everything else.
**When:** at startup and on Refresh (⌘R), the same moments `apps.toml` is read. No button, no timer.

### 4.2 Ask first, not automatic
**Recommendation: ask first.** Reasons: (a) a tile also adds a menu-bar entry and Check builds row for anything with a launch command, and Overseer (pre-build) or a scratch repo would put a dead entry in front of every launch; (b) the owner's own wording allows it; (c) a wrong guess costs one click, a silent tile costs a hunt. The prompt is one inline banner at the top of the Apps page, not a dialog, so it never blocks Launch or Land.

### 4.3 Where the answers live
**Recommendation: `~/Library/Application Support/Lab Hub/apps-local.toml`** (the folder Lab Hub already keeps all state in, `config.py:1-11`), not `lab_hub/lab_hub/apps.toml`. `apps.toml` is a tracked file in Lab Hub's own repo: a running app writing it would dirty the repo and race with sessions that edit it. The local file uses the same format and fields, is read after `apps.toml`, and its entries join the Apps section after the hand-written ones. A key or project that `apps.toml` already lists wins; the duplicate local entry is ignored with a note in `registry.last_error`, never an error that empties the hub.
Dismissals: `~/Library/Application Support/Lab Hub/apps-dismissed.json`: `{"<folder name>": {"answer": "never"|"not_now", "at": "<ISO date>"}}`. A broken or missing file reads as "nothing dismissed" and never blocks the app.
Alternative: append to `apps.toml` (one source of truth, visible in git). Rejected for the reasons above; the owner can move a block into `apps.toml` by hand any time, and the local copy then yields.

### 4.4 The three answers
- **Add to Apps**: writes the entry (§4.5) to `apps-local.toml`, rereads the registry, the tile appears.
- **Not now**: not asked again for 14 days.
- **Never for this folder**: never asked again. Settings gets a short list "Hidden projects" with a Show again button per folder, so the answer is reversible without editing a file.

### 4.5 What an added entry contains
Derived, nothing asked: `key` = folder name; `project` = folder name; `name` = the first `# ` heading of `README.md`, else the folder name (Kaila, Overseer, Shopfront HQ); `summary` = the README's first paragraph cut at its first sentence, at most 220 characters, shown as plain text (it is file content, not markup); `entry` = `main.py` if the folder has one, else none. An entry with no `entry` is a **no-launch** project (§4.6). No build command is guessed.

### 4.6 A project with no launch command
`entry` becomes optional in the registry (still required for every entry in `apps.toml` that today has one; the 9 existing entries are unchanged and a test asserts it, like `test_registry.py`'s "shipped list keeps every registered app"). For an app without `entry`:
- the tile shows name, summary, the version line (VERSION arc and build from git, as `checkout_version` does), repo state, Land, Ask Claude, Open in Terminal;
- it has **no Launch button**, no Stop, no "running" state, no tray or menu-bar entry (`menu_bar_apps` excludes it), and no Check builds row (nothing builds it unless it has `build`/`build_output`, which an added entry never does);
- Settings' "found source folders" count and the self-test skip the launch checks for it.
It sits in the Apps section after the launchable apps.

## 5. Lab Hub's own tile
Built in code, never in a registry file (it must not be hidable or editable by mistake); same no-launch kind as §4.6.
**Shows:** the name "Lab Hub" and a one-sentence summary (§7); the **running build** as the window title shows it (`version.version_string()`, e.g. `v2.208`, with the commit and date in the tooltip, from `version.info()`; no git call on repaint, it is cached); the **build row verdict** from `self_update.build_status(SELF)` ("up to date" or "N commits older than its source"; runs from source: "runs the checkout directly", as `self-update` §2.7); the repo badge and **Land** like any tile, from the `lab_hub` row of the hygiene report; Ask Claude and Open in Terminal.
**Must not offer:** Launch, Bring to front, Stop, Quit, a second window, a menu-bar or tray entry for itself, or its own Update now button (Check builds owns the update and its running-work guard; the tile may say "behind: use Check builds" and nothing more). It never counts itself in "Check builds" twice: the tile reads the existing row.
**Position:** last in the Apps section, after the launchable and no-launch tiles. It is the window the owner is already in, not a destination.

## 6. Tests (success measure)
- Temp lab folder with: a registered app, a new git folder with `docs/foundry/app-context.md` → exactly one suggestion; the same folder after Never → none, after Not now → none until 14 days pass (injected clock); a `.git` **file** folder → none; a folder without app-context → none; `.hidden`, `_x`, a symlink to outside → none; `lab_hub` → none; a worktree under `.claude/worktrees` → not scanned; two refreshes in a row → still one suggestion.
- The scan makes no subprocess call (patched `subprocess` raises).
- Add writes `apps-local.toml`, and a reread shows the tile; a broken local file leaves the list as it was and reports why; a key clash with `apps.toml` yields to `apps.toml`.
- No-launch entry: parses, builds a card with no Launch button, not in `menu_bar_apps`, not in the build report; the 9 shipped entries parse and read exactly as before.
- Lab Hub tile: present, last; no Launch/Stop button; shows the version string and the verdict; Land is offered when the `lab_hub` hygiene row needs attention.
- Mutation check on the detection rules (drop each condition, one test must fail).
- Real run on the Mac at Verify: Kaila's tile and Lab Hub's tile, screenshots.

## 7. User-visible wording (the owner approves these exact words)
- Banner, one row per project: "New project in your lab folder: **Kaila**. *Personal AI assistant: a voice and face layer…*" with buttons **Add to Apps**, **Not now**, **Never for this folder**. The README sentence is shown as found.
- Tooltips: Add to Apps: "Give it a tile here. Nothing is started or changed in the project." Not now: "Ask again in 14 days." Never for this folder: "Do not ask about this folder again. You can undo this in Settings."
- Tile for a project with no launch command: a hint line "No launch button: it has no app to open yet." Tooltip on the name: "Lab Hub shows its version and repo state. Add a launch entry to the registry when it has an app to open."
- Lab Hub tile summary: "This app: the launcher for the lab's projects." Hint line: "You are using it: it has no Launch button." Behind-line tooltip: "A newer build is ready to install: use Check builds."
- Settings list: heading "Hidden projects", row "Kaila · hidden for good" or "· not asked until 5 Dec", button "Show again".
Nothing here claims a project is ready, approved, released or compliant.

## 8. Scope
- **In:** detection and banner; `apps-local.toml` and `apps-dismissed.json`; optional `entry`; the no-launch tile; Lab Hub's tile; Settings "Hidden projects"; tests; README Apps section and CHANGELOG.
- **Out:** guessing a build or run command; registering nested repos or toolbox members (toolbox's own launcher is planned, `toolbox/README.md`); removing a tile from the UI (the owner edits the local file, or a later spec); showing the project's tier; any network call; changing Land, Update now or Check builds.
- **Out, noted:** `docs/foundry/app-context.md` of Lab Hub still has 8 unfilled placeholders (`TODO.md:526`, the session-start warning). Not part of this change; Build does not rely on it, but Release stays blocked by it as before.

## 9. Risks
- README text on a tile: file content, shown as plain text, length-capped; a README that names a path or command is shown, never run.
- A suggestion for a folder that is really scratch work: costs one click and is remembered.
- Three banner rows on the first run (Kaila, Overseer, Shopfront HQ): intended, once.
- Tile order changes for nobody: existing tiles keep their place; new ones come after.

## 10. Phases
Define (this, **GATE**). Design (`ux-designer`: banner and tile states, since it is user-visible). Architect (**GATE**: two small state files and a second registry source; `architect` decides the registry merge and where the scan runs so no refresh blocks). Build, Review, Verify, Secure (reads directory names and README text from the lab folder, writes two files under Application Support, a symlink guard). Document. Skipped: Case, Comply and Launch (tier `public`, no new claim, no new data leaves the machine, no model call), Release (owner's call; Lab Hub updates itself from Check builds).
Estimate: Design 10 min, Architect 20 min, Build 3-4 h, Review/Verify/Secure 1.5 h.
Model advice for Build: Sonnet, medium for the tile and tests; Opus only if the registry merge touches the reload path in a way Architect marks as concurrency work.

## 11. Decisions for the owner
1. **Ask first** (recommended) or add automatically?
2. **Store answers in Application Support** (recommended) or write `apps.toml` directly?
3. **Not now = 14 days; Never = permanent with a way back in Settings** (recommended), or something simpler (Not now = until next start)?
4. **Lab Hub's tile last** (recommended) or first?
5. **Kaila: add** (recommended, as a no-launch tile). Overseer and Shopfront HQ: your pick at the first prompt.
6. **The wording in §7.**

## 12. Design (ux-designer, 2026-11-21)

Phase: Design. Playbook `ux-designer.md` is `status: current`, last-reviewed 2026-11-11 (10 days old, not stale). The §7 words are used exactly as approved; everything else new is in "Wording proposals" at the end, not approved. No code or UI file touched. Code paths are repo-root `ui/` (not `lab_hub/ui/`).

**The user's question on this screen:** "Is there a project in my lab folder that this page does not show yet, and do I want it here?" The one primary figure is the **banner row for the first unanswered project**: nothing else on the page changes until it is answered, and a row is never a dialog. On the tiles the primary figure stays what it is today (the name and, for these two tiles, the version line).

### 12.1 Banner (Apps page)
1. **Placement.** The first thing in the page column, above the first section title (`ui/apps_tab.py:650-654` adds titles to `self.column`). One `theme.card()` (`ui/theme.py:906`) holding one row per suggestion, rows separated by a 1px `p.border` line. It uses card colours, not `warn`: it is a question, not a warning. No heading of its own (the sentence in §7 says what it is). It scrolls with the page and is never modal, so Launch, Land, Check builds and the 3-second poll keep working (`ui/tiles.py:168-170`).
2. **A row, top to bottom.** Line 1: "New project in your lab folder:" in `hint` style, then the name in `appName` style (bold). Line 2 (only if there is a summary): the README sentence, `hint` style, wrapped, shown as found. Line 3: **Add to Apps** (`primary`), **Not now**, **Never for this folder** (both normal secondary buttons; `danger` red would wrongly say "destructive"), left-aligned, 8px apart as on tiles (`ui/tiles.py:119`). Design choice, not a wording change: §7 shows the sentence in italics; the stylesheet has no italic style, so it is muted instead (`hint`).
3. **Plain text.** Name and sentence are file content: both labels `setTextFormat(PlainText)` as `AppCard.hygiene` does (`ui/apps_tab.py:139`); tooltips on them go through `plain_tip` (`apps_tab.py:53`). The §7 tooltips are fixed text.
4. **How many rows.** Show at most **3**, then a muted line "and N more" (proposal A) under the last row. The 3 are exactly today's first run (Kaila, Overseer, Shopfront HQ) and keep the banner under about 360 px, so the first tile is still on screen at the 580 px minimum window height (`ui/main_window.py:63`). Answering a row reveals the next. No Show-all control (it would be a fourth button to design and test for a rare case).
5. **Long text.** The sentence is capped at 220 characters (§4.5): it wraps, at most 3 lines at the narrowest window, so no ellipsis and no tooltip are needed. A long README heading (the name) is elided on the right at one line, full name in the tooltip. No README text: the row has no line 2 and the name is the folder name as it is on disk.
6. **Width.** Banner width is the page column, 500 px at the 760 px minimum window (760 - sidebar 212 - 2 x 24 margin; `ui/theme.py:44`, `ui/widgets.py:205`), 460 px inside the card margins. The three buttons measured 113 + 87 + 161 px plus 16 spacing = 377 px (Qt offscreen, Fusion; macOS fonts may differ by about 10%). They fit one row with 80 px spare. Test: the row's `minimumSizeHint().width()` is at most 500 in Graphite and Paper, so the banner can never make the page scroll sideways (the failure the comments at `apps_tab.py:135-148` record).
7. **Keyboard.** Tab order is document order: banner row 1 (Add to Apps, Not now, Never), row 2, row 3, then the tiles. Space or Return presses the focused button; no button is the default and no key shortcut or Escape handler is added (a stray Return must not answer a project). Not verified: Qt draws a visible focus ring on `QPushButton` under this stylesheet (`theme.py` styles `:focus` only for inputs, line 557); Verify tabs through the banner in both themes and screenshots it.
8. **Accessible names** (the visible label comes first, WCAG 2.5.3): "Add to Apps, Kaila", "Not now, Kaila", "Never for this folder, Kaila"; accessible description = the §7 tooltip; each row's container is named "New project: Kaila". Tooltips are not the only carrier of anything important.
9. **After a click.**
   - **Add to Apps:** the entry is written, the registry reread and the page refreshed in the same step: the row disappears and the tile is in its section at once (no restart, no wait for the poll). The page scrolls the new tile into view. Status bar (`main_window.py:296`, 8 s): "Added Kaila to Apps." (proposal B).
   - **Not now:** the row disappears; status bar "Kaila: not asked for 14 days." (B).
   - **Never for this folder:** the row disappears; status bar "Kaila hidden. You can undo this in Settings." (B).
   - **Focus** goes to the Add to Apps button of the next row; when no row is left, to the page scroll area, so the next Tab reaches the first tile button. Focus is never dropped to the window.
   - **Refresh (Cmd+R) and the poll** rebuild banner rows only when the set of suggestions changed, so a focused button is not replaced under the keyboard. The scan itself runs at startup and Refresh only (§4.1).
10. **Add fails to write** (disk, permissions): the row stays, buttons re-enabled, focus stays on Add to Apps, and a line under the buttons in `stateBad` style: "Could not add Kaila: <reason>." (C). The same for a failed write of Not now or Never ("Could not save your answer for Kaila: <reason>. It will be asked again."). The reason is plain text. The error is words plus colour, never colour alone.

### 12.2 Tile with no launch command
Same `AppCard`/`Tile` frame as every tile (`ui/tiles.py:75-129`), so it keeps the grid's width and height rules. Top to bottom:
1. **Name** (`appName`), tooltip = the §7 sentence, also set as accessible description (a tooltip alone is mouse-only). **No state pill**: the state label is hidden, because an empty pill/dot would draw an orphan marker (`theme.py:415-450`) and "Ready" would be untrue.
2. **Summary** in the existing reserved 52 px block (`tiles.py:32`), so an empty or one-line summary does not shrink the tile. If it has none, the block stays empty.
3. **Version line**, `hint`, wrapped (`apps_tab.py:127-129`), as for launchable tiles, from the checkout (§4.6). Then the **repo badge** below it in `stateWarn`, wrapped, plain text (`apps_tab.py:133-139`). Version and badge stay on their own lines under the name, never beside it (comment `apps_tab.py:141-144`).
4. **Hint line** "No launch button: it has no app to open yet." in the `detail` slot (`tiles.py:112-115`), where launchable tiles show the launch path; `hint` style, wrapped.
5. **Buttons.** No Launch, no Stop, no service line. **Land** (existing, shown only when the repo needs it, `apps_tab.py:323-332`) and **Open in Terminal** (existing flat button, existing tooltip, `apps_tab.py:180-186`). Open in Terminal is **always visible** on these tiles: today it shows only after a failed Land (`apps_tab.py:383`), and without it a no-launch tile with nothing to land would have no control at all. **Correction for the owner:** no tile has an Ask Claude button today (Ask Claude lives in the Land and Build-check windows, `apps_tab.py:926-1030`); §2.3 and §4.6 say "Land, Ask Claude" on the tile. This design does not add one; the Land window still offers it. Say if you want a tile button (a separate, larger change).
6. The button row is left-aligned (Launch's stretch, `apps_tab.py:154`, is gone) and stays pinned to the tile bottom by the existing stretch (`tiles.py:125-129`), so Land lines up with neighbouring tiles' buttons.
7. **Min width:** like every tile, 380 px outer, 340 px inside the margins (`tiles.py:29-31`, `columns_for` 52-56). Every label above wraps; the name elides one line with the full name in its tooltip. Nothing on this tile may set a minimum width above 340 (Land 60 px + Open in Terminal 141 px is 209 px).

### 12.3 Lab Hub's own tile
Same layout as 12.2, **last** in the Apps section, built in code. Differences:
1. Name "Lab Hub", summary and hint line from §7 ("You are using it: it has no Launch button."). No state pill, no Launch, Bring to front, Stop, Quit, no Update now.
2. **Version line:** `version.version_string()` (e.g. `v2.208`), tooltip `version.tooltip()` (commit and date), the same pair Settings uses (`ui/settings_tab.py:127-131`). Plain label, selectable by mouse like Settings.
3. **Behind-line:** when `self_update.build_status(SELF)` says it is older, append " · N behind" in `stateWarn` to the same line, as `apps_tab.py:281-303` does for other tiles, tooltip = the §7 sentence ("A newer build is ready to install: use Check builds."). Up to date or run from source: the verdict words `build_status` already returns, used as they are, no new copy; they wrap. The tile has no button for the update.
4. Land and Open in Terminal as in 12.2.
Not verified, for Architect: where the string "N behind" comes from for Lab Hub (existing `commits_further` wording vs `self_update`'s).

### 12.4 Settings: Hidden projects
1. A new card, `theme.card()` with `theme.section_title("Hidden projects")` (shown uppercase like the others, `theme.py:916`), placed after "Lab folder" (it is about that folder), before "Start at login" (`settings_tab.py:166-169`).
2. **A row:** one label "Kaila · hidden for good" or "Overseer · not asked until 5 Dec" (body text colour, one line) and, right-aligned, a secondary **Show again** button. Date: day and abbreviated month, no year, no leading zero ("5 Dec", the form `land-pick-and-time` uses: "17 Nov"). Rows are ordered by name. Only "Not now" entries still within their 14 days are listed (a lapsed one is simply asked again).
3. **Long names:** the label elides in the middle at one line and its tooltip carries the full text; the button never shrinks (107 px). Accessible names: "Show again, Kaila".
4. **Show again:** removes the entry, writes the file, the row disappears, and the project is suggested on the Apps page at once (rescan, no restart). Focus goes to the next row's button, else the previous row's, else the Settings scroll area. Status bar: "Kaila will be suggested again." (B). Write failure: inline `stateBad` line in that row, row stays (same as 12.1.10).
5. **Empty:** the card stays (it is where the Never tooltip says to undo), with one `hint` line "No hidden projects." (D). No placeholder anywhere else.
6. Min width: the Settings column is `CONTENT_WIDTH` 760 (`theme.py:44`); at the 548 px minimum content width a row fits label plus 107 px button, the label elides first.

### 12.5 States
| State | Banner (Apps) | Tiles | Settings list |
|---|---|---|---|
| Empty (nothing to suggest) | Absent: no card, no placeholder, no gap | Unchanged | Card with "No hidden projects." |
| One | One row | n/a | n/a |
| Many (more than 3) | 3 rows and "and N more" | n/a | One row each, card grows |
| Loading | No state: the scan is file-existence only, run at startup/Refresh; the banner is simply absent until it ends. It must never delay the page (Architect) | n/a | n/a |
| Stale | Not shown: the scan runs only at startup/Refresh (§4.1). A folder created later appears at the next Cmd+R | Existing behaviour | Reread when Settings is shown |
| README missing or unreadable (also bad encoding) | Name is the folder name; no line 2 | Folder name; empty summary block | n/a |
| README first paragraph is badges, HTML, a table or code | Shown as found would be raw markup. Recommend Architect skips such lines when picking the paragraph; if nothing usable is left, as "missing" above | same | n/a |
| `apps-local.toml` broken | Rows as before; one quiet line above the banner (E) | List as before the file was touched | n/a |
| `apps-dismissed.json` corrupt | Treated as empty, so earlier Never answers reappear as rows (surprising, hence the note) | n/a | `hint` line "Your hidden-projects file could not be read, so nothing is hidden." (F) |
| Add or answer fails to write | Row stays, inline `stateBad` line | n/a | Row stays, inline line |
| Light / dark | Tokens below | Tokens below | Tokens below |

**The quiet line for `apps-local.toml`:** one wrapped, plain-text `hint`-style label as the first item of the page column, selectable by mouse (so the path can be copied), full file path in the tooltip. It states that the file was ignored, the reason in one clause (`registry.last_error`, `spec §4.3`) and that the list is unchanged. A key clash with `apps.toml` uses the same line ("... is already in apps.toml: the apps.toml entry is used"); several problems: the first in the line, all in the tooltip. It is not an error colour: the hub works.

**Theme tokens (existing only, `ui/theme.py:83-155`):** card background `card`; row separator `border`; names and Settings rows `text`; sentences, lead-in, hint lines, "and N more", quiet line `muted`; `stateWarn` (`warn`) only where tiles already use it (badge, behind-line); `stateBad` (`bad`) for inline errors; buttons use the stock QPushButton and `primary` styles; focus uses the Qt palette highlight (`accent`). Nothing new is added to `Palette`; `faint` is not used for text. Measured contrast of what is used (WCAG relative luminance, on `card`): Graphite `muted` 5.25, `text` 15.03, `bad` 6.51, `warn` 9.06; Paper `muted` 5.16, `text` 16.49, `bad` 5.12. **Existing issue, not made worse here:** Paper `warn` text on `card` is **3.49:1** (below 4.5 for 12 px text) and Paper `faint` is 3.52; both are old tokens used on every tile's badge and on section titles. The behind-line reuses `stateWarn` for consistency and also says "N behind" in words, so meaning never rests on colour; the token itself belongs in the UX audit, not in this change.

### 12.6 Accessibility summary
- Focus order: sidebar, banner rows top to bottom (Add, Not now, Never), tiles in grid order, page buttons. Focus is moved explicitly after every removal (12.1.9, 12.4.4).
- Every button has the visible label first in its accessible name and the tooltip as description; the no-launch name tooltip is repeated as accessible description.
- No colour-only meaning: errors say "Could not...", behind says "N behind", hidden says "hidden for good" or a date.
- All file-derived text (README name and sentence, folder names, reasons, TOML and OS errors) is `PlainText`, tooltips via `plain_tip`; none of it can open a link or render markup.
- Click targets: stock buttons are 34 px high (measured), above the 24 px minimum.
- Not verified: VoiceOver pass over the banner and the two tiles; assigned to Verify with the screenshots (Graphite and Paper).

### 12.7 Wording proposals for the owner (NOT approved; §7 is unchanged)
A. "and N more" under the third banner row, e.g. "and 4 more". Alternative: "4 more projects to answer."
B. Status-bar confirmations (8 s): "Added Kaila to Apps." / "Kaila: not asked for 14 days." / "Kaila hidden. You can undo this in Settings." / "Kaila will be suggested again."
C. Inline errors: "Could not add Kaila: <reason>." and "Could not save your answer for Kaila: <reason>. It will be asked again."
D. Empty Hidden-projects line: "No hidden projects."
E. Broken local file: "Your added projects file was ignored: <reason>. The list is as it was." (key clash: "<key> is already in apps.toml: the apps.toml entry is used.")
F. Corrupt dismissals: "Your hidden-projects file could not be read, so nothing is hidden."
G. Date in "not asked until": "5 Dec" (day, short month, no year), as already approved in §7's example; confirm it applies to every month and a one-digit day.

### 12.8 Open items for Architect and Verify
- Architect: README summary extraction must skip badge, HTML, table and code lines (12.5); decide whether the corrupt dismissal file is kept as a `.bad` copy before an answer overwrites it.
- Architect: banner rebuild only on a changed suggestion set (12.1.9), and the rescan after Show again in Settings.
- Verify: contrast test for every token above in both palettes (pattern in the playbook, `git_autosync/tests/test_header_fit.py`); banner `minimumSizeHint` at most 500; tile min width test at 380 for both new tiles; focus-ring check; screenshots in both themes of the banner (3 rows), Kaila's tile, Lab Hub's tile and the Hidden projects card.

## 13. Architecture (architect, 2026-11-21)
ADR: `docs/adr/0007-local-app-registry-and-no-launch-tiles.md` (proposed). It fixes two on-disk formats
and a second registry source, so it needs the owner's Architect gate. Playbook `architect.md`
last-reviewed 2026-10-14, status current. `docs/foundry/app-context.md` is still the unfilled template
(no hot spots listed), so every fact below is from the code, with paths relative to the repo root.

### 13.0 Summary
- New Qt-free module `lab_hub/discovery.py` (scan, README extraction, dismissals, the local-file writer).
  Registry gets a second read-only source and an optional `entry`. Lab Hub's tile is a constant in code.
- Everything runs on the GUI thread **except one thing**: Lab Hub's tile verdict (`self_update.self_status`,
  about 170-200 ms of git, measured below) runs on a daemon worker thread. The registry merge itself is
  **not** concurrency work: nothing but the GUI thread reads or reloads the registry (grep of `registry`,
  `launcher.SUITES/APPS/…`, `launcher.reload`: `ui/main_window.py:72,326,368`, `ui/tray.py:121`,
  `ui/apps_tab.py`, `ui/settings_tab.py:219`, `main.py`; `Lander`'s thread uses none of them).
- Deviation from approved §4.3, needs the owner's yes (§13.9 item 1): clashes and a bad local file are
  reported in a new `registry.local_note`, **not** `registry.last_error`. `main.py:383-385` appends any
  `last_error` to the self-test's `problems`, and the self-update helper runs `--selftest` on the installed
  copy and rolls back on failure (`self_update.py`, helper step 4). A typo in the owner's local file must
  never be able to undo an update.

### 13.1 Second registry source (`lab_hub/launcher/registry.py`)
- **Path:** `local_path() -> Path` returns `config.SUPPORT_DIR / "apps-local.toml"`, looked up at call time
  (`from .. import config`), because `tests/conftest.py:37-50` patches `config.SUPPORT_DIR` per test and
  `self_update.py:43` shows what happens when a constant is imported by value. `candidates` (195-205) is
  unchanged: it lists `apps.toml` copies only.
- **Read:** new `_read_local() -> tuple[tuple[ExternalApp, ...] | None, str | None]`: `((), None)` when the
  file is absent (absent is not broken, so deleting the file removes the added tiles), `(None, why)` when it
  cannot be read (OSError, not UTF-8, over 256 KiB) or does not parse, else `(entries, None)`. It uses
  `parse(text, path, local=True)`: only `[[suites]]` allowed, zero entries allowed (the `"it lists no apps"`
  check at `registry.py:178` is skipped), same field rules.
- **Merge:** pure `merge_local(base: Registry, local: tuple[ExternalApp, ...]) -> tuple[Registry, tuple[str, ...]]`,
  no filesystem access. For each local entry in file order it is dropped, with a note naming it, when:
  its key is in `RESERVED` (`{"lab_hub"}`, Lab Hub's own tile) or equals a base key or an earlier local key;
  its `project` equals, or contains, or lies inside a base project or a reserved one (compared as
  `posixpath.normpath(p).casefold()`: APFS is case-insensitive). The kept entries are stable-sorted
  launchable first (spec §4.6: no-launch tiles after the launchable ones) and appended to `base.suites`.
  Result: `Registry(suites=base.suites + kept, backup_sync=…, source=base.source)`.
- **Wiring:** `_read` (212-227) keeps its loop and `last_error` handling, then calls
  `_with_local(found)`, which sets the module globals `local_note: str | None`, `local_ok: bool` and
  `_last_local: tuple[ExternalApp, ...]` and returns the merged registry. `reload` (241-253) and `current`
  (230-238) are unchanged. `use()` (256-259) also resets the three globals, so tests stay isolated.
- **Bad or missing local file:** the **last good local part is kept** (`_last_local`) and re-merged against
  the new `apps.toml`, `local_ok` is False, `local_note` says why. Alternative rejected: drop the local part.
  A half-saved edit would make Kaila's tile vanish and the banner offer Kaila again, and Add would then be
  asked to write into a file Lab Hub cannot read. While `local_ok` is False, `discovery.suggestions` returns
  nothing and `discovery.add` refuses (it never overwrites a file it cannot parse). First use with a bad
  file has no last good part: apps.toml's list only, plus the note; `current()` never raises for it.
- **Change detection:** unchanged. Local entries are merged into `suites`, so `Registry.__eq__`
  (`registry.py:99-102`, via `groups()`) already compares them, `reload` returns True after a local edit
  (the status bar says "the app list changed"), and `AppsTab._sync_cards` (`ui/apps_tab.py:734-753`)
  rebuilds only the changed section. No edit to `__eq__`/`__hash__`.
- **Placement:** hand-written suites, then local launchable entries, then local no-launch entries; Lab Hub's
  tile last (§13.4). Existing tiles do not move.
- **Validation added to `_app` (131-152), for both files** (the 9 shipped entries all pass; a test asserts
  it): `key` fullmatches `[A-Za-z0-9][A-Za-z0-9._-]{0,63}`; `name` has no `/ \ < > &` and no control
  character (it is joined into `/Applications/<name>.app` at `state.py:43`, and shown in message boxes,
  which render rich text); `project` and `entry` are relative with no `..` (`launch` joins them,
  `control.py:272`).

### 13.2 `entry` optional: every path that touches it
Field: `entry: str | None`, **no default, same position** (tests build `ExternalApp("sonar", n, "sonar",
"main.py", "summary")` positionally: `tests/test_apps_tab.py:23,73,86,109`). `_app` sets `entry=None` when the
TOML omits it (`_REQUIRED` at `registry.py:83` loses `"entry"`). New `ExternalApp.launchable -> bool`
(`entry is not None`). An entry with no `entry` that sets `url`, `service`, `args`, `bundle_dir`, `build`,
`build_output` or `runs_from_source = false` is a `RegistryError` ("has no entry, so it cannot set …").

| Site | Safe behaviour for `entry is None` |
|---|---|
| `registry.Registry.menu_bar_apps` 119, `launchpad` 124, `apps` 127 | filter `launchable`. `suites` and the `SUITES` alias stay unfiltered (the Apps page shows no-launch tiles). Shipped list: identical (`test_registry.py:45-46` unchanged). |
| `state.bundle_path` 36-49 | return None first (no `/Applications/<name>.app` lookup, so a stray `Kaila.app` is never reported). Makes `bundle_marker`, `bundle_executable`, `can_bring_to_front` (317), `running_markers` (152) all empty. |
| `state.source_dir` 109-127 | `project if project.is_dir() else None`; skip the entry check and the bundle fallback. |
| `state.checkout_marker` 184-187 | None (it does `project / app.entry`). `presence` 250-280 then returns `Presence(False, False)` at 266-267. |
| `state.version` 837-901 | first line: `project = source_dir(...)`; return `checkout_version(project)` if there is one, else `Version()`. This also guards `_recorded_root_version` (908-909, `"…has no " + app.entry` would raise): reachable only through `version` 888-898, which the early return precedes; add `if app.entry is None: return Version()` there as a second guard. |
| `state.build_status` 1159 / `_build_status` 1215 | return `BuildStatus(app, version, "unknown", "it has no launch command, so there is no build to compare.")` before anything else (without this a checkout-origin version would say "runs the checkout directly"). |
| `state.build_report` 1304-1307 | filter `launchable` on both the default and the passed `apps`. |
| `state.status` 1310 / `readiness` 1352 | `status`: `("source", str(project))` or `("missing", …)`; `readiness`: `Readiness(state, detail, "it has no launch command, so there is nothing to start")` (`ok` False). Nothing calls them for these apps; this is the safe default. |
| `control.launch` 207 / `bring_to_front` 163 | first line: `if not app.launchable: raise LaunchError(f"{app.name} has no launch command.")` (lines 179, 256, 272 would otherwise `TypeError`). `stop`/`server_pids` need `url`, so they are unreachable. |
| `ui/apps_tab.AppCard.__init__` 151-154 | create the Launch button as now, then `setVisible(False)` when not launchable. Keep the `buttons` order: Land (164-172) follows it. |
| `AppCard.refresh` 227-248 | branch first: `if not self.app.launchable: return self._refresh_no_launch(lab_root)`: sets `lab_root`, `running = False`, calls `refresh_version`, the state chip (style `hint`; text per Design), `detail` = the project path or "no folder at …", the hint line in the existing `self.service` label (it is already reserved on every tile, line 100, so tiles stay level), the name tooltip (§7). No `readiness`, no `presence`, no `ps`. |
| `AppCard._update_button` 468-514 | first line `if not self.app.launchable: self.launch_button.hide(); return` (not reached from `refresh`, but it is the one place that sets Launch/Bring to front/Running text; a belt). `_launch` 547: same guard, `return`. `_update_stop` already no-ops (`stop_button` None, 518). |
| `ui/tray.py:121` | `for app in launcher.SUITES + launcher.BACKUP_SYNC_APPS` is **not** `menu_bar_apps`; add `if not app.launchable: continue`. Update `tests/test_tray.py:44` to iterate launchable apps. |
| `ui/settings_tab.py:219` | iterates `launcher.APPS`, which now excludes no-launch entries: the "found source folders" list is unchanged for them. |
| `ui/main_window.py:368` (`start_sync_apps_in_background`) | iterates `BACKUP_SYNC_APPS`; local entries cannot be there (suites only), so no change; add the same one-line `launchable` skip anyway. |
| `ui/apps_tab.py:937-947` (`_handoff_forbidden`) | iterates the four group aliases and calls `source_dir`: for a no-launch entry it now returns the project folder, which is correct (a registered checkout stays forbidden). No change. |
| `ui/apps_tab.py:799,1109`, `progress.py:748` | use `project` / `row.project` only. No change. |
| `main.py:105, 391, 404` (self-test) and `371-385` | loop over `launcher.APPS`: no-launch entries are already excluded. `383-385` keeps `last_error` as a failure (apps.toml only); add one informational `print` of `registry.local_note`, **never** into `problems`. If `selftest()` is too heavy to call from a test, extract lines 370-386 into `_app_list_problems() -> list[str]` and test that. |
| `self_update.py:64-71` `SELF` | unchanged except its comment ("Never registered: no tile" becomes "…no registry entry; its tile is `OWN_TILE`"). It keeps `entry="main.py"` because `self_status` compares the installed bundle. |

Grep found no other reader of `app.entry` outside `lab_hub/tools/` (not an app registry user). The 9 shipped
entries keep behaviour because every changed branch is guarded by `entry is None`/`launchable`.

### 13.3 Where the scan runs, and the two state files
- **Scan: GUI thread, synchronously, at startup and on Refresh only** (`AppsTab.__init__`, after
  `_sync_cards`, and `AppsTab.recheck` 1079-1089; **not** `refresh` 1315 or `showEvent`, which are the 3-second
  poll). Measured 2026-11-21 on `~/Documents/lab/active`: 14 entries, scan median **0.09 ms** (max 0.21 ms)
  over 50 runs, three README reads of at most 8 KiB **0.76 ms**; file existence and `lstat` only, no
  subprocess. The same Refresh already runs `ps` (`process_table`, 5 s timeout, `state.py:138`) and per-card
  version reads, so a worker for under 1 ms would add a thread, a signal and a staleness race for nothing.
  Bounds: at most 400 directory entries examined (`itertools.islice` over `os.scandir`), a missing or
  unreadable lab folder gives no suggestions and no error. A network-mounted lab folder could stall on a
  stat: accepted, `ps` already has the same exposure.
- **`discovery.suggestions(lab_root, today=None)`** is the glue: builds the registered set from
  `registry.current()` (all four groups, plus `registry.RESERVED`) with `os.path.realpath`, loads the
  dismissals, returns `()` when `registry.local_ok` is False, else calls the pure
  `scan(lab_root, registered, dismissed, today)`. Detection conditions in code order (each a named line with
  a `# condition:` comment so Verify can mutate it): real top-level directory (`is_dir(follow_symlinks=False)`,
  so a symlinked project is never suggested, even one pointing inside the lab folder); name does not start
  with `.` or `_`; name fullmatches `NAME_OK` (`[A-Za-z0-9][A-Za-z0-9._-]{0,63}`); `<f>/.git` is a directory by
  `os.lstat` (a `.git` file or symlink fails); `<f>/docs/foundry/app-context.md` is a regular file by
  `lstat` and its `realpath` is inside the folder's; not `lab_hub`; not registered (realpath equal, or a
  registered project inside it); not dismissed.
- **Files (both in `config.SUPPORT_DIR`, looked up at call time; `SUPPORT_DIR` is created with
  `mkdir(parents=True, exist_ok=True)`):**
  - `apps-dismissed.json`, read cap 64 KiB. `load_dismissed()` returns `{}` for a missing, unreadable,
    non-dict or oversized file and ignores any entry whose `answer` is not `never`/`not_now`. `at` is a
    date; `not_now` hides until `at + 14 days` (`NOT_NOW_DAYS`); an unparsable or future `at` counts as
    expired. The clock is a parameter: every function takes `today: date | None` and `discovery.today()`
    (the only `date.today()` call) is what the UI passes and tests patch.
  - `apps-local.toml`: written only by `add`.
  - **Write protocol (both):** read the current bytes, build the new bytes, write
    `<name>.<pid>.tmp` with `os.open(O_WRONLY|O_CREAT|O_EXCL, 0o600)`, `fsync`, check that the target's
    `(st_ino, st_size, st_mtime_ns)` still equals what was read (else `DiscoveryError("changed while Lab Hub
    was writing it; try again")`), `os.replace`; unlink the temp file on any error. A corrupt
    `apps-dismissed.json` is first renamed `apps-dismissed.json.bad`, so the older answers are not lost to
    the overwrite. `config.save` (`config.py:118`, `write_text`, not atomic) is not touched (debt P3).
  - **Races:** all writes happen in a button handler on the GUI thread, so two quick clicks are serial and
    the second re-reads the file (Add is idempotent: a key already present is a no-op; a dismissal just
    rewrites its own key). Two Lab Hub processes cannot write: `SingleInstance` (`ui/single_instance.py`)
    admits one, and the helper's `--selftest` copy only reads. A hand edit landing between the read and the
    replace is caught by the identity check above or, at worst, loses one Add (re-offered next Refresh).
- **Add entry** (`add(s: Suggestion)`): derived fields per §4.5, `key = project = folder`, `entry` =
  `"main.py"` only when `<f>/main.py` is a regular, non-symlink file, else omitted. Text is **appended** to
  the existing file (comments and hand edits survive) as `\n# Added by Lab Hub on <date>.\n[[suites]]\n` plus
  one `key = <toml_string(v)>` line per field. **TOML safety:** no TOML writer is installed
  (`requirements.txt`: no `tomli_w`; `tomllib` only reads) and adding one is a dependency and a notices
  change for 20 lines. `toml_string(value)` emits a basic string: `\` and `"` escaped, every code point
  below U+0020 and U+007F as `\uXXXX` (so no raw newline, quote or `"""` can ever appear), a lone surrogate
  raises. Then **verify before writing:** `tomllib.loads(new_text)` must succeed and its last `suites` table
  must equal the intended fields exactly, and `registry.parse(new_text, local=True)` plus `merge_local`
  against the current registry must keep the entry; otherwise nothing is written and `DiscoveryError` says
  why. `add` also clears any dismissal for that folder. A hostile README therefore cannot add a field, a
  group or a second entry: the test feeds `]]\n[[suites]]\nkey="x"`, `"""`, `\`, U+2028, NUL and emoji.

### 13.4 Lab Hub's own tile
- **A synthetic `ExternalApp`, not a new card family.** In `lab_hub/self_update.py` beside `SELF` (64-71):
  `OWN_TILE = ExternalApp(key="lab_hub", name="Lab Hub", project="lab_hub", entry=None, summary=<§7 summary>)`.
  It is not in any file, not in `registry.current()`, not in `apps`/`menu_bar_apps`, so it cannot be
  hidden, edited, shown in the tray or counted in Settings. `registry.RESERVED = frozenset({"lab_hub"})`
  stops a registry file defining that key or project (`merge_local`; for `apps.toml` a test asserts the
  shipped list has none, and a hand-added one would show two tiles: noted as P3, not guarded in code).
  A test asserts `SELF.key`/`SELF.project` are in `RESERVED` so the two cannot drift.
- **Placement:** `ui/main_window.py:72` becomes `apps=lambda: launcher.SUITES + (self_update.OWN_TILE,)` and
  passes `discover=True`. `AppsTab._sync_cards` builds `OwnCard` (a small `AppCard` subclass in
  `ui/apps_tab.py`, no circular import) when `app == self_update.OWN_TILE`, else `AppCard`.
- **`OwnCard`:** behaves as the no-launch card (§13.2) and overrides `refresh_version(lab_root)`: text =
  `version.version_string()`, tooltip = `version.tooltip()` (both read the `lru_cache`d `version.info()`,
  `version.py:107-156`, so no git on the poll), plus the verdict line from the last result. Land, the badge,
  Open in Terminal and the Land outcome are inherited: `_apply_hygiene` (1105-1111) finds the row by
  `card.app.project == "lab_hub"` (`hygiene.Report.for_project`, `hygiene.py:85`). There is no Ask Claude
  button on any tile (it lives in the Check builds and Land windows, `apps_tab.py:962`): the spec's "Ask
  Claude" for these tiles is that window feature for the `lab_hub` row, so nothing is added.
- **Verdict:** `self_update.self_status(lab_root)`, the same row Check builds shows (appended at
  `apps_tab.py:773-785`), not a second `build_status(SELF)` call: it applies §2.7 ("runs the checkout
  directly") and the main-level logic, so the tile cannot disagree with Check builds. Pure
  `self_update.verdict_line(row: BuildStatus) -> str` maps it to the §7/§5 words. **It costs git:**
  measured here, `git status` 42 ms, `rev-parse` of `main` 34 ms, `rev-list` 22 ms, `merge-base` 16 ms,
  `cat-file` 16 ms: about 170-200 ms per call on a warm repo, uncached (`dirty_checkout`), so it is **not** on
  the 3 s poll and not on the GUI thread. New `ui/own_verdict.py`, `OwnVerdict(QObject)`, the `ui/lander.py:25-90`
  pattern (daemon `threading.Thread`, `queue.SimpleQueue`, `QTimer` 100 ms drain, `ready = Signal(object)`);
  the thread never touches Qt. `request(lab_root)` while one is running sets `_again`, so a burst of Refreshes
  costs at most one extra run. Called from `AppsTab.__init__` and `recheck`; the tile shows no verdict line until
  the first result, and a failure leaves it blank with the reason in the tooltip. `shutdown()` stops the timer;
  the daemon thread needs no join. The comment at `state.py:671-676` ("GUI thread only") becomes untrue and
  must be amended: the caches are plain dict get/set, safe under the GIL, and a duplicated computation is
  harmless.
- **No double count in Check builds:** `launcher.build_report` iterates `registry.current().apps`, which
  never contains `OWN_TILE`; `show_build_report` appends `self_status` once (777). A test asserts exactly one
  `lab_hub` row in `progress.build_check_view` with the tile present. `check_own_builds` tabs build from
  `_shown` (`apps_tab.py:729`) and never show `OWN_TILE`.

### 13.5 README text is untrusted (`discovery.describe(project) -> tuple[str, str]`)
- **Read:** `os.lstat(<f>/README.md)` must be a regular file (a symlink, FIFO or device falls back);
  `os.open(…, O_RDONLY | O_NOFOLLOW | O_NONBLOCK)`, `fstat` re-checked, **`os.read(fd, 8192)`** bytes and no more
  (the Shopfront README is read to the cap), decoded `utf-8` with `errors="replace"`, a leading BOM removed.
- **Clean:** every character of Unicode category `Cc`, `Cf` (bidi overrides, zero-width), `Cs`, `Co`, `Cn`
  is dropped (tab and newline are turned into spaces/line breaks first); runs of whitespace collapse.
- **Name:** first ATX `# ` heading outside a code fence; accepted only if it is 1-60 characters with none of
  `/ \ < > &` and no leading `.`, else the folder name (already `NAME_OK`). **Summary:** the first paragraph
  after it that is not a heading, badge (`![`), tag line (`<`), table row (`|`) or fence; cut at the first
  `. `, `! ` or `? ` (so "e.g. " can cut early: accepted), then capped at **220 characters** on a word
  boundary with `…`. No README or no paragraph: the fallback summary in §13.9 item 7 (the registry requires a
  non-empty one).
- **Never executed, never markup:** the text goes only to `toml_string` (§13.3) and to QLabels set to
  `Qt.PlainText`. `Tile.__init__` (`ui/tiles.py:94,108`) builds `name` and `summary` as auto-text labels, which
  Qt renders as rich text when they look like HTML: Build sets `setTextFormat(Qt.PlainText)` on both (a grep of the sites, dashboards, tools and apps.toml summaries found no markup). `entry` is only ever the literal `main.py`. The banner's labels are
  PlainText too.
- **Scan guard:** §13.3 (lstat-based `.git` and marker checks, no symlinks followed, name pattern, entry cap).

### 13.6 Test strategy (spec §6 mapped)
Conventions: real temp folders, no mocks of the filesystem; `tests/conftest.py` already isolates
`SUPPORT_DIR`. **New autouse fixture** `no_real_discovery` in `conftest.py`: the `window` fixture builds a
real `MainWindow`, which would now scan the owner's real lab folder and start the verdict thread, so patch
`discovery.suggestions` to `()` and `OwnVerdict.request` to a no-op; tests that want them patch them back.
`tests/test_self_update.py:1007` `_drop_tabs` is the precedent for tearing pages down.
- **`tests/test_discovery.py` (Qt-free, new).** Fixture `make_project(root, name, *, git="dir"|"file"|None,
  marker=True, readme=None)`. A **positive control** (all conditions true gives exactly one suggestion) and a
  parametrized **one-breaker-each** table: `.git` file, no `.git`, no app-context, `.hidden`, `_x`, symlink to
  outside, symlink to inside, name with a space / quote / newline, registered by the same project (also
  `./Kaila` and `KAILA`), registered project nested inside, `lab_hub`, dismissed `never`, `not_now` at day 13
  (hidden) and day 14 (shown, `today` injected). Dropping any one `# condition:` line fails its row: Verify
  runs that mutation per line. Also: worktree under `<project>/.claude/worktrees/x` not scanned; two scans in
  a row identical; 500 entries stop at the cap; missing lab folder gives `()`.
- **No subprocess:** `test_the_scan_makes_no_subprocess_call` patches `subprocess.run`, `.Popen`,
  `.check_output`, `os.system`, `os.popen` to raise, then runs `scan`, `suggestions`, `describe`; a second
  test asserts the module source has no `subprocess` import.
- **README:** heading, none, fenced `#`, `<script>`/`/` names fall back, 5 MB file (an `os.read` spy sees at
  most 8192 bytes), invalid UTF-8, NUL, bidi override, FIFO and symlinked README (must return, not hang),
  first-sentence cut, 220 cap.
- **Writer:** `toml_string` hostile-string table round-tripped through `tomllib` to exactly one `suites`
  table with exact values (mutation: swap in a naive `f'"{v}"'`, this must fail); lone surrogate raises; `add`
  appends and keeps existing comments; refuses on an unparsable local file with the bytes unchanged; idempotent;
  patched `os.replace` raising leaves the original and no temp; identity check aborts on a concurrent change;
  dismissals: corrupt, non-dict, bad answer, future `at`, `.bad` rename, two dismissals both kept.
- **`tests/test_registry.py` (extend):** local joins after suites, launchable before no-launch; no-launch
  parses; the 9 shipped entries all `launchable` and unchanged (existing test stays as is); `launchable`
  entries only in `apps`/`menu_bar_apps`; key clash, project clash (case, nested), `lab_hub` yield with a
  `local_note`; broken local (bad TOML, unknown field, `[[utilities]]`, `..` project, `/` in key, name with
  `<`) leaves the list as it was, `last_error` stays None, `local_ok` False; a local edit makes `reload()` True,
  none makes it False; first use with a bad file does not raise; `local_path()` follows a patched
  `config.SUPPORT_DIR`; `RESERVED` matches `SELF`.
- **`tests/test_launcher.py` (extend):** for an entry-less app: `source_dir`, `bundle_path` (None even with a
  bundle present), `presence`, `readiness`, `version == checkout_version`, `build_status` "unknown",
  `build_report` skips it, `launch` and `bring_to_front` raise `LaunchError`.
- **`tests/test_apps_tab.py`, `test_tray.py`, `test_settings_tab.py`, `test_main_window`-level (extend):** no-launch
  card: Launch hidden, no Stop, `_launch()` does nothing, hint text; banner rows and the three handlers
  (store patched to a temp support dir), Add emits `apps_changed` and writes the file; Lab Hub tile present,
  last, `OwnCard`, no Launch/Stop, text equals `version.version_string()` and `version.tooltip()`, verdict
  arrives through the worker (patched `self_status`), **3 polls call `self_status` zero times**, bursts
  coalesce, an exception leaves the line blank; Land visible when the `lab_hub` hygiene row needs attention;
  tray has no no-launch entry; Settings "Hidden projects" lists live `never`/`not_now` only and Show again
  rewrites the file; status bar carries `local_note`. **Existing test to update, stricter not weaker:**
  `tests/test_tab_groups.py:105-108` becomes `on_screen == {app.key for app in launcher.APPS} | {"lab_hub"}`.
- **Self-test:** a garbage `apps-local.toml` in the isolated support folder does not put anything in the
  self-test's `problems` (`_app_list_problems` or `selftest`).
- **Real Mac (Verify):** screenshots of Kaila's and Lab Hub's tiles before/after (spec §2); one Refresh timed.

### 13.7 Overlap with in-flight specs (checked 2026-11-21, `session_start.py --inflight` and `git diff`)
- **`self-update` (built, on main):** shares `self_update.py` and `AppsTab`. We add `OWN_TILE` and
  `verdict_line` after `SELF` (64-71) and amend one comment; we only **read** `self_status`, and do not touch
  `show_build_report` (762-824), `run_updates`, `_restart_on`, `_hold_for`, the helper, `stage_build` or
  `Rebuild`. The one real coupling is the post-install `--selftest` (13.0, 13.2): the local files must never
  fail it. `tests/test_self_update.py:819` replaces `SELF`; `OWN_TILE` is independent of that patch.
- **`land-from-tiles`:** Land button, badge, outcome and `Land all` are reused unchanged through `AppCard`.
  Constraint for Build: keep the Launch button before Land in `buttons` (151-172) and do not touch
  `_sync_land`, `_apply_hygiene`, `_update_land_controls` or the Land handlers. `Land all (N)` counts report
  rows (`_attention_rows`, 1151), not tiles, so it is unaffected; the Kaila and Lab Hub rows it already counted
  now have a tile.
- **`land-blocker-actions` (replaces `land-protected-conflict`):** its scope is `land_resolve.py`, `land.py`,
  `handoff.py` and the stop row in the Land window. No shared code path. The only shared file is
  `ui/apps_tab.py`, in different regions (Land handlers 1150-1300 against our 103-250, 585-760, 1079-1090).
  `claude/land-blocker-actions-f4b91c` has no commits yet (equals `main`). To keep hunks small, all new logic
  goes in new modules (`discovery.py`, `ui/own_verdict.py`, `ui/discovery_banner.py`); Build rebases on `main`
  before starting, re-runs `session_start.py --inflight`, and re-runs the full suite after any merge.
- **`progress-windows`, `tile-resolve` (superseded):** not touched.
- **One process issue, not code:** `session_start.py --inflight` lists two branches for this spec:
  `claude/apps-discovery-37b112` (worktree `bold-merkle-831506`) and `claude/apps-discovery-design-38b98a`
  (this one), both at `d8f66ec`. Only one session may Build; the owner should say which.

### 13.8 Concurrency and the Build model
- **Registry merge and reload: not concurrency work.** Pure functions plus module globals, read and written
  on the GUI thread only; no lock, no thread, no worker. `reload` was already synchronous in `refresh_all`.
- **The one thread** is `OwnVerdict` (§13.4), copying `Lander`'s queue-and-timer pattern; the thread never
  touches Qt or any registry state, only calls `self_status` and puts a frozen `BuildStatus` on a queue.
- **Advice: Sonnet, medium, for Build** (3-4 h), with `OwnVerdict` as its own small commit with its own tests.
  Opus only if Review finds a P1/P2 in that worker. The security-sensitive pieces (README, TOML writer,
  symlink guard) are fully specified above with their tests, so they do not need a bigger model; Secure
  reviews them after.

### 13.9 Decisions for the owner (recommendation first)
1. **Report clashes and a broken local file in a new `registry.local_note`, not `registry.last_error`**
   (spec §4.3 said `last_error`). Yes, because a `last_error` fails the self-test and a failed self-test rolls
   back an update. Shown in the status bar after Refresh, like the existing app-list message.
2. **A broken local file keeps the tiles it last had, suppresses new suggestions and refuses Add** (yes), or
   drops the local tiles.
3. **The local file may list only `[[suites]]`** (yes: it is the Apps page; tray, Backup and Tools code then
   cannot meet an entry with no launch command), or any group.
4. **Detection hardening beyond §4.1** (yes): a symlinked top-level folder is never suggested, and a folder
   name must be letters, digits, `.`, `_`, `-` (up to 64). Anything else is added by hand to the local file.
5. **`entry` is optional in `apps.toml` too** (yes: the way to move a block there by hand is otherwise an
   error that makes that whole file unreadable). Cost: a forgotten `entry` becomes a no-launch tile whose hint
   line says so, not an error. Move a block only after a build with this change is installed.
6. **Lab Hub's verdict line is computed on a background thread at startup and Refresh** (yes; the line is
   blank for a moment), or shown only after Check builds has run.
7. **One new plain string:** when a project has no README, its summary is "A project in your lab folder."
   (the registry requires a summary).

### 13.10 Failure modes (all keep the hub usable)
Absent files: nothing. Unreadable or unparsable `apps-local.toml`: last good part, `local_note`, no Add, no
suggestions. Clash: entry dropped with a note. `apps.toml` broken: as today (`last_error`, last good list).
Corrupt `apps-dismissed.json`: reads empty, renamed `.bad` on the next write. Unwritable support folder, full
disk, concurrent edit: `DiscoveryError`, status-bar message, no state change, the banner row stays. Lab folder
missing: no suggestions. README unreadable or hostile: folder name and fallback summary. `self_status` raises or
git is absent: tile shows version only. Worker still running at quit: daemon thread, nothing to join.

### 13.11 Migration of existing state
None. Both files are new and absent means empty. `apps.toml` and its 9 entries are untouched. First run
shows the banner once for Kaila, Overseer and Shopfront HQ (not for `foundry`, `toolbox`, `lab_hub`; the
`imprint-base`/`imprint-deps` worktrees are absent from the folder today but covered by the `.git`-file test).
Rollback: delete either file; an older build ignores both files, but rejects an `apps.toml` holding an
`entry`-less block (it keeps its bundled copy), which is why decision 5 says to wait for the new build.

### 13.12 Files Build creates or changes (signatures only)
New:
- `lab_hub/discovery.py`: `class DiscoveryError(Exception)`; `@dataclass(frozen=True) class Suggestion:
  folder: str; name: str; summary: str; entry: str | None`; `@dataclass(frozen=True) class Dismissal:
  answer: str; at: date`; `today() -> date`; `dismissed_path() -> Path`; `load_dismissed() ->
  dict[str, Dismissal]`; `dismiss(folder: str, answer: str, today: date | None = None) -> None`;
  `forget(folder: str) -> None`; `hidden(lab_root: Path, today: date | None = None) -> list[tuple[str,
  Dismissal, date | None]]`; `describe(project: Path) -> tuple[str, str]`; `scan(lab_root: Path,
  registered: Collection[str], dismissed: Mapping[str, Dismissal], today: date) -> tuple[Suggestion, ...]`;
  `suggestions(lab_root: Path, today: date | None = None) -> tuple[Suggestion, ...]`; `toml_string(value:
  str) -> str`; `render_entry(s: Suggestion) -> str`; `add(s: Suggestion) -> None`; constants
  `NOT_NOW_DAYS = 14`, `README_MAX_BYTES = 8192`, `SUMMARY_MAX = 220`, `NAME_MAX = 60`,
  `SCAN_MAX_ENTRIES = 400`, `NAME_OK`.
- `ui/own_verdict.py`: `class OwnVerdict(QObject)`: `ready = Signal(object)`; `request(lab_root: Path) -> None`;
  `shutdown() -> None`.
- `ui/discovery_banner.py`: `class SuggestionBanner(QWidget)`: `add_requested`, `not_now_requested`,
  `never_requested = Signal(object)`; `set_suggestions(items: tuple[Suggestion, ...]) -> None` (no rebuild when
  equal).
- `tests/test_discovery.py`; additions to the existing test files named in §13.6.
Changed:
- `lab_hub/launcher/registry.py`: `ExternalApp.entry: str | None`, `ExternalApp.launchable`; `LOCAL_NAME`,
  `RESERVED`, `local_note`, `local_ok`, `local_path() -> Path`, `parse(text, source=None, *, local=False)`,
  `merge_local(base, local) -> tuple[Registry, tuple[str, ...]]`, `_read_local()`, `_with_local()`; the three
  filtered properties; `use()` resets the new globals.
- `lab_hub/launcher/state.py`, `control.py`: the guards in §13.2 and the amended comment at 671-676.
- `lab_hub/self_update.py`: `OWN_TILE`, `verdict_line(row: BuildStatus) -> str`, comment on `SELF`.
- `ui/apps_tab.py`: `AppCard` (no-launch branch), `OwnCard`, `AppsTab(discover: bool = False)`,
  `apps_changed = Signal()`, `_scan`, `_add_suggestion`, `_dismiss_suggestion`, `_sync_cards` choosing the card
  class, `recheck` calling `_scan` and the verdict request. `ui/tiles.py:94,108` PlainText.
  `ui/main_window.py:72` (Apps page source and `discover=True`), connect `apps_changed` to `refresh_all`,
  show `local_note` in the status bar (326-339), the `launchable` skip at 368. `ui/tray.py:121`.
  `ui/settings_tab.py`: "Hidden projects" card, filled in `refresh()` (176).
  `main.py`: the informational `local_note` line.
- Docs: README Apps section, CHANGELOG (Document phase).

## 14. For the owner at the Architect gate (2026-11-21)
Design and Architect were written by their agents; the owner approves, agents do not. Nothing here changes the approved §7 wording.
**Reconciliation for Build:** Design (12.2.4) puts the no-launch hint line in the tile's `detail` slot; Architect (13.2, `AppCard.refresh`) puts it in the existing `self.service` label. Both are one reserved line on the tile; Build picks the one that keeps tiles level and says which in the commit.
**Decisions (recommendation first; "yes" = as written in the section):**
1. §13.9 items 1-7 (local_note not last_error; broken local file keeps last tiles; local file `[[suites]]` only; detection hardening: no symlinked folder, name pattern; `entry` optional in `apps.toml` too; Lab Hub verdict on a background thread; fallback summary "A project in your lab folder."). Recommendation: yes to all.
2. Ask Claude: no tile has the button today (it lives in the Land and Check builds windows), but §2.3/§4.6 say tiles offer it. Recommendation: no tile button now; Open in Terminal is always visible on no-launch tiles; Ask Claude stays in the Land window.
3. Design wording proposals 12.7 A-G (not approved): "and N more" (banner capped at 3), status-bar lines, inline errors, "No hidden projects.", the broken-file and corrupt-file lines, date "5 Dec". Recommendation: approve all.
4. Banner README sentence is shown muted, not italic (stylesheet has no italic). Recommendation: yes.
5. Process: two branches exist for this spec (`claude/apps-discovery-37b112`, `claude/apps-discovery-design-38b98a`, both at `d8f66ec` before this commit). Only one session builds; say which. Recommendation: build on this one, since it holds the Design and Architect sections.
6. Existing issue, out of scope: Paper theme `warn` text on cards is 3.49:1 contrast. Belongs in a UX audit.
**Build model advice:** Sonnet, medium, ~3-4 h; `OwnVerdict` (the one worker thread) as its own commit; Opus only if Review finds a race there. Registry merge is not concurrency work.
