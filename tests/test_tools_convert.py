"""Job planning for the Convert tab.

None of this runs Calibre — it is the decision-making around it: which dropped
paths become jobs, where the output lands, and what is settled as skipped
before the user commits. That last part matters because the queue is shown
before anything runs, so it has to tell the truth up front.
"""

from __future__ import annotations

from pathlib import Path

from lab_hub.tools.convert import formats, jobs
from lab_hub.tools.convert.jobs import OutputMode, Status

EPUB = formats.OUTPUT_BY_EXT["epub"]
PDF = formats.OUTPUT_BY_EXT["pdf"]


def touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x")
    return path


# ----------------------------------------------------------------------
# Collecting what was dropped
# ----------------------------------------------------------------------
def test_a_folder_is_scanned_recursively(tmp_path):
    touch(tmp_path / "a.epub")
    touch(tmp_path / "deep" / "b.epub")

    found = jobs.collect_sources([tmp_path])

    assert {p.name for p in found} == {"a.epub", "b.epub"}


def test_recursion_can_be_turned_off(tmp_path):
    touch(tmp_path / "a.epub")
    touch(tmp_path / "deep" / "b.epub")

    found = jobs.collect_sources([tmp_path], recurse=False)

    assert {p.name for p in found} == {"a.epub"}


def test_files_calibre_cannot_read_are_left_out(tmp_path):
    touch(tmp_path / "book.epub")
    touch(tmp_path / "notes.xyz")

    found = jobs.collect_sources([tmp_path])

    assert {p.name for p in found} == {"book.epub"}


def test_resource_forks_are_ignored(tmp_path):
    """A folder off a USB stick is full of ._Foo.epub stubs; queueing them
    would be a queue of guaranteed failures."""
    touch(tmp_path / "book.epub")
    touch(tmp_path / "._book.epub")

    found = jobs.collect_sources([tmp_path])

    assert {p.name for p in found} == {"book.epub"}


def test_the_same_file_dropped_twice_appears_once(tmp_path):
    book = touch(tmp_path / "book.epub")

    found = jobs.collect_sources([book, book, tmp_path])

    assert len(found) == 1


# ----------------------------------------------------------------------
# Where the output goes
# ----------------------------------------------------------------------
def test_beside_the_source_by_default(tmp_path):
    book = touch(tmp_path / "deep" / "book.epub")

    target = jobs.target_for(book, PDF)

    assert target.parent == book.parent
    assert target.name == "book.pdf"


def test_a_chosen_folder_flattens_the_output(tmp_path):
    book = touch(tmp_path / "deep" / "book.epub")
    out = tmp_path / "out"

    target = jobs.target_for(book, PDF, mode=OutputMode.CUSTOM_FOLDER, output_dir=out)

    assert target == out / "book.pdf"


def test_two_books_of_the_same_name_do_not_overwrite_each_other(tmp_path):
    """The flat-output collision: Volume 1/Book.epub and Volume 2/Book.epub."""
    out = tmp_path / "out"
    sources = [
        touch(tmp_path / "one" / "Book.epub"),
        touch(tmp_path / "two" / "Book.epub"),
        touch(tmp_path / "three" / "Book.epub"),
    ]

    planned = jobs.plan(
        sources, PDF, mode=OutputMode.CUSTOM_FOLDER, output_dir=out
    )

    names = [job.target.name for job in planned]
    assert names == ["Book.pdf", "Book-2.pdf", "Book-3.pdf"]


# ----------------------------------------------------------------------
# What is settled before anything runs
# ----------------------------------------------------------------------
def test_a_file_already_in_the_target_format_is_skipped(tmp_path):
    book = touch(tmp_path / "book.epub")

    planned = jobs.plan([book], EPUB)

    assert planned[0].status is Status.SKIPPED
    assert "already" in planned[0].detail


def test_an_existing_output_is_skipped(tmp_path):
    book = touch(tmp_path / "book.epub")
    touch(tmp_path / "book.pdf")

    planned = jobs.plan([book], PDF)

    assert planned[0].status is Status.SKIPPED
    assert planned[0].detail == "output exists"


def test_overwrite_lets_it_run(tmp_path):
    book = touch(tmp_path / "book.epub")
    touch(tmp_path / "book.pdf")

    planned = jobs.plan([book], PDF, overwrite=True)

    assert planned[0].status is Status.QUEUED


def test_overwrite_does_not_resurrect_a_same_format_skip(tmp_path):
    """Converting an EPUB to an EPUB is pointless whatever the flag says."""
    book = touch(tmp_path / "book.epub")

    planned = jobs.plan([book], EPUB, overwrite=True)

    assert planned[0].status is Status.SKIPPED


def test_a_queued_job_knows_its_extensions(tmp_path):
    book = touch(tmp_path / "book.epub")

    job = jobs.plan([book], PDF)[0]

    assert job.source_ext == "epub"
    assert job.target_ext == "pdf"
    assert job.is_pending
