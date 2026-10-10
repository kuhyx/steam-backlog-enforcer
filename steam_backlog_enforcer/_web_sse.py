"""``GET /api/jobs/{id}/events``: a job's ``events.jsonl`` as Server-Sent Events.

Each event is one unnamed frame — ``id: <seq>`` and ``data: <JobEvent JSON>``
— so ``EventSource.onmessage`` sees every type and a reconnect resumes with
``Last-Event-ID``. That header wins over ``?after=``: ``EventSource`` keeps
the URL it was opened with, so on a reconnect ``after`` is stale.

The stream ends once the job is over: right after the final ``state`` event
that follows ``result`` (the runner writes them back to back), or a short
grace after ``result`` if that state never comes. It also ends when the
server stands down; the browser reconnects to its replacement and resumes.
The server only reads files here, so a job is unaffected by any of this.
"""

from __future__ import annotations

from http import HTTPStatus
import json
import time
from typing import TYPE_CHECKING, Any, Final

from steam_backlog_enforcer._web_errors import ApiError, from_job_error
from steam_backlog_enforcer._web_process import RETIRING
from steam_backlog_enforcer.jobs._errors import JobError
from steam_backlog_enforcer.jobs._events import TERMINAL_STATES
from steam_backlog_enforcer.jobs._view import read_job, read_job_events

if TYPE_CHECKING:
    from http.server import BaseHTTPRequestHandler

    from steam_backlog_enforcer._web_io import Request

_POLL_SECONDS: Final = 0.25
_KEEPALIVE_SECONDS: Final = 15.0
_RESULT_GRACE_SECONDS: Final = 2.0
_RETRY_MS: Final = 2000


def resume_after(request: Request) -> int:
    """The last seq the client has: ``Last-Event-ID``, else ``?after=``.

    Raises:
        ApiError: ``invalid_params`` for a non-numeric value.
    """
    raw = request.headers.get("Last-Event-ID") or request.query.get("after") or "0"
    try:
        return max(0, int(raw))
    except ValueError:
        msg = f"after must be an event seq, got {raw!r}"
        raise ApiError(msg, code="invalid_params") from None


def _frame(event: dict[str, Any]) -> bytes:
    """One SSE frame for *event*."""
    return f"id: {event['seq']}\ndata: {json.dumps(event)}\n\n".encode()


def _is_terminal_state(event: dict[str, Any]) -> bool:
    """Whether *event* is the job's final ``state`` transition."""
    return event.get("type") == "state" and event.get("state") in TERMINAL_STATES


def _pump(handler: BaseHTTPRequestHandler, job_id: str, after: int) -> None:
    """Write events as they appear until the job is over or we retire."""
    last_write = time.monotonic()
    result_at: float | None = None
    while not RETIRING.is_set():
        events = read_job_events(job_id, after)
        for event in events:
            handler.wfile.write(_frame(event))
            after = event["seq"]
            if event.get("type") == "result":
                result_at = time.monotonic()
            if _is_terminal_state(event):
                return
        now = time.monotonic()
        if events:
            handler.wfile.flush()
            last_write = now
        elif result_at is not None and now - result_at > _RESULT_GRACE_SECONDS:
            return
        elif result_at is None and read_job(job_id)["state"] in TERMINAL_STATES:
            return  # Resumed past the end of a finished job: nothing more.
        elif now - last_write >= _KEEPALIVE_SECONDS:
            handler.wfile.write(b": keep-alive\n\n")
            handler.wfile.flush()
            last_write = now
        time.sleep(_POLL_SECONDS)


def stream_job_events(handler: BaseHTTPRequestHandler, request: Request) -> None:
    """Serve the SSE stream for ``request.args[0]`` (auth already checked).

    Raises:
        ApiError: Before any byte is sent, for an unknown job or bad ``after``.
    """
    job_id = request.args[0]
    after = resume_after(request)
    try:
        read_job(job_id)
    except JobError as exc:
        raise from_job_error(exc) from None
    handler.close_connection = True
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Accel-Buffering", "no")
    handler.end_headers()
    try:
        handler.wfile.write(f"retry: {_RETRY_MS}\n\n".encode())
        _pump(handler, job_id, after)
        handler.wfile.flush()
    except BrokenPipeError, ConnectionResetError:
        return  # The browser went away; it will reconnect if it cares.
