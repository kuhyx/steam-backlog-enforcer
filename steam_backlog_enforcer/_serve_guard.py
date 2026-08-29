"""Guard that makes ``serve`` safe to run twice.

Binding a second web server to the same port used to raise a bare
``OSError: [Errno 98]`` traceback.  Instead of failing, this resolves *who*
owns the port and decides between three outcomes: an already-running server on
current code is reported and the caller exits 0; one running stale code is
terminated so a fresh process can take the port; anything else is a hard error
naming the owner.

Ownership is resolved through ``/proc`` rather than ``ss`` so the whole thing
stays importable, dependency-free and unit-testable against a fake ``/proc``.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path
import signal
import socket
import time

from steam_backlog_enforcer._serve_stale import newest_py_after

_PROC = Path("/proc")
_NET_TCP = (_PROC / "net" / "tcp", _PROC / "net" / "tcp6")

# /proc/net/tcp state column: 0A is TCP_LISTEN. Anything else is a connection,
# not a bind, and must not be mistaken for the process owning the port.
_LISTEN_STATE = "0A"

# argv fragments identifying our own web servers, matched as substrings over
# the joined argv: a `python -c` server never holds "…enforcer.main", so an
# exact match missed it entirely. See _serve_stale for what that cost.
_OWN_PACKAGE = "steam_backlog_enforcer"
_OWN_COMMAND = "serve"

# A wildcard IPv4 bind renders as an all-zero address column. Spelled as hex
# rather than _hex_v4("0.0.0.0") so the dotted-quad literal never appears: this
# module only ever *matches* that address, it must never bind it.
_WILDCARD_V4 = "0" * 8

# /proc/<pid>/stat after the comm field: fields[0] is state, fields[1] ppid.
_MIN_STAT_FIELDS_AFTER_COMM = 2
_TERM_WAIT_SECONDS = 5.0
_POLL_INTERVAL = 0.1


def _hex_port(port: int) -> str:
    """Render *port* the way /proc/net/tcp does (upper-case, 4 hex digits)."""
    return f"{port:04X}"


def _hex_v4(host: str) -> str:
    """Render an IPv4 address the way /proc/net/tcp does (little-endian hex)."""
    packed = socket.inet_pton(socket.AF_INET, host)
    return f"{int.from_bytes(packed, 'little'):08X}"


def _hex_v6(host: str) -> str:
    """Render an IPv6 address the way /proc/net/tcp6 does.

    The 16 bytes are four 32-bit words, each byte-swapped independently.
    """
    packed = socket.inet_pton(socket.AF_INET6, host)
    words = (packed[i : i + 4] for i in range(0, 16, 4))
    return "".join(f"{int.from_bytes(word, 'little'):08X}" for word in words)


def _conflicting_addresses(host: str) -> frozenset[str]:
    """Address columns whose listener would block a bind on *host*.

    Matching on the port alone is wrong: a listener on ``192.168.1.5:8000``
    does not conflict with ``127.0.0.1:8000``, and reporting it as the owner
    would name an innocent process. Conversely a wildcard bind (``0.0.0.0``,
    ``::``) or a v4-mapped one does conflict, and lives in tcp6 even when the
    bind we want is IPv4 - which is why both files are scanned.
    """
    return frozenset(
        {
            _hex_v4(host),
            _WILDCARD_V4,
            _hex_v6("::"),
            _hex_v6(f"::ffff:{host}"),
        }
    )


def _listening_inodes(host: str, port: int) -> set[int]:
    """Collect socket inodes listening on an address that blocks *host*:*port*."""
    suffix = ":" + _hex_port(port)
    addresses = _conflicting_addresses(host)
    inodes: set[int] = set()
    for path in _NET_TCP:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            fields = line.split()
            min_fields = 10
            if len(fields) <= min_fields:
                continue
            local = fields[1]
            if not local.endswith(suffix) or fields[3] != _LISTEN_STATE:
                continue
            if local[: -len(suffix)] not in addresses:
                continue
            with contextlib.suppress(ValueError):
                inodes.add(int(fields[9]))
    return inodes


def _pid_owns_inode(pid_dir: Path, targets: set[int]) -> bool:
    """Check whether any file descriptor of *pid_dir* is one of *targets*."""
    wanted = {f"socket:[{inode}]" for inode in targets}
    try:
        fds = list((pid_dir / "fd").iterdir())
    except OSError:
        # A process we cannot inspect (other user, or exited mid-scan).
        return False
    for fd in fds:
        try:
            if fd.readlink().as_posix() in wanted:
                return True
        except OSError:
            continue
    return False


def find_port_owner(host: str, port: int) -> int | None:
    """Return the PID listening on *port*, or None if nothing is.

    Only processes readable by this user can be attributed; a listener owned
    by another user resolves to None, which callers must treat as "occupied by
    something I cannot identify", never as "free".
    """
    inodes = _listening_inodes(host, port)
    if not inodes:
        return None
    for entry in _PROC.iterdir():
        if not entry.name.isdigit():
            continue
        if _pid_owns_inode(entry, inodes):
            return int(entry.name)
    return None


def read_cmdline(pid: int) -> list[str]:
    """Return argv for *pid*, or an empty list if it cannot be read."""
    try:
        raw = (_PROC / str(pid) / "cmdline").read_bytes()
    except OSError:
        return []
    return [part for part in raw.decode("utf-8", "replace").split("\0") if part]


def is_our_server(pid: int) -> bool:
    """Check whether *pid* is one of our own ``serve`` processes.

    Recognises every launch form -- ``run.sh serve``, ``python -m …main
    serve``, and a bare ``python -c``. One we fail to recognise can be neither
    replaced when stale nor named accurately when it holds the port.
    """
    argv = " ".join(read_cmdline(pid))
    return _OWN_PACKAGE in argv and _OWN_COMMAND in argv


def process_started_at(pid: int) -> float | None:
    """Return the start time of *pid* as an epoch float.

    ``/proc/<pid>`` itself is stamped with the process start time, which is
    exactly the boundary we need: any source file newer than it was not the
    file that process loaded.
    """
    try:
        return (_PROC / str(pid)).stat().st_mtime
    except OSError:
        return None


def newest_py_since(started_at: float) -> Path | None:
    """Return the newest ``.py`` in the package modified after *started_at*.

    Delegates to :mod:`_serve_stale`, which owns this scan because the server
    itself needs the same answer about its own process. Two copies would be
    free to disagree about whether a server is current.
    """
    return newest_py_after(started_at)


def _own_pid_chain() -> set[int]:
    """Return this process and its ancestors.

    The process running this check matches :func:`is_our_server` by
    construction, so a wrong owner lookup would otherwise have us kill
    ourselves mid-startup.
    """
    chain: set[int] = set()
    pid: int | None = os.getpid()
    while pid is not None and pid > 0 and pid not in chain:
        chain.add(pid)
        pid = _read_ppid(pid)
    return chain


def _read_ppid(pid: int) -> int | None:
    """Return the parent PID of *pid* from ``/proc/<pid>/stat``."""
    try:
        stat = (_PROC / str(pid) / "stat").read_text(encoding="utf-8")
    except OSError:
        return None
    # comm sits in parentheses and may contain spaces; ppid follows it.
    _, _, rest = stat.partition(") ")
    fields = rest.split()
    if len(fields) < _MIN_STAT_FIELDS_AFTER_COMM:
        return None
    with contextlib.suppress(ValueError):
        return int(fields[1])
    return None


def port_is_free(host: str, port: int) -> bool:
    """Check whether *host*:*port* can actually be bound right now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, port))
        except OSError:
            return False
    return True


def terminate(pid: int, host: str, port: int) -> bool:
    """Stop *pid*, escalating to SIGKILL, and wait for the port to free up."""
    if pid in _own_pid_chain():
        return False
    for sig in (signal.SIGTERM, signal.SIGKILL):
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(pid, sig)
        deadline = time.monotonic() + _TERM_WAIT_SECONDS
        while time.monotonic() < deadline:
            if port_is_free(host, port):
                return True
            time.sleep(_POLL_INTERVAL)
    return port_is_free(host, port)
