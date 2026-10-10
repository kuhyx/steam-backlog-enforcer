"""The ``restart`` op: the only way the socket ever ends the daemon process.

There is deliberately no stop. A restart asks the enforce loop to finish the
pass it is in, bill the time up to now, and exit; ``Restart=always`` in the
unit brings it straight back. Because that makes a restart cost a few seconds
of downtime (and a fresh startup pass), it is rate limited to one per ten
minutes, and the limit is persisted in a root-owned file so restarting the
daemon cannot reset it.

Safety analysis (what a restart does and does not lose, and how the downtime is
billed) is in ``DOCS-ctl-socket.md``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import logging
from pathlib import Path
import threading
import time
from typing import TYPE_CHECKING, Final

from steam_backlog_enforcer._ctl_protocol import (
    OP_FAILED,
    RATE_LIMITED,
    UNSUPPORTED,
    CtlError,
)
from steam_backlog_enforcer.config import _atomic_write

if TYPE_CHECKING:
    from steam_backlog_enforcer._ctl_context import CtlContext

logger = logging.getLogger(__name__)

RESTART_INTERVAL_SECONDS: Final = 600
# Created by StateDirectory=steam-backlog-enforcer in the unit.
RESTART_STATE_FILE: Final = Path("/var/lib/steam-backlog-enforcer/ctl_restart.json")
_STATE_MODE: Final = 0o600

# Serialises concurrent restart requests so two cannot both pass the check.
_restart_lock = threading.Lock()


def _last_restart() -> float:
    """Epoch seconds of the last accepted restart; ``0.0`` if none or unreadable."""
    try:
        raw = json.loads(RESTART_STATE_FILE.read_text(encoding="utf-8"))
        value = raw["last_restart_at"]
    except OSError, ValueError, KeyError, TypeError:
        return 0.0
    return float(value) if isinstance(value, int | float) else 0.0


def seconds_until_available() -> float:
    """Seconds before another restart is allowed; ``0`` if one is allowed now.

    A recorded time in the future (clock stepped backwards) counts as "now", so
    the wait can never exceed the interval.
    """
    elapsed = max(0.0, time.time() - _last_restart())
    return max(0.0, RESTART_INTERVAL_SECONDS - elapsed)


def restart_available_at() -> str | None:
    """ISO time a restart becomes allowed again, or ``None`` if allowed now."""
    wait = seconds_until_available()
    if wait <= 0:
        return None
    return (datetime.now(UTC) + timedelta(seconds=wait)).isoformat()


def op_restart(ctx: CtlContext, _args: dict[str, object]) -> dict[str, object]:
    """Ask the daemon to restart itself (flush, exit, systemd brings it back).

    Raises:
        CtlError: ``unsupported`` when systemd is not supervising the process
            (the exit would be a stop), ``rate_limited`` inside the interval,
            ``op_failed`` if the limit could not be persisted (fail closed).
    """
    if not ctx.supervised:
        raise CtlError(
            UNSUPPORTED,
            "the daemon is not running under systemd; a restart would be a stop",
        )
    with _restart_lock:
        wait = seconds_until_available()
        if wait > 0:
            raise CtlError(
                RATE_LIMITED,
                f"restart allowed again in {wait:.0f} s",
                {"retry_after_seconds": round(wait, 1)},
            )
        try:
            _atomic_write(
                RESTART_STATE_FILE,
                json.dumps({"last_restart_at": time.time()}) + "\n",
                mode=_STATE_MODE,
            )
        except OSError as exc:
            logger.exception("Cannot persist the restart rate limit")
            raise CtlError(OP_FAILED, "cannot record the restart; refusing") from exc
        logger.warning("Restart requested over the control socket.")
        ctx.restart_event.set()
    return {"restarting": True, "restart_available_at": restart_available_at()}


RESTART_OPS: Final = {"restart": op_restart}
