# Update now: an app's own preflight gates the install

Needs: define, build, verify

23 November 2026. Request from the owner's session group: on 22 Nov Update built SYNDUSTRYX from a dirty
checkout and installed an unqualified ad-hoc build beside the accepted release. The owner's 15 Nov choice
(Update installs the build result) stands; this adds a gate, not a removal.

## Change
- `apps.toml`, two optional keys (need an `entry`): `preflight` (a shell command run in the checkout, with
  `{installed}` and `{candidate}` replaced by the shell-quoted bundle paths) and `require_clean` (bool).
- Update's command for a registered build runs, in order: dirty-checkout refusal (if `require_clean`),
  build, `test -d` the output, **preflight**, restore tracked files, move the installed bundle to the
  Trash, copy the new one in, write the install record. A nonzero preflight stops the chain: nothing is
  moved, copied or recorded, and the preflight's own output plus "Update refused" reach the build log.
- `{installed}` is chosen in the shell at run time: `/Applications/<bundle>.app`, else the first
  legacy bundle. With none installed (a first install) the preflight is skipped. Owner decision needed
  if a first install should be blocked too.
- `syndustryx`: `preflight = "python3 -m desktop.update_preflight --installed {installed} --candidate {candidate}"`,
  `require_clean = true`.
- The preflight only reads; Lab Hub never launches, signs or qualifies the candidate.

## Acceptance
`tests/test_update_preflight.py`: registry parsing and rejection; failing preflight installs nothing and
shows its message; passing preflight installs; arguments and working directory; legacy bundle used when it
is the one installed; first install skips; dirty refusal before the build; apps without the keys unchanged;
the real `apps.toml` gates syndustryx. Mutation: removing the preflight step fails 4 tests.
Lab Hub.app must be rebuilt by the owner for the gate to apply (registry is compiled in).
