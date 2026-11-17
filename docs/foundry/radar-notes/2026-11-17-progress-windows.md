# Radar check: progress-windows (2026-11-17)

Scope: the progress windows for Land and Check builds (spec `progress-windows`, merged to main
as `e888bbf`). Surfaces they use: PySide6 widgets and timers, `QProcess` with
`setUnixProcessParameters(CreateNewSession)` and `os.killpg`, and an atomic JSON file in
Application Support. Run after the merge, not before Architect as PROCESS.md asks; recorded late.

Inputs read: `docs/foundry/app-context.md` (Distribution: `public`; **Stack and Security surface
are still placeholders**), `requirements.txt` (all unpinned), `requirements-dev.txt`
(`pytest==9.1.1`), installed PySide6 6.12.0 on Python 3.11.15. Lookups: 6 of 6.

## Findings

| # | Finding | Source (date) | Impact | Recommendation | Approval needed |
|---|---|---|---|---|---|
| 1 | CVE-2026-116337: a crafted HTTP response can exhaust resources in Qt Network (CVSS 4.3, Red Hat). Fixed in Qt 6.12.1 / 6.8.10; the installed PySide6 6.12.0 is affected. PyPI has no PySide6 6.12.1 yet (latest 6.12.0, checked today). Not in the progress windows: Lab Hub reaches it through `ui/links_tab.py` (`QNetworkAccessManager` checks the owner's sites). Worst case: a hostile or hijacked site hangs or slows the Links tab. | https://www.qt.io/blog/security-issue-cve-2026-116337 ; https://wiki.qt.io/List_of_known_vulnerabilities_in_Qt_products ; https://access.redhat.com/security/cve/CVE-2026-116337 (Nov 2026) | P3 | Watch: upgrade PySide6 when 6.12.1 wheels reach PyPI, then rerun the suite | Owner: dependency upgrade |
| 2 | `requirements.txt` pins nothing, so a rebuild picks up whatever PySide6 is newest; the progress windows rely on `QProcess.setUnixProcessParameters` (Qt 6.6+) and the code falls back silently (no own process group, so Cancel stops only the shell) on an older Qt. | `requirements.txt`; `ui/rebuild.py:87-89` (read today) | P3 | Adopt: pin `PySide6>=6.12.1,<6.13` once 6.12.1 ships (a floor of 6.6 is the hard minimum) | Owner: dependency change |
| 3 | PySide6 6.12 blocks deserialising non-simple classes from `QDataStream` and `QSettings`, and `loadUiType()` no longer searches the system path. Lab Hub uses neither, so nothing to do. | https://www.qt.io/blog/qt-for-python-release-6.12-is-here (Sep 2026) | none | Skip | none |

## Checked, nothing new

- OSV (api.osv.dev) for PySide6 6.12.0 and pytest 9.1.1: no published advisories.
- PySide6 6.12 release notes: no `QProcess`, `QTimer` or widget change that affects the
  progress windows. `setUnixProcessParameters` is unchanged.
- Other Qt advisories this year (NTLM, QDom, QTextCodec, QQuick SVG, CoAP, NFC, Qt3D, QWebSocket):
  modules Lab Hub does not use, or fixed in 6.12.0.
- No better-fitting tool or library for the progress windows: the work is plain Qt plus the
  standard library, and no connector or plugin would help.

## Status (2026-11-17)

- Finding 1: **open.** PyPI still has no PySide6 6.12.1 (latest 6.12.0, rechecked four times). Closes
  when 6.12.1 ships and the floor in `requirements.txt` moves to `>=6.12.1`.
- Finding 2: **resolved in part.** `requirements.txt` now pins `PySide6>=6.12.0,<6.13` (owner's yes),
  so Qt cannot fall below 6.12. The 6.12.1 floor is the remaining step.
- Finding 3: skipped, as recommended.

## Gaps

- `app-context.md` Stack and Security surface are unfilled, so this check inferred the stack from
  the manifests and the venv. Filling them makes the next radar check cheaper and complete.
