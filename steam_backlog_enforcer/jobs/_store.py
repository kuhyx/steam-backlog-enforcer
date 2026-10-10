"""Create, prune and start jobs; enforce one mutating job at a time.

The ``busy`` check is a ``flock`` on ``jobs/.mutating.lock``. The server
takes it non-blocking *before* spawning (:mod:`._spawn`) and hands the open
descriptor to the child (``pass_fds``), so the child holds the lock for
exactly its own lifetime and there is no window between "nobody is running"
and "I am". The request is validated, lock gate included, *before* the lock
is taken, so a locked command is refused as ``locked``, never ``busy``.
"""

from __future__ import annotations

from datetime import UTC, datetime
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import shutil
from typing import TYPE_CHECKING, Final

from steam_backlog_enforcer._command_gate import lock_reason
from steam_backlog_enforcer._command_params import (
    InvalidParamsError,
    validate_params,
)
from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.jobs._errors import JobError, PrivilegedViaDaemonError
from steam_backlog_enforcer.jobs._events import (
    PID_NAME,
    REQUEST_NAME,
    TERMINAL_STATES,
    EventWriter,
    now_iso,
    read_events,
)
from steam_backlog_enforcer.jobs._spawn import spawn_job
from steam_backlog_enforcer.jobs._specs import JOB_FLAGS, is_privileged

if TYPE_CHECKING:
    from collections.abc import Mapping

JOBS_DIR = Path.home() / ".local" / "state" / "steam-backlog-enforcer" / "jobs"
MAX_JOBS: Final = 50
LOCK_NAME: Final = ".mutating.lock"
# Microseconds since 2026-10: two jobs created in the same second still
# sort by creation. Ids without them (older history) remain valid.
_ID_PATTERN = re.compile(r"^\d{8}T\d{6}(?:\d{6})?Z-[0-9a-f]{6}$")


def job_dir(job_id: str) -> Path:
    """Resolve a job id to its directory, refusing anything path-like.

    Raises:
        JobError: ``not_found`` for a malformed or unknown id.
    """
    path = JOBS_DIR / job_id
    if not _ID_PATTERN.fullmatch(job_id) or not (path / REQUEST_NAME).is_file():
        msg = f"No such job: {job_id!r}"
        raise JobError(msg, code="not_found")
    return path


def new_job_id() -> str:
    """A sortable id: UTC timestamp to the microsecond, plus a random suffix.

    Sorting by name is creation order (newest-first lists, oldest-first
    pruning); the suffix only keeps simultaneous ids distinct.
    """
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{stamp}-{secrets.token_hex(3)}"


def is_terminal(path: Path) -> bool:
    """Whether the job in *path* has reached a final state."""
    states = [e.get("state") for e in read_events(path) if e.get("type") == "state"]
    return bool(states) and states[-1] in TERMINAL_STATES


def prune(keep: int = MAX_JOBS) -> None:
    """Delete the oldest finished job dirs so at most *keep* remain.

    A job that is still running is never deleted, however old.
    """
    if not JOBS_DIR.is_dir():
        return
    dirs = sorted(
        (p for p in JOBS_DIR.iterdir() if _ID_PATTERN.fullmatch(p.name)),
        key=lambda p: p.name,
    )
    for path in dirs[: max(0, len(dirs) - keep)]:
        if is_terminal(path):
            shutil.rmtree(path, ignore_errors=True)


def acquire_mutating_lock() -> int:
    """Take the one-mutating-job lock and return its open descriptor.

    Raises:
        JobError: ``busy`` when another mutating job holds it.
    """
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    fd = os.open(JOBS_DIR / LOCK_NAME, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        msg = "Another job that changes state is running."
        raise JobError(msg, code="busy") from None
    return fd


def _check_request(command: str, params: Mapping[str, object]) -> dict[str, object]:
    """Validate a request the way the server must before creating a job.

    Raises:
        JobError: ``unknown_command``, ``invalid_params`` or ``locked``.
        PrivilegedViaDaemonError: The command belongs to the root daemon.
    """
    if command not in JOB_FLAGS:
        msg = f"{command!r} does not run as a job."
        raise JobError(msg, code="unknown_command")
    try:
        clean = validate_params(command, params)
    except InvalidParamsError as exc:
        raise JobError(str(exc), code="invalid_params") from exc
    if is_privileged(command, clean):
        raise PrivilegedViaDaemonError(command)
    reason = lock_reason(command, Config.load(), State.load())
    if reason is not None:
        raise JobError(reason, code="locked")
    return dict(clean)


def prepare_job(
    command: str,
    params: Mapping[str, object],
    *,
    confirm_phrase: str | None = None,
) -> Path:
    """Validate a request and write its job dir, without starting it.

    Returns:
        The new job directory, holding ``request.json`` and a ``queued`` event.
    """
    return _write_job(
        command, _check_request(command, params), confirm_phrase=confirm_phrase
    )


def _write_job(
    command: str, clean: Mapping[str, object], *, confirm_phrase: str | None
) -> Path:
    """Write the job dir for an already-validated request."""
    prune(MAX_JOBS - 1)
    path = JOBS_DIR / new_job_id()
    path.mkdir(parents=True, mode=0o700)
    request: dict[str, object] = {
        "command": command,
        "params": dict(clean),
        "created_at": now_iso(),
    }
    if confirm_phrase is not None:
        request["confirm_phrase"] = confirm_phrase
    (path / REQUEST_NAME).write_text(json.dumps(request) + "\n", encoding="utf-8")
    EventWriter(path).emit("state", state="queued")
    return path


def create_job(
    command: str,
    params: Mapping[str, object],
    *,
    confirm_phrase: str | None = None,
) -> str:
    """Create and start a job; return its id.

    Args:
        command: Canonical command name.
        params: Raw params from ``JobRequest.params``.
        confirm_phrase: ``JobRequest.confirm_phrase``; re-checked by the job.

    Raises:
        JobError: ``unknown_command``, ``invalid_params``, ``locked``,
            ``busy``, or ``op_failed`` when the process could not be started
            (the job is then already marked ``failed``).
        PrivilegedViaDaemonError: Route this request to the daemon instead.
    """
    clean = _check_request(command, params)
    lock_fd = acquire_mutating_lock() if JOB_FLAGS[command].mutating else None
    try:
        path = _write_job(command, clean, confirm_phrase=confirm_phrase)
        pid = spawn_job(path, lock_fd)
        (path / PID_NAME).write_text(f"{pid}\n", encoding="utf-8")
    finally:
        if lock_fd is not None:
            os.close(lock_fd)  # The child keeps its inherited copy.
    return path.name
