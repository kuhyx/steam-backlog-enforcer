"""Tests for _stats module — 100% branch coverage."""

from __future__ import annotations

from unittest.mock import patch

from steam_backlog_enforcer._stats import (
    _ensure_completed_rush_data,
    _ensure_rush_data,
    _GameTimes,
)
from steam_backlog_enforcer.protondb import ProtonDBRating
from steam_backlog_enforcer.steam_api import GameInfo

_PKG = "steam_backlog_enforcer._stats_gathering"


def _game(
    app_id: int = 1,
    name: str = "G",
    hours: float = 10.0,
    total: int = 10,
    unlocked: int = 0,
) -> GameInfo:
    return GameInfo(
        app_id=app_id,
        name=name,
        total_achievements=total,
        unlocked_achievements=unlocked,
        playtime_minutes=60,
        completionist_hours=hours,
        comp_100_count=5,
        count_comp=20,
    )


def _unplayable_rating(app_id: int) -> ProtonDBRating:
    return ProtonDBRating(app_id=app_id, tier="borked")


class TestEnsureRushData:
    """Tests for _ensure_rush_data."""

    def _entry(self, rush: float) -> _GameTimes:
        """Test entry."""
        return _GameTimes(
            game=_game(), worst_hours=10.0, rush_hours=rush, leisure_100h=5.0
        )

    def test_empty_qualified_returns_false(self) -> None:
        """Test empty qualified returns false."""
        with patch(f"{_PKG}.fetch_hltb_detail_missing") as mock_fetch:
            result = _ensure_rush_data([])
        assert result is False
        mock_fetch.assert_not_called()

    def test_all_have_rush_returns_false(self) -> None:
        """Test all have rush returns false."""
        entries = [self._entry(10.0), self._entry(5.0)]
        with patch(f"{_PKG}.fetch_hltb_detail_missing") as mock_fetch:
            result = _ensure_rush_data(entries)
        assert result is False
        mock_fetch.assert_not_called()

    def test_missing_rush_fetches_and_returns_true(self) -> None:
        """Test missing rush fetches and returns true."""
        entries = [self._entry(-1.0)]
        with (
            patch(f"{_PKG}.fetch_hltb_detail_missing") as mock_fetch,
            patch(f"{_PKG}._echo"),
        ):
            result = _ensure_rush_data(entries)
        assert result is True
        mock_fetch.assert_called_once()


class TestEnsureCompletedRushData:
    """Tests for _ensure_completed_rush_data."""

    def _complete(self, app_id: int = 1, playtime: int = 600) -> GameInfo:
        """Test complete."""
        return GameInfo(
            app_id=app_id,
            name="Done",
            total_achievements=10,
            unlocked_achievements=10,
            playtime_minutes=playtime,
            completionist_hours=0.0,
            comp_100_count=5,
            count_comp=20,
        )

    def test_no_complete_games_returns_false_without_fetch(self) -> None:
        """Test no complete games returns false without fetch."""
        incomplete = _game(app_id=1, total=10, unlocked=0)
        with patch(f"{_PKG}.fetch_hltb_detail_missing") as mock_fetch:
            result = _ensure_completed_rush_data([incomplete])
        assert result is False
        mock_fetch.assert_not_called()

    def test_complete_game_with_zero_playtime_excluded(self) -> None:
        """Games with playtime_minutes=0 are skipped (no calibration value)."""
        no_play = self._complete(playtime=0)
        with patch(f"{_PKG}.fetch_hltb_detail_missing") as mock_fetch:
            result = _ensure_completed_rush_data([no_play])
        assert result is False
        mock_fetch.assert_not_called()

    def test_complete_game_with_playtime_fetches(self) -> None:
        """Test complete game with playtime fetches."""
        game = self._complete()
        with (
            patch(f"{_PKG}.fetch_hltb_detail_missing", return_value=1) as mock_fetch,
            patch(f"{_PKG}._echo"),
        ):
            result = _ensure_completed_rush_data([game])
        assert result is True
        mock_fetch.assert_called_once_with([(1, "Done")])

    def test_fetch_returns_zero_means_no_new_data(self) -> None:
        """When fetch_hltb_detail_missing returns 0, return False (all cached)."""
        game = self._complete()
        with (
            patch(f"{_PKG}.fetch_hltb_detail_missing", return_value=0),
            patch(f"{_PKG}._echo"),
        ):
            result = _ensure_completed_rush_data([game])
        assert result is False
