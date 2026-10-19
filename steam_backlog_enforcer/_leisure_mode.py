"""Phase 2 of the leisure rollout: is it on for this gaming day, and its billing.

Dormant until ``leisure-watch go-live`` writes the switch file. The only
question asked of it is :func:`earned_time.leisure_active` for the *billed*
gaming day (06:00 boundary, ``state.day_key`` after the roll-over), so the
billing mode always matches the day being billed; no code here reads the file.

When on, the enforced ``seconds`` are billed by the shadow rule (contract C4,
:mod:`_shadow`) instead of games-only: a held locker grab or i3lock pauses
everything, games included; anything the watcher calls leisure -- or a watcher
that cannot be trusted -- bills; overlaps bill the wall clock once.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import TYPE_CHECKING, Final

import earned_time
from leisure_watch.procscan import attributed_key

from steam_backlog_enforcer._playtime_budget import accumulate, bill

if TYPE_CHECKING:
    from steam_backlog_enforcer._playtime_state import PlaytimeRules, PlaytimeState
    from steam_backlog_enforcer._shadow import ShadowVerdict

# Passed explicitly on every call: ``leisure_active``'s default is bound at
# import, so this module constant is what a test redirects.
LEISURE_FROM_PATH: Final = earned_time.LEISURE_FROM_PATH


def leisure_on(day_key: str) -> bool:
    """Whether the gaming day *day_key* (``YYYY-MM-DD``) is on the leisure budget.

    Args:
        day_key: The gaming day being billed.

    Returns:
        ``earned_time.leisure_active`` for that day; ``False`` for a key that is
        not a date (the games-only behaviour, which is what ran before).
    """
    try:
        day = date.fromisoformat(day_key)
    except ValueError:
        return False
    return bool(earned_time.leisure_active(day, LEISURE_FROM_PATH))


@dataclass(frozen=True)
class Tick:
    """What one enforce-loop tick observed, for billing."""

    now: datetime
    """Timezone-aware local timestamp for this tick."""
    interval: float
    """Nominal seconds between ticks."""
    owners: dict[int, str]
    """Qualifying game PIDs to attribution keys."""
    verdict: ShadowVerdict
    """This tick's shadow verdict."""


def leisure_billed(state: PlaytimeState, tick: Tick) -> PlaytimeState:
    """Bill this tick's enforced time by the shadow rule.

    Only a game (``attributed_key``) is ever credited to ``per_game``; other
    leisure shows as unattributed, its split lives in ``shadow_per_source``.

    Args:
        state: Accounting state (shadow already accumulated for this tick).
        tick: This tick's observations.

    Returns:
        The billed state.
    """
    billed = tick.verdict.paused_by is None and bool(tick.verdict.keys)
    return bill(
        state,
        now=tick.now,
        billed=billed,
        interval=tick.interval,
        credited_key=attributed_key(tick.owners) if billed else "",
    )


def bill_tick(
    state: PlaytimeState, rules: PlaytimeRules, tick: Tick
) -> tuple[PlaytimeState, PlaytimeRules]:
    """Bill this tick's enforced time: games-only, or (Phase 2) by the shadow rule.

    Dormant (no switch, a day before it, or a demo): exactly the old
    ``accumulate`` call, and *rules* returned as they came.

    Args:
        state: Accounting state (shadow already accumulated for this tick).
        rules: Policy for this tick.
        tick: This tick's observations.

    Returns:
        The billed state, and the tick's rules -- with ``leisure=True`` when
        live, so the warnings, the cutoff and the kills act for leisure.
    """
    if rules.demo or not leisure_on(state.day_key):
        billed = accumulate(
            state,
            now=tick.now,
            qualifying=set(tick.owners),
            interval=tick.interval,
            credited_key=attributed_key(tick.owners),
        )
        return billed, rules
    return leisure_billed(state, tick), replace(rules, leisure=True)
