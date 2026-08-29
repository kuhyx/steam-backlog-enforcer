"""Argument parsing and the start-or-defer decision for ``serve``.

:mod:`steam_backlog_enforcer._serve_guard` answers *who owns the port*; this
module decides *what to do about it*, so ``cmd_serve`` stays a few lines.
"""

from __future__ import annotations

import ipaddress
import sys
from typing import NoReturn

from steam_backlog_enforcer._serve_guard import (
    find_port_owner,
    is_our_server,
    newest_py_since,
    port_is_free,
    process_started_at,
    read_cmdline,
    terminate,
)
from steam_backlog_enforcer._web_server import DEFAULT_HOST, DEFAULT_PORT
from steam_backlog_enforcer.game_install import _echo

# The dataset API is unauthenticated, so a bind must never leave this machine.
# IPv4 only: ThreadingHTTPServer's address_family is AF_INET and nothing
# overrides it, so accepting "::1" here would ship a flag that always crashes.
_LOOPBACK_ALIAS = "localhost"

_IPV4 = 4
_MIN_PORT = 1024
_MAX_PORT = 65535

_SERVE_USAGE = (
    "Usage: serve [--host HOST] [--port PORT]\n"
    f"  --host : IPv4 loopback only (127.0.0.1 or {_LOOPBACK_ALIAS})\n"
    f"  --port : {_MIN_PORT}-{_MAX_PORT}, default {DEFAULT_PORT}\n\n"
    "Re-running serve is safe: it rebuilds the frontend when stale, reports an\n"
    "already-running server, and replaces one running outdated code."
)


def _fail_usage(message: str) -> NoReturn:
    """Print *message* followed by the usage block, then exit 1."""
    _echo(message)
    _echo(_SERVE_USAGE)
    sys.exit(1)


def _parse_port(raw: str) -> int:
    """Parse and range-check a ``--port`` value."""
    try:
        port = int(raw)
    except ValueError:
        _fail_usage(f"Not a number: {raw}")
    if not _MIN_PORT <= port <= _MAX_PORT:
        _fail_usage(f"Port out of range: {port}")
    return port


def _parse_host(raw: str) -> str:
    """Validate a ``--host`` value and canonicalise it to a literal address."""
    if raw == _LOOPBACK_ALIAS:
        return DEFAULT_HOST
    try:
        addr = ipaddress.ip_address(raw)
    except ValueError:
        _fail_usage(f"Not an IP address: {raw}")
    if not addr.is_loopback or addr.version != _IPV4:
        _fail_usage(f"Refusing to bind non-IPv4-loopback host: {raw}")
    return raw


def parse_serve_args(argv: list[str]) -> tuple[str, int]:
    """Parse ``serve``'s flags into a (host, port) pair.

    Args:
        argv: CLI arguments after the command name.

    Returns:
        The host and port to bind.
    """
    host, port = DEFAULT_HOST, DEFAULT_PORT
    rest = list(argv)
    while rest:
        flag = rest.pop(0)
        if flag not in {"--host", "--port"}:
            _fail_usage(f"Unknown argument: {flag}")
        if not rest:
            _fail_usage(f"{flag} needs a value.")
        value = rest.pop(0)
        if flag == "--port":
            port = _parse_port(value)
        else:
            host = _parse_host(value)
    return host, port


def _describe(pid: int) -> str:
    """Render a short, human-readable identification of *pid*."""
    argv = read_cmdline(pid)
    return f"pid {pid} ({' '.join(argv)})" if argv else f"pid {pid}"


def _exit_foreign(port: int, owner: str) -> NoReturn:
    """Report a port held by something that is not ours, then exit 1."""
    _echo(f"Port {port} is held by {owner}.", flush=True)
    _echo(f"Free it, or choose another port: serve --port {port + 1}")
    sys.exit(1)


def ensure_port_available(host: str, port: int) -> None:
    """Make *host*:*port* bindable, or exit with a clear explanation.

    Returns normally when the port is free or was freed by stopping a stale
    server.  Exits 0 when an up-to-date server of ours already holds it - that
    is success, not failure: the UI the caller asked for is already up.  Exits
    1 when the port belongs to something we must not touch.
    """
    if port_is_free(host, port):
        return

    pid = find_port_owner(host, port)
    if pid is None:
        _exit_foreign(port, "a process this user cannot inspect")
    elif not is_our_server(pid):
        _exit_foreign(port, f"{_describe(pid)}, which is not our web UI")
    else:
        _replace_or_defer(host, port, pid)


def _replace_or_defer(host: str, port: int, pid: int) -> None:
    """Exit 0 if the server at *pid* is current, else terminate it."""
    started_at = process_started_at(pid)
    stale = None if started_at is None else newest_py_since(started_at)
    if started_at is not None and stale is None:
        _echo(
            "Steam Backlog Enforcer web UI already running: "
            f"http://{host}:{port} (pid {pid})",
            flush=True,
        )
        sys.exit(0)

    reason = "start time unreadable" if started_at is None else f"{stale} is newer"
    _echo(f"Restarting stale web UI (pid {pid}): {reason}.", flush=True)
    if not is_our_server(pid):
        # The PID was recycled between the scan and here; never signal blind.
        _exit_foreign(port, f"{_describe(pid)}, which is not our web UI")
    if not terminate(pid, host, port):
        _echo(f"Could not free port {port} from pid {pid}.", flush=True)
        sys.exit(1)
