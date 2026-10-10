"""The two-phase gaming reset as control-socket ops.

``gaming_reset_arm`` -> (``gaming_reset_heartbeat`` every <= 10 s for the whole
countdown) -> ``gaming_reset_commit``. The phrase is checked at arm *and*
again at commit, the countdown and heartbeat bookkeeping live in
:mod:`steam_backlog_enforcer._ctl_pending`, and the reset itself is the same
core the CLI runs (:func:`steam_backlog_enforcer._gaming_reset.reset_today`).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Final

from steam_backlog_enforcer._ctl_context import (
    check_locks,
    hold_tick,
    require_phrase,
    str_arg,
)
from steam_backlog_enforcer._ctl_pending import (
    HEARTBEAT_INTERVAL_SECONDS,
    LAPSE_AFTER_SECONDS,
)
from steam_backlog_enforcer._ctl_protocol import OP_FAILED, CtlError
from steam_backlog_enforcer._friction import expected_phrase
from steam_backlog_enforcer._gaming_reset import reset_today

if TYPE_CHECKING:
    from steam_backlog_enforcer._ctl_context import CtlContext
    from steam_backlog_enforcer._ctl_pending import Pending

logger = logging.getLogger(__name__)

_COMMAND: Final = "gaming-reset"


def _view(pending: Pending) -> dict[str, object]:
    """The wire form of a pending reset (the contract's ``PendingAction``)."""
    return {
        "pending_id": pending.pending_id,
        "phrase": expected_phrase(_COMMAND),
        "armed_at": pending.armed_at.isoformat(),
        "ready_at": pending.ready_at.isoformat(),
        "heartbeat_interval_seconds": HEARTBEAT_INTERVAL_SECONDS,
        "lapse_after_seconds": LAPSE_AFTER_SECONDS,
    }


def op_arm(ctx: CtlContext, args: dict[str, object]) -> dict[str, object]:
    """Start the countdown (or return the one already running)."""
    require_phrase(_COMMAND, args.get("phrase"))
    check_locks(_COMMAND)
    pending = ctx.pending.arm()
    logger.warning("Gaming reset armed; ready at %s", pending.ready_at.isoformat())
    return _view(pending)


def op_heartbeat(ctx: CtlContext, args: dict[str, object]) -> dict[str, object]:
    """Keep the armed reset alive."""
    return _view(ctx.pending.beat(str_arg(args, "pending_id")))


def op_commit(ctx: CtlContext, args: dict[str, object]) -> dict[str, object]:
    """Run the reset, if the countdown finished and the phrase still matches."""
    pending_id = str_arg(args, "pending_id")
    ctx.pending.check_ready(pending_id)
    require_phrase(_COMMAND, args.get("phrase"))
    with hold_tick(ctx):
        # Authoritative re-check under the lock: of two racing commits only
        # the first finds the pending reset still there.
        ctx.pending.check_ready(pending_id)
        check_locks(_COMMAND)
        try:
            outcome = reset_today(source="ctl")
        except OSError as exc:
            logger.exception("Gaming reset failed")
            raise CtlError(OP_FAILED, f"the reset failed: {exc}") from exc
        ctx.pending.finish(pending_id)
    logger.warning(
        "Gaming reset committed: %.0f s billed before, %d mount(s) released",
        outcome.seconds_before,
        len(outcome.released),
    )
    return {
        "day_key": outcome.day_key,
        "seconds_before": round(outcome.seconds_before, 3),
        "was_blocked": outcome.was_blocked,
        "released": [str(path) for path in outcome.released],
    }


def op_cancel(ctx: CtlContext, args: dict[str, object]) -> dict[str, object]:
    """Abandon the armed reset (idempotent)."""
    ctx.pending.finish(str_arg(args, "pending_id"))
    return {"cancelled": True}


RESET_OPS: Final = {
    "gaming_reset_arm": op_arm,
    "gaming_reset_heartbeat": op_heartbeat,
    "gaming_reset_commit": op_commit,
    "gaming_reset_cancel": op_cancel,
}
