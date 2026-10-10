"""The root daemon as the web API sees it: status, and the two-phase reset.

Every call goes through :func:`daemon_call`, which turns the client's
``DaemonUnreachableError`` / ``CtlError`` into contract errors. Calls block for
as long as the daemon takes (up to its own timeouts); each request has its
own thread (``ThreadingHTTPServer``), so a slow op stalls nobody else.

The daemon answers the two-phase reset with ``pending_id`` and an extra
``lapse_after_seconds``; :func:`pending_action` maps that onto the
contract's ``PendingAction``.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Final

from steam_backlog_enforcer import _ctl_client
from steam_backlog_enforcer._ctl_protocol import CtlError, DaemonUnreachableError
from steam_backlog_enforcer._web_errors import (
    ApiError,
    daemon_unreachable,
    from_ctl_error,
)
from steam_backlog_enforcer._web_io import Reply, no_content, ok
from steam_backlog_enforcer.jobs._daemon_jobs import (
    EXIT_FAILED,
    EXIT_OK,
    DaemonOutcome,
    record_daemon_job,
)
from steam_backlog_enforcer.jobs._events import now_iso
from steam_backlog_enforcer.jobs._view import read_job

if TYPE_CHECKING:
    from collections.abc import Callable

    from steam_backlog_enforcer._ctl_types import PendingReset
    from steam_backlog_enforcer._web_io import Request

_JOURNAL_LINES: Final = 50
_RESET: Final = "gaming-reset"


def daemon_call[**P, R](fn: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> R:
    """Run one control-socket call, mapping its failures to :class:`ApiError`.

    Raises:
        ApiError: ``daemon_unreachable`` (503) or the daemon's own code.
    """
    try:
        return fn(*args, **kwargs)
    except DaemonUnreachableError as exc:
        raise daemon_unreachable(str(exc)) from None
    except CtlError as exc:
        raise from_ctl_error(exc) from None


def daemon_view(_request: Request) -> Reply:
    """``GET /api/daemon`` — ``state: 'unreachable'`` when nobody answers."""
    try:
        info = _ctl_client.status()
    except DaemonUnreachableError:
        return ok(
            {
                "state": "unreachable",
                "started_at": None,
                "pid": None,
                "journal_tail": [],
                "restart_available_at": None,
            }
        )
    except CtlError as exc:
        raise from_ctl_error(exc) from None
    try:
        journal = _ctl_client.journal_tail(_JOURNAL_LINES)
    except DaemonUnreachableError, CtlError:
        journal = []  # The status still stands without its log.
    return ok(
        {
            "state": info.state,
            "started_at": info.started_at,
            "pid": info.pid,
            "journal_tail": journal,
            "restart_available_at": info.restart_available_at,
        }
    )


def pending_action(pending: PendingReset) -> dict[str, object]:
    """The contract ``PendingAction`` for an armed gaming reset."""
    return {
        "id": pending.pending_id,
        "command": _RESET,
        "phrase": pending.phrase,
        "armed_at": pending.armed_at,
        "ready_at": pending.ready_at,
        "heartbeat_interval_seconds": pending.heartbeat_interval_seconds,
    }


def confirm_phrase_of(request: Request) -> str:
    """The typed phrase from a body (``confirm_phrase``; ``confirmPhrase`` too)."""
    raw = request.body.get("confirm_phrase", request.body.get("confirmPhrase"))
    if raw is None:
        return ""
    if not isinstance(raw, str):
        msg = "confirm_phrase must be a string."
        raise ApiError(msg, code="invalid_params")
    return raw


def heartbeat_view(request: Request) -> Reply:
    """``POST /api/pending/{id}/heartbeat`` — keep the countdown alive."""
    pending = daemon_call(_ctl_client.gaming_reset_heartbeat, request.args[0])
    return ok(pending_action(pending))


def cancel_pending_view(request: Request) -> Reply:
    """``DELETE /api/pending/{id}`` — abandon the armed reset."""
    daemon_call(_ctl_client.gaming_reset_cancel, request.args[0])
    return no_content()


def commit_view(request: Request) -> Reply:
    """``POST /api/pending/{id}/commit`` — run the reset, record it as a job."""
    created_at = now_iso()
    try:
        result = daemon_call(
            _ctl_client.gaming_reset_commit,
            request.args[0],
            confirm_phrase_of(request),
        )
    except ApiError as exc:
        if exc.code == "op_failed":
            failed = DaemonOutcome(ok=False, summary=exc.message, exit_code=EXIT_FAILED)
            record_daemon_job(_RESET, {}, created_at=created_at, outcome=failed)
        raise
    minutes = result.seconds_before / 60
    summary = f"Today's gaming budget reset ({minutes:.0f} min billed before)."
    done = DaemonOutcome(
        ok=True,
        summary=summary,
        exit_code=EXIT_OK,
        data={
            "day_key": result.day_key,
            "seconds_before": result.seconds_before,
            "was_blocked": result.was_blocked,
            "released": result.released,
        },
    )
    job_id = record_daemon_job(_RESET, {}, created_at=created_at, outcome=done)
    return Reply(HTTPStatus.CREATED, read_job(job_id))
