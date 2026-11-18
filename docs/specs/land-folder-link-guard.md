# Spec: Land stops a branch that already contains a folder link

Status: **Define approved by the owner 2026-11-18 ("Approve as recommended"): §5 takes option A for all four decisions.** Owner of the spec: this
session (`land-folder-link-guard`, worktree `bold-merkle-831506`).
In-flight check (`session_start.py --inflight`, 2026-11-18): no unreleased spec, `claude/*` branch
or worktree covers this. `land-update-gaps` (build done) owns Land's untracked-file rule and left
this gap open (§4, §10.1; code review P2-2). `land-pick-and-time` (build start) changes Land's
confirmation and timing, not merges. `self-update` owns Update now's own `git pull` of Lab Hub;
that pull is out of scope here (§4).
Source: `TODO.md` P1 "Land: stop a branch that already contains a folder link"; readiness audit
2026-11-18 B1 (release blocker, `docs/audit/2026-11-18-readiness-audit.md`).

## 1. Problem
An agent works in its own worktree, where `.venv` is a symlink to the main checkout's virtualenv.
The repo's `.gitignore` has `.venv/`, which matches a folder but not a link, so the agent's
`git add -A` commits the link. When Land merges that branch, git updates the main checkout: it
treats the real `.venv/` folder there as ignored, so expendable, and replaces it with the link.
The virtualenv is gone, git exits 0 and Land then pushes. This is the SONAR loss of 17 Nov 2026.

Reproduced on git 2.56.0 (2026-11-18): main checkout with `.gitignore` = `.venv/`, a real
`.venv/bin/python`; branch `f` commits `.venv -> x`; `git merge --no-ff f` exits 0 and `.venv` is
now the link. `land-update-gaps` stops Land from committing such a link itself
(`land_resolve.never_commit_link`), but nothing checks a link a branch already contains.

The same replacement happens at every point where Land moves the main checkout to new commits:
the plain merge (`repo_tidy.apply`, `git merge --no-ff`), the Claude merge's final
`git merge --ff-only` (`claude_resolve.resolve`), prep's `git switch <default>`
(`land_resolve.apply_step`) and the fast-forward pull (`repo_tidy.apply`, `git pull --ff-only`).

## 2. User and success measure
User: the owner, running Land, Land all, or Tidy.
1. **The SONAR case cannot recur.** End-to-end test: a repo whose `.gitignore` has only `.venv/`,
   a main checkout with a real `.venv/` holding a file, and a branch (made in a worktree) that
   commits `.venv` as a link. After Land: the branch is not merged, `.venv/` in the checkout is
   still the real folder with its file, the default branch did not move and nothing was pushed,
   and Land shows one stop naming the branch and `.venv`.
2. **Every route is covered**: plain merge, Claude merge (before Claude is started, so no money
   is spent, and again right before its fast-forward), prep's switch, and the pull. One test each.
3. **A wanted link still lands**: a branch that adds a link inside the repo to a tracked file or
   folder, at a path the checkout does not have and whose name no rule ignores as a folder,
   merges as today (`land-update-gaps` P3-8 says a wanted folder link is committed by hand).
4. Full suite green; new logic mutation-checked.

## 3. Behaviour
1. **What is checked.** Before Land moves the main checkout from its current commit to a new
   one, it lists the paths that become a symlink, or a symlink with different text, in that move
   (git mode `120000`). Plain merge: the merge result git would produce, computed without touching
   the checkout. Claude merge: first the branch's own changes (before Claude starts), then the
   exact result (before the fast-forward). Switch: the default branch's tip. Pull: what was fetched.
2. **When it stops.** Any one of these, for any such path:
   1. **The checkout has something there git would replace:** a real folder (whatever is in it),
      or a file or link git does not track. This is the `.venv` case.
   2. **The name is ignored as a folder** by the checkout's ignore rules (`ignored_as_folder`), so
      the next checkout or `python -m venv .venv` that has the real folder loses it too.
   3. **The link's text is absolute, ends in `/`, or leads out of the repo**, as `never_commit_link`
      already refuses for untracked links (`land-update-gaps` §10.2 B). Decision §5.2.
   If git or the checks cannot tell, it stops ("cannot tell" counts as a stop, as in
   `ignored_as_folder`).
3. **What the person sees.** One stop per branch (or per default branch, for a pull or switch),
   in the voice of Land's other stops, naming up to three paths and the reason for the first:
   - Merge: "<branch> adds a link at .venv where this checkout has a real folder: remove the link
     from the branch, then Land again".
   - Other reasons: "… a link at .venv, a name ignored as a folder: …", "… a link at x whose
     target is outside the repo: …".
   - Pull: "origin/<default> adds a link at .venv where this checkout has a real folder: remove the
     link from <default> on the remote, then Land again". Nothing is pulled; the other branches
     wait (as today when the default branch is behind origin).
   - Switch: "<default> adds a link at .venv …: remove the link from <default>, then Land again".
     The checkout stays on its branch, with its open work committed as today.
   The log gets one `NOT MERGED` / `NOT PULLED` / `NOT SWITCHED` line with every path.
4. **The branch is kept as it is.** A branch stopped for a link is never sent to Claude's
   land-or-archive verdict and never archived (decision §5.3); it stays a branch under its stop
   until a person removes the link.
5. **Preview.** The check also runs when Land plans, so the confirmation and Tidy's preview show
   the branch as "not merged: …" with the same reason, before anything runs.
6. Tidy (`repo_tidy.apply` outside Land) gets the same check, since it uses the same merge and pull.

## 4. Non-goals
- A plain file a branch adds over an ignored local file (for example a force-added `.env`). Git
  replaces that too, but `git add -A` never adds an ignored file, so it needs a deliberate
  `git add -f`; left to a TODO if the owner wants it (§5.1).
- Fixing a branch: Land does not rewrite or amend a branch to drop the link. A person does.
- Update now's own `git pull` of Lab Hub (`self-update`), other worktrees updating themselves, and
  links already on the default branch in the checkout.

## 5. Decisions for the owner
1. **Scope of what is guarded.**
   - **A (recommended):** links only (§3.2). This is the path `git add -A` takes by itself.
   - B: also any new file over an untracked or ignored local file (the `.env` case). Wider, and it
     stops branches that start tracking a file someone had locally.
2. **Absolute or outside-the-repo link text** (§3.2.3).
   - **A (recommended):** stop, as for untracked links: such a link names a private path
     (`/Users/<name>/...`) in a public repo and can point at a folder later.
   - B: let it land unless 3.2.1 or 3.2.2 applies.
3. **What happens to a stopped branch.**
   - **A (recommended):** a stop only; no Claude verdict, never archived (§3.4).
   - B: let Claude's verdict run as for any other branch that did not land (it may archive it as
     a tag).
4. **The pull.**
   - **A (recommended):** check it (§3.3): a link pushed from elsewhere destroys the folder the
     same way.
   - B: merges, Claude merge and switch only.

## 6. Risks
- A repo that tracks an intentional link under an ignored folder name stops on every branch that
  changes it. The stop says what to do; the owner can untrack it.
- `ignored_as_folder` copies `.gitignore` files into a temporary folder per path. Only paths that
  become links are checked, so the cost is near zero for normal branches.
- `git merge-tree --write-tree` needs git 2.38+; Lab Hub already uses it (`merges_cleanly`).

## 8. Architecture (Architect, 2026-11-18)
No new state, thread or module boundary: no ADR. All checks are read-only git calls made just
before the existing git command that moves the main checkout.

1. **`land_resolve.incoming_links(checkout, old, new)`**: `git diff-tree -r -z --no-renames
   --no-abbrev <old> <new>`; every entry whose new mode is `120000` (added, type-changed, or a link
   whose text changed), as `(path, blob)`. `old`/`new` may be commits or trees. None when git fails.
2. **`land_resolve.link_problem(checkout, rel, blob)`**: the first reason that applies, in the
   order of §3.2: a parent of `rel` in the checkout is a link (cannot tell); the path is a real
   folder; the path exists and `git ls-files` does not list it; `ignored_as_folder(checkout, rel)`;
   the text (`git cat-file blob`) is empty, holds a newline or NUL, is absolute, ends in `/`, or
   `posixpath.normpath(dirname(rel)/text)` starts with `..`. Lexical on purpose: the target need not
   exist yet. Unlike `never_commit_link`, a link to an in-repo folder passes (§2.3).
3. **`land_resolve.link_stop(checkout, old, new, who, fix_in)`**: the stop sentence or "".
   `"<who> adds a link at <path> <why>[; also at <p2>, <p3> and N more]: remove the link from
   <fix_in>, then Land again"`. Paths are untrusted (branch content): control characters become
   `?` and each is cut at 120 characters. If git cannot list or read: `"<who> may add a link that
   git cannot check: Land again, or land it by hand"`.
4. **Call sites.**
   - Plain and Claude merge: `land_resolve.merge_link_stop(repo, default, branch)` runs
     `git merge-tree --write-tree refs/heads/<default> refs/heads/<branch>` (exit 0 clean, 1 with
     conflicts; the tree OID is the first line either way) and checks `default → tree` in the main
     checkout. Called in `repo_tidy.plan_repo` (a `not merged: …` skip, so the preview shows it) and
     in `repo_tidy.check` (re-run by `apply`), for `merge` and `claude_merge`, after the source
     blocker. So Claude is never started for such a branch.
   - Claude merge's fast-forward (`claude_resolve.resolve`): `link_stop(main, d, m)` after
     `merge_target_blocker`, before `merge --ff-only`. Catches what Claude's resolution produced.
   - Prep's switch (`land_resolve.apply_step`): `link_stop(path, "HEAD", refs/heads/<default>,
     who=<default>, fix_in=<default>)` after the open work is committed, before `git switch`.
   - Pull (`repo_tidy.apply`): `git pull --ff-only origin X` becomes `git fetch origin
     +refs/heads/X:refs/remotes/origin/X`, then `link_stop(main, "HEAD", refs/remotes/origin/X,
     who=origin/X, fix_in="X on the remote")`, then `git merge --ff-only refs/remotes/origin/X`.
     Same result as the pull, with the check between fetch and update. `check()` and `plan_repo`
     also check the last-fetched ref for the preview.
5. **A stopped branch is never triaged** (§5.3 A). Merge-time stops start with `it adds a link at`
   or `it may add a link`; `claude_resolve.blocker_kind` returns `"link"` for those, so
   `land.Lander` keeps them in `blocked` and shows them as stops (as for `protected`). A plan-time
   skip with that start is turned into a stop by `Lander.triage` before any verdict, also when
   Claude Code is not available. Branch names cannot contain spaces, so a name cannot fake the
   start. In the merge stop the row already names the branch, so its text says "it adds …".
6. **Log.** The skip or `NOT PULLED` / `NOT SWITCHED` / `CLAUDE not landed` line holds the stop
   text (up to three paths and a count), not every path (narrower than §3.3).
7. **Tests** (`tests/test_land_folder_link_guard.py`, real git repos in `tmp_path`): the helpers
   per reason; the end-to-end `.venv` case through `land.land()`; one test per route (plan skip,
   `apply` merge re-check, Claude ff, switch, pull); a wanted in-repo link still merges; triage
   never asks Claude about a link-stopped branch.

## 7. Phases to run
Define (this) → Architect (section below, after approval) → Build with tests, including the
end-to-end `.venv` test → Review (`code-reviewer`) → Verify (mutation check) → Secure (file writes,
untrusted branch content) → Document (README Land section, CHANGELOG). Design: no new UI; stop
text only, written here. Comply, Launch, Release: not in this change (no new data, claim or
dependency; release is the owner's). Radar: scoped inline to the git features used (`merge-tree
--write-tree`, `diff --raw`), both in the installed git 2.56.0; no new dependency.
