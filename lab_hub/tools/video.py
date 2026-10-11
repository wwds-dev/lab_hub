"""Video conversion: change a folder of videos to another format and size.

Ported from a standalone ffmpeg web app. Nothing here imports Qt.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from . import Reporter, Result

INSTALL_HINT = "Video conversion needs ffmpeg. Install it with: brew install ffmpeg"

VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".flv", ".wmv", ".mpg", ".mpeg", ".gif"}

# ext: (video codec, audio codec, extra args)
FORMATS: dict[str, tuple[str | None, str | None, list[str]]] = {
    "mp4": ("libx264", "aac", ["-movflags", "+faststart", "-pix_fmt", "yuv420p"]),
    "mov": ("libx264", "aac", ["-pix_fmt", "yuv420p"]),
    "mkv": ("libx264", "aac", []),
    "webm": ("libvpx-vp9", "libopus", ["-b:v", "0", "-crf", "32"]),
    "avi": ("mpeg4", "mp3", ["-q:v", "4"]),
    "gif": (None, None, []),
}

ORIGINAL = "original"
HEIGHTS: dict[str, int | None] = {
    ORIGINAL: None, "2160p": 2160, "1440p": 1440, "1080p": 1080,
    "720p": 720, "480p": 480, "360p": 360,
}

# A frozen .app does not inherit the shell's PATH, so Homebrew is checked by hand.
_SEARCH = ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin")


def _find(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    for folder in _SEARCH:
        candidate = Path(folder) / name
        if candidate.is_file():
            return str(candidate)
    return None


def ffmpeg_path() -> str | None:
    return _find("ffmpeg")


def parse_size(text: str) -> tuple[int, int] | None:
    """'1280x720' -> (1280, 720); empty -> None; anything else -> ValueError."""
    text = text.strip().lower()
    if not text:
        return None
    try:
        width, height = (int(part) for part in text.split("x"))
    except ValueError:
        raise ValueError(f"Size must look like 1280x720, not {text!r}.") from None
    if width < 2 or height < 2:
        raise ValueError("Size must be at least 2x2.")
    return width, height


def build_command(
    ffmpeg: str, source: Path, target: Path, fmt: str, height: int | None, size: tuple[int, int] | None,
) -> list[str]:
    vcodec, acodec, extra = FORMATS[fmt]
    filters = []
    if fmt == "gif":
        filters.append("fps=12")
    if size:
        filters.append(f"scale={size[0]}:{size[1]}")
    elif height:
        filters.append(f"scale=-2:'min({height},ih)'")  # never upscales
    command = [ffmpeg, "-y", "-i", str(source)]
    if filters:
        command += ["-vf", ",".join(filters)]
    if vcodec:
        command += ["-c:v", vcodec, "-c:a", acodec]
    return [*command, *extra, str(target)]


def _videos_in(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_SUFFIXES)


def convert_videos(
    source: Path,
    destination: Path,
    report: Reporter,
    *,
    fmt: str = "mp4",
    resolution: str = ORIGINAL,
    custom_size: str = "",
    overwrite: bool = False,
) -> Result:
    """Convert every video in `source` into `destination`."""
    ffmpeg = ffmpeg_path()
    if ffmpeg is None:
        raise FileNotFoundError(INSTALL_HINT)
    if fmt not in FORMATS:
        raise ValueError(f"Unsupported format: {fmt}")
    if not source.is_dir():
        raise NotADirectoryError(f"Not a folder: {source}")
    size = parse_size(custom_size)
    height = HEIGHTS.get(resolution)
    destination.mkdir(parents=True, exist_ok=True)

    files = _videos_in(source)
    result = Result()
    if not files:
        report.log("No videos found.")
        return result
    tag = f"{size[0]}x{size[1]}" if size else (resolution if height else "")

    for done, video in enumerate(files):
        report.checkpoint()
        report.progress(done, len(files))
        target = destination / f"{video.stem}{'_' + tag if tag else ''}.{fmt}"
        if target.resolve() == video.resolve():
            report.log(f"Skipped {video.name}: output would overwrite the source.")
            result.skipped += 1
            continue
        if target.exists() and not overwrite:
            report.log(f"Skipped {video.name}: {target.name} already exists.")
            result.skipped += 1
            continue
        report.log(f"Converting {video.name} → {target.name}")
        run = subprocess.run(
            build_command(ffmpeg, video, target, fmt, height, size),
            capture_output=True, text=True,
        )
        if run.returncode != 0:
            lines = run.stderr.strip().splitlines()
            message = f"{video.name}: {lines[-1] if lines else 'ffmpeg failed'}"
            report.log(f"Failed {message}")
            result.failed += 1
            result.errors.append(message)
            target.unlink(missing_ok=True)
        else:
            result.processed += 1
    report.progress(len(files), len(files))
    return result
