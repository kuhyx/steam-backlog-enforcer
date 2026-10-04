"""Gaming-day arithmetic: which day *now* is, and what it inherits.

A gaming "day" runs 06:00-05:59 local, so late-night sessions count against
the day they started in.

**Free-day carry-over.** Friday to Monday is one block. Whatever a Friday,
Saturday or Sunday leaves unspent is split evenly, with no strings attached,
across the days still left in that block:

    Fri leftover -> Sat, Sun, Mon (a third each)
    Sat leftover -> Sun, Mon      (half each)
    Sun leftover -> Mon

Monday's leftover, and any Tuesday-Thursday leftover, is dropped. A day's
leftover is measured against its whole budget *including* what it inherited,
so time carried into Saturday and not played moves on to Sunday and Monday
rather than being lost.

The ledger lives on ``PlaytimeState`` -- root-owned and immutable -- and never
in ``playtime_history.json``: that file is user-writable, and a stored budget
read from it would let anyone grant themselves unlimited time.

Everything here is pure: it works on primitives handed to it, so it imports
nothing from the playtime modules and cannot close an import cycle.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from datetime import datetime

    from steam_backlog_enforcer._playtime_state import PlaytimeState

# The gaming day starts here, local time. 05:59 belongs to the previous day.
_DAY_BOUNDARY_HOURS: Final = 6

# Weekday (Monday == 0) whose leftover is passed on -> how many later days of
# the Friday-Monday block share it.
_SHARES: Final = {4: 3, 5: 2, 6: 1}


def gaming_day_key(now: datetime) -> str:
    """Return the ``YYYY-MM-DD`` gaming day containing *now*.

    The boundary is 06:00 local, so 02:00 on the 5th belongs to the 4th.

    Args:
        now: Timezone-aware local timestamp.

    Returns:
        The gaming day key.
    """
    return (now - timedelta(hours=_DAY_BOUNDARY_HOURS)).date().isoformat()


def pass_on(
    carry: dict[str, float],
    *,
    outgoing_day: str,
    budget: float,
    spent: float,
    new_day: str,
) -> dict[str, float]:
    """Return the carry ledger as it stands once *new_day* begins.

    Shares owed to days before *new_day* are dropped, which both bounds the
    ledger and means a day the daemon never saw simply forfeits its share.

    Args:
        carry: Day key to seconds owed, as held by the outgoing day.
        outgoing_day: The gaming day that just ended; ``""`` if none.
        budget: The outgoing day's budget, carry included.
        spent: Seconds billed during the outgoing day.
        new_day: The gaming day now starting.

    Returns:
        The ledger for *new_day*, the outgoing day's leftover added.
    """
    owed = {day: seconds for day, seconds in carry.items() if day >= new_day}
    if not outgoing_day:
        return owed
    ended = date.fromisoformat(outgoing_day)
    shares = _SHARES.get(ended.weekday(), 0)
    leftover = max(0.0, budget - spent)
    for offset in range(1, shares + 1):
        target = (ended + timedelta(days=offset)).isoformat()
        if target >= new_day:
            owed[target] = owed.get(target, 0.0) + leftover / shares
    return owed


def carry_due(
    carry: dict[str, float],
    *,
    stored_day: str,
    budget: float,
    spent: float,
    today: str,
) -> float:
    """Return the seconds carried into *today*.

    The stored record may still describe yesterday -- the first tick after
    06:00 resolves the budget before rolling the state over -- so the ledger is
    projected forward exactly as ``roll_over`` will do it.

    Args:
        carry: The stored ledger.
        stored_day: The gaming day the stored record covers.
        budget: That day's budget, carry included.
        spent: Seconds billed during that day.
        today: The current gaming day.

    Returns:
        Seconds inherited by *today*, or 0.
    """
    owed = (
        carry
        if stored_day == today
        else pass_on(
            carry, outgoing_day=stored_day, budget=budget, spent=spent, new_day=today
        )
    )
    return owed.get(today, 0.0)


def carry_into(stored: PlaytimeState | None, now: datetime) -> float:
    """Return the seconds carried into the gaming day containing *now*.

    Args:
        stored: The persisted production state, or ``None`` if unreadable.
        now: Local timestamp for this tick.

    Returns:
        The carry owed to today; 0 when no state is recorded.
    """
    if stored is None:
        return 0.0
    return carry_due(
        stored.carry,
        stored_day=stored.day_key,
        budget=stored.budget_seconds,
        spent=stored.seconds,
        today=gaming_day_key(now),
    )


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
