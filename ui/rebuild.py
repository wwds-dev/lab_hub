"""Run the rebuild commands in-app, one after another, into the Check builds window.

Spec `docs/specs/progress-windows.md` §8.5, §8.7. This is the runner that was
`RebuildDialog`, without widgets of its own: the window (`BuildCheckWindow`)
shows what it does.

The build report used to only *hand over* the commands, on the reasoning that a
rebuild takes minutes and you want somewhere to watch it and stop it. This keeps
both of those — live output and a Cancel that kills the running build — without
leaving Lab Hub, which is the whole point of a button that says "Update now".

Each command is its own `cd … && ./build_app.sh`, so they are independent; one
that fails stops the run rather than rebuilding on top of a broken build. They
run through a login shell (`$SHELL -lc`) because that is the environment the
Terminal handoff always assumed — the build scripts reach for `pyinstaller`,
`uv` and friends that a bundle's bare PATH would miss — and with `child_env()`
so a rebuild is not poisoned by our own Qt runtime, exactly as a real launch is.

After a command exits 0, Lab Hub reads that app's installed version itself
(Verify): informational only, it never changes success. Only then are the
stage durations recorded; a failed or cancelled command records nothing.

Each command starts in a session (and so a process group) of its own, and
Cancel stops the whole group: SIGTERM, then SIGKILL after a short grace. A
build tool the script started (PyInstaller, a copy into /Applications) stops
with it instead of finishing on its own after the window says it was stopped.
A step that starts a session of its own (`setsid`, or job control with `set -m`)
leaves the group and is not stopped; no lab build script does that today.
"""

from __future__ import annotations

import codecs
import os
import re
import signal
import time

from PySide6.QtCore import QEventLoop, QObject, QProcess, QProcessEnvironment, QTimer

from lab_hub import durations, launcher, progress

_LINE_END = re.compile(r"\r\n|\n|\r")
STOP_GRACE_S = 2.0  # after SIGTERM, before SIGKILL
HOLD_POLL_MS = 2000  # how often a held command asks again whether it may start


class Skipped(Exception):
    """Raised by a `hold` hook: this command will not run, and that is not a
    failure. The rest of the run goes on (spec self-update §5.3: Update now
    skips Lab Hub when its checkout is not clean on main)."""


def _signal_group(group: int, sig: int) -> bool:
    """Send `sig` to the process group; False if no process is left in it."""
    try:
        os.killpg(group, sig)
    except ProcessLookupError:
        return False
    except OSError:
        return False  # not ours to signal: nothing more to do with it
    return True


class Rebuild(QObject):
    """`Rebuild(commands, window).exec()`, `.succeeded`: RebuildDialog's contract.

    `exec()` returns once the run has ended and the window is closed. Closing
    the window by any route before the run has ended ends it: a running build
    is killed with everything it started, and no further command starts. A
    command that cannot start at all ends the run as failed.
    """

    def __init__(self, commands: list[str], window, *, verify=None, hold=None) -> None:
        super().__init__(window)
        self._window = window
        self._commands = list(commands)
        self._index = 0
        self._cancelled = False
        self._failed = False
        self._ended = False
        self._loop: QEventLoop | None = None
        self._verify = verify or launcher.version
        # Asked before each command starts: a reason means "not yet", and it is
        # asked again every HOLD_POLL_MS (spec self-update §5.2: Lab Hub's own
        # build waits for a running Land). Cancel while held ends the run.
        self._hold = hold
        self._holding: str | None = None
        self.skipped: list[str] = []
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._partial = ""

        self._proc = QProcess(self)
        env = QProcessEnvironment()
        for name, value in launcher.child_env().items():
            env.insert(name, value)
        self._proc.setProcessEnvironment(env)
        self._proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        # Its own session: the shell leads a process group that Cancel can stop whole.
        self._own_group = hasattr(self._proc, "setUnixProcessParameters")
        if self._own_group:
            self._proc.setUnixProcessParameters(QProcess.UnixProcessFlag.CreateNewSession)
        self._proc.readyReadStandardOutput.connect(self._read)
        self._proc.finished.connect(self._finished)
        self._proc.errorOccurred.connect(self._error)

        window.attach(self)
        window.closed.connect(self._maybe_quit)
        window.begin_update()
        # Start once the window is on screen, so the first line has somewhere to land.
        QTimer.singleShot(0, self._start_next)

    @property
    def succeeded(self) -> bool:
        return not self._cancelled and not self._failed and self._index >= len(
            self._commands
        )

    @property
    def running(self) -> bool:
        return self._proc.state() != QProcess.ProcessState.NotRunning

    @property
    def ended(self) -> bool:
        return self._ended

    def exec(self) -> int:
        if not (self._ended and not self._window.isVisible()):
            self._loop = QEventLoop()
            try:
                self._loop.exec()
            finally:
                self._loop = None
        return 0

    def _release_hold(self) -> None:
        if self._holding and self._index < len(self._commands):
            self._window.command_held(self._command, None)
        self._holding = None

    def cancel(self) -> None:
        """Stop the running build and all it started (if one runs), start
        nothing after it, and end the run."""
        if self._ended:
            return
        self._cancelled = True
        self._release_hold()
        if not self.running:
            self._all_done()  # nothing started yet, or nothing left running
            return
        self._window.say("[cancelled — the running build was stopped]")
        self._stop_group()

    def _stop_group(self) -> None:
        """SIGTERM to the command's process group, SIGKILL to whatever is left
        after STOP_GRACE_S. Blocks the GUI thread for at most that long, as the
        old kill-and-wait did."""
        group = int(self._proc.processId())
        if not (self._own_group and group > 0):
            self._proc.kill()
            self._proc.waitForFinished(3000)
            return
        deadline = time.monotonic() + STOP_GRACE_S
        if _signal_group(group, signal.SIGTERM):
            self._proc.waitForFinished(int(STOP_GRACE_S * 1000))
            # The shell has gone; a tool it started may take a moment longer.
            while _signal_group(group, 0) and time.monotonic() < deadline:
                time.sleep(0.02)
            if _signal_group(group, 0):  # only what outlived the grace
                _signal_group(group, signal.SIGKILL)
        if self.running:
            self._proc.kill()
            self._proc.waitForFinished(3000)

    # -- the run --------------------------------------------------------------
    def _shell(self) -> str:
        return os.environ.get("SHELL", "/bin/zsh")

    @property
    def _command(self) -> str:
        return self._commands[self._index]

    def _start_next(self) -> None:
        if self._ended:
            return
        if self._cancelled or self._index >= len(self._commands):
            self._all_done()
            return
        if self._hold is not None:
            try:
                reason = self._hold(self._command)
            except Skipped as skip:
                self._release_hold()
                self.skipped.append(self._command)
                self._window.command_refused(self._command, str(skip))
                self._index += 1
                self._start_next()
                return
            except Exception as error:  # noqa: BLE001 - a failing check holds nothing back silently
                self._release_hold()
                self._failed = True
                self._window.command_refused(self._command, str(error))
                self._all_done()
                return
            if reason:
                # Said once per reason; every poll still counts as activity,
                # so the window does not call a wait a silence.
                self._window.command_held(self._command, reason,
                                          repeat=reason == self._holding)
                self._holding = reason
                QTimer.singleShot(HOLD_POLL_MS, self._start_next)
                return
            self._release_hold()
        self._decoder.reset()
        self._partial = ""
        self._window.command_started(self._command)
        self._proc.start(self._shell(), ["-lc", self._command])

    def _read(self) -> None:
        text = self._partial + self._decoder.decode(bytes(self._proc.readAllStandardOutput()))
        *lines, self._partial = _LINE_END.split(text)
        # Output with no newline (a progress bar) is shown in pieces, not held
        # until it ends: one 2 MB line used to freeze the window.
        while len(self._partial) > progress.LINE_MAX:
            lines.append(self._partial[:progress.LINE_MAX])
            self._partial = self._partial[progress.LINE_MAX:]
        for line in lines:
            self._window.command_output(self._command, line)

    def _flush(self) -> None:
        text = self._partial + self._decoder.decode(b"", final=True)
        self._partial = ""
        for line in _LINE_END.split(text):
            if line:
                self._window.command_output(self._command, line)

    def _finished(self, code: int, _status: object) -> None:
        if self._ended or self._index >= len(self._commands):
            return
        self._read()
        self._flush()
        command = self._command
        if self._cancelled:
            self._window.command_finished(command, ok=False, cancelled=True)
            self._all_done()
            return
        if code != 0:
            self._failed = True
            self._window.command_finished(command, ok=False, code=code)
            self._window.say(f"[stopped — a rebuild exited with code {code}]")
            self._all_done()
            return
        self._window.command_finished(command, ok=True)
        samples = self._window.verified(command, self._read_version(command))
        app = self._window.view.app_for(command)
        if app is not None:
            subject = durations.subject("app", app.key)
            for kind, seconds in samples.items():
                durations.record(subject, kind, seconds)
        self._index += 1
        self._start_next()

    def _error(self, error: QProcess.ProcessError) -> None:
        """A command that cannot start (no such shell, no permission) never
        sends `finished`: without this the run, and `exec()`, waited for good."""
        if error != QProcess.ProcessError.FailedToStart or self._ended:
            return
        if self._index >= len(self._commands):
            return
        command = self._command
        self._failed = True
        self._window.command_finished(command, ok=False, code=None)
        self._window.say(f"[stopped — a rebuild could not start: {self._proc.errorString()}]")
        self._all_done()

    def _read_version(self, command: str) -> str:
        """Verify: what Lab Hub now reads as installed. Never decides success."""
        app = self._window.view.app_for(command)
        if app is None or self._window.lab_root is None:
            return ""
        if command == getattr(self._window.view, "restarts", None):
            return ""  # /Applications still holds the old build until the restart
        try:
            return self._verify(app, self._window.lab_root).text
        except Exception:  # noqa: BLE001 - a version read must not end the run
            return ""

    def _all_done(self) -> None:
        if self._ended:
            return
        self._ended = True
        how = "cancelled" if self._cancelled else "failed" if self._failed else "done"
        self._window.update_ended(how)
        self._maybe_quit()

    def _maybe_quit(self) -> None:
        if self._loop is not None and self._ended and not self._window.isVisible():
            self._loop.quit()
