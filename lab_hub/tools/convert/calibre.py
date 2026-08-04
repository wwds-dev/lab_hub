"""Locating and driving Calibre's ``ebook-convert`` binary.

Two things here exist purely because the app is packaged as a .app bundle:

* An app launched from Finder inherits a bare ``PATH`` (roughly
  ``/usr/bin:/bin:/usr/sbin:/sbin``) — not the shell's. ``shutil.which`` alone
  therefore finds nothing, even on a machine where ``ebook-convert`` works
  perfectly in Terminal. Hence :data:`SEARCH_PATHS`.
* PyInstaller points the dynamic linker at the bundle's own copies of system
  libraries. A child process inheriting that environment can load the wrong
  ``libssl``/``libz`` and crash. PyInstaller stashes the pre-launch values in
  ``*_ORIG`` variables for exactly this reason; :func:`subprocess_env` puts
  them back.

Vendored copy — developed and tested in
active/convert_epub/ebook_converter/. Keep the two in step.
"""

import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

# Checked in order. Homebrew first (both Apple Silicon and Intel prefixes),
# then the app bundle Calibre's own installer ships.
SEARCH_PATHS: tuple[Path, ...] = (
    Path("/opt/homebrew/bin/ebook-convert"),
    Path("/usr/local/bin/ebook-convert"),
    Path("/Applications/calibre.app/Contents/MacOS/ebook-convert"),
    Path.home() / "Applications/calibre.app/Contents/MacOS/ebook-convert",
)

INSTALL_HINT = (
    "Calibre provides the conversion engine and was not found.\n\n"
    "Install it with:\n"
    "    brew install --cask calibre\n\n"
    "then register its command-line tools:\n"
    "    /Applications/calibre.app/Contents/MacOS/calibre_postinstall"
)


class CalibreNotFound(RuntimeError):
    """Raised when no ``ebook-convert`` binary could be located."""

    def __init__(self) -> None:
        super().__init__(INSTALL_HINT)


class ConversionFailed(RuntimeError):
    """Raised when ``ebook-convert`` exits non-zero."""

    def __init__(self, message: str, output: str = "") -> None:
        super().__init__(message)
        self.output = output


def find_ebook_convert() -> Path | None:
    """The first usable ``ebook-convert``, or ``None``.

    ``PATH`` is consulted first so a deliberately overridden install wins, but
    it is often useless inside a bundle — the explicit list is the fallback
    that makes the packaged app work at all.
    """
    on_path = shutil.which("ebook-convert")
    if on_path:
        return Path(on_path)
    for candidate in SEARCH_PATHS:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def version(binary: Path | None = None) -> str | None:
    """Calibre's version, as a single line, or ``None`` if undeterminable.

    ``ebook-convert --version`` prints an author credit on a second line, which
    has no business in a status bar.
    """
    binary = binary or find_ebook_convert()
    if binary is None:
        return None
    try:
        result = subprocess.run(
            [str(binary), "--version"],
            capture_output=True,
            text=True,
            timeout=30,
            env=subprocess_env(),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    output = result.stdout.strip() or result.stderr.strip()
    return output.splitlines()[0].strip() if output else None


def subprocess_env() -> dict[str, str]:
    """A child environment safe for non-PyInstaller binaries."""
    env = os.environ.copy()

    for var in ("DYLD_LIBRARY_PATH", "DYLD_FRAMEWORK_PATH", "LD_LIBRARY_PATH"):
        original = env.pop(f"{var}_ORIG", None)
        if original:
            env[var] = original
        elif getattr(sys, "frozen", False):
            env.pop(var, None)

    # Calibre shells out to helpers of its own; give them a PATH worth having.
    path_entries = env.get("PATH", "").split(os.pathsep)
    for extra in ("/opt/homebrew/bin", "/usr/local/bin"):
        if extra not in path_entries:
            path_entries.append(extra)
    env["PATH"] = os.pathsep.join(p for p in path_entries if p)
    return env


def build_command(binary: Path, source: Path, target: Path, extra_args: list[str] | None = None) -> list[str]:
    return [str(binary), str(source), str(target), *(extra_args or [])]


def convert(
    source: Path,
    target: Path,
    *,
    binary: Path | None = None,
    extra_args: list[str] | None = None,
    register: Callable[[subprocess.Popen], None] | None = None,
    on_line: Callable[[str], None] | None = None,
) -> str:
    """Convert ``source`` to ``target``, returning Calibre's combined output.

    Output is read line by line rather than with ``communicate()`` because a
    large book takes minutes and those lines are the only sign it is still
    alive: ``on_line`` receives each one as it arrives. ``register`` is handed
    the live child process, so a caller on another thread can terminate a long
    conversion instead of waiting it out.

    Raises :class:`CalibreNotFound` or :class:`ConversionFailed`.
    """
    binary = binary or find_ebook_convert()
    if binary is None:
        raise CalibreNotFound

    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        process = subprocess.Popen(
            build_command(binary, source, target, extra_args),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=subprocess_env(),
        )
    except OSError as exc:
        raise ConversionFailed(str(exc)) from exc

    if register is not None:
        register(process)

    lines: list[str] = []
    try:
        for line in process.stdout or ():
            lines.append(line)
            if on_line is not None:
                stripped = line.strip()
                if stripped:
                    on_line(stripped)
    finally:
        # Whatever happens above — including on_line raising to cancel the run —
        # the child must not be left running and its pipe must not be left open.
        if process.stdout is not None:
            process.stdout.close()
        if process.poll() is None:
            process.terminate()
        process.wait()

    output = "".join(lines)
    if process.returncode != 0:
        raise ConversionFailed(
            _last_meaningful_line(output) or f"exit code {process.returncode}", output
        )
    if not target.exists():
        raise ConversionFailed("Calibre reported success but wrote no file", output)
    return output


def _last_meaningful_line(output: str) -> str:
    """The most useful-looking line of Calibre's output for an error message.

    Calibre puts the real cause on the last non-empty line for tracebacks, but
    prints progress chatter after it for softer failures — so prefer an
    explicit error line when there is one.
    """
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        return ""
    for line in reversed(lines):
        if any(marker in line for marker in ("Error", "error:", "Exception", "Traceback")):
            return line
    return lines[-1]
