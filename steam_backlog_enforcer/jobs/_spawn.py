"""Start a job's detached process, and notice at once when it never started.

Under systemd the job runs through ``systemd-run --user --scope``. When that
cannot register the scope (no user bus, a bad ``XDG_RUNTIME_DIR``) it exits
straight away and the job never runs — yet ``Popen`` succeeded, so without a
check the job would sit ``queued`` until the dead-pid reconciler failed it
30 s later. :func:`spawn_job` waits the few milliseconds it takes to see
either the job's own interpreter (``systemd-run`` execs into it in place) or
the launcher's exit, and fails the job with the launcher's output instead.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Final

from steam_backlog_enforcer.config import _atomic_write
from steam_backlog_enforcer.jobs._errors import JobError
from steam_backlog_enforcer.jobs._events import (
    OUTPUT_NAME,
    RESULT_NAME,
    EventWriter,
    read_events,
)

LOCK_FD_ENV: Final = "SBE_JOB_LOCK_FD"
_PACKAGE_ROOT = Path(__file__).resolve().parents[2]
# How long to wait for the launcher to exec into the job (or die). A healthy
# systemd-run takes milliseconds; past this the reconciler takes over.
_CONFIRM_SECONDS: Final = 3.0
_POLL_SECONDS: Final = 0.02
_OUTPUT_TAIL_CHARS: Final = 600
_EXIT_SPAWN_FAILED: Final = 1


def _spawn_argv(path: Path) -> list[str]:
    """The job subprocess command line.

    Under systemd (the web server's user unit) the job is moved into its own
    transient scope, so restarting the server's unit — which kills its
    whole cgroup — does not take running jobs down with it.
    """
    argv = [sys.executable, "-m", "steam_backlog_enforcer.jobs", "run", str(path)]
    systemd_run = shutil.which("systemd-run")
    if os.environ.get("INVOCATION_ID") and systemd_run:
        unit = f"sbe-job-{path.name.lower()}"
        argv = [systemd_run, "--user", "--scope", "--quiet", "--collect",
                f"--unit={unit}", "--", *argv]  # fmt: skip
    return argv


def _is_job_interpreter(pid: int) -> bool:
    """Whether *pid* is already the job's Python (not still the launcher)."""
    try:
        argv0 = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0", 1)[0]
    except OSError:
        return False
    return argv0 == os.fsencode(sys.executable)


def _output_tail(path: Path) -> str:
    """The end of the job's captured stdout/stderr, for the failure log."""
    try:
        text = (path / OUTPUT_NAME).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text.strip()[-_OUTPUT_TAIL_CHARS:]


def _fail_unstarted(path: Path, summary: str) -> JobError:
    """Fail a job whose process never started; return the error to raise."""
    tail = _output_tail(path)
    writer = EventWriter(path)
    writer.emit("log", level="error", message=f"{summary}\n{tail}".strip())
    writer.emit("result", ok=False, summary=summary)
    result = {"ok": False, "summary": summary, "state": "failed"}
    _atomic_write(
        path / RESULT_NAME,
        json.dumps(result | {"exit_code": _EXIT_SPAWN_FAILED}, indent=2) + "\n",
    )
    writer.emit("state", state="failed")
    return JobError(f"{summary} {tail}".strip(), code="op_failed")


def _confirm_started(proc: subprocess.Popen[bytes], path: Path) -> None:
    """Return once the job runs; raise if the launcher died before it did.

    A job that already finished (fast read-only commands can, without
    systemd) wrote its own result, so an exit with a result is a success.

    Raises:
        JobError: ``op_failed`` when the launcher exited without the job
            ever running.
    """
    deadline = time.monotonic() + _CONFIRM_SECONDS
    while time.monotonic() < deadline:
        code = proc.poll()
        if code is not None:
            if any(e.get("type") == "result" for e in read_events(path)):
                return
            msg = f"The job process could not be started (launcher exit {code})."
            raise _fail_unstarted(path, msg)
        if _is_job_interpreter(proc.pid):
            return
        time.sleep(_POLL_SECONDS)


def spawn_job(path: Path, lock_fd: int | None) -> int:
    """Start the detached job process for *path* and return its pid.

    Args:
        path: The prepared job directory.
        lock_fd: The held one-mutating-job lock, handed to the child.

    Raises:
        JobError: ``op_failed`` when the process could not be started; the
            job is already marked ``failed`` with the reason in its log.
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(_PACKAGE_ROOT), env.get("PYTHONPATH", "")) if p
    )
    if lock_fd is not None:
        env[LOCK_FD_ENV] = str(lock_fd)
    try:
        with (path / OUTPUT_NAME).open("ab") as out:
            proc = subprocess.Popen(
                _spawn_argv(path),
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=out,
                cwd=_PACKAGE_ROOT,
                env=env,
                start_new_session=True,
                pass_fds=() if lock_fd is None else (lock_fd,),
            )
    except OSError as exc:
        msg = f"The job process could not be started: {exc}."
        raise _fail_unstarted(path, msg) from exc
    _confirm_started(proc, path)
    return proc.pid
