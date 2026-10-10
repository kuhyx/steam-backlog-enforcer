"""Tests for ``CtlServer``'s accept loop, admission and handler internals.

These drive the private methods directly with mock sockets, to reach the
failure branches (accept errors, refused uids, exhausted slots, a handler that
blows up) that a well-behaved client never triggers.
"""

from __future__ import annotations

import os
import threading
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer import _ctl_server
from steam_backlog_enforcer._ctl_protocol import CtlError
from steam_backlog_enforcer.tests._ctl_fixtures import make_ctx


def _server() -> _ctl_server.CtlServer:
    return _ctl_server.CtlServer(
        make_ctx(), desktop_uid=os.getuid() + 1, desktop_gid=1, path=MagicMock()
    )


class TestServeLoop:
    """The accept loop survives everything but being stopped."""

    def test_no_socket_returns(self) -> None:
        _server()._serve()

    def test_timeout_then_stop(self) -> None:
        srv = _server()
        sock = MagicMock()

        def accept() -> None:
            srv._stop.set()
            raise TimeoutError

        sock.accept.side_effect = accept
        srv._sock = sock
        srv._serve()
        sock.accept.assert_called_once()

    def test_oserror_while_stopping_returns_quietly(self) -> None:
        srv = _server()
        sock = MagicMock()

        def accept() -> None:
            srv._stop.set()
            msg = "closed"
            raise OSError(msg)

        sock.accept.side_effect = accept
        srv._sock = sock
        with patch.object(_ctl_server.time, "sleep") as sleep:
            srv._serve()
        sleep.assert_not_called()

    def test_oserror_while_running_backs_off(self) -> None:
        srv = _server()
        sock = MagicMock()
        sock.accept.side_effect = [OSError("emfile"), TimeoutError]
        srv._sock = sock

        def stop(_seconds: float) -> None:
            srv._stop.set()

        with patch.object(_ctl_server.time, "sleep", side_effect=stop) as sleep:
            srv._serve()
        sleep.assert_called_once()

    def test_accepted_connection_is_admitted(self) -> None:
        srv = _server()
        conn = MagicMock()
        sock = MagicMock()
        sock.accept.return_value = (conn, None)
        srv._sock = sock

        def admit(_conn: object) -> None:
            srv._stop.set()

        with patch.object(srv, "_admit", side_effect=admit) as admitted:
            srv._serve()
        admitted.assert_called_once_with(conn)


class TestAdmit:
    """Authentication and the connection cap."""

    def test_peercred_failure_closes(self) -> None:
        conn = MagicMock()
        with patch.object(_ctl_server, "peer_uid", side_effect=OSError("no")):
            _server()._admit(conn)
        conn.close.assert_called_once()

    def test_foreign_uid_is_closed_unanswered(self) -> None:
        conn = MagicMock()
        with patch.object(_ctl_server, "peer_uid", return_value=31337):
            _server()._admit(conn)
        conn.close.assert_called_once()
        conn.sendall.assert_not_called()

    def test_no_free_slot_drops(self) -> None:
        srv = _server()
        srv._slots = threading.BoundedSemaphore(1)
        srv._slots.acquire()
        conn = MagicMock()
        with patch.object(_ctl_server, "peer_uid", return_value=0):
            srv._admit(conn)
        conn.close.assert_called_once()

    def test_allowed_uid_gets_a_worker(self) -> None:
        srv = _server()
        conn = MagicMock()
        with (
            patch.object(_ctl_server, "peer_uid", return_value=0),
            patch.object(_ctl_server.threading, "Thread") as thread,
        ):
            srv._admit(conn)
        thread.return_value.start.assert_called_once()
        assert thread.call_args.kwargs["args"] == (conn, 0)


class TestHandle:
    """A connection handler always releases its slot and socket."""

    def test_writes_dispatch_result(self) -> None:
        srv = _server()
        conn = MagicMock()
        with (
            patch.object(_ctl_server, "read_line", return_value=b"line"),
            patch.object(srv, "_dispatch", return_value=b"out") as dispatch,
        ):
            srv._slots.acquire()
            srv._handle(conn, 7)
        dispatch.assert_called_once_with(b"line", 7)
        conn.sendall.assert_called_once_with(b"out")
        conn.close.assert_called_once()

    def test_silent_client_writes_nothing(self) -> None:
        srv = _server()
        conn = MagicMock()
        srv._slots.acquire()
        with patch.object(_ctl_server, "read_line", return_value=None):
            srv._handle(conn, 7)
        conn.sendall.assert_not_called()
        conn.close.assert_called_once()

    def test_write_failure_is_swallowed(self) -> None:
        srv = _server()
        conn = MagicMock()
        conn.sendall.side_effect = BrokenPipeError
        srv._slots.acquire()
        with (
            patch.object(_ctl_server, "read_line", return_value=b"x"),
            patch.object(srv, "_dispatch", return_value=b"out"),
        ):
            srv._handle(conn, 7)
        conn.close.assert_called_once()
        # The slot came back: the semaphore can be filled to its cap again.
        for _ in range(_ctl_server.MAX_CONNECTIONS):
            assert srv._slots.acquire(blocking=False)


class TestDispatch:
    """_dispatch never raises."""

    def test_ok(self) -> None:
        srv = _server()
        assert b'"ok":true' in srv._dispatch(b'{"op":"ping"}', 0)

    def test_ctl_error(self) -> None:
        srv = _server()
        with patch.object(srv, "_run", side_effect=CtlError("locked", "x")):
            assert b'"error":"locked"' in srv._dispatch(b"", 0)

    def test_unexpected_error(self) -> None:
        srv = _server()
        with patch.object(srv, "_run", side_effect=RuntimeError("x")):
            assert b'"error":"op_failed"' in srv._dispatch(b"", 0)

    def test_run_rejects_unknown(self) -> None:
        with pytest.raises(CtlError, match="unknown op"):
            _server()._run(b'{"op":"zzz"}', 0)
