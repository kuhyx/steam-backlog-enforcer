"""Shared builders for the release-lifecycle and tampering tests."""

from __future__ import annotations

from datetime import UTC, datetime
import json

from steam_backlog_enforcer import config as config_mod
from steam_backlog_enforcer.steam_api import AchievementInfo, GameInfo
from steam_backlog_enforcer.tests._main_helpers import STARTED_AT

RELEASED = datetime(2026, 9, 20, tzinfo=UTC)


def pick(app_id: int, **extra: str) -> dict[str, object]:
    """Build one manual-pick entry started a day ago."""
    return {
        "app_id": app_id,
        "game_name": f"G{app_id}",
        "started_at": STARTED_AT,
    } | dict(extra.items())


def game(app_id: int, *unlock_times: int, hours: float = 5.0) -> GameInfo:
    """Build a GameInfo with one unlocked achievement per epoch given."""
    return GameInfo(
        app_id=app_id,
        name=f"G{app_id}",
        total_achievements=10,
        unlocked_achievements=len(unlock_times),
        playtime_minutes=60,
        completionist_hours=hours,
        achievements=[
            AchievementInfo(f"a{t}", f"A{t}", achieved=True, unlock_time=t)
            for t in unlock_times
        ],
    )


def write_state(data: dict[str, object]) -> None:
    """Write raw JSON to the (conftest-redirected) state file."""
    config_mod.STATE_FILE.write_text(json.dumps(data), encoding="utf-8")
