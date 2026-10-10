"""Tests for ``jobs._specs``, ``jobs._errors`` and ``python -m ...jobs``."""

from __future__ import annotations

from pathlib import Path
import runpy
import sys
from unittest.mock import patch

import pytest

from steam_backlog_enforcer.jobs import __main__ as jobs_main
from steam_backlog_enforcer.jobs._errors import (
    JobCancelledError,
    JobError,
    PrivilegedViaDaemonError,
)
from steam_backlog_enforcer.jobs._specs import JOB_FLAGS, JobFlags, is_privileged


class TestIsPrivileged:
    """Which commands must go to the root daemon."""

    def test_enforce_demo_runs_as_job(self) -> None:
        """Only the demo of ``enforce`` is a job."""
        assert is_privileged("enforce", {"demo": 1}) is False

    def test_real_enforce_is_privileged(self) -> None:
        """Anything but the demo is the real enforcer."""
        assert is_privileged("enforce", {}) is True
        assert is_privileged("enforce", {"demo": 0}) is True

    def test_privileged_flag_commands(self) -> None:
        """Daemon commands carry the privileged flag."""
        assert is_privileged("unblock", {}) is True
        assert JOB_FLAGS["unblock"].privileged is True

    def test_plain_command_is_not_privileged(self) -> None:
        """Ordinary commands run as jobs."""
        assert is_privileged("scan", {}) is False

    def test_unknown_command_is_not_privileged(self) -> None:
        """No flags at all means not privileged (the store rejects it later)."""
        assert is_privileged("nope", {}) is False

    def test_flag_defaults(self) -> None:
        """A bare JobFlags is mutating, not cancellable, not privileged."""
        assert JobFlags() == JobFlags(
            mutating=True, cancellable=False, privileged=False
        )


class TestErrors:
    """The exception types the job API raises."""

    def test_job_error_carries_code_and_message(self) -> None:
        """The contract code travels with the message."""
        exc = JobError("nope", code="busy")
        assert exc.code == "busy"
        assert exc.message == "nope"
        assert str(exc) == "nope"

    def test_privileged_error_names_command(self) -> None:
        """The daemon routing error names the command."""
        exc = PrivilegedViaDaemonError("unblock")
        assert exc.command == "unblock"
        assert "unblock runs in the root daemon" in str(exc)

    def test_cancelled_is_an_exception(self) -> None:
        """JobCancelledError can be raised and caught."""
        with pytest.raises(JobCancelledError):
            raise JobCancelledError


class TestMain:
    """The ``python -m steam_backlog_enforcer.jobs`` entry point."""

    def test_run_action_calls_run_job(self, tmp_path: Path) -> None:
        """``run <dir>`` hands the path to the runner and returns its code."""
        with patch.object(jobs_main, "run_job", return_value=2) as run:
            assert jobs_main.main(["run", str(tmp_path)]) == 2
        run.assert_called_once_with(Path(tmp_path))

    def test_action_is_required(self) -> None:
        """No action is a usage error."""
        with pytest.raises(SystemExit) as info:
            jobs_main.main([])
        assert info.value.code == 2

    def test_module_execution_exits_with_job_code(self, tmp_path: Path) -> None:
        """Running the module as a script exits with the runner's code."""
        sys.modules.pop("steam_backlog_enforcer.jobs.__main__", None)
        with (
            patch("steam_backlog_enforcer.jobs._runner.run_job", return_value=7),
            patch("sys.argv", ["jobs", "run", str(tmp_path)]),
            # runpy warns when the module is already imported; run a fresh copy.
            patch.dict(sys.modules),
            pytest.raises(SystemExit) as info,
        ):
            runpy.run_module("steam_backlog_enforcer.jobs", run_name="__main__")
        assert info.value.code == 7
