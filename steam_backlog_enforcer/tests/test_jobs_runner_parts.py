"""Tests for the building blocks of ``jobs._runner``: lock, SIGTERM, verdicts."""

from __future__ import annotations

import json
import os
import signal
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer.jobs import _runner, _spawn, _store
from steam_backlog_enforcer.jobs._errors import JobCancelledError, JobError
from steam_backlog_enforcer.jobs._events import (
    RESULT_NAME,
    EventWriter,
    read_events,
)
from steam_backlog_enforcer.jobs._job_io import JobLogSink
from steam_backlog_enforcer.jobs._specs import JobFlags
from steam_backlog_enforcer.tests._jobs_helpers import make_job

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture(autouse=True)
def sig() -> Iterator[MagicMock]:
    """Stand in for ``signal.signal`` so the test process keeps its handlers."""
    with patch.object(signal, "signal") as fake:
        yield fake


class TestOutcome:
    """The verdict record."""

    def test_ok_only_when_succeeded(self) -> None:
        """Only a succeeded state counts as ok."""
        assert _runner._Outcome("succeeded", "x", 0).ok is True
        assert _runner._Outcome("failed", "x", 1).ok is False

    def test_failed_defaults_to_exit_one(self) -> None:
        """The helper builds a failed outcome."""
        outcome = _runner._failed("boom")
        assert (outcome.state, outcome.exit_code) == ("failed", _runner.EXIT_FAILED)
        assert _runner._failed("no", _runner.EXIT_REFUSED).exit_code == 2


class TestHoldLock:
    """The one-mutating-job lock inside the job process."""

    def test_read_only_job_holds_nothing(self) -> None:
        """Non-mutating jobs skip the lock."""
        assert _runner._hold_lock(JobFlags(mutating=False)) is None

    def test_takes_the_lock_when_run_by_hand(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No inherited descriptor: acquire, and make it non-inheritable."""
        monkeypatch.delenv(_spawn.LOCK_FD_ENV, raising=False)
        fd = _runner._hold_lock(JobFlags())
        assert fd is not None
        try:
            assert os.get_inheritable(fd) is False
            with pytest.raises(JobError):
                _store.acquire_mutating_lock()
        finally:
            os.close(fd)

    def test_busy_when_run_by_hand_and_locked(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Another job already holds it."""
        monkeypatch.delenv(_spawn.LOCK_FD_ENV, raising=False)
        held = _store.acquire_mutating_lock()
        try:
            with pytest.raises(JobError) as info:
                _runner._hold_lock(JobFlags())
            assert info.value.code == "busy"
        finally:
            os.close(held)

    def test_accepts_inherited_lock_descriptor(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The server's descriptor is checked against the lock file, then kept."""
        held = _store.acquire_mutating_lock()
        monkeypatch.setenv(_spawn.LOCK_FD_ENV, str(held))
        try:
            assert _runner._hold_lock(JobFlags()) == held
            assert os.get_inheritable(held) is False
            assert _spawn.LOCK_FD_ENV not in os.environ
        finally:
            os.close(held)

    def test_rejects_descriptor_that_is_not_the_lock(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A reused descriptor number must not pass for the lock."""
        os.close(_store.acquire_mutating_lock())  # Creates the lock file.
        other = tmp_path / "other"
        other.write_text("", encoding="utf-8")
        fd = os.open(other, os.O_RDWR)
        monkeypatch.setenv(_spawn.LOCK_FD_ENV, str(fd))
        try:
            with pytest.raises(JobError) as info:
                _runner._hold_lock(JobFlags())
            assert info.value.code == "busy"
            assert "not the lock file" in info.value.message
        finally:
            os.close(fd)


class TestOnSigterm:
    """Cancel where that is safe, ignore elsewhere."""

    def test_cancellable_raises_in_handler(self, sig: MagicMock) -> None:
        """The handler raises, and does nothing else."""
        _runner._on_sigterm(cancellable=True)
        sigterm, handler = sig.call_args.args
        assert sigterm == signal.SIGTERM
        with pytest.raises(JobCancelledError):
            handler(signal.SIGTERM, None)

    def test_non_cancellable_ignores(self, sig: MagicMock) -> None:
        """SIGTERM is ignored for unsafe-to-stop commands."""
        _runner._on_sigterm(cancellable=False)
        sig.assert_called_once_with(signal.SIGTERM, signal.SIG_IGN)


class TestCompleted:
    """A command that returned normally."""

    def test_printed_error_is_a_failure(self, tmp_path: Path) -> None:
        """``Error: ...`` then return is still a failed job."""
        sink = JobLogSink(EventWriter(tmp_path))
        sink("Error: no key\n")
        outcome = _runner._completed(sink)
        assert (outcome.state, outcome.summary) == ("failed", "Error: no key")

    def test_summary_is_last_line(self, tmp_path: Path) -> None:
        """The last text line summarises; unflushed text is flushed."""
        sink = JobLogSink(EventWriter(tmp_path))
        sink("first\nlast")
        outcome = _runner._completed(sink, {"a": 1})
        assert (outcome.state, outcome.summary, outcome.data) == (
            "succeeded",
            "last",
            {"a": 1},
        )

    def test_silent_command_says_done(self, tmp_path: Path) -> None:
        """No output at all reads as ``Done.``."""
        outcome = _runner._completed(JobLogSink(EventWriter(tmp_path)))
        assert outcome.summary == "Done."
        assert outcome.exit_code == 0


class TestFinish:
    """The single result, in the right order."""

    def test_writes_result_event_file_and_state(self, sig: MagicMock) -> None:
        """result event, result.json, then the final state."""
        path = make_job(states=("running",))
        outcome = _runner._Outcome("succeeded", "ok", 0, {"when": object})
        _runner._finish(path, EventWriter(path), outcome)
        events = read_events(path)
        assert [e["type"] for e in events[-2:]] == ["result", "state"]
        assert events[-2]["ok"] is True
        assert isinstance(events[-2]["data"]["when"], str)
        result = json.loads((path / RESULT_NAME).read_text(encoding="utf-8"))
        assert result["state"] == "succeeded"
        assert result["exit_code"] == 0
        assert events[-1]["state"] == "succeeded"
        sig.assert_called_with(signal.SIGTERM, signal.SIG_IGN)

    def test_no_data_key_without_data(self) -> None:
        """A dataless outcome has no ``data`` field."""
        path = make_job(states=("running",))
        _runner._finish(path, EventWriter(path), _runner._failed("bad"))
        assert "data" not in read_events(path)[-2]
