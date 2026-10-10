"""Shared builders for the ``test_jobs_*`` files: fake job dirs on disk.

The autouse ``_isolate_control_plane`` fixture points ``_store.JOBS_DIR`` at
``tmp_path``; everything here reaches it through the module attribute.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from steam_backlog_enforcer.jobs import _store
from steam_backlog_enforcer.jobs._events import (
    PID_NAME,
    REQUEST_NAME,
    RESULT_NAME,
    EventWriter,
)

if TYPE_CHECKING:
    from pathlib import Path

JOB_ID = "20261010T120000000000Z-abcdef"


def make_job(
    command: str = "scan",
    *,
    job_id: str = JOB_ID,
    states: tuple[str, ...] = ("queued", "running"),
    pid: str | None = None,
    params: dict[str, object] | None = None,
) -> Path:
    """Write a job dir with a request and one ``state`` event per state."""
    path = _store.JOBS_DIR / job_id
    path.mkdir(parents=True)
    request = {
        "command": command,
        "params": params or {},
        "created_at": "2026-10-10T12:00:00Z",
    }
    (path / REQUEST_NAME).write_text(json.dumps(request) + "\n", encoding="utf-8")
    writer = EventWriter(path)
    for state in states:
        writer.emit("state", state=state)
    if pid is not None:
        (path / PID_NAME).write_text(pid, encoding="utf-8")
    return path


def write_result(path: Path, **fields: object) -> None:
    """Write ``result.json`` the way a finished job does."""
    (path / RESULT_NAME).write_text(json.dumps(fields), encoding="utf-8")
