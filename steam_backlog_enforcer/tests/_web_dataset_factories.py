"""Shared GameInfo/WebGame/HLTB-cache builders for the _web_dataset tests."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from steam_backlog_enforcer._flat_record import from_flat
from steam_backlog_enforcer._web_dataset import WebGame
from steam_backlog_enforcer.steam_api import GameInfo


def _gi(**over: object) -> GameInfo:
    """Build a GameInfo with field overrides."""
    base = GameInfo(
        app_id=1,
        name="G",
        total_achievements=10,
        unlocked_achievements=0,
        playtime_minutes=60,
        completionist_hours=20.0,
        comp_100_count=5,
        count_comp=20,
    )
    return replace(base, **over)


def _wg(**over: object) -> WebGame:
    """Build a WebGame with overrides named by its flat (served) keys."""
    base = {
        "app_id": 1,
        "name": "Game1",
        "completion_pct": 0.0,
        "playtime_minutes": 60,
        "rush_hours": 10.0,
        "leisure_hours": 20.0,
        "worst_hours": 25.0,
        "count_comp": 20,
        "comp_100_count": 5,
        "hltb_game_id": 0,
        "protondb_tier": "gold",
        "protondb_trending_tier": "gold",
        "protondb_score": 0.8,
    }
    return from_flat(WebGame, base | over)


def _complete_game(
    app_id: int = 1,
    playtime_minutes: int = 600,
) -> GameInfo:
    """Complete game (100 % achievements, has playtime)."""
    return GameInfo(
        app_id=app_id,
        name=f"Done{app_id}",
        total_achievements=10,
        unlocked_achievements=10,
        playtime_minutes=playtime_minutes,
        completionist_hours=0.0,
        comp_100_count=5,
        count_comp=20,
    )


def _hltb_cache(rush_hours: float, leisure_100h: float) -> dict[int, dict[str, Any]]:
    """HLTB cache holding app 1 (10 h, 5 polls) with the given rush/leisure hours."""
    return {
        1: {
            "hours": 10.0,
            "polls": 5,
            "count_comp": 20,
            "rush_hours": rush_hours,
            "leisure_100h": leisure_100h,
            "hltb_game_id": 0,
        }
    }
