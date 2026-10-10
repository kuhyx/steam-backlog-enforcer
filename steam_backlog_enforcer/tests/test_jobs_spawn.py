"""Tests for ``jobs._spawn``: starting the detached job process."""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer.jobs import _spawn
from steam_backlog_enforcer.jobs._errors import JobError
from steam_backlog_enforcer.jobs._events import (
    OUTPUT_NAME,
    RESULT_NAME,
    EventWriter,
    read_events,
)
from steam_backlog_enforcer.tests._jobs_helpers import JOB_ID, make_job

if TYPE_CHECKING:
    from pathlib import Path

_WHICH = "steam_backlog_enforcer.jobs._spawn.shutil.which"
_PATH = "steam_backlog_enforcer.jobs._spawn.Path"
_POPEN = "steam_backlog_enforcer.jobs._spawn.subprocess.Popen"
_CLOCK = "steam_backlog_enforcer.jobs._spawn.time"


class TestSpawnArgv:
    """Plain interpreter, or wrapped in a transient systemd scope."""

    def test_plain_without_systemd_unit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Outside a unit the job is just the interpreter."""
        monkeypatch.delenv("INVOCATION_ID", raising=False)
        argv = _spawn._spawn_argv(make_job())
        assert argv[:3] == [sys.executable, "-m", "steam_backlog_enforcer.jobs"]
        assert argv[-2] == "run"

    def test_scope_under_systemd(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Inside the server's unit the job gets its own scope."""
        monkeypatch.setenv("INVOCATION_ID", "abc")
        with patch(_WHICH, return_value="/usr/bin/systemd-run"):
            argv = _spawn._spawn_argv(make_job())
        assert argv[0] == "/usr/bin/systemd-run"
        assert f"--unit=sbe-job-{JOB_ID.lower()}" in argv
        assert argv[argv.index("--") + 1] == sys.executable

    def test_plain_when_systemd_run_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No systemd-run on PATH means no wrapping."""
        monkeypatch.setenv("INVOCATION_ID", "abc")
        with patch(_WHICH, return_value=None):
            assert _spawn._spawn_argv(make_job())[0] == sys.executable


class TestIsJobInterpreter:
    """Launcher versus the job's own Python."""

    def test_matches_our_interpreter(self) -> None:
        """argv0 equal to sys.executable."""
        fake = MagicMock()
        fake.return_value.read_bytes.return_value = f"{sys.executable}\0-m\0x".encode()
        with patch(_PATH, fake):
            assert _spawn._is_job_interpreter(1) is True

    def test_launcher_is_not(self) -> None:
        """systemd-run before it execs."""
        fake = MagicMock()
        fake.return_value.read_bytes.return_value = b"/usr/bin/systemd-run\0--user"
        with patch(_PATH, fake):
            assert _spawn._is_job_interpreter(1) is False

    def test_missing_process(self) -> None:
        """A vanished process is not the interpreter."""
        fake = MagicMock()
        fake.return_value.read_bytes.side_effect = FileNotFoundError
        with patch(_PATH, fake):
            assert _spawn._is_job_interpreter(1) is False


class TestOutputTail:
    """The launcher output shown on failure."""

    def test_missing_log(self) -> None:
        """No output.log, no tail."""
        assert _spawn._output_tail(make_job()) == ""

    def test_tail_is_stripped_and_capped(self) -> None:
        """Only the last characters survive."""
        path = make_job()
        (path / OUTPUT_NAME).write_text("\n" + "x" * 1000 + "END\n", encoding="utf-8")
        tail = _spawn._output_tail(path)
        assert len(tail) == 600
        assert tail.endswith("END")


class TestFailUnstarted:
    """Marking a job that never ran as failed."""

    def test_writes_log_result_state_and_returns_error(self) -> None:
        """The job ends failed, with the launcher output in its log."""
        path = make_job(states=("queued",))
        (path / OUTPUT_NAME).write_text("bus unreachable\n", encoding="utf-8")
        err = _spawn._fail_unstarted(path, "Could not start.")
        assert err.code == "op_failed"
        assert err.message == "Could not start. bus unreachable"
        events = read_events(path)
        assert events[1]["level"] == "error"
        assert "bus unreachable" in events[1]["message"]
        assert events[2]["ok"] is False
        assert events[-1]["state"] == "failed"
        result = json.loads((path / RESULT_NAME).read_text(encoding="utf-8"))
        assert result["exit_code"] == 1
        assert result["state"] == "failed"


class TestConfirmStarted:
    """Waiting for the job to exec, or the launcher to die."""

    def test_launcher_exit_with_result_is_success(self) -> None:
        """A fast job that already finished wrote its own result."""
        path = make_job()
        EventWriter(path).emit("result", ok=True, summary="done")
        proc = MagicMock(**{"poll.return_value": 0})
        _spawn._confirm_started(proc, path)

    def test_launcher_exit_without_result_fails_job(self) -> None:
        """The launcher died before the job ran."""
        path = make_job()
        proc = MagicMock(**{"poll.return_value": 3})
        with pytest.raises(JobError) as info:
            _spawn._confirm_started(proc, path)
        assert info.value.code == "op_failed"
        assert "launcher exit 3" in info.value.message

    def test_interpreter_means_started(self) -> None:
        """The launcher exec'd into the job's Python."""
        proc = MagicMock(pid=9, **{"poll.return_value": None})
        with patch.object(_spawn, "_is_job_interpreter", return_value=True):
            _spawn._confirm_started(proc, make_job())

    def test_waits_then_gives_up_quietly(self) -> None:
        """Past the deadline the reconciler takes over; no error here."""
        proc = MagicMock(pid=9, **{"poll.return_value": None})
        clock = MagicMock()
        clock.monotonic.side_effect = [0.0, 1.0, 100.0]
        with (
            patch.object(_spawn, "_is_job_interpreter", return_value=False),
            patch(_CLOCK, clock),
        ):
            _spawn._confirm_started(proc, make_job())
        clock.sleep.assert_called_once()


class TestSpawnJob:
    """Building the environment and starting the process."""

    def _spawn(self, path: Path, lock_fd: int | None) -> tuple[int, MagicMock]:
        popen = MagicMock()
        popen.return_value.pid = 321
        with (
            patch(_POPEN, popen),
            patch.object(_spawn, "_confirm_started") as confirm,
        ):
            pid = _spawn.spawn_job(path, lock_fd)
        confirm.assert_called_once()
        return pid, popen

    def test_with_lock_fd(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The lock descriptor is inherited and announced by env var."""
        monkeypatch.setenv("PYTHONPATH", "/existing")
        pid, popen = self._spawn(make_job(), 17)
        kwargs = popen.call_args.kwargs
        assert pid == 321
        assert kwargs["pass_fds"] == (17,)
        assert kwargs["env"][_spawn.LOCK_FD_ENV] == "17"
        assert kwargs["env"]["PYTHONPATH"].endswith("/existing")
        assert kwargs["start_new_session"] is True

    def test_without_lock_fd(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Read-only jobs inherit nothing and need no PYTHONPATH tail."""
        monkeypatch.delenv("PYTHONPATH", raising=False)
        monkeypatch.delenv(_spawn.LOCK_FD_ENV, raising=False)
        _, popen = self._spawn(make_job(), None)
        kwargs = popen.call_args.kwargs
        assert kwargs["pass_fds"] == ()
        assert _spawn.LOCK_FD_ENV not in kwargs["env"]
        assert kwargs["env"]["PYTHONPATH"] == str(_spawn._PACKAGE_ROOT)

    def test_popen_oserror_fails_job(self) -> None:
        """An exec failure marks the job failed and raises ``op_failed``."""
        path = make_job()
        with (
            patch(_POPEN, side_effect=OSError("no such file")),
            pytest.raises(JobError) as info,
        ):
            _spawn.spawn_job(path, None)
        assert info.value.code == "op_failed"
        assert "no such file" in info.value.message
        assert read_events(path)[-1]["state"] == "failed"
