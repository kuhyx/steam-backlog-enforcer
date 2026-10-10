"""The control socket server: who may talk to the daemon, and how.

A Unix socket at ``/run/steam-backlog-enforcer/ctl.sock``, mode 0660, group =
the desktop user's primary group. Filesystem permissions are the first gate;
``SO_PEERCRED`` is the second and the one that counts: the kernel reports the
connecting process's real uid, and anything but the desktop user is closed
without a byte of reply.

Root is admitted too. Root can already do everything the ops do (``sudo
./run.sh gaming-reset``, ``guardctl``), so refusing it would protect nothing;
admitting it lets recovery and tests use the same interface.

The server must never be the thing that takes the enforcer down or wedges it:
every connection has a read deadline and a size cap, concurrency is bounded,
each connection runs on its own thread, and no exception escapes a handler.
"""

from __future__ import annotations

import logging
import os
import socket
import threading
import time
from typing import TYPE_CHECKING, Final

from steam_backlog_enforcer._ctl_ops import OPS
from steam_backlog_enforcer._ctl_protocol import (
    INVALID_PARAMS,
    MAX_REQUEST_BYTES,
    OP_FAILED,
    SOCKET_PATH,
    UNKNOWN_OP,
    CtlError,
    error_response,
    ok_response,
)
from steam_backlog_enforcer._ctl_wire import (
    parse_request,
    peer_uid,
    read_line,
    socket_is_live,
)

if TYPE_CHECKING:
    from pathlib import Path

    from steam_backlog_enforcer._ctl_context import CtlContext

logger = logging.getLogger(__name__)

SOCKET_MODE: Final = 0o660
WRITE_TIMEOUT_SECONDS: Final = 5.0
MAX_CONNECTIONS: Final = 8
_BACKLOG: Final = 8
_ACCEPT_POLL_SECONDS: Final = 1.0
_ROOT_UID: Final = 0


class CtlServer:
    """Accepts, authenticates and dispatches control-socket connections."""

    def __init__(
        self,
        ctx: CtlContext,
        *,
        desktop_uid: int,
        desktop_gid: int,
        path: Path = SOCKET_PATH,
    ) -> None:
        """Prepare a server; nothing is bound until :meth:`start`.

        Args:
            ctx: Shared op context.
            desktop_uid: The one non-root uid allowed to connect.
            desktop_gid: Group that owns the socket file.
            path: Socket path.
        """
        self._ctx = ctx
        self._allowed = frozenset({desktop_uid, _ROOT_UID})
        self._gid = desktop_gid
        self._path = path
        self._stop = threading.Event()
        self._slots = threading.BoundedSemaphore(MAX_CONNECTIONS)
        self._sock: socket.socket | None = None

    def start(self) -> bool:
        """Bind the socket and start accepting. Never raises.

        Returns:
            Whether the server is now listening.
        """
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            if socket_is_live(self._path):
                logger.error(
                    "Control socket %s is already served; not taking over", self._path
                )
                return False
            self._path.unlink(missing_ok=True)
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.bind(str(self._path))
            # Between bind() and here the file is root-owned 0755: nobody else
            # has write permission, so nobody else can connect yet.
            os.chown(self._path, 0, self._gid)
            self._path.chmod(SOCKET_MODE)
            sock.listen(_BACKLOG)
            sock.settimeout(_ACCEPT_POLL_SECONDS)
        except OSError:
            logger.exception("Cannot start the control socket at %s", self._path)
            return False
        self._sock = sock
        threading.Thread(target=self._serve, name="ctl-accept", daemon=True).start()
        logger.info("Control socket listening on %s", self._path)
        return True

    def stop(self) -> None:
        """Stop accepting and remove the socket file."""
        self._stop.set()
        if self._sock is not None:
            self._sock.close()
            self._sock = None
        self._path.unlink(missing_ok=True)

    def _serve(self) -> None:
        """Accept loop; survives anything but being told to stop."""
        while not self._stop.is_set():
            sock = self._sock
            if sock is None:
                return
            try:
                conn, _ = sock.accept()
            except TimeoutError:
                continue
            except OSError:
                if self._stop.is_set():
                    return
                logger.exception("Control socket accept failed")
                time.sleep(_ACCEPT_POLL_SECONDS)
                continue
            self._admit(conn)

    def _admit(self, conn: socket.socket) -> None:
        """Authenticate *conn* and hand it to a worker, or close it silently."""
        try:
            uid = peer_uid(conn)
        except OSError:
            conn.close()
            return
        if uid not in self._allowed:
            logger.warning("Control socket: refused a connection from uid %d", uid)
            conn.close()
            return
        if not self._slots.acquire(blocking=False):
            logger.warning("Control socket: too many connections, dropping one")
            conn.close()
            return
        threading.Thread(
            target=self._handle, args=(conn, uid), name="ctl-conn", daemon=True
        ).start()

    def _handle(self, conn: socket.socket, uid: int) -> None:
        """Serve one connection, always releasing its slot and socket."""
        try:
            line = read_line(conn)
            if line is not None:
                self._write(conn, self._dispatch(line, uid))
        except Exception:
            logger.debug("Control connection dropped", exc_info=True)
        finally:
            conn.close()
            self._slots.release()

    @staticmethod
    def _write(conn: socket.socket, payload: bytes) -> None:
        """Send the response within the write deadline."""
        conn.settimeout(WRITE_TIMEOUT_SECONDS)
        conn.sendall(payload)

    def _dispatch(self, line: bytes, uid: int) -> bytes:
        """Turn a request line into a response line. Never raises."""
        try:
            return ok_response(self._run(line, uid))
        except CtlError as exc:
            logger.info("Control socket: refused (%s)", exc.code)
            return error_response(exc)
        except Exception:
            logger.exception("Control socket op crashed")
            return error_response(CtlError(OP_FAILED, "internal error"))

    def _run(self, line: bytes, uid: int) -> dict[str, object]:
        """Validate a request line and run its op.

        Raises:
            CtlError: For a malformed request, an unknown op, or a refused op.
        """
        if len(line) > MAX_REQUEST_BYTES:
            raise CtlError(INVALID_PARAMS, "request too large")
        op, args = parse_request(line)
        handler = OPS.get(op)
        if handler is None:
            raise CtlError(UNKNOWN_OP, f"unknown op {op!r}")
        logger.info("Control socket: op=%s uid=%d", op, uid)
        return handler(self._ctx, args)
