"""Tests for ``jobs._view``: folding job dirs into ``Job`` objects."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer.jobs import _store, _view
from steam_backlog_enforcer.jobs._errors import JobError
from steam_backlog_enforcer.jobs._events import (
    REQUEST_NAME,
    EventWriter,
    read_events,
)
from steam_backlog_enforcer.tests._jobs_helpers import JOB_ID, make_job, write_result

if TYPE_CHECKING:
    from pathlib import Path

_PATH = "steam_backlog_enforcer.jobs._view.Path"


def _proc(cmdline: bytes | None) -> MagicMock:
    """A stand-in for ``Path`` whose ``/proc/<pid>/cmdline`` reads *cmdline*."""
    fake = MagicMock()
    if cmdline is None:
        fake.return_value.read_bytes.side_effect = FileNotFoundError
    else:
        fake.return_value.read_bytes.return_value = cmdline
    return fake


def _age(path: Path, seconds: float) -> None:
    """Pretend the request was written *seconds* ago."""
    stamp = (path / REQUEST_NAME).stat().st_mtime - seconds
    os.utime(path / REQUEST_NAME, (stamp, stamp))


class TestPidAlive:
    """Telling a live job process from a dead or recycled pid."""

    def test_no_pid_file_is_unknown(self) -> None:
        """Before spawn there is nothing to check."""
        assert _view._pid_alive(make_job()) is None

    def test_garbage_pid_is_unknown(self) -> None:
        """An unreadable pid file counts as not written yet."""
        assert _view._pid_alive(make_job(pid="soon")) is None

    def test_missing_process_is_dead(self) -> None:
        """No /proc entry means the process is gone."""
        path = make_job(pid="999999\n")
        with patch(_PATH, _proc(None)):
            assert _view._pid_alive(path) is False

    def test_job_cmdline_is_alive(self) -> None:
        """Our module and our job id on the command line."""
        path = make_job(pid="5\n")
        cmd = f"python\0-m\0steam_backlog_enforcer.jobs\0run\0/x/{JOB_ID}".encode()
        with patch(_PATH, _proc(cmd)):
            assert _view._pid_alive(path) is True

    def test_recycled_pid_is_dead(self) -> None:
        """Some other program on the same pid is not the job."""
        path = make_job(pid="5\n")
        with patch(_PATH, _proc(b"vim\0notes.txt")):
            assert _view._pid_alive(path) is False

    def test_zombie_is_dead(self) -> None:
        """A zombie has an empty command line."""
        path = make_job(pid="5\n")
        with patch(_PATH, _proc(b"")):
            assert _view._pid_alive(path) is False


class TestPidOf:
    """The pid of a live job only."""

    def test_dead_job_has_no_pid(self) -> None:
        """Not alive, no pid."""
        assert _view.pid_of(make_job(pid="5\n")) is None

    def test_live_job_returns_pid(self) -> None:
        """Alive: the pid from the file."""
        path = make_job(pid="5\n")
        with patch.object(_view, "_pid_alive", return_value=True):
            assert _view.pid_of(path) == 5


class TestReconcile:
    """A non-terminal job whose process died is failed."""

    def test_terminal_is_left_alone(self) -> None:
        """Finished jobs are never touched."""
        path = make_job(states=("running", "succeeded"))
        _view._reconcile(path, "succeeded")
        assert len(read_events(path)) == 2

    def test_fresh_job_without_pid_gets_grace(self) -> None:
        """Between mkdir and spawn the job is simply young."""
        path = make_job()
        _view._reconcile(path, "running")
        assert read_events(path)[-1]["state"] == "running"

    def test_old_job_without_pid_fails(self) -> None:
        """Past the grace period a pid-less job is dead."""
        path = make_job()
        _age(path, 120)
        _view._reconcile(path, "running")
        assert read_events(path)[-1]["state"] == "failed"

    def test_live_process_is_left_alone(self) -> None:
        """A running process means the job is fine."""
        path = make_job(pid="5\n")
        with patch.object(_view, "_pid_alive", return_value=True):
            _view._reconcile(path, "running")
        assert read_events(path)[-1]["state"] == "running"

    def test_dead_process_fails_job_with_result(self) -> None:
        """A dead pid gets a result then a failed state."""
        path = make_job(pid="5\n")
        _view._reconcile(path, "running")
        last_two = read_events(path)[-2:]
        assert last_two[0]["type"] == "result"
        assert last_two[0]["ok"] is False
        assert last_two[1]["state"] == "failed"


class TestReadJob:
    """Folding the request, events and result into a ``Job``."""

    def test_unknown_job(self) -> None:
        """Unknown ids are ``not_found``."""
        with pytest.raises(JobError) as info:
            _view.read_job(JOB_ID)
        assert info.value.code == "not_found"

    def test_folds_everything(self) -> None:
        """State, timestamps, progress, summary and exit code."""
        path = make_job(states=("queued", "running"), pid="5\n", params={"app_id": 620})
        writer = EventWriter(path)
        writer.emit("progress", step=1, total=2, label="Scan", junk="x")
        writer.emit("state", state="running")  # started_at stays the first.
        writer.emit("log", level="info", message="chatter")
        writer.emit("result", ok=True, summary="All done")
        writer.emit("state", state="succeeded")
        write_result(path, exit_code=0)
        job = _view.read_job(JOB_ID)
        assert job["state"] == "succeeded"
        assert job["command"] == "scan"
        assert job["params"] == {"app_id": 620}
        assert job["progress"] == {"step": 1, "total": 2, "label": "Scan"}
        assert job["summary"] == "All done"
        assert job["exit_code"] == 0
        events = read_events(path)
        assert job["started_at"] == events[1]["ts"]
        assert job["ended_at"] == events[-1]["ts"]

    def test_missing_or_bad_result_file(self) -> None:
        """No result.json or an unparsable one leaves exit_code unset."""
        path = make_job(states=("succeeded",))
        assert _view.read_job(JOB_ID)["exit_code"] is None
        (path / "result.json").write_text("{oops", encoding="utf-8")
        assert _view.read_job(JOB_ID)["exit_code"] is None

    def test_dead_job_is_reconciled(self) -> None:
        """Reading a job whose process vanished reports it failed."""
        make_job(pid="5\n")
        job = _view.read_job(JOB_ID)
        assert job["state"] == "failed"
        assert job["summary"] == "The job process exited without reporting a result."


class TestListJobs:
    """The newest-first job list."""

    def test_no_dir(self) -> None:
        """Nothing yet."""
        assert _view.list_jobs() == []

    def test_newest_first_and_skips_damaged(self) -> None:
        """Damaged dirs are skipped; dirs without a request are ignored."""
        make_job(job_id="20261010T100000000000Z-000001", states=("succeeded",))
        make_job(job_id="20261010T100001000000Z-000002", states=("succeeded",))
        bad_json = make_job(job_id="20261010T100002000000Z-000003")
        (bad_json / REQUEST_NAME).write_text("{oops", encoding="utf-8")
        no_command = make_job(job_id="20261010T100003000000Z-000004")
        (no_command / REQUEST_NAME).write_text("{}", encoding="utf-8")
        (_store.JOBS_DIR / ".mutating.lock").write_text("", encoding="utf-8")
        ids = [job["id"] for job in _view.list_jobs()]
        assert ids == [
            "20261010T100001000000Z-000002",
            "20261010T100000000000Z-000001",
        ]

    def test_caps_at_max_jobs(self) -> None:
        """Only MAX_JOBS entries come back."""
        for i in range(3):
            make_job(job_id=f"20261010T10000{i}000000Z-00000{i}", states=("succeeded",))
        with patch.object(_store, "MAX_JOBS", 2):
            assert len(_view.list_jobs()) == 2


class TestReadJobEvents:
    """Events for the SSE stream."""

    def test_after_seq(self) -> None:
        """Only events past the cursor."""
        make_job(states=("queued", "succeeded"))
        assert [e["seq"] for e in _view.read_job_events(JOB_ID)] == [1, 2]
        assert [e["seq"] for e in _view.read_job_events(JOB_ID, 1)] == [2]

    def test_unknown_job(self) -> None:
        """Unknown ids are ``not_found``."""
        with pytest.raises(JobError):
            _view.read_job_events(JOB_ID)

    def test_dead_job_stream_ends(self) -> None:
        """Reconciliation appends the failed state before reading."""
        make_job(pid="5\n")
        assert _view.read_job_events(JOB_ID)[-1]["state"] == "failed"
