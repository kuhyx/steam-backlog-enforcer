"""Request and reply plumbing shared by every API route.

Routes are plain functions ``(Request) -> Reply``; this module turns the raw
``BaseHTTPRequestHandler`` into a :class:`Request` (body size cap, JSON
content-type check) and writes a :class:`Reply` or an
:class:`~steam_backlog_enforcer._web_errors.ApiError` back. No CORS headers
are ever sent: the API is same-origin only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from http import HTTPStatus
import json
from typing import TYPE_CHECKING, Any, Final

from steam_backlog_enforcer._web_errors import ApiError

if TYPE_CHECKING:
    from email.message import Message
    from http.server import BaseHTTPRequestHandler


# Requests are a handful of short fields; the cap stops a client from
# making the server buffer an arbitrary upload.
MAX_BODY_BYTES: Final = 64 * 1024


@dataclass(frozen=True)
class Request:
    """One parsed API request.

    Attributes:
        method: ``GET``, ``POST`` or ``DELETE``.
        path: URL path without the query.
        query: Parsed query string (first value per key).
        args: Path segments captured by the route pattern.
        headers: The raw request headers.
        body: Parsed JSON object body (empty when there was none).
    """

    method: str
    path: str
    query: dict[str, str]
    args: tuple[str, ...]
    headers: Message
    body: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Reply:
    """A route's answer: a status and an optional JSON payload.

    A route that answers with something other than JSON (cover art) sets
    *raw* and *ctype* instead; *headers* are sent as they are.
    """

    status: HTTPStatus
    payload: object = None
    raw: bytes | None = None
    ctype: str = ""
    headers: dict[str, str] = field(default_factory=dict)


def ok(payload: object) -> Reply:
    """A ``200`` with *payload* as JSON."""
    return Reply(HTTPStatus.OK, payload)


def no_content() -> Reply:
    """A ``204`` with no body."""
    return Reply(HTTPStatus.NO_CONTENT)


def read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    """Read and parse the request body; an absent body is ``{}``.

    Raises:
        ApiError: ``invalid_params`` (413/415/400) for an oversized,
            non-JSON or malformed body.
    """
    if handler.headers.get("Transfer-Encoding"):
        msg = "Chunked request bodies are not accepted; send Content-Length."
        raise ApiError(msg, code="invalid_params", status=HTTPStatus.LENGTH_REQUIRED)
    try:
        length = int(handler.headers.get("Content-Length") or 0)
    except ValueError:
        msg = "Content-Length is not a number."
        raise ApiError(msg, code="invalid_params") from None
    if length <= 0:
        return {}
    if length > MAX_BODY_BYTES:
        msg = f"Request body over {MAX_BODY_BYTES} bytes."
        raise ApiError(
            msg, code="invalid_params", status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE
        )
    ctype = (handler.headers.get("Content-Type") or "").split(";", 1)[0].strip()
    if ctype.lower() != "application/json":
        msg = "Request bodies must be application/json."
        raise ApiError(
            msg, code="invalid_params", status=HTTPStatus.UNSUPPORTED_MEDIA_TYPE
        )
    try:
        body = json.loads(handler.rfile.read(length))
    except ValueError:
        msg = "Request body is not valid JSON."
        raise ApiError(msg, code="invalid_params") from None
    if not isinstance(body, dict):
        msg = "Request body must be a JSON object."
        raise ApiError(msg, code="invalid_params")
    return body


def send_bytes(
    handler: BaseHTTPRequestHandler,
    status: HTTPStatus,
    body: bytes,
    ctype: str,
    headers: dict[str, str] | None = None,
) -> None:
    """Write a complete response with a fixed-length body."""
    handler.send_response(status)
    handler.send_header("Content-Type", ctype)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("X-Content-Type-Options", "nosniff")
    for name, value in (headers or {}).items():
        handler.send_header(name, value)
    handler.end_headers()
    if body:
        handler.wfile.write(body)


def send_reply(handler: BaseHTTPRequestHandler, reply: Reply) -> None:
    """Write a route's :class:`Reply` (``None`` payload means no body)."""
    if reply.raw is not None:
        send_bytes(handler, reply.status, reply.raw, reply.ctype, reply.headers)
        return
    if reply.payload is None:
        # 202/204 without a body: no Content-Type, nothing to sniff.
        handler.send_response(reply.status)
        handler.send_header("Content-Length", "0")
        handler.end_headers()
        return
    body = json.dumps(reply.payload).encode("utf-8")
    send_bytes(
        handler,
        reply.status,
        body,
        "application/json; charset=utf-8",
        {"Cache-Control": "no-store"},
    )


def send_error(handler: BaseHTTPRequestHandler, error: ApiError) -> None:
    """Write an :class:`ApiError` as the contract's error body."""
    body = json.dumps(error.body()).encode("utf-8")
    send_bytes(
        handler,
        error.status,
        body,
        "application/json; charset=utf-8",
        {"Cache-Control": "no-store", **error.headers()},
    )
