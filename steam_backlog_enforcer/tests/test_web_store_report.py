"""Failed store checks in the web server and CLI: failed jobs and todo tasks."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer import _web_privileged, _web_store_report
from steam_backlog_enforcer._ctl_protocol import CtlError, DaemonUnreachableError
from steam_backlog_enforcer._store_verify import (
    Check,
    StoreCheckReport,
    StoreVerifyError,
)
from steam_backlog_enforcer._todo_filing import Filed, FilingError
from steam_backlog_enforcer._web_errors import ApiError
from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.jobs import _store
from steam_backlog_enforcer.jobs._events import read_events
from steam_backlog_enforcer.jobs._view import list_jobs
from steam_backlog_enforcer.main.misc import cmd_unblock

if TYPE_CHECKING:
    from collections.abc import Iterator

_REPORTS = "steam_backlog_enforcer._web_store_report"
_CLIENT = "steam_backlog_enforcer._web_privileged._ctl_client"
_REPORT = {
    "action": "unblock",
    "check": "https",
    "title": "Store unblock verification failed: https",
    "body": "Time: t\n",
}


@pytest.fixture(name="filer")
def fixture_filer() -> Iterator[MagicMock]:
    """The todo filer, faked: files a new task unless told otherwise."""
    filed = Filed(created=True, task="added abc")
    with patch(f"{_REPORTS}.file_report", return_value=filed) as f:
        yield f


def _messages(job_id: str) -> list[str]:
    events = read_events(_store.JOBS_DIR / job_id)
    return [str(e["message"]) for e in events if e.get("type") == "log"]


def _failed_unblock() -> CtlError:
    return CtlError("op_failed", "Store unblock failed: https", {"report": _REPORT})


def test_failed_unblock_job_fails_and_files_task(filer: MagicMock) -> None:
    """op_failed with a report: failed job naming the check, one task filed."""
    with (
        patch(f"{_CLIENT}.store_unblock", side_effect=_failed_unblock()),
        pytest.raises(ApiError) as err,
    ):
        _web_privileged.run_privileged("unblock", {"minutes": 5}, "p")
    assert err.value.code == "op_failed"
    filer.assert_called_once_with(_REPORT)
    (job,) = list_jobs()
    assert (job["state"], job["exit_code"]) == ("failed", 1)
    assert job["summary"] == "Store unblock failed: https"
    log = _messages(str(job["id"]))
    assert "Filed todo task 'Store unblock verification failed: https'" in log[1]


def test_already_open_task_is_logged_not_refiled(filer: MagicMock) -> None:
    """A second failure says the task is already open."""
    filer.return_value = Filed(created=False, task="1234abcd")
    with (
        patch(f"{_CLIENT}.store_unblock", side_effect=_failed_unblock()),
        pytest.raises(ApiError),
    ):
        _web_privileged.run_privileged("unblock", {"minutes": 5}, "p")
    (job,) = list_jobs()
    assert "1234abcd is already open" in _messages(str(job["id"]))[1]


def test_filing_failure_is_in_the_log_and_job_is_non_zero(filer: MagicMock) -> None:
    """MCP down: the job log says the task could not be filed; exit is 1."""
    filer.side_effect = FilingError("todo MCP unreachable")
    with (
        patch(f"{_CLIENT}.store_unblock", side_effect=_failed_unblock()),
        pytest.raises(ApiError),
    ):
        _web_privileged.run_privileged("unblock", {"minutes": 5}, "p")
    (job,) = list_jobs()
    assert job["exit_code"] == 1
    assert "Could not file the todo task" in _messages(str(job["id"]))[1]


def test_op_failed_without_report_files_nothing(filer: MagicMock) -> None:
    """A plain op_failed (no report) is recorded and files nothing."""
    with (
        patch(f"{_CLIENT}.store_unblock", side_effect=CtlError("op_failed", "x")),
        pytest.raises(ApiError),
    ):
        _web_privileged.run_privileged("unblock", {"minutes": 5}, "p")
    filer.assert_not_called()
    assert len(list_jobs()) == 1


def test_collect_records_one_failed_reblock_job_per_report(filer: MagicMock) -> None:
    """Each queued re-block report becomes a failed job and a filed task."""
    report = _REPORT | {"action": "re-block", "check": "dns"}
    with patch(f"{_REPORTS}._ctl_client.store_reports", return_value=[report]):
        assert _web_store_report.collect_store_reports() == 1
    (job,) = list_jobs()
    assert job["summary"] == "Store re-block failed: dns"
    assert job["state"] == "failed"
    filer.assert_called_once_with(report)


@pytest.mark.parametrize("error", [DaemonUnreachableError("x"), CtlError("a", "b")])
def test_collect_survives_daemon_errors(error: Exception) -> None:
    """An unreachable daemon costs one round, nothing else."""
    with patch(f"{_REPORTS}._ctl_client.store_reports", side_effect=error):
        assert _web_store_report.collect_store_reports() == 0


@pytest.mark.usefixtures("filer")
def test_collect_survives_a_job_write_error() -> None:
    """A failed job write is logged and the poller keeps going."""
    with (
        patch(f"{_REPORTS}._ctl_client.store_reports", return_value=[_REPORT]),
        patch(f"{_REPORTS}.record_daemon_job", side_effect=OSError("disk")),
    ):
        assert _web_store_report.collect_store_reports() == 1


def test_poller_runs_until_stopped() -> None:
    """The poller calls collect on its interval and stops on the event."""
    with patch(f"{_REPORTS}.collect_store_reports") as collect:
        stop = _web_store_report.start_store_report_poller(interval=0.01)
        for _ in range(200):
            if collect.call_count:
                break
            stop.wait(0.01)
        stop.set()
    assert collect.call_count >= 1


def test_cli_unblock_failure_prints_check_files_and_exits_1(filer: MagicMock) -> None:
    """``run.sh unblock`` with failing checks: says so, files, exits 1."""
    report = StoreCheckReport("unblock", "t", [Check("hosts", ok=False, detail="x")])
    with (
        patch(
            "steam_backlog_enforcer.main.misc.open_store_window",
            side_effect=StoreVerifyError(report),
        ),
        patch("steam_backlog_enforcer.main.misc._echo") as echo,
        pytest.raises(SystemExit) as exited,
    ):
        cmd_unblock(Config(), State(), ["1"])
    assert exited.value.code == 1
    said = [str(c.args[0]) for c in echo.call_args_list]
    assert said[0] == "Store unblock failed: hosts (the store is NOT open)."
    assert "Filed todo task" in said[1]
    filer.assert_called_once_with(report.to_wire())
