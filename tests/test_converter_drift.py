"""
Narrator converter — drift guard
================================
Type: Cross-repository consistency check.

The same converter exists twice in this workspace:

    imprint/services/narrator/converter.py
    lab_hub/lab_hub/tools/narrator/converter.py

A third copy lived in the standalone audiobook_studio app until that app was
merged into Imprint on 2026-09-30 (archived under
archive/audiobook_studio_standalone_2026-09-30/).

They are copies, not a shared package, and copies drift. This one already
did: for three days lab_hub's copy was missing the fix that clears stale
chunk files when a run's settings change, so it could stitch audio from the
previous settings into a book it then reported as finished. Nothing said so.
The workspace's other vendored pair (`lab_hub/tools/convert` against
`toolbox/convert_epub`) drifted the same way and was only noticed by reading.

So: until the converter becomes one installable package, this test makes
divergence loud. It compares the files line by line after normalising the
handful of differences each copy is *allowed* to have, listed in LOCAL below.

It skips when a sibling checkout is not present, because that is a normal
state for a clone — the test is for this machine, which is where drift
happens.

**If this fails**, do not edit the normaliser to make it pass. Port the
change to the other copies, or add a genuinely local difference to LOCAL
with a comment saying why it is local.
"""

import re
from pathlib import Path

import pytest

# Every copy, relative to the lab root.
SELF = "lab_hub"

COPIES = {
    "imprint": "imprint/services/narrator/converter.py",
    "lab_hub": "lab_hub/lab_hub/tools/narrator/converter.py",
}

# Differences each copy is allowed to keep, and why. Each entry is a regex
# replaced by a placeholder before comparing.
LOCAL = (
    # Default output folder: each app writes somewhere different.
    (re.compile(r"^OUTPUT_ROOT = .*$", re.M), "OUTPUT_ROOT = <local>"),
    (re.compile(r"^# The UI supplies an output folder\..*$", re.M), ""),
    # Default container: kept declarable so a copy can default to M4B.
    (re.compile(r"^DEFAULT_FORMAT = .*$", re.M), "DEFAULT_FORMAT = <local>"),
    # Resume policy: a GUI with no force-rebuild control clears and carries on;
    # a CLI-only copy with an operator present may refuse and ask instead.
    (re.compile(r"^ON_SETTINGS_CHANGE = .*$", re.M), "ON_SETTINGS_CHANGE = <local>"),
    # The module path in the CLI docstring names its own package.
    (re.compile(r"python -m [\w.]*converter"), "python -m <local>.converter"),
)


def _lab_root() -> Path:
    """The workspace root, found by walking up to the directory holding the copies."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "active").is_dir() and (parent / "AGENTS.md").is_file():
            return parent / "active"
        if all((parent / rel).is_file() for rel in COPIES.values()):
            return parent
    return Path(__file__).resolve().parents[3]


def _normalised(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    for pattern, placeholder in LOCAL:
        text = pattern.sub(placeholder, text)
    return [line for line in text.splitlines() if line.strip()]


@pytest.mark.parametrize("other", [name for name in COPIES if name != "SELF"])
def test_converter_copies_have_not_drifted(other):
    root = _lab_root()
    mine = root / COPIES[SELF]
    theirs = root / COPIES[other]
    if other == SELF:
        pytest.skip("same copy")
    if not theirs.is_file():
        pytest.skip(f"{other} is not checked out beside this repository")
    if not mine.is_file():
        pytest.skip("this copy moved; update COPIES")

    a, b = _normalised(mine), _normalised(theirs)
    if a == b:
        return

    import difflib
    diff = "\n".join(list(difflib.unified_diff(
        a, b, fromfile=SELF, tofile=other, lineterm="", n=1))[:60])
    pytest.fail(
        f"{SELF} and {other} converters have drifted.\n\n{diff}\n\n"
        "Port the change to every copy, or add a genuinely local difference "
        "to LOCAL in this file with a comment saying why."
    )
