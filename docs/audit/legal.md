# Legal and compliance audit: Lab Hub (tier public), 2026-11-17

Role: legal-compliance agent (not a lawyer; nothing here is a sign-off). Playbook `last-reviewed 2026-11-11`, status current, 6 days
old. The pack: `docs/legal/{register,licences,privacy,terms,name,ai-act}.md`; root `THIRD_PARTY_NOTICES.md`; README section
"Privacy, disclaimer and third-party notices". `LICENSE` written after the owner chose AGPL-3.0-or-later (2026-11-17).
Gate: `python3 docs/foundry/tooling/legal_gate.py check .` is expected to say only "no legal sign-off recorded".

## P0

None.

## P1 (fix or owner-defer before Release)

1. **GPL-3.0-only Qt modules ship in the installed bundle.** `Contents/Frameworks/PySide6/Qt/lib` holds Qt Graphs, 14 Qt Quick 3D
   frameworks (incl. Physics), Qt Quick Timeline and Qt Virtual Keyboard, which Qt offers only under GPL-3.0 (doc.qt.io/qt-6/licensing.html,
   Qt 6.12, 2026-11-17). Lab Hub imports none (`from PySide6.Qt{Core,Gui,Network,WebEngineCore,WebEngineWidgets,Widgets}`). `build_app.sh:41-47`
   `--exclude-module` removes Python bindings only; frameworks are still collected. Who is exposed: the owner, as distributor, if Lab Hub is
   anything other than AGPL/GPL-3 compatible as a whole. Fix: prune frameworks after the build, re-sign, rerun `--selftest` and the Dashboards tab;
   or accept option A (AGPL-3.0-or-later) where it is permitted.
2. **No licence texts or notices in the bundle.** `LICENSE` (AGPL-3.0, owner's choice 2026-11-17) is now in the repo, but the built `.app` has no LGPL/GPL
   text, no Qt notice, no notice for MIT/BSD/Apache/MPL components (only pydantic, httpcore2, httpx2 ship theirs). EbookLib is AGPL-3.0+ and ships
   (`converter.py:18`), so the binary as a whole must be offered under AGPL-3.0 and its source offered. Fix: add `LICENSE`, `THIRD_PARTY_NOTICES.md`, `LICENSES/LGPL-3.0.txt`, `LICENSES/GPL-3.0.txt` to the bundle via `--add-data`;
   attach the Qt source archives to the release. Suggested cleanup: add an About line pointing to the notices.

## P2

- Websites tab sends a HEAD request to the owner's two commercial sites on every use (`ui/links_tab.py:170-182`); their hosts log each user's IP. Disclosed in
  the README; consider off-by-default or dropping the sites from a public build. `sites.py:47-48` also hard-codes `/Users/as/...`.
- Narrator output carries no AI-generation marker (`converter.py:1016-1021` writes title and chapters only); AI Act Art. 50(2) from 2 Aug 2026 (ai-act.md §4).
  No grace expected for a first release. Voice is user-overridable (`converter.py:1282`); no consent or likeness check.
- Name: exact-match third-party hits for LABHUB; EUIPO, Irish register and CRO not yet queried (`name.md` §2).
- `requirements.txt` pins nothing, so the source offer and notices cannot name what shipped; pin PySide6 etc. before release. Version string in the
  installed bundle is `0.0.0` (`Info.plist` `CFBundleShortVersionString`).
- Narrator does not say, before the first run, that the book text leaves the Mac (`ui/narrator_tab.py:61,92`); README now says so.
- Origin of `assets/tray.png` and `tray@2x.png` unrecorded.
- `regex` (tiktoken dependency) is Apache-2.0 AND CNRI-Python; GPL-compatibility of the CNRI part not verified (folded into the licence lawyer trigger).

## P3

- DPF appeal C-703/25 P pending; PLD Irish transposition not yet found; CRA outside scope only while Lab Hub stays non-commercial.
- `/docs/legal` is git-ignored (`.gitignore:44-45`), so `privacy.md` and `terms.md` are not public: the README section and `THIRD_PARTY_NOTICES.md` are
  the public texts. Copy changes there, not only in the pack.
- 35 of 177 commits are by "Claude"/"Claude AI": AI-assisted authorship of the code; copyright position unsettled, owner decides what he licenses.

## Open lawyer triggers (1)

1. Name "Lab Hub"/"LABHUB": exact-match third-party marks and products found, official registers unqueried.

Not triggered: licence of the binary. It applied only to a choice other than AGPL-3.0-or-later; the owner chose that on 2026-11-17. `regex`'s CNRI-Python part is not verified.

## Residual risks

Regimes ruled out by the agent from playbook text, not re-fetched primary sources: GDPR controller position, CRA, PLD, EAA, CRA 2022, S.I. 68/2003. Each reopens if
the app is monetised, a server or telemetry is added, or a paid build ships. Bundle listing was of the installed build 175, not the build Release will ship.

## Not verified

EUIPO/TMview/IPOI/CRO/PyPI/npm/domain results; the DPF certification of OpenAI, ElevenLabs, Google and Anthropic; provider terms and their effective dates; per-library
licence texts in Pillow's wheel; Chromium third-party list inside the bundle; the individual licences of Qt modules not on Qt's GPL-only list; whether Qt frameworks can be swapped and
re-signed on another Mac (Gatekeeper behaviour); AI Act consolidated text; whether Land and the file tools ask before destructive steps; whether the CNRI-Python licence is compatible
with AGPL-3.0; secrets filtering end to end before diffs reach Anthropic.

## What changed since the last sign-off

No earlier sign-off exists (no `docs/legal/signoff.jsonl`).

## Command for the owner (not run by the agent), after deciding the P1 items

`python3 docs/foundry/tooling/legal_gate.py sign . --by "<name>" --role owner --accept-risk "<why>"`
(`--accept-risk` is needed while the lawyer trigger is open; `--role lawyer` clears them).
