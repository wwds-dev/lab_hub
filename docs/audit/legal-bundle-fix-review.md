# Review: legal-bundle-fix (fix for P1 1 and 2 of `docs/audit/legal.md`)

Reviewer: `code-reviewer` agent (read-only, not the author), 2026-11-17. Its report came back in chat. The author recorded it
here with what was done about each finding. Security review: `docs/audit/legal-bundle-fix-security.md`.

| # | Sev | Finding | Disposition |
|---|---|---|---|
| 1 | P1 | `QtCharts`, `QtChartsQml`, `QtDataVisualization`, `QtDataVisualizationQml` and their QML modules still shipped. The reviewer says Qt offers both only under GPL-3.0 or commercial terms; this is not verified here, and `docs/legal/licences.md` §4.3 treats them as LGPL. They are unused either way (bindings already excluded). | **Fixed:** pruned too (`scripts/prune_gpl_qt.sh`). Their licence status is for the owner or legal-compliance to settle (owner note). `QtShaderTools` licence not checked; still ships. |
| 2 | P2 | The survivors check reused the deleting regex, so it could never fire. | **Fixed:** independent, looser, case-insensitive check (`prune_gpl_qt.sh`), tested with renamed-module fixtures. |
| 3 | P2 | The otool check passed silently if otool was unavailable. | **Fixed:** the script fails when `otool -L /usr/bin/true` fails. |
| 4 | P2 | No automated test for the prune or the web probe. | **Fixed for the prune:** `tests/test_prune_gpl_qt.py` (fake bundle with must-go and must-stay names, run with `/bin/bash`). Mutants killed: adding `Quick` to the module list, dropping the Timeline/VirtualKeyboard QML pattern, skipping the link removal, disabling the survivors check. **Web probe:** covered by the build self-test. A mutation check (bundle with `QtWebEngineProcess.app` removed) made `--selftest` abort with exit 134, which stops the build. No unit test for its timeout branch. |
| 5 | P3 | Any dangling symlink failed with a Qt-specific message. | **Fixed:** its own message. |
| 6 | P3 | `codesign ... 2>/dev/null \|\| true` hid signing errors. | **Fixed:** removed; `codesign --verify --deep --strict` follows. |
| 7 | P3 | "Show licences" opened `Contents/Frameworks/` (the link). | **Fixed:** reveals the resolved path in `Contents/Resources/`. |
| 8 | P3 | The bundling test checked only the `--add-data "<name>:` prefix. | **Fixed:** asserts the full `name:folder` pair. |
