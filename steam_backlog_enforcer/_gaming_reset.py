"""The gaming-reset core: zero today's counter, lift the block, leave a record.

Shared by the CLI (``sudo ./run.sh gaming-reset``, the direct recovery path)
and the daemon's two-phase control-socket op, so both do exactly the same
thing and both leave the same trail. The caller owns the confirmation
(``YES`` on the CLI, a phrase plus a heartbeat countdown on the socket).

Needs root: it releases bind mounts and writes the immutable state file.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
import logging
from typing import TYPE_CHECKING

from steam_backlog_enforcer._gaming_days import gaming_day_key
from steam_backlog_enforcer._playtime_block import release_block
from steam_backlog_enforcer._playtime_budget import roll_over
from steam_backlog_enforcer._playtime_history import record_day
from steam_backlog_enforcer._playtime_log import (
    EVENT_MANUAL_ADJUSTMENT,
    BudgetLog,
    budget_log_path,
)
from steam_backlog_enforcer._playtime_state import (
    PlaytimeState,
    load_state,
    save_state,
)

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResetOutcome:
    """What a gaming reset changed.

    Attributes:
        day_key: The gaming day that was reset.
        seconds_before: Seconds billed before the reset.
        was_blocked: Whether the cutoff had engaged.
        released: Launcher mounts that were released.
    """

    day_key: str
    seconds_before: float
    was_blocked: bool
    released: list[Path]


def reset_today(*, source: str) -> ResetOutcome:
    """Zero today's billed time, drop the block and record the adjustment.

    The earned-time bookkeeping (``carry`` from earlier free days, the day's
    ``budget_seconds`` high-water mark) is kept: resetting spent time must not
    also revoke time already earned. Warnings re-arm because ``seconds`` is
    back at zero.

    The reset is written to the budget audit log as a ``manual_adjustment``
    (with what was billed before, per game); that record is the auditable
    trail. The per-day history is also set to 0 -- it mirrors *current* billed
    time, so it shows the day as quiet and the audit log is what says why.

    Args:
        source: Who asked (``"cli"`` or ``"ctl"``), stored in the audit record.

    Returns:
        What changed.
    """
    now = datetime.now(UTC).astimezone()
    day_key = gaming_day_key(now)
    stored = load_state(demo=False)
    before = roll_over(stored, day_key=day_key) if stored else PlaytimeState()
    released = release_block()
    save_state(
        replace(
            before,
            day_key=day_key,
            seconds=0.0,
            blocked_at=0.0,
            last_tick_at=now.timestamp(),
            per_game={},
            last_credited_key="",
            warned_seconds=[],
        ),
        demo=False,
    )
    _record(source, day_key, before, released)
    return ResetOutcome(
        day_key=day_key,
        seconds_before=before.seconds,
        was_blocked=before.is_blocked(),
        released=released,
    )


def _record(
    source: str, day_key: str, before: PlaytimeState, released: list[Path]
) -> None:
    """Write the audit record and the history point; never raises."""
    log = BudgetLog(path=budget_log_path(demo=False))
    log.record(
        EVENT_MANUAL_ADJUSTMENT,
        kind="gaming_reset",
        source=source,
        day_key=day_key,
        billed_seconds_before=round(before.seconds, 3),
        billed_seconds_after=0.0,
        per_game_before=before.per_game,
        was_blocked=before.is_blocked(),
        released=[str(path) for path in released],
    )
    log.close()
    try:
        record_day(day_key, 0.0, {})
    except OSError as exc:
        # A history point is cosmetic; the reset itself already happened.
        logger.warning("Could not record the reset in the history: %s", exc)
