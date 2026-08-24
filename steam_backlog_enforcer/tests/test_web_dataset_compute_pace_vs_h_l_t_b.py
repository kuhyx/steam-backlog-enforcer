"""Tests for _web_dataset module — 100% branch coverage."""

from __future__ import annotations

from dataclasses import replace

from steam_backlog_enforcer._web_dataset import (
    WebGame,
    compute_pace_vs_hltb,
)
from steam_backlog_enforcer.steam_api import GameInfo

_PKG = "steam_backlog_enforcer._web_dataset"


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


class TestComputePaceVsHLTB:
    """Tests for compute_pace_vs_hltb — 100 % branch coverage."""

    def test_no_completed_games_returns_none(self) -> None:
        """Test no completed games returns none."""
        incomplete = _gi(app_id=1, total_achievements=10, unlocked_achievements=0)
        assert compute_pace_vs_hltb([incomplete], {}) is None

    def test_complete_but_zero_playtime_ignored(self) -> None:
        """Test complete but zero playtime ignored."""
        game = _complete_game(playtime_minutes=0)
        assert compute_pace_vs_hltb([game], {}) is None

    def test_no_rush_data_in_cache_returns_none(self) -> None:
        """Test no rush data in cache returns none."""
        game = _complete_game(app_id=1)
        # cache has hours but no rush_hours
        cache = {
            1: {
                "hours": 10.0,
                "polls": 5,
                "count_comp": 20,
                "rush_hours": -1,
                "leisure_100h": -1,
                "hltb_game_id": 0,
            }
        }
        assert compute_pace_vs_hltb([game], cache) is None

    def test_rush_only_ratio_computed(self) -> None:
        """With rush but no leisure, ratio_vs_rush is computed, interpolation_t = -1."""
        game = _complete_game(app_id=1, playtime_minutes=600)  # 10h actual
        cache = {
            1: {
                "hours": 10.0,
                "polls": 5,
                "count_comp": 20,
                "rush_hours": 8.0,
                "leisure_100h": -1,
                "hltb_game_id": 0,
            }
        }
        result = compute_pace_vs_hltb([game], cache)
        assert result is not None
        assert result.calibration_count == 1
        assert result.ratio_vs_rush == round(10.0 / 8.0, 3)
        assert result.ratio_vs_leisure == -1.0
        assert result.interpolation_t == -1.0

    def test_rush_only_style_faster_than_rush_when_ratio_below_one(self) -> None:
        """Plays faster than rush (actual < rush) → style = faster_than_rush."""
        game = _complete_game(app_id=1, playtime_minutes=300)  # 5h actual
        cache = {
            1: {
                "hours": 10.0,
                "polls": 5,
                "count_comp": 20,
                "rush_hours": 8.0,
                "leisure_100h": -1,
                "hltb_game_id": 0,
            }
        }
        result = compute_pace_vs_hltb([game], cache)
        assert result is not None
        assert result.player_style == "faster_than_rush"

    def test_rush_only_style_unknown_when_ratio_at_or_above_one(self) -> None:
        """Without leisure data and ratio >= 1 → style = unknown."""
        game = _complete_game(app_id=1, playtime_minutes=600)  # 10h
        cache = {
            1: {
                "hours": 10.0,
                "polls": 5,
                "count_comp": 20,
                "rush_hours": 8.0,
                "leisure_100h": -1,
                "hltb_game_id": 0,
            }
        }
        result = compute_pace_vs_hltb([game], cache)
        assert result is not None
        assert result.player_style == "unknown"
