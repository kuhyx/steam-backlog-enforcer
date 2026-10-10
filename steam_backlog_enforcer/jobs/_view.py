"""Read jobs back for the API: the ``Job`` objects and their event streams.

A ``Job`` is never stored; it is folded from ``request.json`` and the event
log every time, so it cannot disagree with the events the UI streams.

A job whose process died without writing a result (killed, OOM, machine
reboot) would otherwise read as "running" forever. :func:`read_job` notices
the dead pid and appends the ``failed`` verdict on the job's behalf.
"""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any, Final

from steam_backlog_enforcer.jobs import _store
from steam_backlog_enforcer.jobs._errors import JobError
from steam_backlog_enforcer.jobs._events import (
    PID_NAME,
    REQUEST_NAME,
    RESULT_NAME,
    TERMINAL_STATES,
    EventWriter,
    read_events,
)

# A fresh job has no pid file for the instant between mkdir and spawn.
_SPAWN_GRACE_SECONDS: Final = 30
_PROGRESS_KEYS: Final = ("step", "total", "label", "item", "eta_seconds")


def _pid_alive(path: Path) -> bool | None:
    """Whether the job's own process is running; ``None`` if unknown yet.

    Checks the command line too, so a recycled pid is not mistaken for the
    job (a zombie has an empty one and counts as dead).
    """
    try:
        pid = int((path / PID_NAME).read_text(encoding="utf-8").strip())
    except FileNotFoundError, ValueError:
        return None
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return False
    return b"steam_backlog_enforcer.jobs" in cmdline and path.name.encode() in cmdline


def pid_of(path: Path) -> int | None:
    """The live job process's pid, or ``None`` if it is not running."""
    if not _pid_alive(path):
        return None
    return int((path / PID_NAME).read_text(encoding="utf-8").strip())


def _reconcile(path: Path, state: str) -> None:
    """Fail a non-terminal job whose process is gone."""
    if state in TERMINAL_STATES:
        return
    alive = _pid_alive(path)
    if alive is None:
        age = time.time() - (path / REQUEST_NAME).stat().st_mtime
        if age < _SPAWN_GRACE_SECONDS:
            return
    elif alive:
        return
    summary = "The job process exited without reporting a result."
    writer = EventWriter(path)
    writer.emit("result", ok=False, summary=summary)
    writer.emit("state", state="failed")


def _fold(path: Path) -> dict[str, Any]:
    """Build the contract's ``Job`` object from one job dir."""
    request = json.loads((path / REQUEST_NAME).read_text(encoding="utf-8"))
    job: dict[str, Any] = {
        "id": path.name,
        "command": request["command"],
        "params": request.get("params", {}),
        "state": "queued",
        "created_at": request.get("created_at"),
        "started_at": None,
        "ended_at": None,
        "exit_code": None,
        "progress": None,
        "summary": None,
    }
    for event in read_events(path):
        kind = event.get("type")
        if kind == "state":
            job["state"] = event["state"]
            if event["state"] == "running" and job["started_at"] is None:
                job["started_at"] = event["ts"]
            if event["state"] in TERMINAL_STATES:
                job["ended_at"] = event["ts"]
        elif kind == "progress":
            job["progress"] = {k: event[k] for k in _PROGRESS_KEYS if k in event}
        elif kind == "result":
            job["summary"] = event.get("summary")
    try:
        result = json.loads((path / RESULT_NAME).read_text(encoding="utf-8"))
        job["exit_code"] = result.get("exit_code")
    except FileNotFoundError, ValueError:
        pass
    return job


def read_job(job_id: str) -> dict[str, Any]:
    """Return one ``Job``, failing it first if its process died.

    Raises:
        JobError: ``not_found`` for an unknown id.
    """
    path = _store.job_dir(job_id)
    job = _fold(path)
    if job["state"] not in TERMINAL_STATES:
        _reconcile(path, job["state"])
        job = _fold(path)
    return job


def list_jobs() -> list[dict[str, Any]]:
    """Return every kept ``Job``, newest first (at most ``MAX_JOBS``)."""
    if not _store.JOBS_DIR.is_dir():
        return []
    ids = sorted(
        (p.name for p in _store.JOBS_DIR.iterdir() if (p / REQUEST_NAME).is_file()),
        reverse=True,
    )
    jobs = []
    for job_id in ids[: _store.MAX_JOBS]:
        try:
            jobs.append(read_job(job_id))
        except JobError, OSError, ValueError, KeyError:
            continue  # A half-written or hand-damaged dir is not fatal.
    return jobs


def read_job_events(job_id: str, after_seq: int = 0) -> list[dict[str, Any]]:
    """Return a job's events after *after_seq*, for the SSE stream.

    Raises:
        JobError: ``not_found`` for an unknown id.
    """
    path = _store.job_dir(job_id)
    read_job(job_id)  # Reconcile first, so a dead job's stream can end.
    return read_events(path, after_seq)
