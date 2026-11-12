"""Shared per-test reset of the web server's process-wide state."""

from __future__ import annotations

from contextlib import contextmanager
import threading
from typing import TYPE_CHECKING
from unittest.mock import patch

from steam_backlog_enforcer import _web_process, _web_server
from steam_backlog_enforcer._web_process import _server

if TYPE_CHECKING:
    from collections.abc import Iterator


def clean_process_state() -> Iterator[None]:
    """Clear the retiring flag and the server slot, never reporting "stale".

    A generator for ``yield from`` inside a module's autouse fixture, so
    other edits to the source tree cannot make a test see a stale server.
    """
    _web_process.RETIRING.clear()
    with patch("steam_backlog_enforcer._web_server.outdated_source", return_value=None):
        yield
    _web_process.RETIRING.clear()
    _server.clear()


@contextmanager
def running_server() -> Iterator[_web_server.WebServer]:
    """Serve on an ephemeral loopback port in a thread."""
    server = _web_server.create_server("127.0.0.1", 0)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
