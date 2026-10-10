"""Shared builders for the control-socket tests."""

from __future__ import annotations

from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
import socket
import tempfile
import threading
from typing import TYPE_CHECKING

from steam_backlog_enforcer._ctl_context import CtlContext
from steam_backlog_enforcer.config import Config

if TYPE_CHECKING:
    from collections.abc import Iterator


def make_ctx(*, supervised: bool = True) -> CtlContext:
    """A fresh op context over a default config."""
    return CtlContext(
        config=Config(),
        tick_lock=threading.Lock(),
        restart_event=threading.Event(),
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
        supervised=supervised,
    )


@contextmanager
def short_socket_dir() -> Iterator[Path]:
    """A short-path temp dir: AF_UNIX paths are capped near 108 bytes."""
    with tempfile.TemporaryDirectory(prefix="ctl") as name:
        yield Path(name)


def serve_once(path: Path, reply: bytes) -> threading.Thread:
    """Answer exactly one connection on *path* with *reply*, then close.

    The listener is bound before this returns, so a client may connect at once.
    """
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(path))
    listener.listen(1)

    def run() -> None:
        conn, _ = listener.accept()
        with conn, listener:
            conn.settimeout(5)
            data = b""
            while b"\n" not in data:
                chunk = conn.recv(1024)
                if not chunk:
                    break
                data += chunk
            # The client may hang up mid-reply (the oversize case).
            if reply:
                with suppress(OSError):
                    conn.sendall(reply)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread
