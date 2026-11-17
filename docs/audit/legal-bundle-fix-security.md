# Secure review: legal bundle fix (packaging)

- Phase: 8 Secure (packaging). Read-only review of the uncommitted diff (`build_app.sh`, `main.py`,
  `lab_hub/__init__.py`, `ui/settings_tab.py`) and untracked `LICENSES/`.
- Reviewer: security-engineer agent, 2026-11-17. Playbook `docs/playbooks/security-engineer.md`
  last-reviewed 2026-11-11, status current (not stale).
- Verdict: **no P0 or P1 findings.** Two P2 and three P3 items, none blocking.

## Threat model (scope of this change)

- Assets: the integrity of the built `Lab Hub.app` (it is installed into /Applications and also
  built by self-update via `lab_hub/self_update.py:142`); the files outside the bundle that the
  build's `rm -rf` could touch; the licence texts users receive.
- Trust boundaries: build script -> filesystem (the destructive prune); bundle -> codesign /
  Gatekeeper; selftest -> QtWebEngine (Chromium) helper process.
- Entry points: `./build_app.sh [--install]` (by hand or from self-update); `Lab Hub --selftest`;
  Settings "Show licences" button.
- No new network listener, secret, auth path or untrusted input is introduced.

## STRIDE notes

- Tampering / elevation (prune `rm -rf`): checked, safe. See "Checked and safe".
- Tampering (signature): improved. The new `--verify --strict` makes a failed re-sign or a broken
  seal fail the build, so `set -e` stops before `--install` and before self-update copies it.
- Information disclosure (web probe): constant inline HTML, no network or file access. See below.
- Repudiation / DoS: n/a for a local build script.

## Findings

### P2-1 Signing errors are still swallowed (`build_app.sh:105`)
`codesign --force --deep -s - ... 2>/dev/null || true`. The new verify at `:107` turns a failed
sign into a build failure, so the `|| true` no longer leaves an unsigned bundle installed. But the
signing error text is discarded, so the only message is the generic "a sealed resource is missing
or invalid" from the verify. Scenario: a future prune leaves a dangling link or an unsealable
file; the build fails with no clue why. Impact: diagnosability only, no exposure. Fix: drop
`2>/dev/null || true` and let `set -e` fail on the sign itself.

### P2-2 Ad hoc signature is the only integrity control for a `public` download (pre-existing, not in this diff)
`codesign -s -` (`:105`) gives no identity and no notarisation. If a built `.app` is published for
download (tier `public`), users get no authenticity check and Gatekeeper quarantine blocks it.
Fix (owner decision, out of this change): publish source only, or sign with a Developer ID and
notarise, or publish SHA-256 sums of release artefacts alongside them.

### P3-1 `--deep` used for signing (`build_app.sh:105`, pre-existing)
Apple deprecates `--deep` for signing (it remains fine for `--verify`). It works today for this
ad hoc bundle. Fix when convenient: sign nested code inside out, then the bundle.

### P3-2 The "still linked" guard fails open if `otool` is missing or errors (`build_app.sh:87-88`)
`xargs -0 otool -L 2>/dev/null | grep ... || true`: with no Xcode command line tools, or if otool
errors, `linked` is empty and the check passes silently. It is a licence guard, not a security
control, and the `survivors` check at `:86` still catches the files themselves. Fix: check
`command -v otool` first and fail if absent.

### P3-3 Dependency audit covers PyPI versions only, not the Chromium inside QtWebEngine
OSV querybatch on the installed venv (43 packages, PySide6 6.12.0): **0 known vulnerabilities**
(command run 2026-11-17). `pip-audit` is not installed (not run). OSV does not map Chromium CVEs to
the PySide6 version, so the WebEngine renderer's patch level is not verified. Nothing in this diff
changes that; the new probe only adds a constant local page.

## Checked and safe (with evidence)

- **`rm -rf` cannot leave the bundle.** Every deleted path comes from `find "$APP/Contents"`
  (`:68`, `:82`), and `$APP` is a fixed relative path built from constants (`:13`, `:15`, `:58`)
  after `cd "$(dirname "$0")"`. `find` defaults to `-P`, so it never descends through a symlinked
  directory and every emitted path is a real path under the bundle. `rm -rf "$path"` on a symlink
  removes the link, not its target (no trailing slash). Quoting is correct throughout:
  `"$path"`, `"$link"`, and `${doomed[@]+"${doomed[@]}"}` (`:70`) keeps elements intact, so the
  space in "Lab Hub" does not split. The regex is anchored on a path component and at `$`, so it
  matches only the named Qt items. `rm -f "$link"` (`:79`) likewise only removes a dangling link
  inside the bundle.
- **Built bundle inspected** (`dist.noindex/Lab Hub.app`, signed 19:20:08):
  `codesign --verify --deep --strict` -> valid on disk, satisfies its DR (one earlier run during a
  rebuild failed mid-churn, and passed on re-run once the build settled); 0 dangling symlinks;
  0 symlinks resolving outside the bundle (all relative, checked by realpath walk); 0 GPL-only Qt
  survivors by the build's own pattern; `LICENSE`, `THIRD_PARTY_NOTICES.md`,
  `LICENSES/{LGPL,GPL}-3.0.txt` present in `Contents/Resources`.
- **Selftest web probe (`main.py:144-183`, called at `:290`)**: `setHtml` with a constant string
  and no base URL; the page loads no subresources, so it makes no network request and reads no
  file. `runJavaScript("document.title")` (`:165`) runs a constant script on that page. It uses
  the default profile, which in Qt 6 is off the record (nothing written to disk) and is separate
  from the Dashboards tab's own profile (`ui/dashboard_view.py:49`), so it shares no cookies or
  storage. Nothing in the repo disables the Chromium sandbox (`--no-sandbox` /
  `QTWEBENGINE_DISABLE_SANDBOX` not found). Bounded by a 20 s timeout.
- **"Show licences" (`ui/settings_tab.py:139`, `_reveal_licences`)** reveals a fixed bundled path
  in Finder; no user input.

## Licence-text provenance

Acceptable. SHA-256 of `LICENSES/GPL-3.0.txt` is
`3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986` and of `LICENSES/LGPL-3.0.txt`
is `e3a994d82e644b03a792a930f574002658412f62407f5fee083f2555c5f23118`. Separately from the
author's cross-check, I found the same hashes in 5 (GPL) and 3 (LGPL) independent copies under
the local Homebrew Cellar and venv. The GPL hash is also the one usually published for gnu.org's
`gpl-3.0.txt`. I did not fetch gnu.org here, so a direct match is **not verified**. The licence
text is not executable, so a tampered copy would be a legal problem, not a security one.
Recommendation: when gnu.org is reachable, compare against
`https://www.gnu.org/licenses/gpl-3.0.txt` and `lgpl-3.0.txt` and record the hashes and source in
`THIRD_PARTY_NOTICES.md` or the legal audit. Whether the texts are adequate is a legal call
(Comply phase); no legal opinion is given here.
