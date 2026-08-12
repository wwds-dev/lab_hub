"""The image utilities, against real files.

These were scripts with their folders hardcoded at the top, so the behaviour
was only ever verified by running them on the real Merch folder. Pillow does
the pixel work; what is worth testing is the surrounding decisions — canvas
size, aspect ratio, numbering continuity, and what is left alone.
"""

from __future__ import annotations

import pytest
from PIL import Image

from lab_hub.tools import Cancelled, images

from .fakes import RecordingReporter


def make_image(path, size=(900, 600), colour=(200, 30, 90)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, colour).save(path)
    return path


# ----------------------------------------------------------------------
# Print sizing
# ----------------------------------------------------------------------
def test_fit_letterboxes_without_distorting(tmp_path):
    source, out = tmp_path / "in", tmp_path / "out"
    make_image(source / "wide.png", (900, 300))

    images.resize_for_print(
        source, out, RecordingReporter(), width_in=2, height_in=3, dpi=100, mode="fit"
    )

    with Image.open(out / "wide.png") as result:
        assert result.size == (200, 300)
        # A 3:1 source on a 2:3 canvas: the artwork spans the full width and is
        # letterboxed, so the vertical middle is artwork and the top is canvas.
        assert result.convert("RGB").getpixel((100, 150)) != (0, 0, 0)
        assert result.convert("RGB").getpixel((100, 5)) == (0, 0, 0)


def test_exact_fills_the_canvas(tmp_path):
    source, out = tmp_path / "in", tmp_path / "out"
    make_image(source / "wide.png", (900, 300))

    images.resize_for_print(
        source, out, RecordingReporter(), width_in=2, height_in=3, dpi=100, mode="exact"
    )

    with Image.open(out / "wide.png") as result:
        assert result.size == (200, 300)
        assert result.convert("RGB").getpixel((100, 5)) != (0, 0, 0), "no letterboxing"


def test_the_dpi_is_written_into_the_file(tmp_path):
    """The whole point: a print shop reads the DPI, not the pixel count."""
    source, out = tmp_path / "in", tmp_path / "out"
    make_image(source / "art.png")

    images.resize_for_print(
        source, out, RecordingReporter(), width_in=12, height_in=16, dpi=300
    )

    with Image.open(out / "art.png") as result:
        # PNG stores pixels-per-metre as an integer, so 300 comes back as 299.9994.
        assert tuple(round(v) for v in result.info["dpi"]) == (300, 300)


def test_a_jpeg_target_is_flattened_rather_than_failing(tmp_path):
    """JPEG has no alpha channel; the canvas is RGBA. Saving naively raises."""
    source, out = tmp_path / "in", tmp_path / "out"
    make_image(source / "art.jpg", (400, 400))

    result = images.resize_for_print(
        source, out, RecordingReporter(), width_in=2, height_in=3, dpi=100
    )

    assert result.failed == 0
    with Image.open(out / "art.jpg") as written:
        assert written.mode == "RGB"


def test_one_unreadable_file_does_not_stop_the_batch(tmp_path):
    source, out = tmp_path / "in", tmp_path / "out"
    make_image(source / "good.png", (100, 100))
    (source / "broken.png").write_text("not an image")

    result = images.resize_for_print(
        source, out, RecordingReporter(), width_in=1, height_in=1, dpi=72
    )

    assert result.processed == 1
    assert result.failed == 1
    assert (out / "good.png").exists()


def test_stop_interrupts_the_batch(tmp_path):
    source, out = tmp_path / "in", tmp_path / "out"
    for index in range(4):
        make_image(source / f"{index}.png", (100, 100))

    with pytest.raises(Cancelled):
        images.resize_for_print(
            source,
            out,
            RecordingReporter(cancel_after=2),
            width_in=1,
            height_in=1,
            dpi=72,
        )


# ----------------------------------------------------------------------
# Renaming
# ----------------------------------------------------------------------
def test_numbering_continues_from_the_target_folder(tmp_path):
    """A second batch must not collide with the first."""
    source, target = tmp_path / "new", tmp_path / "ready"
    make_image(source / "a.png")
    make_image(source / "b.png")
    make_image(target / "art_007.png")

    images.rename_for_print(
        source, target, RecordingReporter(), base_name="art", move=True
    )

    assert (target / "art_008.png").exists()
    assert (target / "art_009.png").exists()
    assert (target / "art_007.png").exists(), "the existing batch is untouched"


def test_renaming_leaves_files_in_place_by_default(tmp_path):
    """The original script's behaviour; moving is opt-in."""
    source, target = tmp_path / "new", tmp_path / "ready"
    make_image(source / "a.png")
    target.mkdir()

    images.rename_for_print(source, target, RecordingReporter(), base_name="art")

    assert (source / "art_001.png").exists()
    assert not (target / "art_001.png").exists()


def test_a_missing_target_folder_is_refused(tmp_path):
    source = tmp_path / "new"
    make_image(source / "a.png")

    with pytest.raises(NotADirectoryError):
        images.rename_for_print(
            source, tmp_path / "nope", RecordingReporter(), base_name="art"
        )


def test_one_already_numbered_file_does_not_stall_the_batch(tmp_path):
    """Regression: the counter used to roll back on every collision, so a
    single pre-existing name made every remaining file retry the same taken
    number and nothing was renamed at all."""
    source, target = tmp_path / "new", tmp_path / "ready"
    make_image(source / "a.png")
    make_image(source / "b.png")
    make_image(source / "art_001.png")  # left over from an earlier run
    target.mkdir()

    result = images.rename_for_print(
        source, target, RecordingReporter(), base_name="art"
    )

    assert result.processed == 2, "the new files must still get numbers"
    assert result.skipped == 1
    assert (source / "art_002.png").exists()
    assert (source / "art_003.png").exists()
    assert (source / "art_001.png").exists(), "the earlier run is left alone"


def test_running_twice_over_the_same_folder_changes_nothing(tmp_path):
    source, target = tmp_path / "new", tmp_path / "ready"
    make_image(source / "a.png")
    target.mkdir()

    images.rename_for_print(source, target, RecordingReporter(), base_name="art")
    before = sorted(p.name for p in source.iterdir())
    result = images.rename_for_print(source, target, RecordingReporter(), base_name="art")

    assert sorted(p.name for p in source.iterdir()) == before
    assert result.processed == 0


# ----------------------------------------------------------------------
# Sweeping
# ----------------------------------------------------------------------
def test_small_images_are_moved_not_deleted(tmp_path):
    """A size filter will sometimes catch something wanted."""
    folder = tmp_path / "pics"
    make_image(folder / "thumb.png", (50, 50))
    make_image(folder / "keep.png", (500, 500))

    result = images.move_small(folder, RecordingReporter(), max_width=200, max_height=200)

    assert (folder / "Delete" / "thumb.png").exists()
    assert (folder / "keep.png").exists()
    assert result.processed == 1
    assert result.skipped == 1


def test_the_threshold_is_inclusive(tmp_path):
    folder = tmp_path / "pics"
    make_image(folder / "exact.png", (200, 200))

    images.move_small(folder, RecordingReporter(), max_width=200, max_height=200)

    assert (folder / "Delete" / "exact.png").exists()


def test_an_image_over_the_limit_in_one_dimension_stays(tmp_path):
    folder = tmp_path / "pics"
    make_image(folder / "tall.png", (50, 400))

    images.move_small(folder, RecordingReporter(), max_width=200, max_height=200)

    assert (folder / "tall.png").exists()


def test_the_delete_folder_is_not_swept_into_itself(tmp_path):
    folder = tmp_path / "pics"
    make_image(folder / "thumb.png", (50, 50))
    make_image(folder / "Delete" / "already.png", (10, 10))

    images.move_small(folder, RecordingReporter(), max_width=200, max_height=200)

    assert (folder / "Delete" / "already.png").exists()
