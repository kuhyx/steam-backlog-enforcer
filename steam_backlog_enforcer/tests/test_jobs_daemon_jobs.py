"""Tests for ``jobs._daemon_jobs``: daemon ops recorded as finished jobs."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from steam_backlog_enforcer.jobs import _daemon_jobs, _store
from steam_backlog_enforcer.jobs._events import REQUEST_NAME, RESULT_NAME, read_events
from steam_backlog_enforcer.jobs._view import read_job

if TYPE_CHECKING:
    from pathlib import Path


def _record(
    *,
    ok: bool = True,
    exit_code: int = _daemon_jobs.EXIT_OK,
    data: dict[str, object] | None = None,
) -> str:
    return _daemon_jobs.record_daemon_job(
        "unblock",
        {"minutes": 5},
        created_at="2026-10-10T12:00:00Z",
        outcome=_daemon_jobs.DaemonOutcome(
            ok=ok,
            summary="Store unblocked." if ok else "Daemon refused.",
            exit_code=exit_code,
            data=data,
        ),
    )


def _dir(job_id: str) -> Path:
    return _store.JOBS_DIR / job_id


class TestRecordDaemonJob:
    """The files a daemon job leaves behind."""

    def test_success_writes_full_sequence(self) -> None:
        """queued -> running -> log -> result -> succeeded, plus result.json."""
        path = _dir(_record())
        events = read_events(path)
        assert [e["type"] for e in events] == [
            "state",
            "state",
            "log",
            "result",
            "state",
        ]
        assert [e.get("state") for e in events if e["type"] == "state"] == [
            "queued",
            "running",
            "succeeded",
        ]
        assert events[2]["level"] == "info"
        request = json.loads((path / REQUEST_NAME).read_text(encoding="utf-8"))
        assert request["via"] == "daemon"
        assert request["params"] == {"minutes": 5}
        result = json.loads((path / RESULT_NAME).read_text(encoding="utf-8"))
        assert result["state"] == "succeeded"
        assert result["exit_code"] == 0
        assert "data" not in result

    def test_failure_is_error_level_and_failed(self) -> None:
        """A refused op reads as a failed job with its exit code."""
        job_id = _record(ok=False, exit_code=_daemon_jobs.EXIT_REFUSED)
        events = read_events(_dir(job_id))
        assert events[2]["level"] == "error"
        assert events[-1]["state"] == "failed"
        job = read_job(job_id)
        assert job["state"] == "failed"
        assert job["exit_code"] == 2

    def test_data_is_json_safe(self) -> None:
        """Non-JSON values in data are stringified, not fatal."""
        job_id = _record(data={"until": object, "n": 1})
        result_event = read_events(_dir(job_id))[3]
        assert result_event["data"]["n"] == 1
        assert isinstance(result_event["data"]["until"], str)

    def test_prunes_before_writing(self) -> None:
        """History is bounded: the oldest finished job makes room."""
        first = _record()
        for _ in range(_store.MAX_JOBS):
            _record()
        assert not _dir(first).exists()
        assert len(list(_store.JOBS_DIR.iterdir())) == _store.MAX_JOBS
