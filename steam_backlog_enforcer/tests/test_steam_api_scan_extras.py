"""Tests for the scan-time behaviours of SteamAPIClient: strictness, skips, cancel."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from steam_backlog_enforcer.steam_api import (
    AchievementInfo,
    SteamAPIClient,
    SteamAPIError,
)

_PKG = "steam_backlog_enforcer._steam_api_client"
_ACH = AchievementInfo("A1", "Ach1", achieved=True, unlock_time=100)


class TestStrictAchievementDetails:
    def test_a_real_failure_raises_when_strict(self) -> None:
        client = SteamAPIClient("key", "id")
        with (
            patch.object(client, "_get", side_effect=SteamAPIError("timeout")),
            pytest.raises(SteamAPIError, match="timeout"),
        ):
            client.get_achievement_details(440, strict=True)

    def test_a_no_stats_answer_is_empty_even_when_strict(self) -> None:
        client = SteamAPIClient("key", "id")
        with (
            patch.object(client, "_get", side_effect=SteamAPIError("400")),
            patch(f"{_PKG}.is_no_stats_answer", return_value=True),
        ):
            assert client.get_achievement_details(440, strict=True) == []


class TestBuildGameListSkips:
    def test_known_no_achievement_games_are_not_asked_about(self) -> None:
        client = SteamAPIClient("key", "id")
        owned = [{"appid": 1, "name": "Bare"}, {"appid": 2, "name": "Rich"}]
        with (
            patch.object(client, "get_owned_games", return_value=owned),
            patch(f"{_PKG}.skippable_app_ids", return_value={1}),
            patch.object(
                client, "get_achievement_details", return_value=[_ACH]
            ) as details,
        ):
            games = client.build_game_list()
        assert [g.app_id for g in games] == [2]
        assert [c.args[0] for c in details.call_args_list] == [2]

    def test_only_answered_games_are_remembered(self) -> None:
        client = SteamAPIClient("key", "id")
        owned = [{"appid": 1}, {"appid": 2}, {"appid": 3}]

        def details(app_id: int, *, strict: bool) -> list[AchievementInfo]:
            assert strict
            if app_id == 1:
                return [_ACH]
            if app_id == 2:
                return []  # Steam said "no stats"
            msg = "timeout"
            raise SteamAPIError(msg)

        with (
            patch.object(client, "get_owned_games", return_value=owned),
            patch.object(client, "get_achievement_details", side_effect=details),
            patch(f"{_PKG}.record_scan") as record,
        ):
            client.build_game_list()
        _, answered, found, _ = record.call_args.args
        assert [g["appid"] for g in answered] == [1, 2]
        assert found == {1}


class TestCancelledScan:
    def test_an_interrupt_propagates_and_drops_queued_requests(self) -> None:
        client = SteamAPIClient("key", "id")

        def cancel(_done: int, _total: int) -> None:
            raise KeyboardInterrupt

        with (
            patch.object(client, "get_owned_games", return_value=[{"appid": 1}]),
            patch.object(client, "get_achievement_details", return_value=[_ACH]),
            pytest.raises(KeyboardInterrupt),
        ):
            client.build_game_list(progress_callback=cancel)
