"""Tests for _web_daemon — daemon status and the two-phase gaming reset."""

from __future__ import annotations

from http import HTTPStatus
from unittest.mock import patch

import pytest

from steam_backlog_enforcer import _web_daemon
from steam_backlog_enforcer._ctl_protocol import CtlError, DaemonUnreachableError
from steam_backlog_enforcer._ctl_types import DaemonInfo, PendingReset, ResetResult
from steam_backlog_enforcer._web_errors import ApiError
from steam_backlog_enforcer.jobs._view import list_jobs
from steam_backlog_enforcer.tests._web_request import make_request, payload_of

_CLIENT = "steam_backlog_enforcer._web_daemon._ctl_client"
_PENDING = PendingReset("p1", "type me", "t0", "t1", 5)
_INFO = DaemonInfo("running", "2026-01-01T00:00:00Z", 77, None)


class TestDaemonCall:
    def test_passes_the_result_through(self) -> None:
        assert _web_daemon.daemon_call(max, 1, 3) == 3

    def test_unreachable_becomes_503(self) -> None:
        with (
            patch(f"{_CLIENT}.ping", side_effect=DaemonUnreachableError("no socket")),
            pytest.raises(ApiError) as err,
        ):
            _web_daemon.daemon_call(_web_daemon._ctl_client.ping)
        assert err.value.status == HTTPStatus.SERVICE_UNAVAILABLE

    def test_refusal_keeps_its_code(self) -> None:
        with (
            patch(f"{_CLIENT}.ping", side_effect=CtlError("locked", "no")),
            pytest.raises(ApiError) as err,
        ):
            _web_daemon.daemon_call(_web_daemon._ctl_client.ping)
        assert err.value.code == "locked"


class TestDaemonView:
    def test_unreachable_is_a_state_not_an_error(self) -> None:
        with patch(f"{_CLIENT}.status", side_effect=DaemonUnreachableError):
            reply = _web_daemon.daemon_view(make_request())
        assert payload_of(reply)["state"] == "unreachable"

    def test_status_refusal_is_an_error(self) -> None:
        with (
            patch(f"{_CLIENT}.status", side_effect=CtlError("busy", "m")),
            pytest.raises(ApiError) as err,
        ):
            _web_daemon.daemon_view(make_request())
        assert err.value.code == "busy"

    def test_reachable_includes_the_journal(self) -> None:
        with (
            patch(f"{_CLIENT}.status", return_value=_INFO),
            patch(f"{_CLIENT}.journal_tail", return_value=["a", "b"]) as tail,
        ):
            reply = _web_daemon.daemon_view(make_request())
        tail.assert_called_once_with(_web_daemon._JOURNAL_LINES)
        assert reply.payload == {
            "state": "running",
            "started_at": "2026-01-01T00:00:00Z",
            "pid": 77,
            "journal_tail": ["a", "b"],
            "restart_available_at": None,
        }

    @pytest.mark.parametrize(
        "failure", [DaemonUnreachableError(), CtlError("busy", "m")]
    )
    def test_status_stands_without_its_journal(self, failure: Exception) -> None:
        with (
            patch(f"{_CLIENT}.status", return_value=_INFO),
            patch(f"{_CLIENT}.journal_tail", side_effect=failure),
        ):
            reply = _web_daemon.daemon_view(make_request())
        assert payload_of(reply)["journal_tail"] == []


class TestPendingRoutes:
    def test_pending_action_maps_the_contract_fields(self) -> None:
        assert _web_daemon.pending_action(_PENDING) == {
            "id": "p1",
            "command": "gaming-reset",
            "phrase": "type me",
            "armed_at": "t0",
            "ready_at": "t1",
            "heartbeat_interval_seconds": 5,
        }

    def test_heartbeat(self) -> None:
        with patch(f"{_CLIENT}.gaming_reset_heartbeat", return_value=_PENDING) as hb:
            reply = _web_daemon.heartbeat_view(make_request("p1"))
        hb.assert_called_once_with("p1")
        assert payload_of(reply)["id"] == "p1"

    def test_cancel(self) -> None:
        with patch(f"{_CLIENT}.gaming_reset_cancel") as cancel:
            reply = _web_daemon.cancel_pending_view(make_request("p1"))
        cancel.assert_called_once_with("p1")
        assert reply.status == HTTPStatus.NO_CONTENT


class TestConfirmPhrase:
    @pytest.mark.parametrize(
        ("body", "expected"),
        [
            ({}, ""),
            ({"confirm_phrase": "a"}, "a"),
            ({"confirmPhrase": "b"}, "b"),
        ],
    )
    def test_reads_either_spelling(self, body: dict[str, str], expected: str) -> None:
        assert _web_daemon.confirm_phrase_of(make_request(body=body)) == expected

    def test_rejects_a_non_string(self) -> None:
        with pytest.raises(ApiError) as err:
            _web_daemon.confirm_phrase_of(make_request(body={"confirm_phrase": 3}))
        assert err.value.code == "invalid_params"


class TestCommit:
    def test_records_a_finished_job(self) -> None:
        result = ResetResult("2026-01-01", 1800.0, was_blocked=True, released=["m"])
        with patch(f"{_CLIENT}.gaming_reset_commit", return_value=result) as commit:
            reply = _web_daemon.commit_view(
                make_request("p1", body={"confirm_phrase": "go"})
            )
        commit.assert_called_once_with("p1", "go")
        assert reply.status == HTTPStatus.CREATED
        assert "30 min billed" in payload_of(reply)["summary"]
        assert [j["id"] for j in list_jobs()] == [payload_of(reply)["id"]]

    def test_failed_op_is_recorded_and_raised(self) -> None:
        failure = CtlError("op_failed", "disk full")
        with (
            patch(f"{_CLIENT}.gaming_reset_commit", side_effect=failure),
            pytest.raises(ApiError) as err,
        ):
            _web_daemon.commit_view(make_request("p1"))
        assert err.value.code == "op_failed"
        (job,) = list_jobs()
        assert job["summary"] == "disk full"
        assert job["exit_code"] == 1

    def test_refusal_leaves_no_job(self) -> None:
        with (
            patch(
                f"{_CLIENT}.gaming_reset_commit",
                side_effect=CtlError("wrong_phrase", "no"),
            ),
            pytest.raises(ApiError),
        ):
            _web_daemon.commit_view(make_request("p1"))
        assert list_jobs() == []
