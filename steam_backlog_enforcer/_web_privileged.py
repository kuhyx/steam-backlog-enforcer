"""Privileged commands: ``POST /api/jobs`` requests the root daemon carries out.

The web server never gets root, so ``unblock``, ``buy-dlc``, ``block-gaming``,
``gaming-unblock``, ``gaming-reset`` and the real ``enforce`` restart become
control-socket ops. The typed phrase is passed through untouched: the daemon
is the trust boundary and checks it, along with the locks and caps.

A completed op is recorded as a finished job (:mod:`.jobs._daemon_jobs`) so
it shows in the same history as everything else; so is an op the daemon
ran and failed (``op_failed``). Refusals — wrong phrase, locked, rate limited,
daemon unreachable — are answered as errors and leave no job behind.
``gaming-reset`` answers ``202`` with a ``PendingAction`` instead: its job is
written when it is committed (:func:`._web_daemon.commit_view`).
"""

from __future__ import annotations

from datetime import datetime
from http import HTTPStatus
from typing import TYPE_CHECKING, Final

from steam_backlog_enforcer import _ctl_client
from steam_backlog_enforcer._store_window import DEFAULT_WINDOW_MINUTES
from steam_backlog_enforcer._web_daemon import daemon_call, pending_action
from steam_backlog_enforcer._web_errors import ApiError
from steam_backlog_enforcer._web_io import Reply
from steam_backlog_enforcer.jobs._daemon_jobs import (
    EXIT_FAILED,
    EXIT_OK,
    DaemonOutcome,
    record_daemon_job,
)
from steam_backlog_enforcer.jobs._events import now_iso
from steam_backlog_enforcer.jobs._view import read_job

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from steam_backlog_enforcer._command_params import ParamValue

type Outcome = tuple[str, dict[str, object]]
type Op = Callable[[Mapping[str, ParamValue], str], Outcome]

# buy-dlc has no knobs: always the default-length store window.
BUY_DLC_MINUTES: Final = DEFAULT_WINDOW_MINUTES


def _local_hhmm(iso: str | None) -> str:
    """``HH:MM`` local time of an ISO timestamp (the raw text if unparsable)."""
    if not iso:
        return "?"
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%H:%M")
    except ValueError:
        return iso


def _store_window(minutes: int, phrase: str) -> Outcome:
    """Open the store for *minutes*."""
    window = daemon_call(_ctl_client.store_unblock, minutes, phrase)
    summary = (
        f"Store unblocked for {window.minutes} min, until {_local_hhmm(window.until)}."
    )
    return summary, {"minutes": window.minutes, "until": window.until}


def _unblock(params: Mapping[str, ParamValue], phrase: str) -> Outcome:
    """``unblock`` — a 1-30 minute store window."""
    return _store_window(int(params["minutes"]), phrase)


def _buy_dlc(_params: Mapping[str, ParamValue], phrase: str) -> Outcome:
    """``buy-dlc`` — the fixed default-length store window."""
    return _store_window(BUY_DLC_MINUTES, phrase)


def _block_gaming(params: Mapping[str, ParamValue], phrase: str) -> Outcome:
    """``block-gaming`` — the irreversible total block."""
    result = daemon_call(_ctl_client.block_gaming, int(params["days"]), phrase)
    summary = f"Total gaming block active for {result.days} day(s)."
    return summary, {"days": result.days, "until": result.until}


def _gaming_unblock(_params: Mapping[str, ParamValue], phrase: str) -> Outcome:
    """``gaming-unblock`` — force-release the playtime mounts."""
    released = daemon_call(_ctl_client.gaming_unblock, phrase)
    return f"Released {len(released)} playtime mount(s).", {"released": released}


def _restart(_params: Mapping[str, ParamValue], _phrase: str) -> Outcome:
    """``enforce`` (restart) — flush, exit, come back under systemd."""
    available = daemon_call(_ctl_client.restart)
    summary = "The enforcer daemon is restarting (state flushed first)."
    return summary, {"restart_available_at": available}


OPS: Final[dict[str, Op]] = {
    "unblock": _unblock,
    "buy-dlc": _buy_dlc,
    "block-gaming": _block_gaming,
    "gaming-unblock": _gaming_unblock,
    "enforce": _restart,
}


def run_privileged(
    command: str, params: Mapping[str, ParamValue], phrase: str | None
) -> Reply:
    """Carry out a privileged command through the daemon.

    Args:
        command: Canonical command name.
        params: Params already validated against the command's spec.
        phrase: ``JobRequest.confirm_phrase`` (checked by the daemon).

    Returns:
        ``201`` with the recorded ``Job``, or ``202`` with a
        ``PendingAction`` for ``gaming-reset``.

    Raises:
        ApiError: The daemon's refusal, mapped to its HTTP status.
    """
    typed = phrase or ""
    if command == "gaming-reset":
        pending = daemon_call(_ctl_client.gaming_reset_arm, typed)
        return Reply(HTTPStatus.ACCEPTED, pending_action(pending))
    op = OPS.get(command)
    if op is None:
        msg = f"{command!r} is not a daemon command."
        raise ApiError(msg, code="unknown_command")
    created_at = now_iso()
    try:
        summary, data = op(params, typed)
    except ApiError as exc:
        if exc.code == "op_failed":
            failed = DaemonOutcome(ok=False, summary=exc.message, exit_code=EXIT_FAILED)
            record_daemon_job(command, params, created_at=created_at, outcome=failed)
        raise
    done = DaemonOutcome(ok=True, summary=summary, exit_code=EXIT_OK, data=data)
    job_id = record_daemon_job(command, params, created_at=created_at, outcome=done)
    return Reply(HTTPStatus.CREATED, read_job(job_id))
