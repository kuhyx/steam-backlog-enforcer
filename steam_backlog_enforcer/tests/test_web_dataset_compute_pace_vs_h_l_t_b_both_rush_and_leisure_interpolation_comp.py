"""Tests for _web_dataset module — 100% branch coverage."""

from __future__ import annotations

from dataclasses import replace

from steam_backlog_enforcer._web_dataset import (
    PaceVsHLTB,
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


class TestComputePaceVsHLTBGroup2:
    """Tests for compute_pace_vs_hltb — 100 % branch coverage."""

    def test_both_rush_and_leisure_interpolation_computed(self) -> None:
        """With both rush + leisure, interpolation_t is computed."""
        # actual=10h, rush=8h, leisure=20h → t = (10-8)/(20-8) = 2/12 ≈ 0.167
        game = _complete_game(app_id=1, playtime_minutes=600)
        cache = {
            1: {
                "hours": 10.0,
                "polls": 5,
                "count_comp": 20,
                "rush_hours": 8.0,
                "leisure_100h": 20.0,
                "hltb_game_id": 0,
            }
        }
        result = compute_pace_vs_hltb([game], cache)
        assert result is not None
        assert result.interpolation_t == round((10.0 - 8.0) / (20.0 - 8.0), 3)
        assert result.ratio_vs_leisure == round(10.0 / 20.0, 3)
        assert result.player_style == "rush_to_leisure"

    def test_style_faster_than_rush_when_t_negative(self) -> None:
        """t < 0 means faster than rush."""
        game = _complete_game(app_id=1, playtime_minutes=300)  # 5h actual
        cache = {
            1: {
                "hours": 10.0,
                "polls": 5,
                "count_comp": 20,
                "rush_hours": 8.0,
                "leisure_100h": 20.0,
                "hltb_game_id": 0,
            }
        }
        result = compute_pace_vs_hltb([game], cache)
        assert result is not None
        assert result.interpolation_t < 0
        assert result.player_style == "faster_than_rush"

    def test_style_slower_than_leisure_when_t_above_one(self) -> None:
        """t > 1 means slower than leisure."""
        game = _complete_game(app_id=1, playtime_minutes=1500)  # 25h actual
        cache = {
            1: {
                "hours": 10.0,
                "polls": 5,
                "count_comp": 20,
                "rush_hours": 8.0,
                "leisure_100h": 20.0,
                "hltb_game_id": 0,
            }
        }
        result = compute_pace_vs_hltb([game], cache)
        assert result is not None
        assert result.interpolation_t > 1.0
        assert result.player_style == "slower_than_leisure"

    def test_interpolation_t_minus_one_when_leisure_not_greater_than_rush(self) -> None:
        """Edge case: leisure <= rush, can't divide, interpolation_t = -1."""
        game = _complete_game(app_id=1, playtime_minutes=600)
        # leisure == rush → denominator = 0
        cache = {
            1: {
                "hours": 10.0,
                "polls": 5,
                "count_comp": 20,
                "rush_hours": 8.0,
                "leisure_100h": 8.0,
                "hltb_game_id": 0,
            }
        }
        result = compute_pace_vs_hltb([game], cache)
        assert result is not None
        assert result.interpolation_t == -1.0

    def test_pace_vs_hltb_is_dataclass(self) -> None:
        """Return type is PaceVsHLTB."""
        game = _complete_game(app_id=1)
        cache = {
            1: {
                "hours": 10.0,
                "polls": 5,
                "count_comp": 20,
                "rush_hours": 8.0,
                "leisure_100h": 20.0,
                "hltb_game_id": 0,
            }
        }
        result = compute_pace_vs_hltb([game], cache)
        assert isinstance(result, PaceVsHLTB)
