"""Who may talk to the web server: Host, Origin and the per-launch token.

The contract's "Web server auth" section, in one place:

- ``Host`` must name this server on loopback (``127.0.0.1:<port>`` or
  ``localhost:<port>``) on *every* request, static files included. That is
  the DNS-rebinding guard: a page on ``evil.example`` re-pointed at
  127.0.0.1 still sends its own name as ``Host``, so it can read neither
  the data nor the ``index.html`` that carries the token.
- Every non-GET must carry ``Origin`` equal to the origin it was served from.
- Every non-GET, and the SSE stream (``EventSource`` cannot set headers, so
  it sends ``?token=``), must carry the per-launch token.

The token is 32 random bytes, regenerated at every launch, written owner-only
to ``$XDG_RUNTIME_DIR/steam-backlog-enforcer/web-<port>.token`` (per port, so
a scratch server on another port never clobbers the live one's file) and
injected into the served ``index.html`` as ``<meta name="sbe-token">``. A page from a
previous launch therefore stops working when the server restarts: the UI
must reload on ``bad_token``.
"""

from __future__ import annotations

import hmac
import os
from pathlib import Path
import re
import secrets
from typing import TYPE_CHECKING, Final

from steam_backlog_enforcer._web_errors import ApiError

if TYPE_CHECKING:
    from email.message import Message

# Where the token travels. Names, not secrets; the UI's copies are
# ``TOKEN_HEADER`` / ``TOKEN_META`` in web/src/api/contract.ts.
AUTH_HEADER: Final = "X-SBE-Token"
AUTH_META: Final = "sbe-token"
AUTH_QUERY: Final = "token"
_RUNTIME_SUBDIR: Final = "steam-backlog-enforcer"
_LOOPBACK_NAMES: Final = ("127.0.0.1", "localhost")
_HEAD_TAG = re.compile(rb"<head[^>]*>", re.IGNORECASE)


def new_token() -> str:
    """A fresh per-launch token: 32 random bytes as hex."""
    return secrets.token_hex(32)


def token_path(port: int) -> Path:
    """Where the token file of the server on *port* lives.

    ``$XDG_RUNTIME_DIR/steam-backlog-enforcer/web-<port>.token`` (runtime dir
    ``/run/user/<uid>`` when unset). The Vite dev server reads the same file.
    """
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return Path(runtime) / _RUNTIME_SUBDIR / f"web-{port}.token"


def write_token_file(token: str, port: int) -> Path:
    """Write *token* owner-only (dir 0700, file 0600) and return its path.

    The file is created with mode 0600 from the start, never chmod-ed after
    a world-readable write, and replaced atomically so a reader never sees a
    half-written token.
    """
    path = token_path(port)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, f"{token}\n".encode("ascii"))
    finally:
        os.close(fd)
    tmp.replace(path)
    return path


def allowed_hosts(port: int) -> frozenset[str]:
    """The ``Host`` header values this server answers to."""
    return frozenset(f"{name}:{port}" for name in _LOOPBACK_NAMES)


def check_host(headers: Message, port: int) -> str:
    """Return the validated ``Host`` header.

    Raises:
        ApiError: ``bad_host`` for a missing or foreign host.
    """
    host = (headers.get("Host") or "").strip().lower()
    if host not in allowed_hosts(port):
        msg = f"Host {host or '(none)'!r} is not this server."
        raise ApiError(msg, code="bad_host")
    return host


def check_origin(headers: Message, host: str) -> None:
    """Require ``Origin`` to be the origin this request's page came from.

    Raises:
        ApiError: ``bad_origin`` for a missing or different origin.
    """
    origin = (headers.get("Origin") or "").strip().lower()
    if origin != f"http://{host}":
        msg = f"Origin {origin or '(none)'!r} may not change state here."
        raise ApiError(msg, code="bad_origin")


def check_token(supplied: str | None, token: str) -> None:
    """Compare a supplied token in constant time.

    Raises:
        ApiError: ``bad_token`` for a missing or wrong token.
    """
    if not supplied or not hmac.compare_digest(supplied.encode(), token.encode()):
        msg = "Missing or stale token: reload the page."
        raise ApiError(msg, code="bad_token")


def inject_token(html: bytes, token: str) -> bytes:
    """Insert the token ``<meta>`` right after ``<head>`` in *html*."""
    meta = f'<meta name="{AUTH_META}" content="{token}">'.encode("ascii")
    match = _HEAD_TAG.search(html)
    if match is None:
        return meta + html
    return html[: match.end()] + meta + html[match.end() :]
