"""Pure state transitions for the daily playtime budget.

Separated from persistence: nothing here touches the disk or the clock
beyond what it is handed, which is what makes the budget arithmetic
straightforward to test.
"""

from __future__ import annotations

from dataclasses import replace
import logging
from typing import TYPE_CHECKING

from steam_backlog_enforcer._playtime_state import (
    _DELTA_CLAMP_FACTOR,
    PlaytimeRules,
    PlaytimeState,
)

if TYPE_CHECKING:
    from datetime import datetime

logger = logging.getLogger(__name__)


def accumulate(
    state: PlaytimeState,
    *,
    now: datetime,
    qualifying: set[int],
    interval: float,
) -> PlaytimeState:
    """Add this tick's elapsed gaming time to *state*.

    Pure. Every argument is mandatory, including the clock — a defaulted ``now``
    would add a branch that exists only to be covered.

    The delta is clamped to ``_DELTA_CLAMP_FACTOR`` intervals so that a suspend,
    a skipped tick or a forward NTP step cannot inflate the count, and floored
    at zero so a backward step cannot refund time.

    Args:
        state: Current accounting state.
        now: Timezone-aware local timestamp for this tick.
        qualifying: PIDs currently counting against the budget.
        interval: Nominal seconds between ticks.

    Returns:
        The updated state.
    """
    stamp = now.timestamp()
    if state.last_tick_at <= 0.0:
        return replace(state, last_tick_at=stamp)

    delta = stamp - state.last_tick_at
    if delta <= 0.0 or not qualifying:
        return replace(state, last_tick_at=stamp)

    credited = min(delta, interval * _DELTA_CLAMP_FACTOR)
    return replace(state, last_tick_at=stamp, seconds=state.seconds + credited)


def roll_over(state: PlaytimeState, *, day_key: str) -> PlaytimeState:
    """Reset *state* if the gaming day has changed.

    Pure. ``last_tick_at`` carries across the boundary so the first tick of the
    new day measures a sane delta rather than restarting from zero.

    Args:
        state: Current accounting state.
        day_key: The gaming day *now* falls in.

    Returns:
        Either *state* unchanged, or a fresh record for *day_key*.
    """
    if state.day_key == day_key:
        return state
    return PlaytimeState(day_key=day_key, last_tick_at=state.last_tick_at)


def pending_warning(state: PlaytimeState, rules: PlaytimeRules) -> int | None:
    """Return the largest un-fired warning threshold *state* has crossed.

    Pure. Returning only the largest matters when a tick is skipped: crossing
    two thresholds at once should warn once, not twice.

    Args:
        state: Current accounting state.
        rules: Policy for this tick.

    Returns:
        The threshold in seconds-remaining, or ``None`` if none is due.
    """
    remaining = rules.budget_seconds - state.seconds
    for threshold in rules.warn_at:
        if remaining <= threshold and threshold not in state.warned_seconds:
            return threshold
    return None
