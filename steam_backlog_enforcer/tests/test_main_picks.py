"""Tests for the main CLI: pick and pick-manual commands."""

from unittest.mock import patch

import pytest

from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.main import (
    _resolve_game_name,
    cmd_pick,
)
from steam_backlog_enforcer.steam_api import GameInfo, SteamAPIError
from steam_backlog_enforcer.tests._main_helpers import (
    snap,
)

PKG = "steam_backlog_enforcer.main.picks"


class TestCmdPick:
    """Tests for cmd_pick."""

    def test_no_snapshot_prints_message(self) -> None:
        with (
            patch(f"{PKG}.load_snapshot", return_value=[]),
            patch(f"{PKG}._echo") as mock_echo,
        ):
            cmd_pick(Config(steam_api_key="k", steam_id="i"), State())
        mock_echo.assert_called_once_with("No snapshot found. Run 'scan' first.")

    def test_calls_pick_next_game(self) -> None:
        snapshot = [snap(2, "NewGame", 10, 0, 5.0)]
        with (
            patch(f"{PKG}.load_snapshot", return_value=snapshot),
            patch(f"{PKG}.load_hltb_cache", return_value={2: 5.0}),
            patch(f"{PKG}.pick_next_game") as mock_pick,
            patch(f"{PKG}.get_all_owned_app_ids", return_value=[]),
        ):
            config = Config(steam_api_key="k", steam_id="i")
            state = State()
            cmd_pick(config, state)
        mock_pick.assert_called_once()

    def test_hides_games_after_pick(self) -> None:
        snapshot = [snap(2, "NewGame", 10, 0, 5.0)]
        state = State(current_app_id=2, current_game_name="NewGame")
        with (
            patch(f"{PKG}.load_snapshot", return_value=snapshot),
            patch(f"{PKG}.load_hltb_cache", return_value={2: 5.0}),
            patch(f"{PKG}.pick_next_game"),
            patch(f"{PKG}.get_all_owned_app_ids", return_value=[1, 2, 3]),
            patch(f"{PKG}.try_hide_other_games", return_value=(2, None)) as mock_hide,
            patch(f"{PKG}._echo"),
        ):
            cmd_pick(Config(steam_api_key="k", steam_id="i"), state)
        mock_hide.assert_called_once_with([1, 2, 3], {2})

    def test_no_hide_message_when_none_hidden(self) -> None:
        snapshot = [snap(2, "NewGame", 10, 0, 5.0)]
        state = State(current_app_id=2, current_game_name="NewGame")
        with (
            patch(f"{PKG}.load_snapshot", return_value=snapshot),
            patch(f"{PKG}.load_hltb_cache", return_value={}),
            patch(f"{PKG}.pick_next_game"),
            patch(f"{PKG}.get_all_owned_app_ids", return_value=[1, 2, 3]),
            patch(f"{PKG}.try_hide_other_games", return_value=(0, None)),
            patch(f"{PKG}._echo") as mock_echo,
        ):
            cmd_pick(Config(steam_api_key="k", steam_id="i"), state)
        mock_echo.assert_not_called()

    def test_unreachable_steam_reports_skip(self) -> None:
        snapshot = [snap(2, "NewGame", 10, 0, 5.0)]
        state = State(current_app_id=2, current_game_name="NewGame")
        with (
            patch(f"{PKG}.load_snapshot", return_value=snapshot),
            patch(f"{PKG}.load_hltb_cache", return_value={}),
            patch(f"{PKG}.pick_next_game"),
            patch(f"{PKG}.get_all_owned_app_ids", return_value=[1, 2, 3]),
            patch(
                f"{PKG}.try_hide_other_games",
                return_value=(0, "Steam is not installed"),
            ),
            patch(f"{PKG}._echo") as mock_echo,
        ):
            cmd_pick(Config(steam_api_key="k", steam_id="i"), state)
        output = " ".join(str(c) for c in mock_echo.call_args_list)
        assert "skipped (Steam is not installed)" in output

    def test_no_hide_when_no_current_app(self) -> None:
        snapshot = [snap(2, "NewGame", 10, 0, 5.0)]
        with (
            patch(f"{PKG}.load_snapshot", return_value=snapshot),
            patch(f"{PKG}.load_hltb_cache", return_value={}),
            patch(f"{PKG}.pick_next_game"),
            patch(f"{PKG}.get_all_owned_app_ids") as mock_owned,
        ):
            cmd_pick(Config(steam_api_key="k", steam_id="i"), State())
        mock_owned.assert_not_called()

    def test_no_hide_when_owned_ids_empty(self) -> None:
        snapshot = [snap(2, "NewGame", 10, 0, 5.0)]
        state = State(current_app_id=2, current_game_name="NewGame")
        with (
            patch(f"{PKG}.load_snapshot", return_value=snapshot),
            patch(f"{PKG}.load_hltb_cache", return_value={}),
            patch(f"{PKG}.pick_next_game"),
            patch(f"{PKG}.get_all_owned_app_ids", return_value=[]),
            patch(f"{PKG}.try_hide_other_games") as mock_hide,
        ):
            cmd_pick(Config(steam_api_key="k", steam_id="i"), state)
        mock_hide.assert_not_called()

    def test_hltb_cache_applied_to_games(self) -> None:
        snapshot = [snap(2, "NewGame", 10, 0, -1.0)]
        captured_games: list[list[GameInfo]] = []
        config = Config(steam_api_key="k", steam_id="i")
        state = State()

        def capture_pick(games: list[GameInfo], *_args: object) -> None:
            captured_games.append(list(games))

        with (
            patch(f"{PKG}.load_snapshot", return_value=snapshot),
            patch(f"{PKG}.load_hltb_cache", return_value={2: 7.5}),
            patch(f"{PKG}.pick_next_game", side_effect=capture_pick),
            patch(f"{PKG}.get_all_owned_app_ids", return_value=[]),
        ):
            cmd_pick(config, state)

        assert len(captured_games) == 1
        assert captured_games[0][0].completionist_hours == pytest.approx(7.5)


class TestResolveGameName:
    def test_found_in_snapshot(self) -> None:
        snapshot = [
            {
                "app_id": 440,
                "name": "TF2",
                "total_achievements": 0,
                "unlocked_achievements": 0,
                "playtime_minutes": 0,
            }
        ]
        with patch(f"{PKG}.load_snapshot", return_value=snapshot):
            result = _resolve_game_name(Config(), 440)
        assert result == "TF2"

    def test_not_in_snapshot_found_via_api(self) -> None:
        with (
            patch(f"{PKG}.load_snapshot", return_value=[]),
            patch(f"{PKG}.SteamAPIClient") as mock_cls,
        ):
            mock_cls.return_value.get_owned_games.return_value = [
                {"appid": 730, "name": "Counter-Strike 2"}
            ]
            result = _resolve_game_name(Config(), 730)
        assert result == "Counter-Strike 2"

    def test_api_raises_returns_none(self) -> None:
        with (
            patch(f"{PKG}.load_snapshot", return_value=[]),
            patch(f"{PKG}.SteamAPIClient") as mock_cls,
        ):
            mock_cls.return_value.get_owned_games.side_effect = SteamAPIError("fail")
            result = _resolve_game_name(Config(), 999)
        assert result is None

    def test_not_found_anywhere_returns_none(self) -> None:
        with (
            patch(f"{PKG}.load_snapshot", return_value=[{"app_id": 1, "name": "X"}]),
            patch(f"{PKG}.SteamAPIClient") as mock_cls,
        ):
            mock_cls.return_value.get_owned_games.return_value = [{"appid": 1}]
            result = _resolve_game_name(Config(), 999)
        assert result is None

    def test_no_snapshot_falls_through_to_api(self) -> None:
        with (
            patch(f"{PKG}.load_snapshot", return_value=None),
            patch(f"{PKG}.SteamAPIClient") as mock_cls,
        ):
            mock_cls.return_value.get_owned_games.return_value = [
                {"appid": 440, "name": "TF2"}
            ]
            result = _resolve_game_name(Config(), 440)
        assert result == "TF2"


# ──────────────────────────────────────────────────────────────
# cmd_pick_manual
# ──────────────────────────────────────────────────────────────
