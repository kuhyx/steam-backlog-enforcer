"""Tests for steam_api module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from steam_backlog_enforcer.steam_api import (
    AchievementInfo,
    SteamAPIClient,
    SteamAPIError,
)


class TestSteamAPIClient:
    """Tests for SteamAPIClient."""

    def test_init(self) -> None:
        """Test init."""
        client = SteamAPIClient("key", "id")
        assert client.api_key == "key"
        assert client.steam_id == "id"

    def test_rate_limit(self) -> None:
        """Test rate limit."""
        client = SteamAPIClient("key", "id")
        # Should not block on first call
        client._rate_limit()

    def test_rate_limit_throttle(self) -> None:
        """Test rate limit throttle."""
        client = SteamAPIClient("key", "id")
        # Fill up the rate limit window
        client._request_times = [__import__("time").time()] * client._max_rps
        with patch(
            "steam_backlog_enforcer._steam_api_client.time.sleep",
        ) as mock_sleep:
            # Next call should trigger sleep then succeed
            client._rate_limit()
            mock_sleep.assert_called()

    def test_get_success(self) -> None:
        """Test get success."""
        client = SteamAPIClient("key", "id")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": "value"}
        client.session.get = MagicMock(return_value=mock_resp)
        result = client._get("https://example.com/api")
        assert result == {"data": "value"}

    def test_get_with_params(self) -> None:
        """Test get with params."""
        client = SteamAPIClient("key", "id")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": "value"}
        client.session.get = MagicMock(return_value=mock_resp)
        result = client._get("https://example.com/api", params={"foo": "bar"})
        assert result == {"data": "value"}
        # Verify key was added to existing params dict
        call_kwargs = client.session.get.call_args
        assert call_kwargs[1]["params"]["foo"] == "bar"
        assert call_kwargs[1]["params"]["key"] == "key"

    def test_get_failure(self) -> None:
        """Test get failure."""
        client = SteamAPIClient("key", "id")
        client.session.get = MagicMock(side_effect=requests.RequestException("fail"))
        with pytest.raises(SteamAPIError):
            client._get("https://example.com/api")

    def test_get_owned_games(self) -> None:
        """Test get owned games."""
        client = SteamAPIClient("key", "id")
        with patch.object(
            client,
            "_get",
            return_value={"response": {"games": [{"appid": 440}]}},
        ):
            games = client.get_owned_games()
            assert len(games) == 1
            assert games[0]["appid"] == 440

    def test_get_owned_games_empty(self) -> None:
        """Test get owned games empty."""
        client = SteamAPIClient("key", "id")
        with patch.object(client, "_get", return_value={"response": {}}):
            games = client.get_owned_games()
            assert games == []

    def test_get_achievement_details(self) -> None:
        """Test get achievement details."""
        client = SteamAPIClient("key", "id")
        with patch.object(
            client,
            "_get",
            return_value={
                "playerstats": {
                    "success": True,
                    "achievements": [
                        {
                            "apiname": "ACH_1",
                            "name": "First",
                            "achieved": 1,
                            "unlocktime": 1000,
                        },
                    ],
                },
            },
        ):
            result = client.get_achievement_details(440)
            assert len(result) == 1
            assert result[0].achieved is True

    def test_get_achievement_details_failure(self) -> None:
        """Test get achievement details failure."""
        client = SteamAPIClient("key", "id")
        with patch.object(client, "_get", side_effect=SteamAPIError("fail")):
            result = client.get_achievement_details(440)
            assert result == []

    def test_get_achievement_details_not_success(self) -> None:
        """Test get achievement details not success."""
        client = SteamAPIClient("key", "id")
        with patch.object(
            client,
            "_get",
            return_value={"playerstats": {"success": False}},
        ):
            result = client.get_achievement_details(440)
            assert result == []

    def test_fetch_one_game(self) -> None:
        """Test fetch one game."""
        client = SteamAPIClient("key", "id")
        ach = AchievementInfo("A1", "Ach1", achieved=True, unlock_time=100)
        with patch.object(client, "get_achievement_details", return_value=[ach]):
            result = client._fetch_one_game(
                {"appid": 440, "name": "TF2", "playtime_forever": 60},
            )
            assert result is not None
            assert result.app_id == 440

    def test_fetch_one_game_no_achievements(self) -> None:
        """Test fetch one game no achievements."""
        client = SteamAPIClient("key", "id")
        with patch.object(client, "get_achievement_details", return_value=[]):
            result = client._fetch_one_game({"appid": 440})
            assert result is None

    def test_build_game_list(self) -> None:
        """Test build game list."""
        client = SteamAPIClient("key", "id")
        ach = AchievementInfo("A1", "Ach1", achieved=True, unlock_time=100)
        with (
            patch.object(
                client,
                "get_owned_games",
                return_value=[{"appid": 440, "name": "TF2", "playtime_forever": 60}],
            ),
            patch.object(client, "get_achievement_details", return_value=[ach]),
        ):
            progress_calls: list[tuple[int, int]] = []

            def progress(c: int, t: int) -> None:
                """Test progress."""
                progress_calls.append((c, t))

            games = client.build_game_list(progress_callback=progress)
            assert len(games) == 1
            assert len(progress_calls) > 0

    def test_build_game_list_no_achievements_excluded(self) -> None:
        """Games without achievements are excluded from results."""
        client = SteamAPIClient("key", "id")
        with (
            patch.object(
                client,
                "get_owned_games",
                return_value=[{"appid": 440, "name": "TF2"}],
            ),
            patch.object(client, "get_achievement_details", return_value=[]),
        ):
            games = client.build_game_list()
            assert games == []

    def test_build_game_list_exception_in_future(self) -> None:
        """Test build game list exception in future."""
        client = SteamAPIClient("key", "id")
        with (
            patch.object(
                client,
                "get_owned_games",
                return_value=[{"appid": 440, "name": "TF2"}],
            ),
            patch.object(
                client,
                "get_achievement_details",
                side_effect=SteamAPIError("err"),
            ),
        ):
            games = client.build_game_list()
            assert games == []

    def test_refresh_single_game(self) -> None:
        """Test refresh single game."""
        client = SteamAPIClient("key", "id")
        ach = AchievementInfo("A1", "Ach1", achieved=True, unlock_time=100)
        with patch.object(client, "get_achievement_details", return_value=[ach]):
            result = client.refresh_single_game(440, "TF2", 60)
            assert result is not None
            assert result.unlocked_achievements == 1

    def test_refresh_single_game_no_achievements(self) -> None:
        """Test refresh single game no achievements."""
        client = SteamAPIClient("key", "id")
        with patch.object(client, "get_achievement_details", return_value=[]):
            result = client.refresh_single_game(440, "TF2")
            assert result is None
