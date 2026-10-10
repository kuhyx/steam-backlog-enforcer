"""Bill the downtime of a requested restart, so restarting is not free play.

The budget measures wall-clock deltas between ticks and clamps each one to two
tick intervals (so a suspend cannot inflate the count). A restart is the one
gap that clamp would wrongly forgive: ``RestartSec`` plus interpreter start plus
the startup pass can be tens of seconds, and the first tick would bill only 6 s
of it -- repeatable free play every ten minutes.

So the exiting daemon leaves a root-only marker with its exit time, and the
next daemon spends it on its first tick by widening that one tick's interval to
cover the gap. The marker is deleted before it is used, expires after
``MAX_GAP_SECONDS`` and only a *requested* restart writes one, so a crash or a
long outage never over-bills and the clamp still protects against suspends.
A tick with no qualifying process bills nothing whatever its interval.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import time
from typing import TYPE_CHECKING, Final

from steam_backlog_enforcer._playtime import playtime_tick
from steam_backlog_enforcer.config import _atomic_write

if TYPE_CHECKING:
    from steam_backlog_enforcer._playtime_session import PlaytimeSession
    from steam_backlog_enforcer.config import Config

logger = logging.getLogger(__name__)

# Beside the restart rate limit (StateDirectory=, root only).
RESTART_EXIT_FILE: Final = Path("/var/lib/steam-backlog-enforcer/ctl_restart_exit.json")
MAX_GAP_SECONDS: Final = 300.0
_MARKER_MODE: Final = 0o600


def record_exit() -> None:
    """Leave the exit-time marker for the next daemon. Never raises."""
    try:
        _atomic_write(
            RESTART_EXIT_FILE,
            json.dumps({"exited_at": time.time()}) + "\n",
            mode=_MARKER_MODE,
        )
    except OSError:
        logger.warning("Cannot record the restart exit time; the gap goes unbilled")


def _drop_marker() -> None:
    """Delete the marker; a caller without root rights just leaves it."""
    try:
        RESTART_EXIT_FILE.unlink(missing_ok=True)
    except OSError:
        logger.debug("Cannot delete the restart exit marker", exc_info=True)


def _take_exit_time() -> float | None:
    """Read and delete the marker; ``None`` if absent or unusable."""
    try:
        raw = json.loads(RESTART_EXIT_FILE.read_text(encoding="utf-8"))
        exited = raw["exited_at"]
    except OSError, ValueError, KeyError, TypeError:
        return None
    finally:
        _drop_marker()
    return float(exited) if isinstance(exited, int | float) else None


def settle_restart_gap(
    config: Config,
    session: PlaytimeSession,
    *,
    base_interval: float,
    demo: bool,
) -> None:
    """Bill the time since a requested restart's exit, once.

    Args:
        config: Enforcer configuration.
        session: The new daemon's logging session.
        base_interval: The normal tick interval (lower bound for the widened one).
        demo: Whether this is a demo run (never settles).
    """
    # A demo run (often the desktop user, via the web UI) must not touch the
    # daemon's root-only marker at all, let alone consume it.
    if demo:
        return
    exited = _take_exit_time()
    if exited is None:
        return
    gap = time.time() - exited
    if not 0 < gap <= MAX_GAP_SECONDS:
        return
    logger.info("Billing %.0f s of restart downtime.", gap)
    # accumulate() clamps a delta to 2 x interval; this admits exactly the gap.
    playtime_tick(
        config, interval=max(base_interval, gap / 2 + 1), session=session, demo=demo
    )
