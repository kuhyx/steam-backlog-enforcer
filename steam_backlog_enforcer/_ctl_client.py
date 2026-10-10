"""Client for the root daemon's control socket (used by the web server).

One typed function per allowlisted op. A socket that is missing, refuses the
connection, times out or is closed without an answer (which is how the daemon
turns away a uid it does not know) raises :class:`DaemonUnreachableError`; a request
the daemon understood but refused raises :class:`CtlError` carrying the
contract's error code.

Imports nothing from the enforcer except the wire module, so the unprivileged
server can load it without pulling in the daemon's side effects.
"""

from __future__ import annotations

import socket
from typing import TYPE_CHECKING, Final, cast

from steam_backlog_enforcer._ctl_protocol import (
    MAX_RESPONSE_BYTES,
    SOCKET_PATH,
    CtlError,
    DaemonUnreachableError,
    decode_line,
    encode_line,
)
from steam_backlog_enforcer._ctl_types import (
    BlockResult,
    DaemonInfo,
    PendingReset,
    ResetResult,
    StoreWindow,
)

if TYPE_CHECKING:
    from pathlib import Path


# Most ops answer in well under a second; the ones that run privileged
# commands (iptables, pacman, guardctl) are given room, and every one may also
# wait up to a minute for the enforce loop's current pass to finish.
_DEFAULT_TIMEOUT: Final = 15.0
_SLOW_TIMEOUT: Final = 150.0
_BLOCK_TIMEOUT: Final = 600.0


def call(
    op: str,
    args: dict[str, object] | None = None,
    *,
    timeout: float = _DEFAULT_TIMEOUT,
    path: Path = SOCKET_PATH,
) -> dict[str, object]:
    """Send one request and return the response's ``data``.

    Args:
        op: Op name.
        args: Op arguments.
        timeout: Seconds to wait for connect and for the reply.
        path: Socket path (overridable for tests).

    Returns:
        The ``data`` object of a successful response.

    Raises:
        DaemonUnreachableError: No daemon answered on the socket.
        CtlError: The daemon refused or failed the op.
    """
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    conn.settimeout(timeout)
    try:
        conn.connect(str(path))
        conn.sendall(encode_line({"op": op, "args": args or {}}))
        raw = _read_reply(conn)
    except OSError as exc:  # missing, refused, permission denied, timeout, reset
        msg = f"control socket {path}: {exc}"
        raise DaemonUnreachableError(msg) from exc
    finally:
        conn.close()
    if not raw.strip():
        msg = f"control socket {path} closed without answering (uid not permitted?)"
        raise DaemonUnreachableError(msg)
    return _unwrap(raw)


def _read_reply(conn: socket.socket) -> bytes:
    """Read until the daemon closes the connection, within the size cap."""
    data = b""
    while chunk := conn.recv(65536):
        data += chunk
        if len(data) > MAX_RESPONSE_BYTES:
            msg = "control socket reply too large"
            raise OSError(msg)
    return data


def _unwrap(raw: bytes) -> dict[str, object]:
    """Decode a response line into its data, or raise its error."""
    try:
        reply = decode_line(raw.split(b"\n", 1)[0])
    except ValueError as exc:
        msg = "control socket sent a malformed reply"
        raise DaemonUnreachableError(msg) from exc
    if not isinstance(reply, dict):
        msg = "control socket sent a malformed reply"
        raise DaemonUnreachableError(msg)
    if reply.get("ok") is True:
        data = reply.get("data")
        return cast("dict[str, object]", data) if isinstance(data, dict) else {}
    extra = reply.get("data")
    raise CtlError(
        str(reply.get("error", "op_failed")),
        str(reply.get("message", "")),
        cast("dict[str, object]", extra) if isinstance(extra, dict) else None,
    )


def _pending(data: dict[str, object]) -> PendingReset:
    """Build a :class:`PendingReset` from an arm/heartbeat reply."""
    return PendingReset(
        pending_id=str(data["pending_id"]),
        phrase=str(data["phrase"]),
        armed_at=str(data["armed_at"]),
        ready_at=str(data["ready_at"]),
        heartbeat_interval_seconds=int(cast("int", data["heartbeat_interval_seconds"])),
    )


def ping() -> None:
    """Check the daemon answers. Raises :class:`DaemonUnreachableError` if not."""
    call("ping")


def status() -> DaemonInfo:
    """The daemon's state, start time, pid and next-restart time."""
    data = call("status")
    until = data.get("restart_available_at")
    return DaemonInfo(
        state=str(data["state"]),
        started_at=str(data["started_at"]),
        pid=int(cast("int", data["pid"])),
        restart_available_at=str(until) if until else None,
    )


def journal_tail(lines: int = 50) -> list[str]:
    """The last *lines* (1-200) journal lines of the enforcer unit."""
    data = call("journal_tail", {"lines": lines})
    return [str(line) for line in cast("list[object]", data["lines"])]


def store_unblock(minutes: int, phrase: str) -> StoreWindow:
    """Open the store for *minutes* (1-30); *phrase* is checked by the daemon."""
    data = call(
        "store_unblock",
        {"minutes": minutes, "phrase": phrase},
        timeout=_SLOW_TIMEOUT,
    )
    return StoreWindow(
        minutes=int(cast("int", data["minutes"])), until=str(data["until"])
    )


def block_gaming(days: int, phrase: str) -> BlockResult:
    """Start a total gaming block for *days* days. Irreversible from the app."""
    data = call(
        "block_gaming", {"days": days, "phrase": phrase}, timeout=_BLOCK_TIMEOUT
    )
    until = data.get("until")
    return BlockResult(
        days=int(cast("int", data["days"])), until=str(until) if until else None
    )


def gaming_unblock(phrase: str) -> list[str]:
    """Release every playtime mount; returns the targets released."""
    data = call("gaming_unblock", {"phrase": phrase}, timeout=_SLOW_TIMEOUT)
    return [str(path) for path in cast("list[object]", data["released"])]


def gaming_reset_arm(phrase: str) -> PendingReset:
    """Start the gaming-reset countdown (or join the one already running)."""
    return _pending(call("gaming_reset_arm", {"phrase": phrase}))


def gaming_reset_heartbeat(pending_id: str) -> PendingReset:
    """Keep an armed reset alive; call at least every 10 s."""
    return _pending(call("gaming_reset_heartbeat", {"pending_id": pending_id}))


def gaming_reset_commit(pending_id: str, phrase: str) -> ResetResult:
    """Run the reset once the countdown has finished."""
    data = call(
        "gaming_reset_commit",
        {"pending_id": pending_id, "phrase": phrase},
        timeout=_SLOW_TIMEOUT,
    )
    return ResetResult(
        day_key=str(data["day_key"]),
        seconds_before=float(cast("float", data["seconds_before"])),
        was_blocked=bool(data["was_blocked"]),
        released=[str(path) for path in cast("list[object]", data["released"])],
    )


def gaming_reset_cancel(pending_id: str) -> None:
    """Abandon an armed reset."""
    call("gaming_reset_cancel", {"pending_id": pending_id})


def restart() -> str | None:
    """Restart the daemon (rate limited); returns when the next one is allowed."""
    data = call("restart")
    until = data.get("restart_available_at")
    return str(until) if until else None
