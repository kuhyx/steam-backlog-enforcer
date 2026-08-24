"""Tests for the main CLI: done command dispatch."""

from unittest.mock import MagicMock, patch

from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.main import (
    cmd_done,
)
from steam_backlog_enforcer.steam_api import GameInfo

PKG = "steam_backlog_enforcer.main"
CMD_DONE_PKG = "steam_backlog_enforcer._cmd_done_finalize"


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
