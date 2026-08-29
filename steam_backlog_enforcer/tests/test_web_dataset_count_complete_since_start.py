"""Tests for _web_dataset module — 100% branch coverage."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from steam_backlog_enforcer._web_dataset import (
    WebGame,
    _state_info,
    count_complete_since_start,
)
from steam_backlog_enforcer.config import State
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


class TestCountCompleteSinceStart:
    """Tests for count_complete_since_start."""

    def _ach(self, ts: int, *, achieved: bool = True) -> object:
        """Test ach."""
        from steam_backlog_enforcer.steam_api import AchievementInfo

        return AchievementInfo(
            api_name="A", display_name="A", achieved=achieved, unlock_time=ts
        )

    def _complete_game(self, app_id: int, unlock_ts: int) -> GameInfo:
        """Test complete game."""
        achs = [self._ach(unlock_ts)] * 5
        return _gi(
            app_id=app_id,
            total_achievements=5,
            unlocked_achievements=5,
            achievements=achs,
        )

    def test_empty_started_at_returns_zero(self) -> None:
        """Test empty started at returns zero."""
        games = [self._complete_game(1, 1_000_000)]
        assert count_complete_since_start(games, "") == 0

    def test_invalid_started_at_returns_zero(self) -> None:
        """Test invalid started at returns zero."""
        games = [self._complete_game(1, 1_000_000)]
        assert count_complete_since_start(games, "not-a-date") == 0

    def test_counts_game_completed_after_start(self) -> None:
        """Test counts game completed after start."""
        started = datetime(2026, 1, 1, tzinfo=UTC)
        after_ts = int(datetime(2026, 6, 1, tzinfo=UTC).timestamp())
        games = [self._complete_game(1, after_ts)]
        assert count_complete_since_start(games, started.isoformat()) == 1

    def test_excludes_game_completed_before_start(self) -> None:
        """Test excludes game completed before start."""
        started = datetime(2026, 1, 1, tzinfo=UTC)
        before_ts = int(datetime(2025, 6, 1, tzinfo=UTC).timestamp())
        games = [self._complete_game(1, before_ts)]
        assert count_complete_since_start(games, started.isoformat()) == 0

    def test_excludes_incomplete_game(self) -> None:
        """Test excludes incomplete game."""
        started = datetime(2026, 1, 1, tzinfo=UTC)
        after_ts = int(datetime(2026, 6, 1, tzinfo=UTC).timestamp())
        incomplete = _gi(
            app_id=1,
            total_achievements=5,
            unlocked_achievements=3,
            achievements=[self._ach(after_ts)] * 3,
        )
        assert count_complete_since_start([incomplete], started.isoformat()) == 0

    def test_excludes_game_with_no_achievement_timestamps(self) -> None:
        """Complete game with unlock_time=0 on all achievements is excluded."""
        started = datetime(2026, 1, 1, tzinfo=UTC)
        no_ts = _gi(
            app_id=1,
            total_achievements=5,
            unlocked_achievements=5,
            achievements=[self._ach(0)] * 5,
        )
        assert count_complete_since_start([no_ts], started.isoformat()) == 0

    def test_mixed_games_counts_only_post_start(self) -> None:
        """Test mixed games counts only post start."""
        started = datetime(2026, 1, 1, tzinfo=UTC)
        after_ts = int(datetime(2026, 6, 1, tzinfo=UTC).timestamp())
        before_ts = int(datetime(2025, 6, 1, tzinfo=UTC).timestamp())
        games = [
            self._complete_game(1, after_ts),
            self._complete_game(2, before_ts),
            self._complete_game(3, after_ts),
        ]
        assert count_complete_since_start(games, started.isoformat()) == 2

    def test_uses_max_unlock_time_across_achievements(self) -> None:
        """Game counts if its LAST achievement was unlocked after start."""
        started = datetime(2026, 1, 1, tzinfo=UTC)
        before_ts = int(datetime(2025, 12, 1, tzinfo=UTC).timestamp())
        after_ts = int(datetime(2026, 2, 1, tzinfo=UTC).timestamp())
        # Mix of before/after timestamps — max is after start, so should count
        achs = [self._ach(before_ts)] * 4 + [self._ach(after_ts)]
        game = _gi(
            app_id=1, total_achievements=5, unlocked_achievements=5, achievements=achs
        )
        assert count_complete_since_start([game], started.isoformat()) == 1


class TestStateInfo:
    """Tests for _state_info pace calculation."""

    def test_no_start_date(self) -> None:
        """Test no start date."""
        info = _state_info(State(), games_done=5, games_done_since_start=5)
        assert info.days_elapsed == 0
        assert info.pace_games_per_day == 0.0
        assert info.games_done == 5
        assert info.games_done_since_start == 5

    def test_invalid_start_date(self) -> None:
        """Test invalid start date."""
        info = _state_info(
            State(enforcement_started_at="not-a-date"),
            games_done=5,
            games_done_since_start=5,
        )
        assert info.days_elapsed == 0
        assert info.pace_games_per_day == 0.0

    def test_valid_start_with_games(self) -> None:
        """Test valid start with games."""
        started = datetime.now(UTC) - timedelta(days=50)
        info = _state_info(
            State(enforcement_started_at=started.isoformat()),
            games_done=12,
            games_done_since_start=10,
        )
        assert info.days_elapsed >= 49
        assert info.pace_games_per_day > 0.0
        assert info.games_done == 12
        assert info.games_done_since_start == 10

    def test_valid_start_zero_since_start_keeps_zero_pace(self) -> None:
        """games_done_since_start=0 → pace stays 0 even if total games_done > 0."""
        started = datetime.now(UTC) - timedelta(days=50)
        info = _state_info(
            State(enforcement_started_at=started.isoformat()),
            games_done=5,
            games_done_since_start=0,
        )
        assert info.days_elapsed >= 49
        assert info.pace_games_per_day == 0.0
