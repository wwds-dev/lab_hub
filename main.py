#!/usr/bin/env python3
"""Lab Hub — entry point.

    python main.py              launch the app
    python main.py --selftest   check a build's wiring and exit

The self-test exists because a packaged .app fails in ways the source tree
cannot: the icon may not have made it into the bundle, settings may resolve to
a path inside the bundle (which a reinstall wipes), and Pillow's binary
extension is exactly the kind of dependency PyInstaller can miss. Run it
against the built binary before trusting the build.
"""

import sys


# A frozen app has no Python interpreter with which to run ``-m``. Narrator
# re-invokes the Lab Hub executable with this sentinel so conversion still runs
# in a separate, stoppable process and keeps the UI responsive.
if "--narrator-worker" in sys.argv:
    sys.argv.remove("--narrator-worker")
    from lab_hub.tools.narrator.converter import main as _narrator_main

    _narrator_main()


def _probe_conversion() -> tuple[bool, str]:
    """Convert a throwaway file end to end and describe the outcome."""
    import tempfile
    from pathlib import Path

    from lab_hub.tools.convert import formats, runner
    from lab_hub.tools.convert.jobs import Job, Status

    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "selftest.txt"
        source.write_text("Chapter 1\n\nRound-trip probe.\n", encoding="utf-8")
        job = Job(source=source, target=Path(tmp) / "selftest.epub")
        runner.execute(job, formats.OUTPUT_BY_EXT["epub"])
        return job.status is Status.DONE, f"{job.status.value} {job.detail}".strip()


def _probe_child_launch(lab_root) -> tuple[bool | None, str]:
    """Start a real PySide6 process the way the Apps tab does.

    Inspecting the environment proves we *intend* to hand a child a clean one.
    This proves the child actually survives, which is the thing that was broken:
    a launched app inherited this bundle's Qt paths, loaded our cocoa plugin
    against its own QtGui, and was killed by qFatal inside QApplication().

    Needs a second Python that has its own PySide6 — one of the lab projects'
    venvs. Returns (None, reason) when there is no such interpreter to probe
    with, which is not a failure, just nothing to say.
    """
    import subprocess

    from lab_hub import launcher

    python = None
    for app in launcher.APPS:
        project = launcher.source_dir(app, lab_root)
        if project is not None:
            python = launcher.venv_python(project)
            if python is not None:
                break
    if python is None:
        return None, "no project venv to probe with"

    # A QApplication is the whole test — that is where the abort happened.
    code = "from PySide6.QtWidgets import QApplication; QApplication([])"
    try:
        result = subprocess.run(
            [str(python), "-c", code],
            env=launcher.child_env(),
            capture_output=True,
            text=True,
            timeout=90,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return False, f"could not run the probe ({error})"

    if result.returncode == 0:
        return True, f"a real Qt child started under {python.parent.parent.parent.name}"

    output = (result.stderr or result.stdout).strip().splitlines()
    if any("No module named 'PySide6'" in line for line in output):
        return None, "the probe interpreter has no PySide6"

    # Qt prints several lines and the diagnosis is rarely the last one — the
    # useful sentence is the one naming the failure, not the trailing list of
    # available plugins.
    telling = next(
        (
            line.strip()
            for line in output
            if "failed to start" in line or "Could not load" in line
        ),
        output[-1].strip() if output else f"exit {result.returncode}",
    )
    return False, f"a launched Qt app would die at startup: {telling}"


def selftest() -> int:
    from lab_hub import APP_NAME, asset_path, config, launcher

    frozen = getattr(sys, "frozen", False)
    icon = asset_path("icon.icns")
    tray_icon = asset_path("tray.png")
    settings = config.load()
    lab_root = settings.resolved_lab_root()

    print(f"{APP_NAME} self-test")
    print(f"  frozen bundle:   {frozen}")
    print(f"  icon asset:      {icon} ({'found' if icon.exists() else 'MISSING'})")
    print(f"  menu bar icon:   {tray_icon} ({'found' if tray_icon.exists() else 'MISSING'})")
    print(f"  config path:     {config.CONFIG_PATH}")
    print(f"  lab root:        {lab_root}")

    # A frozen bundle exports its own Qt and Python paths into the process
    # environment. A launched app that inherits them loads our Qt plugins
    # against its own Qt and aborts inside QApplication() — invisible from
    # source, because from source there is nothing to inherit.
    import os

    stripped = sorted(set(os.environ) - set(launcher.child_env()))
    print(f"  child env strips: {', '.join(stripped) if stripped else 'nothing'}")

    problems = []
    if not icon.exists():
        problems.append("icon asset missing from the bundle")
    if not tray_icon.exists():
        problems.append("menu bar icon missing from the bundle")
    if frozen and ".app/" in str(config.CONFIG_PATH):
        problems.append("config would be written inside the .app bundle")

    # Guards the fix for the crash where a launched app inherited our Qt paths.
    leaked = [
        name
        for name in ("QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH")
        if name in os.environ and name in launcher.child_env()
    ]
    if leaked:
        problems.append(
            f"launched apps would inherit our Qt paths ({', '.join(leaked)}) "
            "and abort at startup"
        )

    try:
        from PIL import Image  # noqa: F401

        print("  pillow:          ok")
    except ImportError as error:
        print("  pillow:          MISSING")
        problems.append(f"Pillow did not import: {error}")

    try:
        from lab_hub.tools.narrator import converter as narrator_converter

        print(f"  narrator:        ok ({narrator_converter.TTS_MODEL})")
    except ImportError as error:
        print("  narrator:        MISSING DEPENDENCY")
        problems.append(f"Narrator did not import: {error}")

    from lab_hub.tools import convert

    binary = convert.converter_path()
    print(f"  ebook-convert:   {binary or 'not installed (Convert tab will say so)'}")
    if binary:
        # A real conversion, not just a lookup: a bundled app gets a bare PATH
        # and a rewritten dynamic-linker environment, and both break the
        # subprocess rather than the import.
        ok, detail = _probe_conversion()
        print(f"  txt -> epub:     {detail}")
        if not ok:
            problems.append(f"round-trip conversion failed: {detail}")

    launched, detail = _probe_child_launch(lab_root)
    print(f"  child Qt app:    {'ok — ' + detail if launched else detail}")
    if launched is False:
        problems.append(detail)

    # Reported but never fatal: whether the other apps are installed says
    # nothing about whether this build is sound.
    print("  apps:")
    for app in launcher.APPS:
        state, detail = launcher.status(app, lab_root)
        print(f"    {app.name:<24} {state:<10} {detail}")

    if problems:
        print("\nFAILED:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print("\nOK")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())

    from ui.main_window import run

    sys.exit(run())
