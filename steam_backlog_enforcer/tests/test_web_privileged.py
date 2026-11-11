"""Tests for _web_privileged — commands the root daemon carries out."""

from __future__ import annotations

from http import HTTPStatus
from unittest.mock import patch

import pytest

from steam_backlog_enforcer import _web_privileged
from steam_backlog_enforcer._ctl_protocol import CtlError
from steam_backlog_enforcer._ctl_types import BlockResult, PendingReset, StoreWindow
from steam_backlog_enforcer._web_errors import ApiError
from steam_backlog_enforcer._web_privileged import _local_hhmm
from steam_backlog_enforcer.jobs._view import list_jobs
from steam_backlog_enforcer.tests._web_request import payload_of

_CLIENT = "steam_backlog_enforcer._web_privileged._ctl_client"


class TestLocalHhmm:
    """Formatting an ISO time as local HH:MM."""

    @pytest.mark.parametrize("iso", [None, ""])
    def test_missing_is_a_question_mark(self, iso: str | None) -> None:
        """No timestamp renders as ``?``."""
        assert _local_hhmm(iso) == "?"

    def test_unparsable_is_returned_as_is(self) -> None:
        """Text that is not ISO comes back unchanged."""
        assert _local_hhmm("soon") == "soon"

    def test_parsable_is_hh_mm(self) -> None:
        """A valid ISO time renders as five-char HH:MM."""
        got = _local_hhmm("2026-01-01T10:30:00+00:00")
        assert len(got) == 5
        assert got[2] == ":"


class TestRunPrivileged:
    """Dispatching privileged commands to the root daemon."""

    def test_gaming_reset_arms_and_answers_202(self) -> None:
        """gaming-reset arms a pending reset, answers 202, records no job."""
        pending = PendingReset("p1", "phrase", "t0", "t1", 5)
        with patch(f"{_CLIENT}.gaming_reset_arm", return_value=pending) as arm:
            reply = _web_privileged.run_privileged("gaming-reset", {}, None)
        arm.assert_called_once_with("")
        assert reply.status == HTTPStatus.ACCEPTED
        assert payload_of(reply)["id"] == "p1"
        assert list_jobs() == []

    def test_unblock_records_a_job(self) -> None:
        """unblock forwards minutes and phrase, answers 201, records a job."""
        window = StoreWindow(10, "2026-01-01T10:30:00+00:00")
        with patch(f"{_CLIENT}.store_unblock", return_value=window) as unblock:
            reply = _web_privileged.run_privileged("unblock", {"minutes": 10}, "p")
        unblock.assert_called_once_with(10, "p")
        assert reply.status == HTTPStatus.CREATED
        assert "10 min" in payload_of(reply)["summary"]
        assert [j["id"] for j in list_jobs()] == [payload_of(reply)["id"]]

    def test_buy_dlc_uses_the_default_window(self) -> None:
        """buy-dlc unblocks the store for the default DLC window."""
        window = StoreWindow(_web_privileged.BUY_DLC_MINUTES, "x")
        with patch(f"{_CLIENT}.store_unblock", return_value=window) as unblock:
            _web_privileged.run_privileged("buy-dlc", {}, None)
        unblock.assert_called_once_with(_web_privileged.BUY_DLC_MINUTES, "")

    def test_block_gaming(self) -> None:
        """block-gaming summarises the blocked days."""
        with patch(f"{_CLIENT}.block_gaming", return_value=BlockResult(3, None)):
            reply = _web_privileged.run_privileged("block-gaming", {"days": 3}, "p")
        assert "3 day(s)" in payload_of(reply)["summary"]

    def test_gaming_unblock(self) -> None:
        """gaming-unblock summarises the released mounts."""
        with patch(f"{_CLIENT}.gaming_unblock", return_value=["a", "b"]):
            reply = _web_privileged.run_privileged("gaming-unblock", {}, "p")
        assert "2 playtime mount(s)" in payload_of(reply)["summary"]

    def test_enforce_restart(self) -> None:
        """enforce restarts the daemon."""
        with patch(f"{_CLIENT}.restart", return_value="t") as restart:
            reply = _web_privileged.run_privileged("enforce", {"demo": 0}, None)
        restart.assert_called_once_with()
        assert "restarting" in payload_of(reply)["summary"]

    def test_unknown_command(self) -> None:
        """A command with no privileged route is unknown_command."""
        with pytest.raises(ApiError) as err:
            _web_privileged.run_privileged("scan", {}, None)
        assert err.value.code == "unknown_command"

    def test_failed_op_is_recorded_then_raised(self) -> None:
        """An op failure is recorded as a failed job, then raised."""
        with (
            patch(f"{_CLIENT}.restart", side_effect=CtlError("op_failed", "boom")),
            pytest.raises(ApiError) as err,
        ):
            _web_privileged.run_privileged("enforce", {"demo": 0}, None)
        assert err.value.code == "op_failed"
        (job,) = list_jobs()
        assert (job["summary"], job["exit_code"]) == ("boom", 1)

    def test_refusal_leaves_no_job(self) -> None:
        """A daemon refusal is raised and records no job."""
        with (
            patch(f"{_CLIENT}.gaming_unblock", side_effect=CtlError("locked", "no")),
            pytest.raises(ApiError) as err,
        ):
            _web_privileged.run_privileged("gaming-unblock", {}, None)
        assert err.value.code == "locked"
        assert list_jobs() == []
