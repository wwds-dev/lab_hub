"""Executing a planned :class:`~lab_hub.tools.convert.jobs.Job`.

Separate from both the planner and the Qt worker so the awkward parts — the
KEPUB rename, overwrite handling, partial-output cleanup — can be tested
without a running event loop.

Vendored copy — developed and tested in
active/convert_epub/ebook_converter/. Keep the two in step.
"""

import subprocess
from collections.abc import Callable
from pathlib import Path

from . import calibre, formats
from .jobs import Job, Status


def execute(
    job: Job,
    output_format: formats.OutputFormat,
    *,
    binary: Path | None = None,
    register: Callable[[subprocess.Popen], None] | None = None,
    on_line: Callable[[str], None] | None = None,
) -> Job:
    """Run one conversion and record the outcome on ``job``.

    Never raises for an ordinary conversion failure — the job carries the
    result, because one bad file in a queue of two hundred should not stop the
    other hundred and ninety-nine.
    """
    job.status = Status.RUNNING
    job.detail = ""

    # Calibre picks its output plugin from the extension it is handed, so a
    # KEPUB has to be written as .kepub and renamed afterwards to the
    # .kepub.epub that Kobo devices actually recognise.
    write_path = job.target
    if output_format.renames_output:
        write_path = job.target.with_name(job.target.name[: -len(output_format.final_suffix)] + output_format.convert_suffix)

    try:
        job.log = calibre.convert(
            job.source, write_path, binary=binary, register=register, on_line=on_line
        )
    except calibre.CalibreNotFound as exc:
        job.status = Status.FAILED
        job.detail = "Calibre not found"
        job.log = str(exc)
        return job
    except calibre.ConversionFailed as exc:
        job.status = Status.FAILED
        job.detail = str(exc)
        job.log = exc.output
        _cleanup(write_path)
        return job

    if write_path != job.target:
        try:
            job.target.unlink(missing_ok=True)
            write_path.rename(job.target)
        except OSError as exc:
            job.status = Status.FAILED
            job.detail = f"could not rename to {job.target.name}: {exc}"
            return job

    job.status = Status.DONE
    job.detail = _format_size(job.target)
    return job


def _cleanup(path: Path) -> None:
    """Remove a half-written output so a failed run leaves nothing behind."""
    try:
        if path.exists() and path.stat().st_size == 0:
            path.unlink()
    except OSError:
        pass


def _format_size(path: Path) -> str:
    try:
        size = path.stat().st_size
    except OSError:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return ""
