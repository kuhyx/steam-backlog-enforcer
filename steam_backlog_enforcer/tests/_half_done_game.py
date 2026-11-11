"""Shared builder for a half-completed, hour-played game in the pick prompt tests."""

from __future__ import annotations

from steam_backlog_enforcer.steam_api import GameInfo


def half_done_game(app_id: int, name: str, hours: float = -1) -> GameInfo:
    """Return a game with 5 of 10 achievements, an hour played, ``hours`` to 100 %."""
    return GameInfo(
        app_id=app_id,
        name=name,
        total_achievements=10,
        unlocked_achievements=5,
        playtime_minutes=60,
        completionist_hours=hours,
    )
