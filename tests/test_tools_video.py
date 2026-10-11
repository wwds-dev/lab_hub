"""Video conversion, against real ffmpeg output."""

from __future__ import annotations

import json
import subprocess

import pytest

from lab_hub.tools import video

from .fakes import RecordingReporter

needs_ffmpeg = pytest.mark.skipif(video.ffmpeg_path() is None, reason="ffmpeg not installed")


def make_video(path, size="320x180"):
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [video.ffmpeg_path(), "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc=d=1:s={size}:r=10", str(path)],
        check=True,
    )
    return path


def dimensions(path):
    out = subprocess.check_output(
        [video.ffmpeg_path().replace("ffmpeg", "ffprobe"), "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "json", str(path)]
    )
    stream = json.loads(out)["streams"][0]
    return stream["width"], stream["height"]


def test_parse_size():
    assert video.parse_size("") is None
    assert video.parse_size(" 1280X720 ") == (1280, 720)
    with pytest.raises(ValueError):
        video.parse_size("big")


def test_height_never_upscales():
    command = video.build_command("ffmpeg", "a.mov", "a.mp4", "mp4", 1080, None)
    assert "scale=-2:'min(1080,ih)'" in command


@needs_ffmpeg
def test_converts_format_and_custom_size(tmp_path):
    make_video(tmp_path / "in" / "clip.mp4")
    result = video.convert_videos(
        tmp_path / "in", tmp_path / "out", RecordingReporter(), fmt="webm", custom_size="160x90"
    )
    assert result.processed == 1
    assert dimensions(tmp_path / "out" / "clip_160x90.webm") == (160, 90)


@needs_ffmpeg
def test_skips_existing_unless_overwrite(tmp_path):
    make_video(tmp_path / "in" / "clip.mp4")
    args = (tmp_path / "in", tmp_path / "out", RecordingReporter())
    assert video.convert_videos(*args, fmt="mkv").processed == 1
    assert video.convert_videos(*args, fmt="mkv").skipped == 1
    assert video.convert_videos(*args, fmt="mkv", overwrite=True).processed == 1


@needs_ffmpeg
def test_refuses_to_overwrite_the_source(tmp_path):
    make_video(tmp_path / "in" / "clip.mp4")
    result = video.convert_videos(tmp_path / "in", tmp_path / "in", RecordingReporter(), fmt="mp4", overwrite=True)
    assert result.skipped == 1 and (tmp_path / "in" / "clip.mp4").stat().st_size > 0
