# SynCorp Inc. tile: display name apart from bundle name

Needs: define, build, review, verify

23 November 2026. Part of the SYNDUSTRYX Stage 2 rename (`syndustryx/docs/specs/syncorp-rename-stage2.md`,
agreed by the owner 23 Nov). The tile shows "SynCorp Inc.", but the app's bundle is `SynCorp.app` and the
installed build71 is still `/Applications/SYNDUSTRYX.app` until the owner installs a new build.

## Change
- `ExternalApp.bundle` (optional): the `/Applications/<bundle>.app` and built-bundle name; defaults to `name`.
- `ExternalApp.legacy_bundles` (optional list): older installed names that are still found for launch and
  version reading; never built, installed or moved to the Trash by Lab Hub (the owner removes the old app).
- A copy running from an installed legacy bundle still counts as running (`running_markers`), so Launch
  does not start a second copy while both bundles are installed.
- Both are validated like `name` and need an `entry`. Local (README-named) apps never select a bundle.
- `apps.toml`: `name = "SynCorp Inc."`, `bundle = "SynCorp"`, `legacy_bundles = ["SYNDUSTRYX"]`,
  `build_output = "dist/SynCorp.app"`. `key` and `project` stay `syndustryx` (folder keeps its name).

## Acceptance
`tests/test_bundle_name.py`: parsing and defaults; bad values refused; installed lookup prefers the bundle
name, then legacy names, and never the display name; Update now installs `/Applications/SynCorp.app`.
Full suite green. Lab Hub.app must be rebuilt by the owner for the tile to change (registry is compiled in).

## Review (23 Nov 2026)
Independent read-only review with the SYNDUSTRYX Stage 2 diff: no P0/P1. Fixed: legacy-bundle running check
(P3-4) and test gaps (P3-5). Full suite 1,822 pass.
