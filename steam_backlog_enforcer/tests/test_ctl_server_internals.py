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
    """Build a server whose desktop uid is not the test's own uid."""
    return _ctl_server.CtlServer(
        make_ctx(), desktop_uid=os.getuid() + 1, desktop_gid=1, path=MagicMock()
    )


class TestServeLoop:
    """The accept loop survives everything but being stopped."""

    def test_no_socket_returns(self) -> None:
        """Without a bound socket the accept loop returns at once."""
        _server().serve()

    def test_timeout_then_stop(self) -> None:
        """An accept timeout loops again until the server is stopped."""
        srv = _server()
        sock = MagicMock()

        def accept() -> None:
            srv.stop()
            raise TimeoutError

        sock.accept.side_effect = accept
        srv.sock = sock
        srv.serve()
        sock.accept.assert_called_once()

    def test_oserror_while_stopping_returns_quietly(self) -> None:
        """An accept error after stop() exits without backing off."""
        srv = _server()
        sock = MagicMock()

        def accept() -> None:
            srv.stop()
            msg = "closed"
            raise OSError(msg)

        sock.accept.side_effect = accept
        srv.sock = sock
        with patch.object(_ctl_server.time, "sleep") as sleep:
            srv.serve()
        sleep.assert_not_called()

    def test_oserror_while_running_backs_off(self) -> None:
        """An accept error while running sleeps before retrying."""
        srv = _server()
        sock = MagicMock()
        sock.accept.side_effect = [OSError("emfile"), TimeoutError]
        srv.sock = sock

        def stop(_seconds: float) -> None:
            srv.stop()

        with patch.object(_ctl_server.time, "sleep", side_effect=stop) as sleep:
            srv.serve()
        sleep.assert_called_once()

    def test_accepted_connection_is_admitted(self) -> None:
        """An accepted connection is passed to admission."""
        srv = _server()
        conn = MagicMock()
        sock = MagicMock()
        sock.accept.return_value = (conn, None)
        srv.sock = sock

        def admit(_conn: object) -> None:
            srv.stop()

        with patch.object(srv, "admit", side_effect=admit) as admitted:
            srv.serve()
        admitted.assert_called_once_with(conn)


class TestAdmit:
    """Authentication and the connection cap."""

    def test_peercred_failure_closes(self) -> None:
        """A connection whose peer uid cannot be read is closed."""
        conn = MagicMock()
        with patch.object(_ctl_server, "peer_uid", side_effect=OSError("no")):
            _server().admit(conn)
        conn.close.assert_called_once()

    def test_foreign_uid_is_closed_unanswered(self) -> None:
        """A foreign uid is closed without any reply."""
        conn = MagicMock()
        with patch.object(_ctl_server, "peer_uid", return_value=31337):
            _server().admit(conn)
        conn.close.assert_called_once()
        conn.sendall.assert_not_called()

    def test_no_free_slot_drops(self) -> None:
        """A connection is dropped when every slot is taken."""
        srv = _server()
        srv.slots = threading.BoundedSemaphore(1)
        assert srv.take_slot()
        conn = MagicMock()
        with patch.object(_ctl_server, "peer_uid", return_value=0):
            srv.admit(conn)
        conn.close.assert_called_once()

    def test_allowed_uid_gets_a_worker(self) -> None:
        """An allowed uid is served on a worker thread."""
        srv = _server()
        conn = MagicMock()
        with (
            patch.object(_ctl_server, "peer_uid", return_value=0),
            patch.object(_ctl_server.threading, "Thread") as thread,
        ):
            srv.admit(conn)
        thread.return_value.start.assert_called_once()
        assert thread.call_args.kwargs["args"] == (conn, 0)


class TestHandle:
    """A connection handler always releases its slot and socket."""

    def test_writes_dispatch_result(self) -> None:
        """The handler writes the dispatched reply and closes."""
        srv = _server()
        conn = MagicMock()
        with (
            patch.object(_ctl_server, "read_line", return_value=b"line"),
            patch.object(srv, "dispatch", return_value=b"out") as dispatch,
        ):
            assert srv.take_slot()
            srv.handle(conn, 7)
        dispatch.assert_called_once_with(b"line", 7)
        conn.sendall.assert_called_once_with(b"out")
        conn.close.assert_called_once()

    def test_silent_client_writes_nothing(self) -> None:
        """A client that sends no line gets no reply."""
        srv = _server()
        conn = MagicMock()
        assert srv.take_slot()
        with patch.object(_ctl_server, "read_line", return_value=None):
            srv.handle(conn, 7)
        conn.sendall.assert_not_called()
        conn.close.assert_called_once()

    def test_write_failure_is_swallowed(self) -> None:
        """A failed write is swallowed and the slot is returned."""
        srv = _server()
        conn = MagicMock()
        conn.sendall.side_effect = BrokenPipeError
        assert srv.take_slot()
        with (
            patch.object(_ctl_server, "read_line", return_value=b"x"),
            patch.object(srv, "dispatch", return_value=b"out"),
        ):
            srv.handle(conn, 7)
        conn.close.assert_called_once()
        # The slot came back: the semaphore can be filled to its cap again.
        for _ in range(_ctl_server.MAX_CONNECTIONS):
            assert srv.take_slot()

    def test_a_bug_ends_the_thread_but_frees_the_slot(self) -> None:
        """A bug outside FAIL_SAFE_ERRORS escapes; the socket and slot do not leak."""
        srv = _server()
        conn = MagicMock()
        assert srv.take_slot()
        with (
            patch.object(_ctl_server, "read_line", return_value=b"x"),
            patch.object(srv, "dispatch", side_effect=AttributeError("bug")),
            pytest.raises(AttributeError),
        ):
            srv.handle(conn, 7)
        conn.close.assert_called_once()
        for _ in range(_ctl_server.MAX_CONNECTIONS):
            assert srv.take_slot()


class TestDispatch:
    """_dispatch never raises."""

    def test_ok(self) -> None:
        """A valid ping answers ok."""
        srv = _server()
        assert b'"ok":true' in srv.dispatch(b'{"op":"ping"}', 0)

    def test_ctl_error(self) -> None:
        """A CtlError becomes its error code in the reply."""
        srv = _server()
        with patch.object(srv, "run", side_effect=CtlError("locked", "x")):
            assert b'"error":"locked"' in srv.dispatch(b"", 0)

    def test_unexpected_error(self) -> None:
        """An unexpected exception becomes op_failed."""
        srv = _server()
        with patch.object(srv, "run", side_effect=RuntimeError("x")):
            assert b'"error":"op_failed"' in srv.dispatch(b"", 0)

    def test_a_programming_bug_is_loud(self) -> None:
        """An error outside FAIL_SAFE_ERRORS is not dressed up as op_failed."""
        srv = _server()
        with (
            patch.object(srv, "run", side_effect=AttributeError("bug")),
            pytest.raises(AttributeError),
        ):
            srv.dispatch(b"", 0)

    def test_run_rejects_unknown(self) -> None:
        """An unknown op raises CtlError."""
        with pytest.raises(CtlError, match="unknown op"):
            _server().run(b'{"op":"zzz"}', 0)
