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
from steam_backlog_enforcer._ctl_protocol import (
    MAX_REQUEST_BYTES,
    CtlError,
    DaemonUnreachableError,
)
from steam_backlog_enforcer.tests._ctl_fixtures import make_ctx, short_socket_dir

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture(name="sock_path")
def fixture_sock_path() -> Iterator[Path]:
    """Yield a socket path inside a short temporary directory."""
    with short_socket_dir() as directory:
        yield directory / "ctl.sock"


@pytest.fixture(name="server")
def fixture_server(sock_path: Path) -> Iterator[_ctl_server.CtlServer]:
    """Yield a started server bound to ``sock_path``, stopped afterwards."""
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
        """A started server answers ping with the socket mode set; stop unlinks it."""
        assert _ctl_client.call("ping", path=sock_path) == {"pong": True}
        assert sock_path.stat().st_mode & 0o777 == _ctl_server.SOCKET_MODE
        server.stop()
        assert not sock_path.exists()

    @pytest.mark.usefixtures("server")
    def test_does_not_take_over_a_live_socket(self, sock_path: Path) -> None:
        """A second server refuses a live socket and the first keeps serving."""
        second = _ctl_server.CtlServer(
            make_ctx(), desktop_uid=os.getuid(), desktop_gid=os.getgid(), path=sock_path
        )
        assert second.start() is False
        assert _ctl_client.call("ping", path=sock_path) == {"pong": True}

    def test_replaces_a_stale_socket_file(self, sock_path: Path) -> None:
        """A leftover non-listening file at the path is replaced on start."""
        sock_path.write_text("stale")
        srv = _ctl_server.CtlServer(
            make_ctx(), desktop_uid=os.getuid(), desktop_gid=os.getgid(), path=sock_path
        )
        with patch.object(_ctl_server.os, "chown"):
            assert srv.start() is True
        srv.stop()

    def test_bind_failure_returns_false(self, sock_path: Path) -> None:
        """An unbindable path makes start report failure instead of raising."""
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
        """Stopping a never-started server is a harmless no-op."""
        srv = _ctl_server.CtlServer(
            make_ctx(), desktop_uid=1, desktop_gid=1, path=sock_path
        )
        srv.stop()


class TestRequests:
    """End-to-end dispatch through the real socket."""

    @pytest.mark.usefixtures("server")
    def test_unknown_op(self, sock_path: Path) -> None:
        """An op the server does not know is refused as unknown_command."""
        with pytest.raises(CtlError) as caught:
            _ctl_client.call("rm_rf", path=sock_path)
        assert caught.value.code == "unknown_command"

    @pytest.mark.usefixtures("server")
    def test_crashing_op_is_internal_error(self, sock_path: Path) -> None:
        """An op that raises a bare exception answers op_failed."""
        boom = MagicMock(side_effect=ValueError("bad"))
        with (
            patch.dict(_ctl_server.OPS, {"boom": boom}),
            pytest.raises(CtlError) as caught,
        ):
            _ctl_client.call("boom", path=sock_path)
        assert caught.value.code == "op_failed"

    @pytest.mark.usefixtures("server")
    def test_refused_op_carries_error_data(self, sock_path: Path) -> None:
        """A CtlError raised by an op reaches the client with its code and data."""
        refuse = MagicMock(side_effect=CtlError("busy", "wait", {"n": 1}))
        with (
            patch.dict(_ctl_server.OPS, {"r": refuse}),
            pytest.raises(CtlError) as caught,
        ):
            _ctl_client.call("r", path=sock_path)
        assert (caught.value.code, caught.value.data) == ("busy", {"n": 1})

    @pytest.mark.usefixtures("server")
    def test_oversize_line(self, sock_path: Path) -> None:
        """A request line over the size cap is refused as invalid_params."""
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as raw:
            raw.settimeout(5)
            raw.connect(str(sock_path))
            raw.sendall(b"x" * (MAX_REQUEST_BYTES + 1))
            reply = json.loads(raw.makefile().readline())
        assert reply["error"] == "invalid_params"

    @pytest.mark.usefixtures("server")
    def test_malformed_request_over_socket(self, sock_path: Path) -> None:
        """A non-JSON line gets an ok=false invalid_params reply."""
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as raw:
            raw.settimeout(5)
            raw.connect(str(sock_path))
            raw.sendall(b"not json\n")
            reply = json.loads(raw.makefile().readline())
        assert reply["ok"] is False
        assert reply["error"] == "invalid_params"

    @pytest.mark.usefixtures("server")
    def test_silent_client_gets_no_reply(self, sock_path: Path) -> None:
        """A client that sends nothing is closed without a reply."""
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as raw:
            raw.settimeout(5)
            raw.connect(str(sock_path))
            raw.shutdown(socket.SHUT_WR)
            assert raw.recv(10) == b""

    def test_unreachable_after_stop(
        self, server: _ctl_server.CtlServer, sock_path: Path
    ) -> None:
        """After stop, a client call raises DaemonUnreachableError."""
        server.stop()
        with pytest.raises(DaemonUnreachableError):
            _ctl_client.call("ping", path=sock_path)
