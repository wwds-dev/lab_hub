"""Document conversion, via Calibre's ebook-convert.

Replaces the old EPUB → PDF tool, which walked one folder and understood
exactly one format pair. This converts anything Calibre reads into anything
Calibre writes, from an explicit list of files rather than a folder scan.

`formats`, `calibre`, `jobs` and `runner` are vendored copies of the engine in
`active/convert_epub/ebook_converter/`, which is where they are developed and
tested. They are copied rather than imported so Lab Hub does not depend on a
sibling checkout being present; keep the two in step when either changes.

Nothing in this package imports Qt.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from .. import Cancelled, Reporter, Result
from . import calibre, formats, jobs, runner
from .jobs import OutputMode, Status

INSTALL_HINT = calibre.INSTALL_HINT

__all__ = [
    "INSTALL_HINT",
    "OutputMode",
    "calibre",
    "convert",
    "converter_path",
    "formats",
    "jobs",
    "runner",
]


def converter_path() -> str | None:
    """Where ebook-convert lives, or None if Calibre is not installed."""
    found = calibre.find_ebook_convert()
    return str(found) if found else None


def convert(
    sources: Iterable[Path],
    report: Reporter,
    *,
    output_ext: str = formats.DEFAULT_OUTPUT_EXT,
    mode: OutputMode = OutputMode.BESIDE_SOURCE,
    output_dir: Path | None = None,
    overwrite: bool = False,
) -> Result:
    """Convert every file in `sources` to `output_ext`."""
    binary = calibre.find_ebook_convert()
    if binary is None:
        raise FileNotFoundError(INSTALL_HINT)

    output_format = formats.OUTPUT_BY_EXT.get(output_ext)
    if output_format is None:
        raise ValueError(f"Not an output format Calibre writes: {output_ext}")

    planned = jobs.plan(
        sources,
        output_format,
        mode=mode,
        output_dir=output_dir,
        overwrite=overwrite,
    )
    report.log(f"{len(planned)} file(s) queued → {output_format.label}.")

    result = Result()
    for index, job in enumerate(planned):
        report.checkpoint()
        report.progress(index, len(planned))

        if job.status is Status.SKIPPED:
            report.log(f"Skipping ({job.detail}): {job.source.name}")
            result.skipped += 1
            continue

        report.log(f"Converting: {job.source.name} → {job.target.name}")
        _run(job, output_format, binary, report, result)

    report.progress(len(planned), len(planned))
    return result


def _run(job, output_format, binary, report: Reporter, result: Result) -> None:
    """Execute one job, translating its outcome into the Result tally."""

    def on_line(line: str) -> None:
        # Calibre's progress chatter doubles as the cancellation checkpoint:
        # a big book is minutes of one subprocess, so waiting for it to finish
        # before honouring Stop would not feel like stopping at all.
        report.checkpoint()
        report.log(f"    {line}")

    try:
        runner.execute(job, output_format, binary=binary, on_line=on_line)
    except Cancelled:
        # The child was terminated mid-write; do not leave the stub behind.
        try:
            job.target.unlink(missing_ok=True)
        except OSError:
            pass
        raise

    if job.status is Status.DONE:
        result.processed += 1
        report.log(f"Wrote: {job.target.name} ({job.detail})")
    else:
        message = f"Failed: {job.source.name} ({job.detail})"
        report.log(message)
        result.failed += 1
        result.errors.append(message)
