"""Tests for steam_api module."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests

from python_pkg.steam_backlog_enforcer.steam_api import (
    AchievementInfo,
    GameInfo,
    SteamAPIClient,
    SteamAPIError,
)


class TestAchievementInfo:
    """Tests for AchievementInfo."""

    def test_create(self) -> None:
        a = AchievementInfo(
            api_name="ACH_1", display_name="First", achieved=True, unlock_time=1000
        )
        assert a.api_name == "ACH_1"
        assert a.achieved is True


class TestGameInfo:
    """Tests for GameInfo."""

    def test_completion_pct_zero_achievements(self) -> None:
        g = GameInfo(
            app_id=1,
            name="G",
            total_achievements=0,
            unlocked_achievements=0,
            playtime_minutes=0,
        )
        assert g.completion_pct == 100.0

    def test_completion_pct_partial(self) -> None:
        g = GameInfo(
            app_id=1,
            name="G",
            total_achievements=10,
            unlocked_achievements=5,
            playtime_minutes=0,
        )
        assert g.completion_pct == 50.0

    def test_is_complete_true(self) -> None:
        g = GameInfo(
            app_id=1,
            name="G",
            total_achievements=5,
            unlocked_achievements=5,
            playtime_minutes=0,
        )
        assert g.is_complete is True

    def test_is_complete_false(self) -> None:
        g = GameInfo(
            app_id=1,
            name="G",
            total_achievements=5,
            unlocked_achievements=3,
            playtime_minutes=0,
        )
        assert g.is_complete is False

    def test_is_complete_zero(self) -> None:
        g = GameInfo(
            app_id=1,
            name="G",
            total_achievements=0,
            unlocked_achievements=0,
            playtime_minutes=0,
        )
        assert g.is_complete is False

    def test_to_snapshot(self) -> None:
        ach = AchievementInfo(
            api_name="A1", display_name="Ach1", achieved=True, unlock_time=99
        )
        g = GameInfo(
            app_id=1,
            name="G",
            total_achievements=1,
            unlocked_achievements=1,
            playtime_minutes=60,
            achievements=[ach],
            completionist_hours=5.0,
        )
        snap = g.to_snapshot()
        assert snap["app_id"] == 1
        assert snap["achievements"][0]["api_name"] == "A1"
        assert snap["completionist_hours"] == 5.0

    def test_from_snapshot(self) -> None:
        data: dict[str, Any] = {
            "app_id": 2,
            "name": "G2",
            "total_achievements": 3,
            "unlocked_achievements": 1,
            "playtime_minutes": 120,
            "completionist_hours": 10.0,
            "achievements": [
                {
                    "api_name": "A1",
                    "display_name": "First",
                    "achieved": False,
                    "unlock_time": 0,
                },
            ],
        }
        g = GameInfo.from_snapshot(data)
        assert g.app_id == 2
        assert g.completionist_hours == 10.0
        assert len(g.achievements) == 1

    def test_from_snapshot_defaults(self) -> None:
        data: dict[str, Any] = {
            "app_id": 3,
            "name": "G3",
            "total_achievements": 0,
            "unlocked_achievements": 0,
        }
        g = GameInfo.from_snapshot(data)
        assert g.playtime_minutes == 0
        assert g.completionist_hours == -1
        assert g.achievements == []

    def test_from_snapshot_achievement_defaults(self) -> None:
        data: dict[str, Any] = {
            "app_id": 4,
            "name": "G4",
            "total_achievements": 1,
            "unlocked_achievements": 0,
            "achievements": [{"api_name": "X", "achieved": False}],
        }
        g = GameInfo.from_snapshot(data)
        assert g.achievements[0].display_name == "X"
        assert g.achievements[0].unlock_time == 0


class TestSteamAPIClient:
    """Tests for SteamAPIClient."""

    def test_init(self) -> None:
        client = SteamAPIClient("key", "id")
        assert client.api_key == "key"
        assert client.steam_id == "id"

    def test_rate_limit(self) -> None:
        client = SteamAPIClient("key", "id")
        # Should not block on first call
        client._rate_limit()

    def test_rate_limit_throttle(self) -> None:
        client = SteamAPIClient("key", "id")
        # Fill up the rate limit window
        client._request_times = [__import__("time").time()] * client._max_rps
        with patch(
            "python_pkg.steam_backlog_enforcer.steam_api.time.sleep",
        ) as mock_sleep:
            # Next call should trigger sleep then succeed
            client._rate_limit()
            mock_sleep.assert_called()

    def test_get_success(self) -> None:
        client = SteamAPIClient("key", "id")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": "value"}
        client.session.get = MagicMock(return_value=mock_resp)
        result = client._get("https://example.com/api")
        assert result == {"data": "value"}

    def test_get_with_params(self) -> None:
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
        client = SteamAPIClient("key", "id")
        client.session.get = MagicMock(side_effect=requests.RequestException("fail"))
        with pytest.raises(SteamAPIError):
            client._get("https://example.com/api")

    def test_get_owned_games(self) -> None:
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
        client = SteamAPIClient("key", "id")
        with patch.object(client, "_get", return_value={"response": {}}):
            games = client.get_owned_games()
            assert games == []

    def test_get_achievement_details(self) -> None:
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
        client = SteamAPIClient("key", "id")
        with patch.object(client, "_get", side_effect=SteamAPIError("fail")):
            result = client.get_achievement_details(440)
            assert result == []

    def test_get_achievement_details_not_success(self) -> None:
        client = SteamAPIClient("key", "id")
        with patch.object(
            client,
            "_get",
            return_value={"playerstats": {"success": False}},
        ):
            result = client.get_achievement_details(440)
            assert result == []

    def test_fetch_one_game(self) -> None:
        client = SteamAPIClient("key", "id")
        ach = AchievementInfo("A1", "Ach1", True, 100)
        with patch.object(client, "get_achievement_details", return_value=[ach]):
            result = client._fetch_one_game(
                {"appid": 440, "name": "TF2", "playtime_forever": 60},
                set(),
            )
            assert result is not None
            assert result.app_id == 440

    def test_fetch_one_game_skipped(self) -> None:
        client = SteamAPIClient("key", "id")
        result = client._fetch_one_game({"appid": 440}, {440})
        assert result is None

    def test_fetch_one_game_no_achievements(self) -> None:
        client = SteamAPIClient("key", "id")
        with patch.object(client, "get_achievement_details", return_value=[]):
            result = client._fetch_one_game({"appid": 440}, set())
            assert result is None

    def test_build_game_list(self) -> None:
        client = SteamAPIClient("key", "id")
        ach = AchievementInfo("A1", "Ach1", True, 100)
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
                progress_calls.append((c, t))

            games = client.build_game_list(progress_callback=progress)
            assert len(games) == 1
            assert len(progress_calls) > 0

    def test_build_game_list_with_skip(self) -> None:
        client = SteamAPIClient("key", "id")
        with patch.object(
            client,
            "get_owned_games",
            return_value=[{"appid": 440, "name": "TF2"}],
        ):
            games = client.build_game_list(skip_app_ids=[440])
            assert games == []

    def test_build_game_list_exception_in_future(self) -> None:
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
        client = SteamAPIClient("key", "id")
        ach = AchievementInfo("A1", "Ach1", True, 100)
        with patch.object(client, "get_achievement_details", return_value=[ach]):
            result = client.refresh_single_game(440, "TF2", 60)
            assert result is not None
            assert result.unlocked_achievements == 1

    def test_refresh_single_game_no_achievements(self) -> None:
        client = SteamAPIClient("key", "id")
        with patch.object(client, "get_achievement_details", return_value=[]):
            result = client.refresh_single_game(440, "TF2")
            assert result is None
