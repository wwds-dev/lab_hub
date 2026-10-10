# Lab Hub

One front door for the lab's desktop tools: a launcher for the standalone apps,
and a home for the small utilities that never had a UI.

Tabs: **Apps** · **Websites** · **Dashboards** · **Backup and Sync** · **Tools** · **Settings**

## Why two kinds of thing

The projects behind this app do not want the same treatment, so they do not get
it.

**Launched, not embedded.** Sentinel, Imprint, SONAR, Backup Control Center,
git_autosync, Unblock Tracker and Backstage are complete PySide6 applications — own
window, own settings, own background work, own lifecycle. Embedding them would mean
nesting seven apps' worth of UI and state inside an eighth, and every one of them is
something you leave running. Lab Hub starts them as separate processes: quit it
and they keep going. Their internal agents are *their* business, not Lab Hub's.

**Embedded, not launched.** convert_epub and image_tools were single-file
scripts whose configuration lived in a `# === CONFIG ===` block at the top —
you edited the source to point them at a folder. There is no UI to preserve and
nothing to keep running, so the logic moved into `lab_hub/tools/` as plain
functions and the config block became a form.

The conversion engine under `tools/convert/` is a **vendored copy** of
`active/toolbox/convert_epub/ebook_converter/`, where it is developed and tested. It is
copied rather than imported so Lab Hub does not depend on a sibling checkout
being present — keep the two in step when either changes.

**Narrator belongs here.** Its tab runs Lab Hub's bundled ebook-to-audiobook
engine in a separate, stoppable worker process. It does not launch or import
Sentinel and works the same way from source and from the installed app.

## Tabs

**Trackpad swipes change tab** (`ui/swipe.py`). macOS has two horizontal
swipes and the app sees them as two different Qt events, so both are handled:
a two-finger swipe arrives as an ordinary horizontal scroll (`QEvent.Wheel`),
a three-finger one as `QEvent.NativeGesture` with `Qt.SwipeNativeGesture`.
Which one reaches the app is a System Settings choice, not ours —
**Trackpad ▸ More Gestures ▸ Swipe between pages**.

Worth knowing before filing it as broken: by default macOS gives the
three-finger horizontal swipe to *Swipe between full-screen apps*
(`TrackpadThreeFingerHorizSwipeGesture = 2`), and while that is selected the
window server consumes the gesture and no application ever sees it. Two fingers
is what works out of the box.

Three rules it keeps:

* **It never wraps.** The macOS page swipe does not, and a navigation gesture
  that loops makes the ends indistinguishable from the middle.
* **Only the top row moves.** Apps through Settings, and nothing else: a swipe
  inside Tools — on *All tools* or any tool's page — moves the window's tabs,
  never the Tools sub-tabs, which are reached by clicking (the user's call,
  2026-10-07). Until then the window registered both rows, innermost first, so
  a swipe inside Tools walked the tools before falling out to the top row.
  `SwipeTabs` still supports that — pass several tab widgets, innermost first,
  and `tests/test_swipe.py` keeps it working — but the window passes one.
* **A widget that can genuinely use the gesture keeps it.** A table wide enough
  to scroll sideways (the Narrator library's eight columns) takes the swipe;
  one whose content fits does not, because it is not using it for anything.

One gesture is one tab: the change latches on the first delta past the
threshold and the rest of the swipe — including the momentum after the fingers
lift — is swallowed. Without that, inertia alone walks several tabs.

### Apps
One tile per umbrella app: **Sentinel**, **Imprint**, **SONAR**, **Provisio**,
**SYNDUSTRYX** (the last two added 2026-10-07).

**Provisio is a native app** as of 2026-10-07: `/Applications/Provisio.app`
(its own `scripts/install_app.sh`), a window that starts and stops its own local
server and switches between a demo and a real workspace. Its tile launches it
like Imprint's, from the bundle when installed and from the checkout's `.venv`
(`main.py`) otherwise. Until then it was this hub's one **web app**, and that
support is kept for any served app (`ExternalApp.url`): *Running* means the
address answers, Launch starts the server through a login shell and
`ui/web_open.py` opens the page once it answers, **Stop** sends SIGTERM to the
server's process group (only for a server started with the absolute entry path
Lab Hub uses), and *Did not start* waits 60 seconds (`SERVER_CONFIRM_SECONDS`)
because a dev server compiles before it listens. The tile must not start
Provisio's browser-mode server any more: vinext allows one dev server per
checkout, so it would stop the app's own server from starting.

**Headroom has no tile.** It is Provisio's `engine/` — a sub-module, reached
through Provisio, under the same rule as Tunnel and Bug Spray below.

**SYNDUSTRYX is the Antfarm workstation, named by the owner.** Its current
source and Lab registration use `syndustryx`; the source stays in the Codex
workspace and `active/syndustryx` links to it. Desktop records and credentials
migrate compatibly; historical releases remain intact. Two registry fields
exist for it:

* `bundle_dir="dist"` — its builder stops at `dist/SYNDUSTRYX.app` and has no
  installer, so a bundle there counts when none is installed. The tile says
  *Built* rather than *Installed*, and shows the path the lab reaches it by; the
  running marker uses the resolved path, because `ps` only ever shows the real
  one. An installed copy in `/Applications` still wins.
* `runs_from_source=False` — its `server.py` is the engine without the window,
  on port 8765, which the Lab Project Monitor already holds. Only the built
  bundle is ever launched; with none built, Launch is disabled and says so.

Its builder stamps its own release version and it has no git history, so
Check builds reports comparison with the lab version scheme as *unknown* — with a note that it does not use
the lab's version scheme, not the usual "rebuild it once", which could not work.

A `VERSION` file holding a release line rather than an arc is kept whole:
Provisio's `2.0` reads `v2.0.064`, the same number its own footer stamps. Only a
three-digit tail is treated as a hand-written build (Sentinel's `2.002`).

**Agents and sub-modules are deliberately not here.** Tunnel and Bug Spray live
inside Sentinel (`sentinel/agents/`), the video pipeline inside Imprint,
macro and Playmaker inside SONAR — and each is reached from its own app, never from
Lab Hub. Two doors to the same feature is how you end up with a standalone VPN
Agent window that knows nothing about the Sentinel session that should own
it. The same rule covers the menu bar, which lists only these umbrella apps.

A tile shows where its app will start from:

| State | Meaning |
| --- | --- |
| Installed | found in `/Applications` — launched with `open` |
| Built | not installed, but built inside its checkout (`bundle_dir`) — launched with `open` |
| Source only | not installed, but the checkout is there — run with that project's own `.venv` |
| Stopped | a web app whose server is not answering — Launch starts it |
| Not found | neither; Launch is disabled |
| Starting… | launched, waiting for it to appear |
| Running | its process is in the table; the button raises it instead |
| Did not start | it was launched and never came up — a notice, and it expires |
| Started | it was launched and nothing here could watch for it — also a notice, and it expires |

Source runs never use Lab Hub's own interpreter. Frozen, that is this app's
binary, and it would run the other project inside this bundle's dependencies.

**Whether an app *can* start is answered before the button is pressed**, by
`launcher.readiness()` rather than by `launch()` failing into a dialog. It
catches the two cases that used to look fine right up until the press: a
checkout with no `.venv` and no `python3` on `PATH`, and a bundle that is still
a directory but has lost the executable inside it. Either disables Launch and
says why on the tile itself. The executable is read from `CFBundleExecutable`,
not assumed to share the app's name — Sentinel's binary is `SentinelLauncher`,
and an `osacompile` applet's is always `applet`.

**Two kinds of bundle, and *Bring to front* has to tell them apart.** A
PyInstaller bundle owns its own window, so `open -a` raises it. Sentinel's does
not: `/Applications/Sentinel.app` is a compiled AppleScript applet that starts
the real GUI as a separate process, which edits go live in without a rebuild.
macOS then registers two apps — the applet, which owns no window, and the
python process, which does. `open -a` reaches the applet, which is sitting
inside `do shell script` and deaf to the reopen event, so raising the app that
way silently did nothing at all. `is_launcher_bundle()` recognises one by its
`applet` executable and re-runs the entry script instead; the app's own
single-instance guard hands off, brings the running copy forward and exits 0. A
non-zero exit is reported with the tail of its output rather than swallowed.

**A running app is matched on two paths, not one.** `running_markers()`
returns the installed bundle's `Contents/MacOS` *and* the checkout's entry
script, and a hit on either counts. The bundle is not reliably the thing that
keeps running: Sentinel's is a one-shot launcher that execs the project's own
python and exits, so moments after a good launch nothing in the process table
mentions the bundle at all. Matching the bundle alone reported a running
Sentinel as *Did not start* and went on reporting it for as long as the window
stayed open. Checking both is also what survives the next change of launcher —
this one bundle has been a PyInstaller build, an AppleScript applet and a
compiled C stub inside a month, while the checkout path stayed put.

**The checkout half comes from the bundle when the name here is stale.** The
same bug came back on 2026-10-07 by a different road. `ExternalApp.project` is a
directory name written by hand in `launcher.py`, so it is only as current as the
last Lab Hub build: the Sentinel folder was renamed from `sentinel_fork` to
`sentinel`, the installed v2.049 went on looking for the old one, `source_dir()`
found nothing, the checkout marker disappeared and the tile was left matching
the bundle alone — the exact failure above, reached without touching
`running_markers()` at all. `source_dir()` now falls back to the checkout the
bundle records in `Contents/Resources/project_root.txt`, which Sentinel's own
installer rewrites the day the folder moves. The configured lab folder is still
asked first, so the Settings tab keeps deciding where projects are looked for;
the record is the fallback, not the authority. This also restores the version
label and the build report, which went blank for the same reason.

**Silence is only evidence when there was something to listen for.**
`launch_is_observable()` asks whether a missing process means anything at all.
For a stub bundle that execs and exits, with no checkout left to watch, a launch
that worked and a launch that died look identical from here — so the tile says
*Started*, with a tooltip saying it cannot tell, rather than accusing a running
app of dying. *Did not start* is reserved for the cases where the app really was
being watched.

**A stale `project` fails the build.** `main.py --selftest` prints a
`registered paths` line per app and fails when one's configured directory is
gone while the bundle's own record points at a working checkout — the signature
of a rename that was made everywhere except here. `build_app.sh` runs the
self-test against the built bundle before installing it, so the next rename is
caught at build time instead of on a tile.

**A headless daemon is not an open app.** A command line carrying a flag in
`NO_WINDOW_FLAGS` (`--headless`) is skipped: SONAR ships a launchd agent running
`main.py --headless` around the clock, and once the checkout became a marker
that agent alone made the tile read *Running* permanently — offering to raise a
window that does not exist. `--background` is deliberately not in that list; it
is the whole app started with its window hidden, which is how Lab Hub starts
Backup Control Center and git_autosync, and those can be raised. Matching is
done per command line rather than across the whole snapshot, so a flag on one
process cannot discount another.

**"Running" can outlive the window, legitimately.** SONAR and Lab Hub both hide
to the menu bar on close and quit only from there, so closing the window leaves
the process up and the tile correctly says *Running*. That is not a stale tile;
*Bring to front* will bring the window back.

**An installed build older than its source says so.** A frozen bundle is only
as new as its last build, and committing to a project does not rebuild it — so
the tile reads `v2.104 · 5 behind`, and the tooltip says Launch will open the
older build until it is rebuilt and reinstalled. Reporting only the number
would be true and useless: the button would still open the old one without a
word. A launcher bundle can never be behind, because it runs the checkout.

The commit count is cached against the repository's `HEAD` (and the ref it
points at), so the tile can re-read the version on every poll without a
`git rev-list` per app every three seconds. A bundle's own number is a single
small file read.

**Check builds** on the launchpad answers the whole question at once: for every
registered app, is what the button would open the newest thing there is? It
reports `behind` (commits since the build), `uncommitted` (edits the commit
count cannot see — it only moves on commit, so a bundle built from the last
commit looks level while the source has since been edited), `unknown` (installed
but carrying no stamp), and names the build script for anything out of date.

A launcher bundle is never out of date, and being dirty does not change that:
it runs the source, so uncommitted edits are exactly what opens.

It hands over the command rather than running it: **Copy commands** puts it on
the clipboard, and **Copy and open Terminal** does that and opens a window to
paste into. Not typed in for you — driving Terminal needs an Apple Events
grant, and a window that runs something the instant it opens is the wrong shape
for a command that replaces an installed app. The flag is read from each build script, because they
disagree and do so silently: `sonar`, `unblock_tracker`, `lab_hub` and Sentinel
build into `dist.noindex/` and copy into `/Applications` only when passed
`--install`, while `backup_manager`, `git_autosync` and Imprint install by
default. A command without the flag where it is needed costs several minutes of
build and leaves the old app exactly where it was — the thing the report exists
to warn about. Reading it from the script beats a table here, which would be a
second place to be wrong.

**Renaming a launched app means rebuilding Lab Hub.** The registry is compiled
into this bundle, so until it is rebuilt the tile looks for a bundle name that
no longer exists, falls back to the checkout, and reads *Source only* — which
looks like a fault in the renamed app rather than a stale hub. This has now
happened twice, with `Create & Publish` → `Imprint` and `Sentinel Fork` →
`Sentinel`.

Renaming the *checkout folder* is the sharper version of the same thing, and it
used to be worse than *Source only*: a stale `project` cost the tile its running
marker and produced a confident *Did not start* under an app that was open on
screen (`sentinel_fork` → `sentinel`, 2026-10-07). A stub bundle's own
`project_root.txt` now covers the gap until Lab Hub is rebuilt, and the
self-test fails the next build that is still wrong about it — but rebuild
anyway, because that record only exists for the bundles that have one.

**A launch is not believed until the app shows up.** `launch()` returning only
means something was started. A source run is watched for a second and a half
and reports its exit code and captured output if it dies, but an installed
bundle is started through `open` and is not our child, so there is no code to
read. The tile therefore says *Starting…* and waits for the process to appear
in the table; if it has not within twenty seconds it says *Did not start* and
the status bar names where the output went — the `log show` predicate for a
bundle, the captured temp file for a source run. Before this, a child that died
inside `QApplication()` was indistinguishable from one that started fine: the
button greyed for a moment and nothing else ever happened.

*Did not start* is a notice about one launch rather than a property of the app,
so it expires after a minute, and **Re-check** clears it outright. It used to
persist: a tile could still be reading *Did not start* long after the app had
been opened and closed again by hand.

### Websites

**altmerch.store** (Shopify) and **bookadatewithme.com** (Netlify), registered in
`lab_hub/sites.py`. Built like the Apps tab on purpose — same tile, same grid,
Re-check, a state on every tile that is re-read rather than remembered, and a
poll that runs only while the tab is on screen — but a site's state is **whether
it answers right now**: *Online*, *Error 404* (or whichever code), *Unreachable*,
with the detail in the tooltip. **Open site** opens it; **Show files** shows its
local folder (`active/altmerch_store`, `~/Documents/Websites/bookadatewithme`).

The check is a `HEAD` through Qt's `QNetworkAccessManager`, on the event loop
rather than a thread — so there is nothing to stop when the app quits — and a
page is never downloaded to learn its status. It runs when the tab is shown (if
the last check is over a minute old), every five minutes while it stays shown,
and on Re-check; never in the constructor, since the window builds every tab at
startup. A 4xx counts as **down**: a host answering 404 at the front door is
serving nobody. That is exactly what bookadatewithme.com did the day this tab
was written — Netlify answering for the domain with no site deployed behind it.

The tests never reach the network: a session-scoped fixture in
`tests/conftest.py` replaces `SiteChecker.check`, because a swipe or a tab switch
in any test can reveal this tab.

### Dashboards

Every entry in the lab's `dashboard_catalog.json` — the **same file** the Lab
Project Monitor's Dashboards section reads, one folder up from the projects
folder. Nothing is copied into Lab Hub: add a dashboard to the catalog and it is
on this tab (and in the menu bar) without a rebuild; the tab rebuilds itself when
the catalog's modification time changes. A tile shows its source and kind, and a
state: *Link*, *Local file*, or *File missing* (Open disabled). **Show catalog**
reveals the file to edit. On 2026-10-07 the Antfarm workstation concept (superseded
by the SYNDUSTRYX app) and Provisio · Protection Studio (the hosted copy of the
Provisio app, which now has its own tile) were taken out of the catalog.

A local dashboard opens through the Monitor's own server
(`127.0.0.1:8765/dashboards/<id>`) when that is up, because its route wraps an
HTML fragment — the Prompt injection taxonomy is one — in a proper page; otherwise the
file opens directly, which is the Monitor page's own fallback. Long paths are
shortened on the tile (full path in the tooltip): a path is one unbreakable word,
and at full length the Antfarm workstation's (since removed from the catalog) set
the whole tab's minimum width.

### Backup and Sync

Launch **Backup Control Center** and **git_autosync** from one place. Spelled
"and", not "&": Qt reads an ampersand in a tab label as a mnemonic marker and
renders "Backup & Sync" as "Backup _Sync". Neither app has a launchpad tile, so
the tab carries its own **Check builds** and Update now
(`AppsTab(check_own_builds=True)`), scoped to these two.

### Tools

The built-in utilities and occasional standalone tools are grouped under one
tab: **Convert Files**, **Narrator**, **Prepare Images**, **Unblock Tracker** and
**Backstage**.

It opens on **All tools** (`ui/tools_tab.py`, added 2026-10-07): every tool as a
tile, on the same grid as Apps, Websites and Dashboards, with Re-check and an
on-screen-only poll. A built-in tool's tile says only what can be known without
asking it to do anything — *Running* while a job is going, *Needs Calibre* when
Convert Files has no `ebook-convert`, and otherwise *Built in*; Narrator checks
its keys and ffmpeg when it starts, so *Ready* before that would be a guess.
**Open** moves the tab strip to that tool's page. Unblock Tracker and Backstage
get the Apps tab's own tile (`AppCard`), so Launch, *Running*, *Bring to front*
and the version behave as they do there. Their own pages are unchanged —
Backstage's still carries Check build — and neither gains a menu bar entry.

#### Convert Files
Any document format Calibre reads into any format it writes — **47 in, 19 out**.
EPUB, AZW3, MOBI, DOCX, PDF, TXT, RTF, FB2, KEPUB and the long tail, in both
directions.

Drop files or folders onto the list, or use **Add Files…** / **Add Folder…**.
Folders are scanned (recursively unless you turn that off) and anything Calibre
cannot read is left out, with a line saying which extensions were rejected —
silently dropping a file you just dragged in looks like a broken app.

Converted files land beside the original or in one folder you pick; in folder
mode two books of the same name get a `-2` suffix rather than overwriting each
other. Files already in the target format, and outputs that already exist, are
skipped unless you turn on overwrite. One unreadable file fails on its own and
the rest of the queue carries on.

Needs Calibre's `ebook-convert`; the tab says so and disables Convert when it is
missing.

    brew install --cask calibre
    /Applications/calibre.app/Contents/MacOS/calibre_postinstall

Output is streamed line by line, and Stop terminates the running conversion —
a full-length book takes minutes.

> **PDF, DjVu and comic formats are poor inputs.** Calibre converts them, but
> they carry no reliable text structure, so expect broken paragraphs and lost
> formatting. The tab warns rather than refusing.

#### Narrator
Two sub-tabs sharing one settings object: **Convert** turns one ebook into an
MP3 audiobook, and **Library** browses a generated ebook catalogue and feeds
books into Convert.

**Convert** extracts the book's text (EPUB, PDF, MOBI, AZW3 or TXT), creates
speech with OpenAI in one of ten voices, and joins the chunks into a single
MP3. Chunk size (in tokens) is adjustable; interrupted books keep the chunks
they already finished and resume on the next run rather than starting over.
Requires `OPENAI_API_KEY` (Lab Hub's `.env` file or the environment) and
`ffmpeg` on PATH — the tab checks both before it will start and explains
which is missing. Runs as a separate, stoppable worker process (`QProcess`):
from source that's `python -m lab_hub.tools.narrator.converter`, frozen it's
the app's own binary re-invoked with `--narrator-worker`, so the packaged app
needs no separate interpreter for it. OpenAI usage costs real money.

**Library** reads `ebook_catalog.csv` from wherever the Codex project last
wrote it (`~/Documents/Codex/**/outputs/`, newest match; overridable with
`EBOOK_CATALOG_PATH`) and shows it as a searchable, filterable table: Ranked
recommendations, Books I've read, or Narrated books (detected by matching
title against existing audio files — `.mp3`/`.m4b`/`.wav`/`.aac` — under the
Narrator output folder, so nothing has to be tracked separately). Two
per-row checkboxes persist to `narrator_library_state.json`: **Read** and
**Queue**. Double-click a row, or **Use selected in Converter**, to load that
book straight into the Convert sub-tab. **Copy queued books to Narrator**
copies every queued file into the default Narrator input folder in one pass,
skipping books already there and reporting what was unavailable.

#### Prepare Images
Three tools sharing one log:

- **Resize for print** — copies at an exact pixel size with the DPI written into the
  file. *Fit* scales and centres on a canvas; *Exact* stretches to fill, which
  distorts anything that is not already the target aspect ratio. The two modes
  were the two separate `dpi/` scripts.
- **Rename in sequence** — numbers files `base_001`, `base_002`, … continuing from the
  highest number already in the target folder, so a second batch never collides
  with the first. Optionally moves them there too.
- **Move small aside** — moves images at or under a size threshold into a `Delete`
  subfolder. Moved, not deleted: a filter on pixel size alone will occasionally
  catch something wanted.

#### Unblock Tracker

An occasional standalone tool, kept with the other tools rather than competing
with the main launchpad apps.

#### Backstage

A standalone app with its own repository, launched from its card at the end of
Tools and **nowhere else**: no Apps tile and no menu bar entry, by the user's
choice (2026-09-27). It lives in `launcher.TOOLS_ONLY_APPS`, which the menu bar
does not read and `launcher.APPS` — the self-test, the build report, Settings —
does; `tests/test_tab_groups.py` pins both halves. Its card carries a **Check build**
button — the launchpad's Check builds and Update now, scoped to Backstage alone
(`AppsTab(check_own_builds=True)`), since a Tools-only app has no launchpad tile to be
rebuilt from. A scoped check says which apps it looked at and never reports
"every app", which only the launchpad's all-apps report can claim.

### Settings
Only the lab folder, and only because it cannot always be inferred: launching an
installed app does not need it, but running one from source does, and the
Dashboards tab finds its catalog one folder up from it. Blank means auto-detect
(`$LAB_ROOT`, then the checkout this was run from, then `~/Documents/lab/active`).

## One instance, and the menu bar

Only one copy runs. The guard is a local socket rather than a lock file,
because a lock can only refuse the second launch — a socket lets it hand the
request over, so double-clicking the Dock icon brings the running window
forward instead of doing nothing.

The menu bar item carries the same 2×2 mark, drawn solid black on transparent
and flagged as a mask so macOS recolours it for a light or dark menu bar. Its
menu opens the window and launches apps directly — **umbrella apps only**
(`launcher.MENU_BAR_APPS`). An agent belongs to its own app, so it gets no entry
here; listing VPN Agent, Bug Spray and vidforge turned a six-item menu into a
nine-item one and buried what is actually reached for.

A served app picked there opens its page if its server already answers — a
second launch would start a second server on the next port — and otherwise
starts it and opens the page once it does (no registered app is served since
Provisio became a native app). Below the apps, a **Websites** submenu opens
each site and a **Dashboards** submenu opens each catalog entry; the dashboards
are re-read from the catalog every time the menu opens, and a missing local file
is listed but disabled.

Because the app lives in the menu bar, **closing the window hides it** rather
than quitting — a conversion left running would otherwise lose the log it is
writing to. **Quitting from the Dock, or with ⌘Q, hides it as well.** The Dock
icon only exists while a window does, so choosing Quit from it means "clear this
off my screen", not "shut the whole thing down"; the menu bar item's own **Quit
Lab Hub** is the single real exit. The first time the window is hidden it says
so, so nothing disappears silently. If no system tray is available the app falls
back to quitting on window close — hiding with nothing to retreat to would leave
it running with no way to reach or stop it.

macOS routes both the Dock's Quit and ⌘Q through `applicationShouldTerminate:`,
which Qt delivers as a `QEvent.Quit` to the application object; `_QuitGuard` in
`ui/main_window.py` filters it. The refusal is `event.ignore()` — **consuming
the event by returning `True` is not enough**, because a `QEvent` is accepted
from the moment it is constructed and filtering one out leaves that flag set,
which macOS reads as "yes, terminate". `MainWindow.quit()` never goes through
this event at all: it calls `QApplication.quit()`, which ends the event loop
directly. A test runs a real event loop, with a failsafe timer, to prove that
still works — the failure mode being guarded against is an app nobody can quit.

When **Open Lab Hub at login** is enabled, Lab Hub starts hidden in the menu bar
and quietly starts Backup Control Center and git_autosync the same way. After
the Mac wakes from sleep, it checks those two companions again and starts only
the ones that are not already running; no windows are brought forward.

## The Dock icon follows the window

Lab Hub is two things at once: a menu bar item that stays, and a window you open
occasionally. The Dock carries an icon only while there is a window behind it.

| Situation | Dock icon |
| --- | --- |
| Started at login (`--background`) | no |
| An app launched from the menu bar | no |
| Lab Hub's own window opened | yes |
| Window closed again | no |
| Quit chosen from the Dock, or ⌘Q | no (it hides) |

Three pieces, and leaving any one out breaks it in a way that looks like one of
the others:

* **The bundle declares `LSUIElement`.** LaunchServices pins a bundled app's type
  from `Info.plist` at launch, so a runtime switch alone is ignored in the `.app`
  while working perfectly from source. `build_app.sh` sets the key after
  PyInstaller runs, then re-signs — editing `Info.plist` invalidates the ad-hoc
  signature.
* **`ui/dock.py` switches the activation policy** — `Regular` against `Accessory`
  — through one Objective-C selector reached with ctypes, rather than pulling a
  whole framework binding into the bundle for a single call.
* **Promoting is not enough; the app has to be activated too.** An app that moves
  from `Accessory` to `Regular` gets a Dock icon but does not become frontmost, so
  its window is created and then sits behind everything else. That is
  indistinguishable from no window at all, and it is what made the first attempt
  at this look like a failure. `dock.activate()` sends
  `activateIgnoringOtherApps:` straight after the promotion; the order is pinned
  by a test.

**Measure this with `--selftest`.** Steering by `lsappinfo` produced two wrong
conclusions in a row here, including one that had this feature reverted as
impossible — but the tool was not the liar the note here used to call it. Its
`ApplicationType` does follow the live policy: against one running pid it reads
`Foreground` with the window up and `UIElement` once the window is hidden. What
it could not show was a switch that was not happening, because the promotion was
landing and the activation was missing. Read it if you like, but the self-test is
the reading that comes from inside the process, via `dock.current_policy()`:

    dock policy:     starts Accessory (menu bar only); switchable at runtime: yes

The menu bar item is unaffected by any of this: a status item does not depend on
the activation policy, which is what makes the switch safe. Closing the window
never removes it; only quitting does.

Hiding the Dock icon is skipped when there is no menu bar item — without a status
item the Dock is the only way back, and dropping it would strand the app.

Using the menu bar does not drag the window along either. Opening the tray menu
activates Lab Hub, and so does the focus change when a launched app appears; both
used to be mistaken for "the user wants the hub back". `suppress_reopen()` ignores
activations for five seconds afterwards — a grace, not a block, so switching back
to Lab Hub still restores the window and "Open Lab Hub" still works while
suppressed.

## Layout

    main.py              entry point; --selftest checks a build
    lab_hub/             no Qt imports below this line
      config.py          settings, stored in Application Support
      launcher.py        finding and starting the standalone apps
      sites.py           the websites, and what an answer from one means
      dashboards.py      reading the lab's dashboard catalog
      tools/convert/     any format to any format (vendored engine)
      tools/images.py    resizing, renaming, moving small files aside
    ui/                  the only package that imports PySide6
      widgets.py         folder field, run/log panel
      worker.py          runs any tool off the GUI thread
      single_instance.py the one-copy guard
      tray.py            the menu bar item
      links_tab.py       the Websites and Dashboards tabs
      web_open.py        opens a web app once its server answers
    tests/               pytest, offscreen — see Tests below
    assets/make_icon.py  regenerates icon.icns and the menu bar PNGs
    docs/                reserved for future documentation; currently empty

The tools take a `Reporter` rather than printing, which is what lets the same
function back both the GUI and a shell call. `ui/worker.py` supplies a Reporter
that emits Qt signals and raises `Cancelled` when Stop is pressed.

## Running and building

    uv venv .venv && source .venv/bin/activate
    uv pip install -r requirements.txt
    python main.py

    uv pip install -r requirements-dev.txt
    python -m pytest

    ./build_app.sh            # -> dist.noindex/Lab Hub.app
    ./build_app.sh --install  # -> /Applications/Lab Hub.app

`build_app.sh` runs `--selftest` against the built binary before it installs
anything. That check matters here because Pillow ships a binary extension, and
because a frozen app that writes its config inside its own bundle breaks its
signature and loses everything on reinstall — settings go to
`~/Library/Application Support/Lab Hub/` instead.

## Tests

`python -m pytest` — offscreen, no display needed, about a second.

The weight is on the window lifecycle, because that is where this app has
actually broken: the red button once quit instead of hiding, and the fix for
that then re-showed the window in the same breath as closing it (a visible but
never-repainted black rectangle). Both shipped. `tests/test_window_lifecycle.py`
is that hunt written down, and its regression test fails against the old code.

`tests/test_swipe.py` drives synthetic events shaped the way macOS shapes the
real ones, because the gesture itself cannot be produced from a test — what it
pins down is everything after the event arrives. Every rule above is
mutation-tested: removing the momentum guard, the latch, the dominance check or
the sideways-scroll veto each fails a named test. Two of those tests originally
passed against the broken code (they swiped off the last tab, where nothing
could move either way); if you add one here, check it fails without the feature.

`--selftest` covers what pytest structurally cannot. It runs against the built
binary from `build_app.sh`, and beyond checking assets and paths it **starts a
real PySide6 child under every registered app's own venv**. That is the one bug
class this app is uniquely prone to — it exists only in the bundle, because from
source there are no Qt paths to leak into a child — so no unit test can reach
it. A build whose launched apps would die now fails before it installs.

It probes each app's interpreter rather than running the app. The environment
being scrubbed is shared, but the Qt build on the other side of it belongs to
each project, so each venv is its own answer; running the apps themselves would
open six windows on every build and would prove nothing extra, because the crash
happens inside `QApplication()` before any of them reaches its own code. An app
with no checkout or no venv is reported as skipped, not as a pass — and so is one
that is not a Qt app started from a venv at all (SYNDUSTRYX only ever opens its own
bundle). Provisio is probed like the others since it became a PySide6 app.

It also fails a build with **no TLS backend**: the Websites tab's checks need
Qt's `tls` plugin, which a bundle has only if PyInstaller collected it, and
without one every site would read *Unreachable* — which looks like the sites'
fault. The dashboard catalog and the registered sites are listed, never fatal.

## What this does not do

It does not replace any of the projects it launches. Each keeps its own repo,
README, venv and build script; Lab Hub only points at them. Changing what
Sentinel does still mean changing Sentinel.

## Version

`v<MAJOR>.<BUILD>` — e.g. `v2.025`. **MAJOR** is the product arc, the only
hand-edited part, in the `VERSION` file at the project root. **BUILD** is
`git rev-list --count HEAD`, zero-padded to three digits, so it is derived and
cannot be forgotten: a hand-maintained build number is wrong the first time
someone ships without remembering it, and then silently wrong forever.

The number is shown in the window title and on the Settings tab. A frozen `.app` has no `.git`, so
`scripts/stamp_version.py` writes `_build_info.json` at package time and
`lab_hub/version.py` reads it back; a checkout prefers live git, so an edit shows up on
the next launch without re-stamping. With neither, it says `v2.???` rather than
inventing a number — claiming a version with no evidence is a lie told in
exactly the moment someone is asking.

This is the lab-wide scheme, shared with `imprint`, `sonar` and `lab_hub`, and
the Lab Project Monitor computes the same string from the same two inputs, so
the dashboard and the running app cannot disagree.
## Housekeeping

`_to_delete/` holds a stray, empty `.git/index.lock` file quarantined from an
earlier device-bridge session (the bridge's shell can create a transient lock
during a read-only `git status`/`git diff` call but cannot delete it
afterward). It is 0 bytes and safe to delete by hand.
