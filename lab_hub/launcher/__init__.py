"""Finding, checking and starting the standalone apps.

Three parts, one name. Callers keep writing `launcher.X`:

* `registry` — `ExternalApp` and which apps exist, read from `lab_hub/apps.toml`
  and re-read by `reload()` (the window's Refresh);
* `state` — where an app is, whether it is up, its version, its build status
  and whether it could start (`readiness`);
* `control` — launching, stopping and raising, and the child environment.

The old group constants (`SUITES`, `APPS`, `MENU_BAR_APPS` …) are answered from
the list in force each time they are read, never frozen at import.

Setting an attribute here also sets it in whichever part defines it, so
`monkeypatch.setattr(launcher, "APPLICATIONS", …)` still reaches the code that
reads it. Without that a patch would land on this facade alone and the function
it was aimed at would go on reading its own module's value.
"""

from __future__ import annotations

import os  # noqa: F401 - re-exported: tests patch launcher.os.killpg
import shutil  # noqa: F401 - re-exported: tests patch launcher.shutil.which
import subprocess  # noqa: F401 - re-exported: tests patch launcher.subprocess.run
import sys
import types

from . import control, registry, state
from .control import (  # noqa: F401
    INHERITED_VARS,
    STARTUP_GRACE_SECONDS,
    LaunchError,
    _log_tail,
    bring_to_front,
    child_env,
    is_launcher_bundle,
    launch,
    launch_log,
    open_terminal,
    open_url,
    reveal,
    server_pids,
    startup_log_hint,
    stop,
)
from .registry import (  # noqa: F401
    GROUPS,
    ExternalApp,
    Registry,
    RegistryError,
    current,
    reload,
)
from .state import (  # noqa: F401
    APPLICATIONS,
    BUILD_INFO_NAME,
    BUILD_SCRIPTS,
    INSTALL_FLAG,
    NO_WINDOW_FLAGS,
    PROJECT_ROOT_FILE,
    SERVE_PROBE_SECONDS,
    BuildStatus,
    Presence,
    Readiness,
    Version,
    _COUNT_CACHE,
    _bundle_executable_path,
    _commit_count,
    _head_stamp,
    _major,
    _plist_version,
    _stamped_build,
    _stamped_version,
    build_report,
    build_script,
    build_status,
    bundle_executable,
    bundle_marker,
    bundle_path,
    bundle_runs_checkout,
    can_bring_to_front,
    checkout_marker,
    checkout_version,
    dirty_checkout,
    hands_off_and_exits,
    install_command,
    is_running,
    launch_is_observable,
    presence,
    process_table,
    readiness,
    recorded_project_root,
    running_markers,
    serving,
    source_dir,
    status,
    venv_python,
    version,
)

_PARTS = (registry, state, control)


def __getattr__(name: str):
    # SUITES, APPS and the rest: the list in force, not a copy from import.
    return registry.__getattr__(name)


class _Facade(types.ModuleType):
    def __setattr__(self, name: str, value) -> None:
        super().__setattr__(name, value)
        for part in _PARTS:
            if name in vars(part):
                setattr(part, name, value)


sys.modules[__name__].__class__ = _Facade
