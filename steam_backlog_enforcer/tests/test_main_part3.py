"""Tests for main CLI module — part 3 (cmd_done, main, cmd_pick)."""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer._cmd_done import (
    cmd_done,
)
from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.main import cmd_pick, main
from steam_backlog_enforcer.steam_api import GameInfo

CMD_DONE_PKG = "steam_backlog_enforcer._cmd_done"
PKG = "steam_backlog_enforcer.main"


def _snap(
    app_id: int,
    name: str,
    total: int,
    unlocked: int,
    hours: float,
) -> dict[str, Any]:
    return {
        "app_id": app_id,
        "name": name,
        "total_achievements": total,
        "unlocked_achievements": unlocked,
        "playtime_minutes": 0,
        "completionist_hours": hours,
        "achievements": [],
    }


class TestCmdDone:
    """Tests for cmd_done."""

    def test_no_game_assigned(self) -> None:
        with patch(f"{CMD_DONE_PKG}._echo") as mock_echo:
            cmd_done(Config(), State())
        assert any("No game" in str(c) for c in mock_echo.call_args_list)

    def test_fetch_fails(self) -> None:
        mock_client = MagicMock()
        mock_client.refresh_single_game.return_value = None
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{CMD_DONE_PKG}.SteamAPIClient", return_value=mock_client),
            patch(f"{CMD_DONE_PKG}._echo"),
        ):
            cmd_done(Config(steam_api_key="k", steam_id="i"), state)

    def test_not_complete_enforces(self) -> None:
        game = GameInfo(
            app_id=1,
            name="G",
            total_achievements=10,
            unlocked_achievements=5,
            playtime_minutes=60,
        )
        mock_client = MagicMock()
        mock_client.refresh_single_game.return_value = game
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{CMD_DONE_PKG}.SteamAPIClient", return_value=mock_client),
            patch(f"{CMD_DONE_PKG}._echo"),
            patch(f"{CMD_DONE_PKG}.load_hltb_cache", return_value={1: 20.0}),
            patch(f"{CMD_DONE_PKG}._enforce_on_done"),
        ):
            cmd_done(Config(steam_api_key="k", steam_id="i"), state)

    def test_complete_finalizes(self) -> None:
        game = GameInfo(
            app_id=1,
            name="G",
            total_achievements=10,
            unlocked_achievements=10,
            playtime_minutes=60,
        )
        mock_client = MagicMock()
        mock_client.refresh_single_game.return_value = game
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{CMD_DONE_PKG}.SteamAPIClient", return_value=mock_client),
            patch(f"{CMD_DONE_PKG}._echo"),
            patch(f"{CMD_DONE_PKG}.load_hltb_cache", return_value={1: 10.0}),
            patch(f"{CMD_DONE_PKG}._finalize_completion") as mock_final,
        ):
            cmd_done(Config(steam_api_key="k", steam_id="i"), state)
        mock_final.assert_called_once()

    def test_hltb_cache_miss_fetches(self) -> None:
        game = GameInfo(
            app_id=1,
            name="G",
            total_achievements=10,
            unlocked_achievements=5,
            playtime_minutes=60,
        )
        mock_client = MagicMock()
        mock_client.refresh_single_game.return_value = game
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{CMD_DONE_PKG}.SteamAPIClient", return_value=mock_client),
            patch(f"{CMD_DONE_PKG}._echo"),
            patch(f"{CMD_DONE_PKG}.load_hltb_cache", return_value={}),
            patch(
                f"{CMD_DONE_PKG}.fetch_hltb_times_cached",
                return_value={1: 15.0},
            ),
            patch(f"{CMD_DONE_PKG}._enforce_on_done"),
        ):
            cmd_done(Config(steam_api_key="k", steam_id="i"), state)

    def test_hltb_negative_no_display(self) -> None:
        """Covers the hours <= 0 branch (no HLTB estimate display)."""
        game = GameInfo(
            app_id=1,
            name="G",
            total_achievements=10,
            unlocked_achievements=5,
            playtime_minutes=60,
        )
        mock_client = MagicMock()
        mock_client.refresh_single_game.return_value = game
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{CMD_DONE_PKG}.SteamAPIClient", return_value=mock_client),
            patch(f"{CMD_DONE_PKG}._echo"),
            patch(f"{CMD_DONE_PKG}.load_hltb_cache", return_value={1: -1.0}),
            patch(f"{CMD_DONE_PKG}._enforce_on_done"),
        ):
            cmd_done(Config(steam_api_key="k", steam_id="i"), state)

    def test_reassign_returns_true(self) -> None:
        game = GameInfo(
            app_id=1,
            name="G",
            total_achievements=10,
            unlocked_achievements=10,
            playtime_minutes=60,
        )
        mock_client = MagicMock()
        mock_client.refresh_single_game.return_value = game
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{CMD_DONE_PKG}.SteamAPIClient", return_value=mock_client),
            patch(f"{CMD_DONE_PKG}._echo"),
            patch(f"{CMD_DONE_PKG}.load_hltb_cache", return_value={1: 50.0}),
            patch(f"{CMD_DONE_PKG}._finalize_completion"),
        ):
            cmd_done(Config(steam_api_key="k", steam_id="i"), state)


class TestMain:
    """Tests for main CLI entry point."""

    def test_no_args_exits(self) -> None:
        with (
            patch.object(sys, "argv", ["prog"]),
            patch(f"{PKG}._echo"),
            pytest.raises(SystemExit, match="1"),
        ):
            main()

    def test_unknown_command_exits(self) -> None:
        with (
            patch.object(sys, "argv", ["prog", "bogus"]),
            patch(f"{PKG}._echo"),
            pytest.raises(SystemExit, match="1"),
        ):
            main()

    def test_valid_command_runs(self) -> None:
        mock_cmd = MagicMock()
        with (
            patch.object(sys, "argv", ["prog", "status"]),
            patch(f"{PKG}.Config.load", return_value=Config(steam_api_key="k")),
            patch(f"{PKG}.State.load", return_value=State()),
            patch.dict(f"{PKG}.COMMANDS", {"status": ("s", mock_cmd)}),
        ):
            main()
        mock_cmd.assert_called_once()

    def test_setup_no_key_required(self) -> None:
        mock_cmd = MagicMock()
        with (
            patch.object(sys, "argv", ["prog", "setup"]),
            patch(f"{PKG}.Config.load", return_value=Config()),
            patch(f"{PKG}.State.load", return_value=State()),
            patch.dict(f"{PKG}.COMMANDS", {"setup": ("s", mock_cmd)}),
        ):
            main()
        mock_cmd.assert_called_once()

    def test_no_api_key_exits(self) -> None:
        with (
            patch.object(sys, "argv", ["prog", "status"]),
            patch(f"{PKG}.Config.load", return_value=Config()),
            patch(f"{PKG}._echo"),
            pytest.raises(SystemExit, match="1"),
        ):
            main()


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
        snap = [_snap(2, "NewGame", 10, 0, 5.0)]
        with (
            patch(f"{PKG}.load_snapshot", return_value=snap),
            patch(f"{PKG}.load_hltb_cache", return_value={2: 5.0}),
            patch(f"{PKG}.pick_next_game") as mock_pick,
            patch(f"{PKG}.get_all_owned_app_ids", return_value=[]),
        ):
            config = Config(steam_api_key="k", steam_id="i")
            state = State()
            cmd_pick(config, state)
        mock_pick.assert_called_once()

    def test_hides_games_after_pick(self) -> None:
        snap = [_snap(2, "NewGame", 10, 0, 5.0)]
        state = State(current_app_id=2, current_game_name="NewGame")
        with (
            patch(f"{PKG}.load_snapshot", return_value=snap),
            patch(f"{PKG}.load_hltb_cache", return_value={2: 5.0}),
            patch(f"{PKG}.pick_next_game"),
            patch(f"{PKG}.get_all_owned_app_ids", return_value=[1, 2, 3]),
            patch(f"{PKG}.hide_other_games", return_value=2) as mock_hide,
            patch(f"{PKG}._echo"),
        ):
            cmd_pick(Config(steam_api_key="k", steam_id="i"), state)
        mock_hide.assert_called_once_with([1, 2, 3], 2)

    def test_no_hide_message_when_none_hidden(self) -> None:
        snap = [_snap(2, "NewGame", 10, 0, 5.0)]
        state = State(current_app_id=2, current_game_name="NewGame")
        with (
            patch(f"{PKG}.load_snapshot", return_value=snap),
            patch(f"{PKG}.load_hltb_cache", return_value={}),
            patch(f"{PKG}.pick_next_game"),
            patch(f"{PKG}.get_all_owned_app_ids", return_value=[1, 2, 3]),
            patch(f"{PKG}.hide_other_games", return_value=0),
            patch(f"{PKG}._echo") as mock_echo,
        ):
            cmd_pick(Config(steam_api_key="k", steam_id="i"), state)
        mock_echo.assert_not_called()

    def test_no_hide_when_no_current_app(self) -> None:
        snap = [_snap(2, "NewGame", 10, 0, 5.0)]
        with (
            patch(f"{PKG}.load_snapshot", return_value=snap),
            patch(f"{PKG}.load_hltb_cache", return_value={}),
            patch(f"{PKG}.pick_next_game"),
            patch(f"{PKG}.get_all_owned_app_ids") as mock_owned,
        ):
            cmd_pick(Config(steam_api_key="k", steam_id="i"), State())
        mock_owned.assert_not_called()

    def test_no_hide_when_owned_ids_empty(self) -> None:
        snap = [_snap(2, "NewGame", 10, 0, 5.0)]
        state = State(current_app_id=2, current_game_name="NewGame")
        with (
            patch(f"{PKG}.load_snapshot", return_value=snap),
            patch(f"{PKG}.load_hltb_cache", return_value={}),
            patch(f"{PKG}.pick_next_game"),
            patch(f"{PKG}.get_all_owned_app_ids", return_value=[]),
            patch(f"{PKG}.hide_other_games") as mock_hide,
        ):
            cmd_pick(Config(steam_api_key="k", steam_id="i"), state)
        mock_hide.assert_not_called()

    def test_hltb_cache_applied_to_games(self) -> None:
        snap = [_snap(2, "NewGame", 10, 0, -1.0)]
        captured_games: list[list[GameInfo]] = []
        config = Config(steam_api_key="k", steam_id="i")
        state = State()

        def capture_pick(games: list[GameInfo], *_args: object) -> None:
            captured_games.append(list(games))

        with (
            patch(f"{PKG}.load_snapshot", return_value=snap),
            patch(f"{PKG}.load_hltb_cache", return_value={2: 7.5}),
            patch(f"{PKG}.pick_next_game", side_effect=capture_pick),
            patch(f"{PKG}.get_all_owned_app_ids", return_value=[]),
        ):
            cmd_pick(config, state)

        assert len(captured_games) == 1
        assert captured_games[0][0].completionist_hours == pytest.approx(7.5)
