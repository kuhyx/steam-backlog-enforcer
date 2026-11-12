"""A route bug outside FAIL_SAFE_ERRORS is loud, and the server keeps serving."""

from __future__ import annotations

from http.client import HTTPConnection, RemoteDisconnected
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from steam_backlog_enforcer.tests._web_process_state import (
    clean_process_state,
    running_server,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from steam_backlog_enforcer._web_io import Reply, Request

_PKG = "steam_backlog_enforcer._web_server"


@pytest.fixture(autouse=True)
def _clean_process_state() -> Iterator[None]:
    """No retiring flag, and never "stale"."""
    yield from clean_process_state()


def _get(port: int, path: str) -> int:
    """One GET; the status, or ``-1`` if the server hung up without one."""
    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("GET", path)
        return conn.getresponse().status
    except RemoteDisconnected:
        return -1
    finally:
        conn.close()


def test_a_bug_drops_the_request_and_the_server_survives() -> None:
    """The buggy request gets no answer; the next request is served."""

    def route(_request: Request) -> Reply:
        msg = "bug"
        raise AttributeError(msg)

    with running_server() as server:
        with (
            patch(f"{_PKG}.resolve", return_value=(route, ())),
            patch.object(server, "handle_error") as handle_error,
        ):
            assert _get(server.port, "/api/budget") == -1
        handle_error.assert_called_once()
        assert _get(server.port, "/api/jobs") == 200
