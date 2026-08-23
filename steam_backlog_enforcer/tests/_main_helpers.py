"""Shared fixtures and builders for the ``main`` CLI test modules.

Lives outside a ``test_*.py`` name on purpose: these are constructors, not
tests. ``name-tests-test`` exempts ``tests/_*.py`` for exactly this.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from steam_backlog_enforcer._actions import MANUAL_GRACE_DAYS
from steam_backlog_enforcer._allowed_games import MANUAL_LOCK_DAYS
from steam_backlog_enforcer._total_block import TotalBlockStatus
from steam_backlog_enforcer.config import State

STARTED_AT = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()

# A start timestamp that is always past the 14-day deadline.
EXPIRED_AT = (
    datetime.now(timezone.utc) - timedelta(days=MANUAL_LOCK_DAYS + 1)
).isoformat()

ACTIVE_STATUS = TotalBlockStatus(
    active=True,
    started_at=datetime.now(timezone.utc) - timedelta(hours=1),
    until=datetime.now(timezone.utc) + timedelta(hours=23),
    days=1,
    days_remaining=0.96,
)
INACTIVE_STATUS = TotalBlockStatus(
    active=False, started_at=None, until=None, days=0, days_remaining=0.0
)


def snap(
    app_id: int = 1,
    name: str = "G",
    total: int = 10,
    unlocked: int = 0,
    hours: float = -1,
) -> dict[str, Any]:
    """Build one snapshot entry.

    Args:
        app_id: Steam application id.
        name: Game name.
        total: Total achievement count.
        unlocked: Unlocked achievement count.
        hours: Completionist hours (-1 when unknown).

    Returns:
        A snapshot dict shaped like the on-disk format.
    """
    return {
        "app_id": app_id,
        "name": name,
        "total_achievements": total,
        "unlocked_achievements": unlocked,
        "playtime_minutes": 60,
        "completionist_hours": hours,
    }


def snap_with_achievements(
    app_id: int = 1,
    name: str = "G",
    total: int = 10,
    unlocked: int = 0,
    hours: float = -1,
) -> dict[str, Any]:
    """Build a snapshot entry carrying an empty ``achievements`` list.

    Args:
        app_id: Steam application id.
        name: Game name.
        total: Total achievement count.
        unlocked: Unlocked achievement count.
        hours: Completionist hours (-1 when unknown).

    Returns:
        A snapshot dict with ``achievements`` and zero playtime.
    """
    entry = snap(app_id, name, total, unlocked, hours)
    entry["playtime_minutes"] = 0
    entry["achievements"] = []
    return entry


def locked_state(
    app_id: int = 100,
    name: str = "TestGame",
    started_at: str = STARTED_AT,
) -> State:
    """Build a State carrying one active manual pick.

    Args:
        app_id: Picked application id.
        name: Picked game name.
        started_at: ISO timestamp the pick started at.

    Returns:
        A State with a single manual pick.
    """
    return State(
        manual_picks=[{"app_id": app_id, "game_name": name, "started_at": started_at}],
    )


IN_GRACE = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
PAST_GRACE = (
    datetime.now(timezone.utc) - timedelta(days=MANUAL_GRACE_DAYS + 1)
).isoformat()

VALID_REASON = "I need this game installed for a work presentation this week."


def abandonable_state(app_id: int = 100, started_at: str = IN_GRACE) -> State:
    """Build a State whose single manual pick is still abandonable.

    Args:
        app_id: Picked application id.
        started_at: ISO timestamp the pick started at.

    Returns:
        A State with the pick also set as the current assignment.
    """
    state = locked_state(app_id=app_id, started_at=started_at)
    state.current_app_id = app_id
    state.current_game_name = state.manual_pick_game_name
    return state


def two_pick_state() -> State:
    """Build a State carrying two active manual picks.

    Returns:
        A State whose current assignment is the second pick.
    """
    state = State(
        manual_picks=[
            {"app_id": 100, "game_name": "TestGame", "started_at": IN_GRACE},
            {"app_id": 200, "game_name": "SecondGame", "started_at": IN_GRACE},
        ],
    )
    state.current_app_id = 200
    state.current_game_name = "SecondGame"
    return state
