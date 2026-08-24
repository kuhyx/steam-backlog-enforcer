"""Tests for _stats module — 100% branch coverage."""

from __future__ import annotations

from unittest.mock import patch

from steam_backlog_enforcer.config import Config
from steam_backlog_enforcer.protondb import ProtonDBRating
from steam_backlog_enforcer.steam_api import GameInfo, SteamAPIError

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


class TestRefreshRecentlyPlayedCompletions:
    """Tests for _refresh_recently_played_completions."""

    def test_oserror_on_stat_returns_games_unchanged(self) -> None:
        """Test oserror on stat returns games unchanged."""
        games = [GameInfo(1, "G", 10, 0, 60)]
        with patch(f"{_PKG}.SNAPSHOT_FILE") as mock_sf:
            mock_sf.stat.side_effect = OSError("no file")
            from steam_backlog_enforcer._stats import (
                _refresh_recently_played_completions,
            )

            result = _refresh_recently_played_completions(games, Config())
        assert result == games

    def test_steam_api_error_returns_games_unchanged(self) -> None:
        """A SteamAPIError while fetching owned games is swallowed."""
        games = [GameInfo(1, "G", 10, 0, 60)]
        with (
            patch(f"{_PKG}.SNAPSHOT_FILE") as mock_sf,
            patch(f"{_PKG}.SteamAPIClient") as mock_cls,
        ):
            mock_sf.stat.return_value.st_mtime = 1_000_000.0
            mock_cls.return_value.get_owned_games.side_effect = SteamAPIError(
                "api down"
            )
            from steam_backlog_enforcer._stats import (
                _refresh_recently_played_completions,
            )

            result = _refresh_recently_played_completions(games, Config())
        assert result == games

    def test_no_recently_played_returns_games_unchanged(self) -> None:
        """Test no recently played returns games unchanged."""
        games = [GameInfo(1, "G", 10, 0, 60)]
        with (
            patch(f"{_PKG}.SNAPSHOT_FILE") as mock_sf,
            patch(f"{_PKG}.SteamAPIClient") as mock_cls,
        ):
            mock_sf.stat.return_value.st_mtime = 1_000_000.0
            mock_cls.return_value.get_owned_games.return_value = [
                {"appid": 1, "rtime_last_played": 500_000}
            ]
            from steam_backlog_enforcer._stats import (
                _refresh_recently_played_completions,
            )

            result = _refresh_recently_played_completions(games, Config())
        assert result == games

    def test_recently_played_game_is_refreshed(self) -> None:
        """Test recently played game is refreshed."""
        from steam_backlog_enforcer._stats import _refresh_recently_played_completions
        from steam_backlog_enforcer.steam_api import AchievementInfo

        game = GameInfo(1, "G", 5, 0, 60)
        new_achievements = [
            AchievementInfo("a1", "A1", achieved=True, unlock_time=1_500_001),
            AchievementInfo("a2", "A2", achieved=True, unlock_time=1_500_002),
            AchievementInfo("a3", "A3", achieved=False, unlock_time=0),
            AchievementInfo("a4", "A4", achieved=False, unlock_time=0),
            AchievementInfo("a5", "A5", achieved=False, unlock_time=0),
        ]
        with (
            patch(f"{_PKG}.SNAPSHOT_FILE") as mock_sf,
            patch(f"{_PKG}.SteamAPIClient") as mock_cls,
            patch(f"{_PKG}._echo"),
        ):
            mock_sf.stat.return_value.st_mtime = 1_000_000.0
            mock_cls.return_value.get_owned_games.return_value = [
                {"appid": 1, "rtime_last_played": 1_500_000}
            ]
            mock_cls.return_value.get_achievement_details.return_value = (
                new_achievements
            )
            result = _refresh_recently_played_completions([game], Config())
        refreshed = next(g for g in result if g.app_id == 1)
        assert refreshed.unlocked_achievements == 2

    def test_get_achievement_details_empty_keeps_old_game(self) -> None:
        """Test get achievement details empty keeps old game."""
        from steam_backlog_enforcer._stats import _refresh_recently_played_completions

        game = GameInfo(1, "G", 5, 3, 60)
        with (
            patch(f"{_PKG}.SNAPSHOT_FILE") as mock_sf,
            patch(f"{_PKG}.SteamAPIClient") as mock_cls,
            patch(f"{_PKG}._echo"),
        ):
            mock_sf.stat.return_value.st_mtime = 1_000_000.0
            mock_cls.return_value.get_owned_games.return_value = [
                {"appid": 1, "rtime_last_played": 1_500_000}
            ]
            mock_cls.return_value.get_achievement_details.return_value = []
            result = _refresh_recently_played_completions([game], Config())
        refreshed = next(g for g in result if g.app_id == 1)
        assert refreshed.unlocked_achievements == 3
