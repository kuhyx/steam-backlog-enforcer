"""``_ctl_client.add_exception`` and the tests' socket backstop."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from steam_backlog_enforcer import _ctl_client
from steam_backlog_enforcer._ctl_context import LOCK_WAIT_SECONDS
from steam_backlog_enforcer._ctl_protocol import SOCKET_PATH, DaemonUnreachableError


def test_add_exception_sends_args_and_returns_message() -> None:
    """Only id, reason and phrase go over the wire; the message comes back."""
    with patch.object(
        _ctl_client, "call", return_value={"app_id": 1, "message": "approved"}
    ) as call:
        assert _ctl_client.add_exception(1, "a reason", "the phrase") == "approved"
    assert call.call_args.args == (
        "add_exception",
        {"app_id": 1, "reason": "a reason", "phrase": "the phrase"},
    )


def test_add_exception_outwaits_the_tick_lock() -> None:
    """A client that gave up while the daemon waits for the tick would report
    a failure for an entry the daemon then writes."""
    with patch.object(_ctl_client, "call", return_value={"message": "m"}) as call:
        _ctl_client.add_exception(1, "r", "p")
    assert call.call_args.kwargs["timeout"] > LOCK_WAIT_SECONDS


def test_tests_never_reach_the_live_socket() -> None:
    """conftest points the default socket away from the live daemon."""
    assert vars(_ctl_client)["SOCKET_PATH"] != SOCKET_PATH
    with pytest.raises(DaemonUnreachableError):
        _ctl_client.ping()
