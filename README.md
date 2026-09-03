# Lab Hub

One front door for the lab's desktop tools: a launcher for the standalone apps,
and a home for the small utilities that never had a UI.

Tabs: **Apps** · **Backup & Sync** · **Tools** · **Settings**

## Why two kinds of thing

The projects behind this app do not want the same treatment, so they do not get
it.

**Launched, not embedded.** Sentinel AI, Sentinel Fork, Create & Publish, SONAR,
VPN Agent, Backup Control Center, git_autosync, and Unblock Tracker are complete
PySide6 applications — own window, own settings, own background work, own
lifecycle. Embedding them would mean nesting eight apps' worth of UI and state
inside a ninth, and every one of them is something you leave running. Lab Hub
starts them as separate processes: quit it and they keep going.

**Embedded, not launched.** convert_epub and image_tools were single-file
scripts whose configuration lived in a `# === CONFIG ===` block at the top —
you edited the source to point them at a folder. There is no UI to preserve and
nothing to keep running, so the logic moved into `lab_hub/tools/` as plain
functions and the config block became a form.

The conversion engine under `tools/convert/` is a **vendored copy** of
`active/convert_epub/ebook_converter/`, where it is developed and tested. It is
copied rather than imported so Lab Hub does not depend on a sibling checkout
being present — keep the two in step when either changes.

**Narrator belongs here.** Its tab runs Lab Hub's bundled ebook-to-audiobook
engine in a separate, stoppable worker process. It does not launch or import
Sentinel AI and works the same way from source and from the installed app.

## Tabs

### Apps
The front desk for **Sentinel AI**, **Sentinel Fork**, **Create & Publish**,
**SONAR**, and **VPN Agent**. A card per app, showing where it will start from:

| State | Meaning |
| --- | --- |
| Installed | found in `/Applications` — launched with `open` |
| Source only | not installed, but the checkout is there — run with that project's own `.venv` |
| Not found | neither; Launch is disabled |

Source runs never use Lab Hub's own interpreter. Frozen, that is this app's
binary, and it would run the other project inside this bundle's dependencies.

### Backup & Sync

Launch **Backup Control Center** and **git_autosync** from one place.

### Tools

The built-in utilities and occasional standalone tools are grouped under one
tab: **Convert Files**, **Narrator**, **Prepare Images**, and **Unblock Tracker**.

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

### Settings
Only the lab folder, and only because it cannot always be inferred: launching an
installed app does not need it, but running one from source does. Blank means
auto-detect (`$LAB_ROOT`, then the checkout this was run from, then
`~/Documents/lab/active`).

## One instance, and the menu bar

Only one copy runs. The guard is a local socket rather than a lock file,
because a lock can only refuse the second launch — a socket lets it hand the
request over, so double-clicking the Dock icon brings the running window
forward instead of doing nothing.

The menu bar item carries the same 2×2 mark, drawn solid black on transparent
and flagged as a mask so macOS recolours it for a light or dark menu bar. Its
menu opens the window and launches the launchpad apps directly.

Because the app lives in the menu bar, **closing the window hides it** rather
than quitting — a conversion left running would otherwise lose the log it is
writing to. Quit from the menu bar item (or ⌘Q). The first time the window is
hidden it says so, so nothing disappears silently. If no system tray is
available the app falls back to quitting on window close.

When **Open Lab Hub at login** is enabled, Lab Hub starts hidden in the menu bar
and quietly starts Backup Control Center and git_autosync the same way. After
the Mac wakes from sleep, it checks those two companions again and starts only
the ones that are not already running; no windows are brought forward.

## The Dock icon follows the window

Lab Hub is two things at once: a window you open occasionally, and a menu bar
item that stays. The Dock only carries an icon when there is actually a window
behind it — close the window and the icon goes, leaving the status item.

macOS has a matching pair of activation policies, and the app switches between
them: `Regular` (Dock icon, ⌘-Tab entry) when a window is shown, `Accessory`
(status item only) when it is hidden. The switch is one Objective-C selector
reached through ctypes; pulling a whole framework binding into the bundle for
`setActivationPolicy:` was not worth the weight.

Two things about this took a while to get right, both invisible from source:

* **The bundle has to declare `LSUIElement`.** LaunchServices pins a bundled
  app's type from `Info.plist` at launch, so the runtime call alone was ignored
  in the `.app` while working perfectly from source. `build_app.sh` sets the key
  after PyInstaller runs — and re-signs, because editing `Info.plist`
  invalidates the signature. The app then *promotes* itself to `Regular`
  whenever it shows a window.
* **The menu bar item is unaffected by any of this.** A status item does not
  depend on the activation policy, which is what makes the switch safe. Closing
  the window never removes it; only quitting does.

Hiding the Dock icon is skipped when there is no menu bar item — without a
status item the Dock is the only way back, and dropping it would strand the app.

**Reopening only happens for a real Dock click.** A `_Reopener` watches
`applicationStateChanged` (not the raw activation event — closing the window
delivers that event too, and filtering on it re-showed a window that had
never been repainted: a black rectangle) and re-shows the window on an
inactive→active transition, but only when `reopen_allowed()` agrees:

* Hiding the window stamps `_hidden_at`; for `REOPEN_GRACE_MS` afterward,
  activation is treated as the echo of that hide, not a click — this is what
  stops leaving fullscreen from reopening the window it was just told to hide.
* Opening the tray menu, or launching an app from it, calls `suppress_reopen()`
  and blocks reactivation for `TRAY_SUPPRESS_S` (5s) — using the menu bar item
  activates Lab Hub, and launching SONAR (say) activates it again as focus
  moves; neither means "bring my window back."

## Layout

    main.py              entry point; --selftest checks a build
    lab_hub/             no Qt imports below this line
      config.py          settings, stored in Application Support
      launcher.py        finding and starting the standalone apps
      tools/convert/     any format to any format (vendored engine)
      tools/images.py    resizing, renaming, moving small files aside
    ui/                  the only package that imports PySide6
      widgets.py         folder field, run/log panel
      worker.py          runs any tool off the GUI thread
      single_instance.py the one-copy guard
      tray.py            the menu bar item
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

`--selftest` covers what pytest structurally cannot. It runs against the built
binary from `build_app.sh`, and beyond checking assets and paths it **starts a
real PySide6 child** from a sibling project's venv. That is the one bug class
this app is uniquely prone to — it exists only in the bundle, because from
source there are no Qt paths to leak into a child — so no unit test can reach
it. A build whose launched apps would die now fails before it installs.

## What this does not do

It does not replace any of the projects it launches. Each keeps its own repo,
README, venv and build script; Lab Hub only points at them. Changing what
Sentinel AI does still means changing Sentinel AI.
