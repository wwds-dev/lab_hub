"""Turning dropped paths into a concrete conversion plan.

Kept free of Qt so the planning rules can be tested directly.

Vendored copy — developed and tested in
active/convert_epub/ebook_converter/. Keep the two in step.
"""

import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from . import formats


class OutputMode(str, Enum):
    BESIDE_SOURCE = "beside"
    CUSTOM_FOLDER = "folder"


class Status(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    SKIPPED = "skipped"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Job:
    """One source file destined for one output file."""

    source: Path
    target: Path
    status: Status = Status.QUEUED
    detail: str = ""
    log: str = field(default="", repr=False)

    @property
    def source_ext(self) -> str:
        return self.source.suffix.lower().lstrip(".")

    @property
    def target_ext(self) -> str:
        return self.target.name.split(".", 1)[-1].lower() if "." in self.target.name else ""

    @property
    def is_pending(self) -> bool:
        return self.status is Status.QUEUED


def collect_sources(paths: Iterable[Path], *, recurse: bool = True) -> list[Path]:
    """Expand dropped paths into a de-duplicated list of convertible files.

    Files are taken at face value — if the user explicitly picked it, it is
    included as long as Calibre can read the extension. Folders are scanned,
    recursively unless told otherwise. Hidden files and macOS resource forks
    are always ignored; a folder full of ``._Foo.epub`` stubs would otherwise
    produce a queue of guaranteed failures.
    """
    found: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path) -> None:
        resolved = path.resolve()
        if resolved in seen:
            return
        if path.name.startswith("."):
            return
        if not formats.is_convertible(path.suffix):
            return
        seen.add(resolved)
        found.append(resolved)

    for raw in paths:
        path = Path(raw)
        if path.is_file():
            add(path)
        elif path.is_dir():
            if recurse:
                for dirpath, dirnames, filenames in os.walk(path):
                    dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
                    for name in sorted(filenames):
                        add(Path(dirpath) / name)
            else:
                for child in sorted(path.iterdir()):
                    if child.is_file():
                        add(child)

    return found


def target_for(
    source: Path,
    output_format: formats.OutputFormat,
    *,
    mode: OutputMode = OutputMode.BESIDE_SOURCE,
    output_dir: Path | None = None,
) -> Path:
    """Where the converted copy of ``source`` should land.

    In custom-folder mode the flat output can collide — two ``Book.epub`` files
    from different folders both want ``Book.pdf``. Callers resolve that with
    :func:`deduplicate_targets`.
    """
    name = source.stem + output_format.final_suffix
    if mode is OutputMode.CUSTOM_FOLDER and output_dir is not None:
        return Path(output_dir) / name
    return source.parent / name


def deduplicate_targets(jobs: list[Job]) -> None:
    """Give colliding targets a ``-2``, ``-3``… suffix, in place."""
    used: set[Path] = set()
    for job in jobs:
        target = job.target
        if target not in used:
            used.add(target)
            continue
        stem, suffix = _split_name(target.name)
        counter = 2
        while True:
            candidate = target.with_name(f"{stem}-{counter}{suffix}")
            if candidate not in used:
                break
            counter += 1
        job.target = candidate
        used.add(candidate)


def plan(
    sources: Iterable[Path],
    output_format: formats.OutputFormat,
    *,
    mode: OutputMode = OutputMode.BESIDE_SOURCE,
    output_dir: Path | None = None,
    overwrite: bool = False,
) -> list[Job]:
    """Build the job list, pre-marking everything that will not run.

    Two cases are settled up front rather than at conversion time, so the queue
    shows the truth before the user commits: a file already in the target
    format, and an existing output that overwrite is off for.
    """
    jobs: list[Job] = []
    for source in sources:
        target = target_for(source, output_format, mode=mode, output_dir=output_dir)
        job = Job(source=Path(source), target=target)

        if _same_format(job.source, output_format):
            job.status = Status.SKIPPED
            job.detail = f"already {output_format.label}"
        jobs.append(job)

    deduplicate_targets(jobs)

    if not overwrite:
        for job in jobs:
            if job.is_pending and job.target.exists():
                job.status = Status.SKIPPED
                job.detail = "output exists"

    return jobs


def _same_format(source: Path, output_format: formats.OutputFormat) -> bool:
    source_name = source.name.lower()
    return source_name.endswith(output_format.final_suffix) or source_name.endswith(
        output_format.convert_suffix
    )


def _split_name(name: str) -> tuple[str, str]:
    """Split into stem and suffix, keeping compound suffixes intact.

    ``Book.kepub.epub`` must split as ``("Book", ".kepub.epub")``, otherwise a
    de-duplicated name comes out as ``Book.kepub-2.epub``.
    """
    for output_format in formats.OUTPUT_FORMATS:
        if output_format.renames_output and name.lower().endswith(output_format.final_suffix):
            return name[: -len(output_format.final_suffix)], name[-len(output_format.final_suffix) :]
    path = Path(name)
    return path.stem, path.suffix


def summarize(jobs: list[Job]) -> str:
    """A one-line tally of a finished run."""
    counts: dict[Status, int] = {}
    for job in jobs:
        counts[job.status] = counts.get(job.status, 0) + 1
    order = [
        (Status.DONE, "converted"),
        (Status.SKIPPED, "skipped"),
        (Status.FAILED, "failed"),
        (Status.CANCELLED, "cancelled"),
    ]
    parts = [f"{counts[status]} {label}" for status, label in order if counts.get(status)]
    return ", ".join(parts) if parts else "nothing to do"
