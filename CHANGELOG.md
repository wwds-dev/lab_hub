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

### Added
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
- A rebuild command that cannot start at all now ends the run as failed
  instead of leaving the window waiting.
