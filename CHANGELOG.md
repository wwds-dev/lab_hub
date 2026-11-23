# Changelog

What changed in Lab Hub, for the person using it. The format follows
[Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/), adapted to the
lab's version scheme.

Lab Hub does not use semantic versioning. A version reads `v<MAJOR>.<BUILD>`,
for example `v2.170`: MAJOR is the product arc in the `VERSION` file, and BUILD
is the number of commits (`git rev-list --count HEAD`), so it moves by itself
with every commit (README, "Version"). Released versions are listed newest
first as `## v<MAJOR>.<BUILD> - YYYY-MM-DD`.

This file was started at v2.170; earlier changes are not listed here. The
README and the specs in `docs/specs/` describe them.

## Unreleased

### Fixed
- **Opening Dashboards no longer takes the window out of fullscreen.** The first time
  Dashboards was opened in a run, macOS dropped the window out of fullscreen (the
  second time it did not). Lab Hub now starts the web engine once, right after the
  window comes up, before anyone can have gone fullscreen.
- **Opening Dashboards in fullscreen no longer makes the screen slide sideways and back.**
  The first dashboard of a run switched the window to GPU drawing, and macOS showed the
  rebuilt window as leaving fullscreen and returning. Lab Hub now draws through the GPU
  from the start. Apps it launches are not affected.
- **No white flash before the first dashboard appears.** A dashboard's view starts in the
  window's own colour instead of white until the page has drawn.
- **The first visit to Dashboards no longer freezes and redraws the window.** Lab Hub now
  prepares the dashboard view while it starts, before its window appears (it loads an
  empty page, so nothing is fetched early). This replaces the web-engine warm-up above.

### Changed
- **The new-project question names the folder.** When a project's README title differs from
  its folder name (ignoring case), the row reads "Shopfront HQ (shopfront)", so a title
  cannot pass for another app. Add to Apps also checks the folder again just before it
  writes, and refuses one that has become a link since the question was asked.
- **Text on an Apps tile is shown as typed.** A project's name, summary and version line
  (and the tooltips that quote them) never turn into formatting or links, which matters
  now that a tile's name and summary can come from a project's README. A long name is
  cut to one line on a tile with no launch command, with the whole name in its tooltip.
- **Every Land stop says what clears it.** No stop row ends in "merge it by hand",
  "close that terminal" or "in Terminal" any more. A `.claude/` conflict reads "a
  conflict in .claude/ that Land may not resolve: press Ask Claude… to merge it with
  Claude Code, with you watching"; a failing default branch reads "main's own tests
  fail in a clean copy (…): press Ask Claude… to fix them"; the other stops Ask
  Claude… clears end in "press Ask Claude…". For those two, Ask Claude's session is
  told what to do: merge the branch in a temporary worktree with you and ask before it
  lands, or fix the failing tests on a branch and ask before merging.
- **Try again on the network stop.** "cannot reach origin" now says what failed (name
  lookup, a port, the proxy, a timeout) and has a **Try again** button on its Land row:
  it checks origin again, changes nothing in git while it is down, and lands the repo
  (after the usual confirmation) once it answers.
- **Close it… on a busy checkout.** "a process is running in it" has a **Close it…**
  button: you confirm the listed processes, Lab Hub asks each to quit (SIGTERM only,
  only processes still in that checkout, never itself), waits up to 5 seconds, checks
  again with `lsof`, and logs "owner closed: …". One that will not quit stays on the row,
  named: an interactive zsh ignores the request, so close its Terminal window and press
  Close it… again. A process in a separate repo inside the checkout is never closed.
- After Try again or Close it… clears a stop, that repo lands again in the same Land
  window: only its row resets; after Land all, the other repos' rows stay.
- **Land checks that GitHub answers before it starts.** Each repo with an `origin` is
  asked once (about a second, at most 15 seconds) before any commit, merge, Claude
  run or test. With no network it stops in seconds with "cannot reach origin (no
  network?), so no merge or test was started: press Try again", instead of reporting it after a merge and a full
  test run (50 minutes for imprint on 2026-11-21). Repos with no `origin`, or with
  nothing to land, are not asked. The check in the push step stays.
- **Land and Resolve leave a repo alone while its files are still changing.** A
  checkout or worktree with a changed or new file that was modified in the last
  15 minutes is not committed, switched or cleaned up: a session may still be
  editing it, including one that works from another folder, which Land could not
  see before. This now covers each repo's main checkout too, which was never
  checked. The stop names the newest file, how long ago it changed and when to
  try again; you can also commit the file yourself. Other repos in the same
  Land all are not held up.
- **Lab Hub updates itself even while other sessions work in its checkout.** Update
  now builds Lab Hub in a private copy of the repository at the `main` commit its
  row shows ("Update now builds `<sha>`"), not in the shared checkout, so
  uncommitted edits or new commits there no longer stop Close and restart. Edits
  that are not yet committed to `main` are no longer a reason for Lab Hub's row
  to say it is behind.
- **Scrolling moves between sections only over the left sidebar.** Over a page, the
  wheel or trackpad only scrolls that page, including at its top or bottom; it no
  longer jumps to the next section. Sideways swipes are unchanged.

### Added
- **Apps asks about new projects in your lab folder.** A folder directly inside the
  lab folder that is its own git project, has Foundry's `docs/foundry/app-context.md`
  and is not on the Apps page yet gets one question in a card at the top of the page:
  "New project in your lab folder: Kaila", with the first sentence of its README and
  three answers:
  - **Add to Apps** gives it a tile at once, with no restart. Nothing is started or
    changed in the project.
  - **Not now** asks again in 14 days.
  - **Never for this folder** stops the question for good. **Settings ▸ Hidden
    projects** lists the hidden folders ("Kaila · hidden for good", or "Overseer · not
    asked until 5 Dec") with a **Show again** button, so the answer can be undone.
  - The card shows three projects at a time and says "and N more" under them. The
    question never blocks anything else on the page.
  - On a first run it asks about Kaila, Overseer and Shopfront HQ. It does not ask
    about foundry, toolbox, Lab Hub or a linked worktree of another project.
  - It looks again at start-up and on Refresh (Cmd+R). It reads folder names, checks
    that a few files exist and reads the start of each README: no git, no network, no
    program is run.
- **A project with no launch command gets a tile with no Launch button.** It shows its
  name, its one-sentence summary, its version and its repo state, with **Land** where
  there is something to land and **Open in Terminal** always. It has no Launch, no
  menu bar entry and no row in Check builds, and the tile says "No launch button: it
  has no app to open yet." Kaila, Overseer and Shopfront HQ are tiles of this kind once
  added.
- **Lab Hub has its own tile**, last on the Apps page: its name, "This app: the
  launcher for the lab's projects.", the build you are running (like `v2.170`, with the
  commit and date in the tooltip), whether that build is up to date, **Land**
  and **Open in Terminal**. The build line is the same verdict as Lab Hub's row in Check
  builds, worked out in the background, so it may be blank for a moment after start-up
  or Refresh. The tile has no Launch, Bring to front, Stop, Quit or Update now, and no
  menu bar entry; when a newer build is ready it says "N behind" and its tooltip points
  to Check builds.
- **Your additions live in two files of their own**, in
  `~/Library/Application Support/Lab Hub/`: `apps-local.toml` holds the tiles you added
  (same format as `lab_hub/apps.toml`, `[[suites]]` only) and `apps-dismissed.json` holds
  your Not now and Never answers. `apps.toml` is never written by Lab Hub. If a project
  is in both, the `apps.toml` entry is used and the Apps page says so. If
  `apps-local.toml` cannot be read, Lab Hub keeps the tiles it last had, says why on the
  Apps page and in the status bar after Refresh, asks about nothing new and writes nothing
  into that file. If `apps-dismissed.json` cannot be read, nothing is hidden and
  Settings says so. A new Lab Hub build still installs even if `apps-local.toml` is
  broken, because the update's self-test only reports it.
- **`entry` is optional in `apps.toml`.** Leave it out for a project with no launch
  command. A forgotten `entry` now gives such a tile, with the hint line, instead of an
  error. An older Lab Hub rejects an `apps.toml` with such a block, so move
  one there only after this version is installed.
- **Choose what Land all lands.** Each repo card in the Land confirmation has a
  tick box, on by default. Untick a repo to leave it out: its card folds, its
  tile goes back at once, and the title, stop count, Claude Code cost panel,
  Details and the Land button count only the ticked repos.
- **The Land window keeps the time at the end:** "Took 14:22 · 13:55 to 14:09",
  each repo's time in its status (also "Needs you" and "Stopped" rows), finished
  repos open into their steps with times, and an "Earlier:" line shows the last
  three Lands' totals (new `land-runs.json`, no repo names). The title reads
  "Land finished · N repos" or "Land stopped". Times over an hour read `h:mm:ss`.
- **Ask Claude…** in Check builds (Review and Done) and the Land window (after
  the run):
  - It opens one Claude Code session per repo in Terminal for the rows Lab Hub
    could not clear: Needs you, Not now, Cannot check, Not rebuilt, a Land stop,
    archived branches. Each row goes in word for word.
  - A confirmation with tick boxes and the cost comes first.
  - Sessions run in manual permission mode with Lab Hub's ask/deny rules and
    seven written limits. They never sign, accept, push or merge without your
    yes in that session.
  - The button is off while Land or Update now runs. If Claude Code is already
    running in that repo, it offers Copy prompt instead.
- **Lab Hub updates itself** from Check builds:
  - The launchpad's report ends with a **Lab Hub (this app)** row, and Update
    now builds it last.
  - Before the build, it waits for any running Land or tool, and it builds only
    from a clean checkout on `main`.
  - Lab Hub restarts when you close the window (**Close and restart**). A
    helper installs the new build after the old copy has quit, self-tests it,
    puts the previous build back if that fails, and opens Lab Hub.
  - The next start says how the update went.
  - No terminal, no `kill`, no menu bar click.
- A **Land window** for Land and Land all: a progress bar and percent, time
  elapsed, time left and "done around HH:MM", counts, one row per repo with a
  Commit / Merge and test / Push / Tidy track, the running repo's steps with
  their own timer, the reason under any repo that did not land, and the live
  output. It is not modal: closing it only hides it and landing goes on;
  **Show progress** on the page brings it back while the Land runs.
- A working signal in both progress windows: moving dots, a spinner on the
  running row, and "Last activity Ns ago", which turns amber after 60 s with
  no output ("No output for 1:00. Still running.").
- Time-left estimates from how long the same steps took before. Until every
  step still to come has a recorded time, the window shows "Estimating…"
  instead of a guess; a step past its usual time says "Taking longer than
  usual".
- `~/Library/Application Support/Lab Hub/durations.json`: the last five
  durations of each successful step, per repo and per app, used only for the
  estimates. Deleting it only resets them; a broken or oversized file is
  ignored and replaced by the next good save.

### Changed
- The **Land confirmation** is readable at a glance: one card per repo with
  what Land will do and a separate **Only you can clear** section (place,
  problem, the one action; busy folders count their processes instead of
  listing process ids), one Claude Code panel with a single total instead of
  one paragraph per repo, a line for repos with nothing to land, and the full
  text under **Show details**. Return no longer does anything there; Escape
  cancels.
- **Check builds** opens one window instead of a message box and a separate
  rebuild dialog. It steps through Check, Review, Update and Done; Review shows
  one row per app with its verdict in words and the up-to-date apps on one
  line, with the same buttons as before under the same conditions. During
  **Update now** the app being rebuilt shows its stages (Build, Package,
  Install, Verify, or one "Rebuilding" when its output has no known markers),
  and Verify shows the version now installed.
- The **Land all** summary ("Landed N of M repos.", and why each other repo
  did not land) is now the end state of the Land window instead of a separate
  box.
- `requirements.txt` now limits PySide6 to `>=6.12.0,<6.13` instead of taking
  whatever is newest, so a rebuild cannot pick up a Qt older than the one the
  progress windows need. The floor moves to 6.12.1 once Qt ships it, which also
  fixes CVE-2026-116337 (a crafted HTTP response can exhaust resources in Qt
  Network; Lab Hub reaches it through the Links tab).
- **Land runs each test suite less often.** After a conflicting branch lands,
  Land no longer re-runs the default branch's tests on the commit it has just
  tested. A chain of N branches that need Claude Code now takes N + 1 test runs
  instead of 2N. In the fixture benchmark, 11 test runs dropped to 7 and 9
  Claude Code runs to 5.
- **A default branch whose own tests fail is tested once per Land**, not once
  per branch. It is one stop that starts "fix main's own tests, then Land
  again", names the error and lists the branches waiting on it. Those branches
  stay as branches and are not archived.
- **Conflicts in Foundry's own files** (`.claude/commands/`, `.claude/agents/`
  in an app Foundry installed into) take the default branch's copy without
  Claude Code. Any other `.claude/` conflict is a stop that says to merge it by
  hand. Land no longer pays for a test run and a Claude run that cannot edit
  the file.

### Fixed
- **A failed Lab Hub update no longer leaves its build behind.** When the new build fails
  its self-test and the previous one is put back, the failed copy (about 14 MB) is now
  deleted from `update/staged/` instead of waiting for the next Update now.
- **Land no longer lets a branch's link replace a folder.** A symlink an agent
  committed on its branch (`.venv`, with only `.venv/` in `.gitignore`) used to
  replace the checkout's real, ignored `.venv` when Land merged it, which lost
  the virtualenv. Land now checks every merge, Claude merge, switch and pull
  first and stops with "it adds a link at .venv where this checkout has a real
  folder: remove the link from the branch, then Land again". The same stop
  covers a plain file at a folder's path, a name ignored as a folder, and a
  link to an absolute path, outside the repo or into `.git`. Such a branch is
  never archived, and a stopped pull or switch holds the repo's other branches.
- **The app now carries its licences.** `Lab Hub.app` ships `LICENSE` (GNU
  AGPL-3.0), `THIRD_PARTY_NOTICES.md` and the GNU LGPL-3.0 and GPL-3.0 texts
  that Qt's licence requires. **Settings → This build → Show licences** opens
  them. The self-test fails a build that lacks them.
- **Qt modules offered only under GPL-3.0 are no longer shipped.** These were
  Qt Graphs, Qt Quick 3D (with Physics), Qt Quick Timeline and Qt Virtual
  Keyboard. Qt Charts and Qt Data Visualization are removed as well. Lab Hub
  used none of them. The build removes them and fails if
  any remain. The self-test now loads a page in QtWebEngine, so a build whose
  Dashboards page would stay blank fails too.
- A branch whose plain merge became a conflict after an earlier merge in the
  same Land never got a Claude Code merge and was archived. It now gets one in
  the next round.
- A branch Claude Code said to land was archived when its only problem was a
  `.claude/` conflict or a failing default branch. It now stays as a branch,
  with the reason a person must clear.
- Escape during a rebuild hid the window but left the build running unwatched,
  and the next rebuild then started. Escape, the red button, Close and Cancel
  now all stop the running build, and no later rebuild starts.
- Cancel now stops everything the build script started (such as PyInstaller or
  the copy into `/Applications`), not only the shell that ran it.
- A rebuild command that cannot start at all is now marked failed instead of
  leaving the window waiting.
- **Land committed a symlink to a folder.** An agent worktree's `.venv` link
  to the checkout's virtualenv was committed because `.gitignore` had only
  `.venv/`, which does not match a link. Merged into `main`, it replaced the
  real virtualenv with a link to itself. Land now never commits a symlink to a
  folder, or one whose name is ignored as a folder. It leaves the link in place
  and ignores its exact path. The same goes for a symlink that is absolute or
  leads out of the repo, so a link such as `/Users/<name>/.ssh/id_ed25519` is
  never pushed. A link already committed on a branch is not checked yet.
- **Update now stopped at the first failed rebuild,** so the apps after it,
  and Lab Hub's own update (always last), were never built. A failed or
  unstartable rebuild is now marked failed and the run goes on. The window and
  the page name the apps that failed. Lab Hub still restarts into its new
  build when only another app failed. Terminal installers still open only when
  nothing failed.
- Check builds said "1 commits further on"; it now says "1 commit".
