# Spec: Apps finds new projects and shows Lab Hub itself

Status: **Define, awaiting the owner's approval (GATE: user-visible).** Written 2026-11-21 from the owner's request of the same day. No code written.
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
