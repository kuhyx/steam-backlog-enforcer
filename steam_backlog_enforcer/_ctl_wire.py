"""Server-side wire helpers for the control socket.

Everything that touches the raw connection before an op runs: who is on the
other end, whether anything already serves the path, and reading/validating one
request line under a deadline and a size cap.
"""

from __future__ import annotations

import socket
import struct
import time
from typing import TYPE_CHECKING, Final

from steam_backlog_enforcer._ctl_protocol import (
    INVALID_PARAMS,
    MAX_REQUEST_BYTES,
    CtlError,
    decode_line,
)

if TYPE_CHECKING:
    from pathlib import Path

READ_TIMEOUT_SECONDS: Final = 5.0
_PEERCRED: Final = struct.Struct("3i")  # struct ucred: pid, uid, gid


def peer_uid(conn: socket.socket) -> int:
    """The kernel-reported uid of the process on the other end of *conn*."""
    raw = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, _PEERCRED.size)
    return int(_PEERCRED.unpack(raw)[1])


def socket_is_live(path: Path) -> bool:
    """Whether something is already accepting connections on *path*."""
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    probe.settimeout(1.0)
    try:
        probe.connect(str(path))
    except OSError:
        return False
    finally:
        probe.close()
    return True


def read_line(conn: socket.socket) -> bytes | None:
    """Read one request line within the deadline and size cap.

    Returns:
        The line, or ``None`` if the client sent nothing or stalled.
    """
    deadline = time.monotonic() + READ_TIMEOUT_SECONDS
    data = b""
    while b"\n" not in data:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        conn.settimeout(remaining)
        try:
            chunk = conn.recv(1024)
        except TimeoutError:
            return None
        if not chunk:
            break
        data += chunk
        if len(data) > MAX_REQUEST_BYTES:
            return data[: MAX_REQUEST_BYTES + 1]
    return data.split(b"\n", 1)[0] if data else None


def parse_request(line: bytes) -> tuple[str, dict[str, object]]:
    """Decode a request into ``(op, args)``.

    Raises:
        CtlError: ``invalid_params`` for anything that is not
            ``{"op": str, "args": object?}``.
    """
    try:
        request = decode_line(line)
    except ValueError as exc:
        raise CtlError(INVALID_PARAMS, "request is not valid JSON") from exc
    if not isinstance(request, dict) or not isinstance(request.get("op"), str):
        raise CtlError(INVALID_PARAMS, 'request must be {"op": "<name>", ...}')
    args = request.get("args", {})
    if not isinstance(args, dict):
        raise CtlError(INVALID_PARAMS, "args must be an object")
    return request["op"], args
