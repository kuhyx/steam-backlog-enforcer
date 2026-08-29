"""Builders for a fake ``/proc`` tree used by the _serve_guard tests.

``_serve_guard`` was written to resolve port ownership through ``/proc`` rather
than ``ss`` precisely so it could be graded against a synthetic tree instead of
the host's real process table.  This module is that tree.

Note that ``_NET_TCP`` is derived from ``_PROC`` at import time, so redirecting
the guard needs *both* patched — see :func:`patch_proc`.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING
from unittest.mock import patch

from steam_backlog_enforcer import _serve_guard

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from pathlib import Path

# A real /proc/net/tcp row has 17 whitespace-separated columns. The guard reads
# only 1 (local address), 3 (state) and 9 (inode), but rejects short rows, so
# the surrounding columns have to be present and correctly positioned.
_REM_ADDRESS = "00000000:0000"
_QUEUES = "00000000:00000000 00:00000000 00000000"
_UID_TIMEOUT = "1000        0"
_ROW_TAIL = "1 0000000000000000 100 0 0 10 0"


def make_proc(root: Path) -> Path:
    """Create an empty fake ``/proc`` under *root* and return it."""
    proc = root / "proc"
    (proc / "net").mkdir(parents=True)
    for name in ("tcp", "tcp6"):
        write_net_tcp(proc, [], v6=name == "tcp6")
    return proc


def tcp_row(local: str, inode: object = 4242, state: str = "0A") -> str:
    """Render one ``/proc/net/tcp`` row for a socket at *local*.

    *inode* is deliberately untyped so a test can plant a non-numeric value in
    the column the guard parses with ``int()``.
    """
    return (
        f"   0: {local} {_REM_ADDRESS} {state} {_QUEUES} "
        f"{_UID_TIMEOUT} {inode} {_ROW_TAIL}"
    )


def write_net_tcp(proc: Path, rows: Sequence[str], *, v6: bool = False) -> None:
    """Write *rows* into ``net/tcp`` (or ``net/tcp6``) with a header line."""
    name = "tcp6" if v6 else "tcp"
    header = "  sl  local_address rem_address   st ...\n"
    (proc / "net" / name).write_text(header + "\n".join(rows), encoding="utf-8")


def add_pid(
    proc: Path,
    pid: int,
    *,
    inodes: Sequence[int] = (),
    cmdline: Sequence[str] = (),
    ppid: int | None = None,
) -> Path:
    """Create ``/proc/<pid>`` with the requested sockets, argv and parent."""
    pid_dir = proc / str(pid)
    pid_dir.mkdir()
    fd_dir = pid_dir / "fd"
    fd_dir.mkdir()
    for index, inode in enumerate(inodes):
        (fd_dir / str(index)).symlink_to(f"socket:[{inode}]")
    if cmdline:
        (pid_dir / "cmdline").write_bytes("\0".join(cmdline).encode("utf-8") + b"\0")
    if ppid is not None:
        # comm may contain spaces and parentheses; the guard splits on ") ".
        (pid_dir / "stat").write_text(
            f"{pid} (py thon) S {ppid} 1 1 0", encoding="utf-8"
        )
    return pid_dir


@contextmanager
def patch_proc(proc: Path) -> Iterator[None]:
    """Point the guard at *proc*, including the derived _NET_TCP tuple."""
    with (
        patch.object(_serve_guard, "_PROC", proc),
        patch.object(
            _serve_guard,
            "_NET_TCP",
            (proc / "net" / "tcp", proc / "net" / "tcp6"),
        ),
    ):
        yield


def add_opaque_pid(proc: Path, pid: int) -> Path:
    """Create a ``/proc/<pid>`` whose ``fd/`` cannot be opened.

    This is what another user's process looks like from here: it holds the
    port, but nothing about it can be attributed.
    """
    pid_dir = proc / str(pid)
    pid_dir.mkdir()
    (pid_dir / "fd").write_text("", encoding="utf-8")
    return pid_dir
