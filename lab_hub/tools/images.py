"""The image_tools utilities: print-size resizing, batch rename, small-image sweep.

Ported from image_tools/{dpi,rename,move}, which were four scripts with their
folders and sizes hardcoded at the top. The processing is the same; the config
block is now a function signature.

The two DPI scripts differed only in whether artwork was stretched to the
target or scaled proportionally onto a canvas, so they are one function with a
`mode` here.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from PIL import Image

from . import IMAGE_SUFFIXES, Reporter, Result

BACKGROUNDS: dict[str, tuple[int, int, int, int]] = {
    "black": (0, 0, 0, 255),
    "white": (255, 255, 255, 255),
    "transparent": (0, 0, 0, 0),
}

MODE_FIT = "fit"
MODE_EXACT = "exact"


def _images_in(folder: Path) -> list[Path]:
    return sorted(
        p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES
    )


# ----------------------------------------------------------------------
# DPI / print size
# ----------------------------------------------------------------------
def resize_for_print(
    source: Path,
    destination: Path,
    report: Reporter,
    *,
    width_in: int = 12,
    height_in: int = 16,
    dpi: int = 300,
    mode: str = MODE_FIT,
    background: str = "black",
) -> Result:
    """Write print-ready copies at an exact pixel size and DPI.

    `fit` scales the artwork proportionally and centres it on a canvas, so
    nothing is distorted. `exact` stretches to fill, matching the original
    dpi_resize_exact.py.
    """
    if not source.is_dir():
        raise NotADirectoryError(f"Not a folder: {source}")
    if mode not in (MODE_FIT, MODE_EXACT):
        raise ValueError(f"Unknown mode: {mode}")
    if background not in BACKGROUNDS:
        raise ValueError(f"Unknown background: {background}")

    target_px = (width_in * dpi, height_in * dpi)
    fill = BACKGROUNDS[background]
    destination.mkdir(parents=True, exist_ok=True)

    files = [p for p in _images_in(source) if p.parent != destination]
    report.log(f"{len(files)} image(s) in {source}")
    report.log(
        f"Target: {target_px[0]}×{target_px[1]}px "
        f"({width_in}×{height_in}in @ {dpi} DPI), mode '{mode}'."
    )

    result = Result()
    for index, path in enumerate(files, start=1):
        report.checkpoint()
        report.progress(index - 1, len(files))
        output = destination / path.name

        try:
            with Image.open(path) as image:
                image = image.convert("RGBA")

                if mode == MODE_EXACT:
                    canvas = image.resize(target_px, Image.Resampling.LANCZOS)
                else:
                    scale = min(
                        target_px[0] / image.width, target_px[1] / image.height
                    )
                    size = (max(1, int(image.width * scale)), max(1, int(image.height * scale)))
                    resized = image.resize(size, Image.Resampling.LANCZOS)
                    canvas = Image.new("RGBA", target_px, fill)
                    offset = (
                        (target_px[0] - size[0]) // 2,
                        (target_px[1] - size[1]) // 2,
                    )
                    canvas.paste(resized, offset, resized)

                # JPEG has no alpha channel; flatten onto the chosen colour
                # rather than failing at save time.
                if output.suffix.lower() in {".jpg", ".jpeg"}:
                    flat = Image.new("RGB", canvas.size, fill[:3])
                    flat.paste(canvas, mask=canvas.split()[3])
                    canvas = flat

                canvas.save(output, dpi=(dpi, dpi))

            result.processed += 1
            report.log(f"{path.name} → {canvas.width}×{canvas.height}px")
        except Exception as error:  # noqa: BLE001 - one bad file must not stop the batch
            message = f"Failed: {path.name} ({error})"
            report.log(message)
            result.failed += 1
            result.errors.append(message)

    report.progress(len(files), len(files))
    report.log(f"Output folder: {destination}")
    return result


# ----------------------------------------------------------------------
# Rename
# ----------------------------------------------------------------------
def next_index(folder: Path, base_name: str) -> int:
    """The highest `base_name_NNN` already used in `folder`."""
    pattern = re.compile(rf"{re.escape(base_name)}_(\d+)", re.IGNORECASE)
    highest = 0
    if folder.is_dir():
        for path in folder.iterdir():
            match = pattern.search(path.stem)
            if path.is_file() and match:
                highest = max(highest, int(match.group(1)))
    return highest


def rename_for_print(
    source: Path,
    target: Path,
    report: Reporter,
    *,
    base_name: str = "sweet_poison",
    padding: int = 3,
    move: bool = False,
) -> Result:
    """Number images sequentially, continuing from what `target` already holds.

    `target` is the numbering authority — the counter picks up after the
    highest index found there, so a second batch never collides with the first.
    By default the files are renamed where they are (the original script's
    behaviour); `move` also relocates them into `target`.
    """
    if not source.is_dir():
        raise NotADirectoryError(f"Source folder not found: {source}")
    if not target.is_dir():
        raise NotADirectoryError(f"Target folder not found: {target}")

    index = next_index(target, base_name)
    report.log(f"Highest existing index in {target.name}: {index}")

    files = [p for p in _images_in(source) if p.parent != target]
    if not files:
        report.log("No images found to rename.")
        return Result()

    result = Result()
    for position, path in enumerate(files, start=1):
        report.checkpoint()
        report.progress(position - 1, len(files))

        index += 1
        name = f"{base_name}_{str(index).zfill(padding)}{path.suffix.lower()}"
        destination = (target if move else source) / name

        if destination.exists():
            message = f"Skipped: {name} already exists"
            report.log(message)
            result.skipped += 1
            index -= 1  # do not burn a number on a file we did not write
            continue

        try:
            path.rename(destination)
            result.processed += 1
            report.log(f"{path.name} → {name}")
        except OSError as error:
            message = f"Failed: {path.name} ({error})"
            report.log(message)
            result.failed += 1
            result.errors.append(message)

    report.progress(len(files), len(files))
    return result


# ----------------------------------------------------------------------
# Move small images
# ----------------------------------------------------------------------
def move_small(
    source: Path,
    report: Reporter,
    *,
    max_width: int = 200,
    max_height: int = 200,
    folder_name: str = "Delete",
) -> Result:
    """Sweep thumbnails and junk into a subfolder instead of deleting them.

    Moving rather than deleting is the point: the sweep is by pixel size alone,
    which will occasionally catch something wanted.
    """
    if not source.is_dir():
        raise NotADirectoryError(f"Not a folder: {source}")

    destination = source / folder_name
    destination.mkdir(parents=True, exist_ok=True)

    files = [p for p in _images_in(source) if p.parent != destination]
    report.log(f"Checking {len(files)} image(s) in {source}")
    report.log(f"Moving anything at or under {max_width}×{max_height}px.")

    result = Result()
    for index, path in enumerate(files, start=1):
        report.checkpoint()
        report.progress(index - 1, len(files))

        try:
            with Image.open(path) as image:
                width, height = image.size
            if width > max_width or height > max_height:
                result.skipped += 1
                continue
            shutil.move(str(path), str(destination / path.name))
            result.processed += 1
            report.log(f"Moved: {path.name} ({width}×{height})")
        except Exception as error:  # noqa: BLE001 - skip unreadable files
            report.log(f"Skipping {path.name}: {error}")
            result.failed += 1
            result.errors.append(f"{path.name}: {error}")

    report.progress(len(files), len(files))
    if result.processed == 0:
        report.log(f"Nothing was under {max_width}×{max_height}px.")
    else:
        report.log(f"Moved {result.processed} image(s) into {destination}")
    return result
