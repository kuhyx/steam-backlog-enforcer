"""Tests for _web_dataset module — 100% branch coverage."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import patch

from steam_backlog_enforcer._web_dataset import (
    WebGame,
    build_web_dataset,
    dataset_to_payload,
)
from steam_backlog_enforcer.config import State
from steam_backlog_enforcer.steam_api import GameInfo

_PKG = "steam_backlog_enforcer._web_games"
# build_web_dataset itself did not move.
_DATASET_PKG = "steam_backlog_enforcer._web_dataset"


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
    """Build a WebGame with field overrides."""
    base = WebGame(
        app_id=1,
        name="Game1",
        completion_pct=0.0,
        playtime_minutes=60,
        rush_hours=10.0,
        leisure_hours=20.0,
        worst_hours=25.0,
        count_comp=20,
        comp_100_count=5,
        hltb_game_id=0,
        protondb_tier="gold",
        protondb_trending_tier="gold",
        protondb_score=0.8,
    )
    return replace(base, **over)


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


class TestDatasetToPayload:
    """Tests for dataset_to_payload."""

    def test_serializes_to_dict(self) -> None:
        """Test serializes to dict."""
        with (
            patch(f"{_DATASET_PKG}.load_snapshot", return_value=None),
            patch(f"{_PKG}._read_raw_cache", return_value={}),
            patch(f"{_PKG}._load_cache", return_value={}),
        ):
            payload = dataset_to_payload(build_web_dataset(State()))
        assert set(payload) == {
            "games",
            "state",
            "defaults",
            "default_summary",
            "pace_vs_hltb",
            "generated_at",
        }
        assert isinstance(payload["games"], list)
        assert isinstance(payload["state"], dict)
