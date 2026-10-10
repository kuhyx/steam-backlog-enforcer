"""Tests for ``CtlServer`` over a real Unix socket in a temp directory.

``os.chown`` (the server chowns its socket to root) is mocked: the suite runs
unprivileged. Clients are the real ``_ctl_client.call`` against the server.
"""

from __future__ import annotations

import json
import os
import socket
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer import _ctl_client, _ctl_server
from steam_backlog_enforcer._ctl_protocol import CtlError, DaemonUnreachableError
from steam_backlog_enforcer.tests._ctl_fixtures import make_ctx, short_socket_dir

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture
def sock_path() -> Iterator[Path]:
    with short_socket_dir() as directory:
        yield directory / "ctl.sock"


@pytest.fixture
def server(sock_path: Path) -> Iterator[_ctl_server.CtlServer]:
    srv = _ctl_server.CtlServer(
        make_ctx(), desktop_uid=os.getuid(), desktop_gid=os.getgid(), path=sock_path
    )
    with patch.object(_ctl_server.os, "chown"):
        assert srv.start() is True
    yield srv
    srv.stop()


class TestLifecycle:
    """Binding, refusing a second server, stopping."""

    def test_serves_ping_and_stop_removes_socket(
        self, server: _ctl_server.CtlServer, sock_path: Path
    ) -> None:
        assert _ctl_client.call("ping", path=sock_path) == {"pong": True}
        assert sock_path.stat().st_mode & 0o777 == _ctl_server.SOCKET_MODE
        server.stop()
        assert not sock_path.exists()

    def test_does_not_take_over_a_live_socket(
        self, server: _ctl_server.CtlServer, sock_path: Path
    ) -> None:
        second = _ctl_server.CtlServer(
            make_ctx(), desktop_uid=os.getuid(), desktop_gid=os.getgid(), path=sock_path
        )
        assert second.start() is False
        assert _ctl_client.call("ping", path=sock_path) == {"pong": True}

    def test_replaces_a_stale_socket_file(self, sock_path: Path) -> None:
        sock_path.write_text("stale")
        srv = _ctl_server.CtlServer(
            make_ctx(), desktop_uid=os.getuid(), desktop_gid=os.getgid(), path=sock_path
        )
        with patch.object(_ctl_server.os, "chown"):
            assert srv.start() is True
        srv.stop()

    def test_bind_failure_returns_false(self, sock_path: Path) -> None:
        blocker = sock_path.parent / "file"
        blocker.write_text("x")
        srv = _ctl_server.CtlServer(
            make_ctx(),
            desktop_uid=os.getuid(),
            desktop_gid=os.getgid(),
            path=blocker / "ctl.sock",
        )
        assert srv.start() is False

    def test_stop_before_start(self, sock_path: Path) -> None:
        srv = _ctl_server.CtlServer(
            make_ctx(), desktop_uid=1, desktop_gid=1, path=sock_path
        )
        srv.stop()


class TestRequests:
    """End-to-end dispatch through the real socket."""

    def test_unknown_op(self, server: _ctl_server.CtlServer, sock_path: Path) -> None:
        with pytest.raises(CtlError) as caught:
            _ctl_client.call("rm_rf", path=sock_path)
        assert caught.value.code == "unknown_command"

    def test_crashing_op_is_internal_error(
        self, server: _ctl_server.CtlServer, sock_path: Path
    ) -> None:
        boom = MagicMock(side_effect=ValueError("bad"))
        with (
            patch.dict(_ctl_server.OPS, {"boom": boom}),
            pytest.raises(CtlError) as caught,
        ):
            _ctl_client.call("boom", path=sock_path)
        assert caught.value.code == "op_failed"

    def test_refused_op_carries_error_data(
        self, server: _ctl_server.CtlServer, sock_path: Path
    ) -> None:
        refuse = MagicMock(side_effect=CtlError("busy", "wait", {"n": 1}))
        with (
            patch.dict(_ctl_server.OPS, {"r": refuse}),
            pytest.raises(CtlError) as caught,
        ):
            _ctl_client.call("r", path=sock_path)
        assert (caught.value.code, caught.value.data) == ("busy", {"n": 1})

    def test_oversize_line(self, server: _ctl_server.CtlServer) -> None:
        with pytest.raises(CtlError) as caught:
            server._run(b"x" * (_ctl_server.MAX_REQUEST_BYTES + 1), 0)
        assert caught.value.code == "invalid_params"

    def test_malformed_request_over_socket(
        self, server: _ctl_server.CtlServer, sock_path: Path
    ) -> None:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as raw:
            raw.settimeout(5)
            raw.connect(str(sock_path))
            raw.sendall(b"not json\n")
            reply = json.loads(raw.makefile().readline())
        assert reply["ok"] is False
        assert reply["error"] == "invalid_params"

    def test_silent_client_gets_no_reply(
        self, server: _ctl_server.CtlServer, sock_path: Path
    ) -> None:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as raw:
            raw.settimeout(5)
            raw.connect(str(sock_path))
            raw.shutdown(socket.SHUT_WR)
            assert raw.recv(10) == b""

    def test_unreachable_after_stop(
        self, server: _ctl_server.CtlServer, sock_path: Path
    ) -> None:
        server.stop()
        with pytest.raises(DaemonUnreachableError):
            _ctl_client.call("ping", path=sock_path)
