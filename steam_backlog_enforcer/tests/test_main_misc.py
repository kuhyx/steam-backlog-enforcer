"""Tests for the main CLI: store, reset, setup, exception and block-gaming commands."""

from unittest.mock import patch

from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.main import (
    cmd_buy_dlc,
    cmd_reset,
    cmd_setup,
    cmd_unblock,
)

PKG = "steam_backlog_enforcer.main.misc"


class TestCmdUnblock:
    """Tests for cmd_unblock."""

    def test_success(self) -> None:
        with (
            patch(f"{PKG}.unblock_store", return_value=True),
            patch(f"{PKG}._echo"),
        ):
            cmd_unblock(Config(), State())

    def test_fail(self) -> None:
        with (
            patch(f"{PKG}.unblock_store", return_value=False),
            patch(f"{PKG}._echo") as mock_echo,
        ):
            cmd_unblock(Config(), State())
            assert any("Failed" in str(c) for c in mock_echo.call_args_list)


class TestCmdBuyDlc:
    """Tests for cmd_buy_dlc."""

    def test_no_game(self) -> None:
        with patch(f"{PKG}._echo") as mock_echo:
            cmd_buy_dlc(Config(), State())
            assert any("No game" in str(c) for c in mock_echo.call_args_list)

    def test_unblock_fails(self) -> None:
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{PKG}.unblock_store", return_value=False),
            patch(f"{PKG}._echo"),
        ):
            cmd_buy_dlc(Config(), state)

    def test_success_reblock(self) -> None:
        state = State(current_app_id=1, current_game_name="G")
        config = Config(block_store=True)
        with (
            patch(f"{PKG}.unblock_store", return_value=True),
            patch(f"{PKG}.block_store", return_value=True),
            patch(f"{PKG}.restart_steam"),
            patch(f"{PKG}._echo"),
            patch("builtins.input", return_value=""),
        ):
            cmd_buy_dlc(config, state)

    def test_reblock_fails(self) -> None:
        state = State(current_app_id=1, current_game_name="G")
        config = Config(block_store=True)
        with (
            patch(f"{PKG}.unblock_store", return_value=True),
            patch(f"{PKG}.block_store", return_value=False),
            patch(f"{PKG}._echo") as mock_echo,
            patch("builtins.input", return_value=""),
        ):
            cmd_buy_dlc(config, state)
            assert any("Warning" in str(c) for c in mock_echo.call_args_list)

    def test_no_reblock(self) -> None:
        state = State(current_app_id=1, current_game_name="G")
        config = Config(block_store=False)
        with (
            patch(f"{PKG}.unblock_store", return_value=True),
            patch(f"{PKG}._echo"),
            patch("builtins.input", return_value=""),
        ):
            cmd_buy_dlc(config, state)


class TestCmdReset:
    """Tests for cmd_reset."""

    def test_normal_reset(self) -> None:
        state = State(current_app_id=1, current_game_name="G", finished_app_ids=[1])
        with (
            patch(f"{PKG}.unblock_store"),
            patch(f"{PKG}.get_all_owned_app_ids", return_value=[1, 2]),
            patch(f"{PKG}.unhide_all_games", return_value=2),
            patch(f"{PKG}._echo"),
            patch.object(State, "save"),
        ):
            cmd_reset(Config(), state)
            assert state.current_app_id is None
            assert state.finished_app_ids == []

    def test_unhide_fails(self) -> None:
        state = State(current_app_id=1)
        with (
            patch(f"{PKG}.unblock_store"),
            patch(
                f"{PKG}.get_all_owned_app_ids",
                side_effect=OSError("fail"),
            ),
            patch(f"{PKG}._echo"),
            patch.object(State, "save"),
        ):
            cmd_reset(Config(), state)

    def test_unhide_returns_zero(self) -> None:
        state = State(current_app_id=1)
        with (
            patch(f"{PKG}.unblock_store"),
            patch(f"{PKG}.get_all_owned_app_ids", return_value=[1, 2]),
            patch(f"{PKG}.unhide_all_games", return_value=0),
            patch(f"{PKG}._echo"),
            patch.object(State, "save"),
        ):
            cmd_reset(Config(), state)

    def test_no_owned_ids(self) -> None:
        state = State(current_app_id=1)
        with (
            patch(f"{PKG}.unblock_store"),
            patch(f"{PKG}.get_all_owned_app_ids", return_value=[]),
            patch(f"{PKG}._echo"),
            patch.object(State, "save"),
        ):
            cmd_reset(Config(), state)


class TestCmdSetup:
    """Tests for cmd_setup."""

    def test_calls_interactive(self) -> None:
        with patch(f"{PKG}.interactive_setup") as mock_setup:
            cmd_setup(Config(), State())
            mock_setup.assert_called_once()
