"""Settings, stored outside the app bundle.

A frozen .app must not write inside itself — that breaks the code signature and
a reinstall wipes whatever was written. Everything persistent goes to
~/Library/Application Support/Lab Hub/ instead.

Most of these fields are just remembered folder choices. The scripts these
tools came from had their paths hardcoded in a CONFIG block at the top of the
file; keeping the last-used folder is what replaces editing the source.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from . import APP_NAME

SUPPORT_DIR = Path.home() / "Library" / "Application Support" / APP_NAME
CONFIG_PATH = SUPPORT_DIR / "config.json"

# Where the lab's project folders live. Only needed to run a sibling app from
# source; launching an installed .app does not touch it.
LAB_ROOT_ENV = "LAB_ROOT"
DEFAULT_LAB_ROOT = Path.home() / "Documents" / "lab" / "active"


@dataclass
class Settings:
    lab_root: str = ""

    # Convert (any document format to any other)
    convert_output_ext: str = "epub"
    convert_output_mode: str = "beside"  # "beside" (next to the source) or "folder"
    convert_output_dir: str = ""
    convert_overwrite: bool = False
    convert_recurse: bool = True
    convert_source_dir: str = ""  # where the Add dialogs open

    # Narrator (ebook to audiobook)
    narrator_input: str = ""
    narrator_output: str = ""
    narrator_voice: str = "alloy"
    narrator_chunk_tokens: int = 1400

    # Image tools — DPI
    dpi_input: str = ""
    dpi_output: str = ""
    dpi_width_in: int = 12
    dpi_height_in: int = 16
    dpi_mode: str = "fit"  # "fit" (letterbox) or "exact" (stretch)
    dpi_background: str = "black"  # black | white | transparent

    # Image tools — rename
    rename_source: str = ""
    rename_target: str = ""
    rename_base: str = "sweet_poison"

    # Image tools — move small
    move_source: str = ""
    move_max_width: int = 200
    move_max_height: int = 200

    recent_logs: list[str] = field(default_factory=list)

    def resolved_lab_root(self) -> Path:
        """Where to look for sibling project folders.

        Explicit setting wins, then $LAB_ROOT, then the location this file was
        run from (correct in a source checkout, meaningless once frozen), then
        the conventional path under ~/Documents.
        """
        if self.lab_root:
            return Path(self.lab_root).expanduser()
        env = os.environ.get(LAB_ROOT_ENV)
        if env:
            return Path(env).expanduser()

        # lab_hub/lab_hub/config.py -> lab_hub -> active/. Inside a frozen
        # bundle this resolves somewhere in the app's temp tree, so it is only
        # accepted when the expected siblings are actually there.
        here = Path(__file__).resolve().parents[2]
        if (here / "unblock_tracker").is_dir():
            return here
        return DEFAULT_LAB_ROOT


def load() -> Settings:
    """Read settings, falling back to defaults for anything missing or broken."""
    if not CONFIG_PATH.exists():
        return Settings()
    try:
        raw = json.loads(CONFIG_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return Settings()
    if not isinstance(raw, dict):
        return Settings()

    known = {f.name for f in fields(Settings)}
    return Settings(**{k: v for k, v in raw.items() if k in known})


def save(settings: Settings) -> None:
    SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(asdict(settings), indent=2))
