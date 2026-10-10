"""What runs inside a job subprocess: one command, start to result.

``python -m steam_backlog_enforcer.jobs run <job_dir>`` lands here. The
runner passes the same lock gate as the CLI, runs the command with the job's
output sink, progress reporter and prompter installed, and always ends with
exactly one ``result`` event, ``result.json`` and a final ``state`` event —
whether the command succeeded, refused, raised, exited or was cancelled.
"""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
import fcntl
import json
import logging
import os
import signal
from typing import TYPE_CHECKING, Any, Final

from steam_backlog_enforcer._command_gate import lock_reason
from steam_backlog_enforcer._echo import routed_echo
from steam_backlog_enforcer._progress import use_progress
from steam_backlog_enforcer._prompter import PromptAbortedError, use_prompter
from steam_backlog_enforcer.config import Config, State, _atomic_write
from steam_backlog_enforcer.jobs import _spawn, _store
from steam_backlog_enforcer.jobs._errors import (
    JobCancelledError,
    JobError,
    PrivilegedViaDaemonError,
)
from steam_backlog_enforcer.jobs._events import (
    PID_NAME,
    REQUEST_NAME,
    RESULT_NAME,
    EventWriter,
)
from steam_backlog_enforcer.jobs._job_io import EventLogHandler, JobLogSink, JobProgress
from steam_backlog_enforcer.jobs._job_prompter import JobPrompter
from steam_backlog_enforcer.jobs._registry import HANDLERS
from steam_backlog_enforcer.jobs._specs import JOB_FLAGS, JobFlags
from steam_backlog_enforcer.main._gate import enforce_gate

if TYPE_CHECKING:
    from pathlib import Path
    from types import FrameType

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_REFUSED = 2
EXIT_CANCELLED = 130
# The job lock fd is ours alone: anything the job spawns must not keep the
# lock alive after we exit. (``os.set_inheritable`` takes it positionally.)
_CHILDREN_INHERIT_LOCK: Final = False


@dataclass
class _Outcome:
    """How the job ended; becomes the ``result`` event and ``result.json``."""

    state: str
    summary: str
    exit_code: int
    data: Any = None

    @property
    def ok(self) -> bool:
        """Whether the command did what was asked."""
        return self.state == "succeeded"


def _failed(summary: str, exit_code: int = EXIT_FAILED) -> _Outcome:
    """A failed outcome."""
    return _Outcome("failed", summary, exit_code)


def _hold_lock(flags: JobFlags) -> int | None:
    """Hold the one-mutating-job lock for the life of this process.

    Spawned by the server, the lock is already ours (inherited descriptor);
    run by hand, it is taken here. Either way it is made non-inheritable so
    a program the job starts (Steam) cannot keep it after the job ends.

    The inherited descriptor is checked against the lock file itself, not
    trusted by number: were it closed or reused on the way in (a wrapper like
    ``systemd-run``), the busy guarantee would silently vanish.

    Raises:
        JobError: ``busy`` when another job holds the lock, or the inherited
            descriptor is not the lock file.
    """
    if not flags.mutating:
        return None
    inherited = os.environ.pop(_spawn.LOCK_FD_ENV, None)
    if inherited is None:
        fd = _store.acquire_mutating_lock()
    else:
        fd = int(inherited)
        lock_file = (_store.JOBS_DIR / _store.LOCK_NAME).stat()
        held = os.fstat(fd)
        if (held.st_dev, held.st_ino) != (lock_file.st_dev, lock_file.st_ino):
            msg = "The inherited job lock is not the lock file; refusing to run."
            raise JobError(msg, code="busy")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # Ours already: no-op.
    os.set_inheritable(fd, _CHILDREN_INHERIT_LOCK)
    return fd


def _on_sigterm(*, cancellable: bool) -> None:
    """Install the SIGTERM policy: cancel if that is safe, else ignore it.

    The handler does no I/O: a signal landing mid-``emit`` would otherwise
    deadlock on the event writer's own lock.
    """

    def cancel(_signum: int, _frame: FrameType | None) -> None:
        raise JobCancelledError

    signal.signal(signal.SIGTERM, cancel if cancellable else signal.SIG_IGN)


def _completed(sink: JobLogSink, data: object = None) -> _Outcome:
    """The outcome of a command that returned (or exited 0) normally.

    Many commands report a failure by printing ``Error: ...`` and returning;
    such a run is a failure, with that line as its summary.
    """
    sink.flush()
    if sink.last_error is not None:
        return _failed(sink.last_error)
    return _Outcome("succeeded", sink.last_line or "Done.", EXIT_OK, data)


def _run_command(
    job_dir: Path, writer: EventWriter, sink: JobLogSink, request: dict[str, Any]
) -> _Outcome:
    """Gate and run the requested command under the job's I/O adapters."""
    command = str(request["command"])
    params = dict(request.get("params", {}))
    flags, job = JOB_FLAGS.get(command), HANDLERS.get(command)
    if flags is None or job is None:
        return _failed(f"{command!r} does not run as a job.", EXIT_REFUSED)
    _hold_lock(flags)
    writer.emit("state", state="running")
    progress = JobProgress(writer)
    prompter = JobPrompter(writer, job_dir, preset_phrase=request.get("confirm_phrase"))
    handler = EventLogHandler(writer)
    with ExitStack() as stack:
        stack.enter_context(routed_echo(sink))
        stack.enter_context(use_progress(progress))
        stack.enter_context(use_prompter(prompter))
        logging.getLogger().addHandler(handler)
        stack.callback(logging.getLogger().removeHandler, handler)
        _on_sigterm(cancellable=flags.cancellable)
        stack.callback(signal.signal, signal.SIGTERM, signal.SIG_IGN)

        config = Config.load()
        try:
            enforce_gate(command, config)
        except SystemExit:
            # The gate already printed its banner (now log events); the
            # summary is the one-line form of the same refusal.
            sink.flush()
            reason = lock_reason(command, config, State.load())
            return _failed(reason or "Refused by the lock gate.", EXIT_REFUSED)
        try:
            data = job(params, progress, prompter)
        except SystemExit as exc:
            if exc.code in {0, None}:
                return _completed(sink)
            sink.flush()
            return _failed(sink.last_line or f"Exited with status {exc.code}.")
        return _completed(sink, data)


def _finish(job_dir: Path, writer: EventWriter, outcome: _Outcome) -> None:
    """Write the single result: event, ``result.json``, then final state."""
    signal.signal(signal.SIGTERM, signal.SIG_IGN)  # Never die half-written.
    fields: dict[str, Any] = {"ok": outcome.ok, "summary": outcome.summary}
    if outcome.data is not None:
        fields["data"] = json.loads(json.dumps(outcome.data, default=str))
    writer.emit("result", **fields)
    result = fields | {"state": outcome.state, "exit_code": outcome.exit_code}
    _atomic_write(job_dir / RESULT_NAME, json.dumps(result, indent=2) + "\n")
    writer.emit("state", state=outcome.state)


def run_job(job_dir: Path) -> int:
    """Run the job in *job_dir* to completion and return its exit code."""
    job_dir = job_dir.resolve()
    writer = EventWriter(job_dir)
    sink = JobLogSink(writer)
    (job_dir / PID_NAME).write_text(f"{os.getpid()}\n", encoding="utf-8")
    try:
        request = json.loads((job_dir / REQUEST_NAME).read_text(encoding="utf-8"))
        outcome = _run_command(job_dir, writer, sink, request)
    except JobCancelledError, KeyboardInterrupt:
        sink.flush()
        outcome = _Outcome("cancelled", "Cancelled.", EXIT_CANCELLED)
    except PromptAbortedError as exc:
        outcome = _failed(str(exc) or "Aborted.")
    except JobError as exc:
        outcome = _failed(exc.message, EXIT_REFUSED)
    except PrivilegedViaDaemonError as exc:
        outcome = _failed(str(exc), EXIT_REFUSED)
    except Exception as exc:
        logger.exception("Job %s crashed", job_dir.name)
        outcome = _failed(f"{type(exc).__name__}: {exc}")
    except BaseException as exc:  # SystemExit from outside a handler, etc.
        logger.exception("Job %s stopped", job_dir.name)
        outcome = _failed(f"{type(exc).__name__}: {exc}")
    _finish(job_dir, writer, outcome)
    return outcome.exit_code
