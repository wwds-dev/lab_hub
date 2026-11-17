# Comply: legal-bundle-fix (2026-11-17)

Role: legal-compliance agent. Not a lawyer; nothing here is a sign-off. Spec `legal-bundle-fix`, PR #10, merge `ee2ae17`. Tier `public`.

## Results
1. **P1 1 (GPL-3.0-only Qt modules in the bundle): fixed in the build.** `scripts/prune_gpl_qt.sh` prunes Graphs, Quick 3D (+Physics),
   Quick Timeline, Virtual Keyboard, Charts, Data Visualization. Security report: 0 survivors in a built bundle.
2. **P1 2 (no licence texts in the bundle): fixed.** `LICENSE`, `THIRD_PARTY_NOTICES.md`, `LICENSES/{LGPL,GPL}-3.0.txt` go to `Contents/Resources`.
   Still open: Qt source archives attached to a GitHub release (offer in `THIRD_PARTY_NOTICES.md` links the upstream tarballs, HTTP 200 on 2026-11-17).
3. **Qt module question settled for 6.12.** doc.qt.io/qt-6/licensing.html, read 2026-11-17: the GPL-only list is Canvas Painter, CoAP, Graphs,
   GRPC, HTTP Server, Lottie Animation, MQTT, Network Authorization, Qml Compiler, Quick 3D, Quick 3D Physics, Quick Timeline, Virtual Keyboard,
   Wayland Compositor. **Charts, Data Visualization and Shader Tools are not on it.** The code reviewer's claim is not supported by that page.
   Shader Tools ships and is not GPL-only: no finding. Nothing that still ships is on the list. Caveat: absence from the list is the only evidence.
4. **Licence texts vs gnu.org: not verified.** gnu.org unreachable (curl timed out at 20 s twice; browser fetch refused). SHA-256 recomputed today:
   GPL `3972dc97…986`, LGPL `e3a994d8…118`, matching the owner note. Provenance is Homebrew COPYING files (two to three independent copies agree).

## Findings
- P2: the installed `/Applications/Lab Hub.app` is the old build 175 (still holds Quick3D, Graphs, Charts, Data Visualization frameworks). Release must
  rebuild, list the bundle and re-run the prune survivors check on that build.
- P2: `docs/foundry/app-context.md` still has 8 unfilled placeholders (Product, Stack, Commands, ...); the Product paragraph feeds legal claims.
- P3: `/docs/legal` is git-ignored (a link to the HQ); this report in `docs/audit/` is the tracked record.

## Pack files changed
`docs/legal/licences.md` (§1 licence-texts bullet, §4.2 row 1, §4.3 rewritten), `docs/legal/register.md` row 11, `docs/audit/legal.md` (P1 1-2 marked fixed,
Not verified, What changed). This makes any existing sign-off stale; none exists (`docs/legal/signoff.jsonl` absent).

## Owner can verify the licence texts (needs network)
    curl -sS https://www.gnu.org/licenses/gpl-3.0.txt | shasum -a 256   # expect 3972dc97...986
    curl -sS https://www.gnu.org/licenses/lgpl-3.0.txt | shasum -a 256  # expect e3a994d8...118
