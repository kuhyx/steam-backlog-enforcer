"""The server process itself: when it started, what code it runs, stand-down.

``ServerHealth`` (``GET /api/server``) and ``POST /api/server/restart`` live
here, next to the retirement switch the stale-code check
(:mod:`steam_backlog_enforcer._serve_stale`) already used: a restart is the
same stand-down, asked for instead of detected. Exiting is enough because
``steam-backlog-enforcer-web.service`` has ``Restart=always``; jobs survive
it, being their own processes in their own systemd scopes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from functools import cache
from http import HTTPStatus
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
from typing import TYPE_CHECKING, Final

from steam_backlog_enforcer._serve_stale import newest_py_after, outdated_source
from steam_backlog_enforcer._web_errors import ApiError
from steam_backlog_enforcer._web_io import Reply, ok

if TYPE_CHECKING:
    from socketserver import BaseServer

    from steam_backlog_enforcer._web_io import Request

# Epoch seconds this process began, captured at import. Anything in the
# package newer than this is code we did not load.
STARTED_AT: Final = time.time()
# Set once the server has begun standing down, so concurrent requests do
# not each spawn a shutdown thread (and SSE streams know to end).
RETIRING: Final = threading.Event()
# Long enough for the 202 to leave before the process goes.
_RESTART_DELAY_SECONDS: Final = 0.5
_REPO_ROOT: Final = Path(__file__).resolve().parent.parent
_server: list[BaseServer] = []


def register(server: BaseServer) -> None:
    """Remember the running server so :func:`retire` can stop it."""
    _server[:] = [server]


def retire(delay: float = 0.0) -> None:
    """Stop serving (once) so the supervisor starts current code.

    ``shutdown`` blocks until ``serve_forever`` returns and cannot run on a
    request thread, so it gets its own; *delay* lets the reply that asked
    for it reach the client first.
    """
    if RETIRING.is_set() or not _server:
        return
    RETIRING.set()
    timer = threading.Timer(delay, _server[0].shutdown)
    timer.daemon = True
    timer.start()


def _iso(epoch: float) -> str:
    """Epoch seconds as ISO-8601 UTC with a ``Z`` suffix."""
    return datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@cache
def version() -> str:
    """The git short sha of the checkout, else the newest source mtime."""
    git = shutil.which("git")
    if git is not None:
        try:
            out = subprocess.run(
                [git, "-C", str(_REPO_ROOT), "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            )
        except OSError, subprocess.SubprocessError:
            pass
        else:
            return out.stdout.strip()
    newest = newest_py_after(0.0)
    return _iso(newest.stat().st_mtime) if newest else "unknown"


def health() -> dict[str, object]:
    """The contract ``ServerHealth``."""
    return {
        "stale": outdated_source(STARTED_AT) is not None,
        "started_at": _iso(STARTED_AT),
        "version": version(),
    }


def health_view(_request: Request) -> Reply:
    """``GET /api/server``."""
    return ok(health())


def restart_view(_request: Request) -> Reply:
    """``POST /api/server/restart`` — answer 202, then exit for systemd.

    Raises:
        ApiError: ``unsupported`` when no supervisor would bring the server
            back (started by hand, the restart would be a stop).
    """
    if not os.environ.get("INVOCATION_ID"):
        msg = "This server is not running under systemd; a restart would stop it."
        raise ApiError(msg, code="unsupported")
    retire(_RESTART_DELAY_SECONDS)
    return Reply(HTTPStatus.ACCEPTED)
