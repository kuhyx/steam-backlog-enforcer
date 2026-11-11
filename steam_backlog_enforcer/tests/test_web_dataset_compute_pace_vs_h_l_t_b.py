"""Tests for _web_dataset module — 100% branch coverage."""

from __future__ import annotations

from steam_backlog_enforcer._web_dataset import (
    compute_pace_vs_hltb,
)
from steam_backlog_enforcer.tests._web_dataset_factories import (
    _complete_game,
    _gi,
    _hltb_cache,
)

_PKG = "steam_backlog_enforcer._web_dataset"


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
        cache = _hltb_cache(-1, -1)
        assert compute_pace_vs_hltb([game], cache) is None

    def test_rush_only_ratio_computed(self) -> None:
        """With rush but no leisure, ratio_vs_rush is computed, interpolation_t = -1."""
        game = _complete_game(app_id=1, playtime_minutes=600)  # 10h actual
        cache = _hltb_cache(8.0, -1)
        result = compute_pace_vs_hltb([game], cache)
        assert result is not None
        assert result.calibration_count == 1
        assert result.ratio_vs_rush == round(10.0 / 8.0, 3)
        assert result.ratio_vs_leisure == -1.0
        assert result.interpolation_t == -1.0

    def test_rush_only_style_faster_than_rush_when_ratio_below_one(self) -> None:
        """Plays faster than rush (actual < rush) → style = faster_than_rush."""
        game = _complete_game(app_id=1, playtime_minutes=300)  # 5h actual
        cache = _hltb_cache(8.0, -1)
        result = compute_pace_vs_hltb([game], cache)
        assert result is not None
        assert result.player_style == "faster_than_rush"

    def test_rush_only_style_unknown_when_ratio_at_or_above_one(self) -> None:
        """Without leisure data and ratio >= 1 → style = unknown."""
        game = _complete_game(app_id=1, playtime_minutes=600)  # 10h
        cache = _hltb_cache(8.0, -1)
        result = compute_pace_vs_hltb([game], cache)
        assert result is not None
        assert result.player_style == "unknown"
