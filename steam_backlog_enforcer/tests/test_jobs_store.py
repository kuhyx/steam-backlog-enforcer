"""Tests for ``jobs._store``: ids, pruning, the lock and job creation."""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest

from steam_backlog_enforcer.jobs import _store
from steam_backlog_enforcer.jobs._errors import JobError, PrivilegedViaDaemonError
from steam_backlog_enforcer.jobs._events import PID_NAME, REQUEST_NAME, read_events
from steam_backlog_enforcer.tests._jobs_helpers import JOB_ID, make_job

_GATE = "steam_backlog_enforcer.jobs._store.lock_reason"
_SPAWN = "steam_backlog_enforcer.jobs._store.spawn_job"


class TestJobDir:
    """Resolving an id to its directory."""

    def test_valid_id(self) -> None:
        """A well-formed id with a request file resolves."""
        path = make_job()
        assert _store.job_dir(JOB_ID) == path

    def test_older_id_without_microseconds(self) -> None:
        """History from before microsecond ids stays valid."""
        make_job(job_id="20261010T120000Z-abcdef")
        assert _store.job_dir("20261010T120000Z-abcdef").name.endswith("abcdef")

    @pytest.mark.parametrize("bad", ["../etc", "nope", "20261010T120000Z-ZZZZZZ"])
    def test_malformed_id_is_not_found(self, bad: str) -> None:
        """Path-like and malformed ids are refused."""
        with pytest.raises(JobError) as info:
            _store.job_dir(bad)
        assert info.value.code == "not_found"

    def test_unknown_id_is_not_found(self) -> None:
        """A valid id with no request file is unknown."""
        with pytest.raises(JobError) as info:
            _store.job_dir(JOB_ID)
        assert info.value.code == "not_found"


def test_new_job_ids_are_valid_and_sortable() -> None:
    """Fresh ids match the pattern and are distinct."""
    first, second = _store.new_job_id(), _store.new_job_id()
    assert _store._ID_PATTERN.fullmatch(first)
    assert first != second


class TestIsTerminal:
    """Whether a job reached a final state."""

    def test_states(self) -> None:
        """Only the last state event counts."""
        assert _store.is_terminal(make_job(states=())) is False
        assert (
            _store.is_terminal(make_job(job_id="20261010T120001000000Z-aaaaaa"))
            is False
        )
        done = make_job(
            job_id="20261010T120002000000Z-bbbbbb", states=("running", "failed")
        )
        assert _store.is_terminal(done) is True


class TestPrune:
    """Keeping the history bounded."""

    def test_missing_dir_is_a_noop(self) -> None:
        """No jobs dir, nothing to prune."""
        _store.prune(1)
        assert not _store.JOBS_DIR.exists()

    def test_removes_oldest_finished_only(self) -> None:
        """Running jobs and foreign names survive; old finished ones go."""
        old = make_job(job_id="20261010T100000000000Z-000001", states=("succeeded",))
        running = make_job(job_id="20261010T100001000000Z-000002", states=("running",))
        newest = make_job(job_id="20261010T100002000000Z-000003", states=("succeeded",))
        (_store.JOBS_DIR / "notes").mkdir()
        _store.prune(1)
        assert not old.exists()
        assert running.exists()
        assert newest.exists()
        assert (_store.JOBS_DIR / "notes").exists()


class TestMutatingLock:
    """The one-mutating-job lock."""

    def test_second_holder_is_busy(self) -> None:
        """A held lock makes the next acquire raise ``busy``."""
        fd = _store.acquire_mutating_lock()
        try:
            with pytest.raises(JobError) as info:
                _store.acquire_mutating_lock()
            assert info.value.code == "busy"
        finally:
            os.close(fd)

    def test_released_lock_can_be_retaken(self) -> None:
        """Closing the descriptor frees the lock."""
        os.close(_store.acquire_mutating_lock())
        os.close(_store.acquire_mutating_lock())


class TestPrepareJob:
    """Validation and the job dir it writes."""

    def test_unknown_command(self) -> None:
        """Commands outside the table are refused."""
        with pytest.raises(JobError) as info:
            _store.prepare_job("frobnicate", {})
        assert info.value.code == "unknown_command"

    def test_invalid_params(self) -> None:
        """Bad params become ``invalid_params``."""
        with pytest.raises(JobError) as info:
            _store.prepare_job("pick-manual", {})
        assert info.value.code == "invalid_params"

    def test_privileged_goes_to_daemon(self) -> None:
        """Daemon commands raise the routing error."""
        with pytest.raises(PrivilegedViaDaemonError):
            _store.prepare_job("block-gaming", {"days": 3})

    def test_locked(self) -> None:
        """A gate refusal becomes ``locked`` with its reason."""
        with (
            patch(_GATE, return_value="Total gaming block active"),
            pytest.raises(JobError) as info,
        ):
            _store.prepare_job("scan", {})
        assert info.value.code == "locked"
        assert "Total gaming block" in info.value.message

    def test_writes_request_and_queued_event(self) -> None:
        """The dir holds the request and a ``queued`` state."""
        with patch(_GATE, return_value=None):
            path = _store.prepare_job(
                "pick-manual", {"app_id": "620"}, confirm_phrase="x"
            )
        request = json.loads((path / REQUEST_NAME).read_text(encoding="utf-8"))
        assert request["command"] == "pick-manual"
        assert request["params"] == {"app_id": 620}
        assert request["confirm_phrase"] == "x"
        assert [e["state"] for e in read_events(path)] == ["queued"]

    def test_no_phrase_key_without_phrase(self) -> None:
        """An absent phrase is not stored."""
        with patch(_GATE, return_value=None):
            path = _store.prepare_job("scan", {})
        request = json.loads((path / REQUEST_NAME).read_text(encoding="utf-8"))
        assert "confirm_phrase" not in request


class TestCreateJob:
    """Creating and starting a job."""

    def test_mutating_job_holds_lock_during_spawn(self) -> None:
        """The child gets the lock fd; the server releases its copy after."""
        seen: dict[str, object] = {}

        def fake_spawn(path: object, lock_fd: int | None) -> int:
            seen["fd"] = lock_fd
            with pytest.raises(JobError):  # Still held while spawning.
                _store.acquire_mutating_lock()
            return 4242

        with patch(_GATE, return_value=None), patch(_SPAWN, side_effect=fake_spawn):
            job_id = _store.create_job("scan", {})
        assert isinstance(seen["fd"], int)
        assert (_store.JOBS_DIR / job_id / PID_NAME).read_text(
            encoding="utf-8"
        ) == "4242\n"
        os.close(_store.acquire_mutating_lock())  # Released again.

    def test_read_only_job_takes_no_lock(self) -> None:
        """Non-mutating commands run alongside a held lock."""
        fd = _store.acquire_mutating_lock()
        try:
            with (
                patch(_GATE, return_value=None),
                patch(_SPAWN, return_value=7) as spawn,
            ):
                _store.create_job("stats", {})
            assert spawn.call_args.args[1] is None
        finally:
            os.close(fd)

    def test_busy_when_lock_held(self) -> None:
        """A second mutating job is refused before anything is written."""
        fd = _store.acquire_mutating_lock()
        try:
            with patch(_GATE, return_value=None), pytest.raises(JobError) as info:
                _store.create_job("scan", {})
            assert info.value.code == "busy"
        finally:
            os.close(fd)

    def test_spawn_failure_releases_lock(self) -> None:
        """If the process cannot start, the lock is not leaked."""
        err = JobError("could not start", code="op_failed")
        with (
            patch(_GATE, return_value=None),
            patch(_SPAWN, side_effect=err),
            pytest.raises(JobError),
        ):
            _store.create_job("scan", {})
        os.close(_store.acquire_mutating_lock())
