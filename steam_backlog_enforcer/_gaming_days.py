"""Gaming-day arithmetic: which day *now* is, and what it already granted.

A gaming "day" runs 06:00-05:59 local, so late-night sessions count against
the day they started in.

There is no carry-over: unspent time is dropped at 06:00, every day. The
Friday-Monday carry ledger was removed on 2026-10-18, after a Sunday ran
past the 6.0h the i3 bar showed because 2h47m had been carried into it.
``load_state`` takes a legacy ledger's share back out of the stored
high-water mark.

Everything here is pure: it works on primitives handed to it, so it imports
nothing from the playtime modules and cannot close an import cycle.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from datetime import datetime

    from steam_backlog_enforcer._playtime_state import PlaytimeState

# The gaming day starts here, local time. 05:59 belongs to the previous day.
_DAY_BOUNDARY_HOURS: Final = 6


def gaming_day_key(now: datetime) -> str:
    """Return the ``YYYY-MM-DD`` gaming day containing *now*.

    The boundary is 06:00 local, so 02:00 on the 5th belongs to the 4th.

    Args:
        now: Timezone-aware local timestamp.

    Returns:
        The gaming day key.
    """
    return (now - timedelta(hours=_DAY_BOUNDARY_HOURS)).date().isoformat()


def held_today(stored: PlaytimeState | None, now: datetime) -> float:
    """Return the budget already granted earlier in *now*'s gaming day.

    Earners reset at calendar midnight but the gaming day runs to 05:59, and a
    cold restart starts with empty answer caches, so a live re-resolution can
    come in lower than what was granted hours ago. ``rules_for`` holds the day
    at this high-water mark so neither can cut a session off unwarned.

    Args:
        stored: The persisted production state, or ``None`` if unreadable.
        now: Local timestamp for this tick.

    Returns:
        The recorded high-water budget; 0 when the state is another day's.
    """
    if stored is None or stored.day_key != gaming_day_key(now):
        return 0.0
    return stored.budget_seconds


def held_shadow_today(stored: PlaytimeState | None, now: datetime) -> float:
    """Return the shadow leisure budget already granted in *now*'s gaming day.

    The same high-water rule as :func:`held_today`, for ``shadow_budget_seconds``.

    Args:
        stored: The persisted production state, or ``None`` if unreadable.
        now: Local timestamp for this tick.

    Returns:
        The recorded shadow high-water budget; 0 when the state is another day's.
    """
    if stored is None or stored.day_key != gaming_day_key(now):
        return 0.0
    return stored.shadow_budget_seconds
