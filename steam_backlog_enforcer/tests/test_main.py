"""Tests for main CLI module."""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import patch

import pytest

from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.main import (
    cmd_add_exception,
    cmd_buy_dlc,
    cmd_hide,
    cmd_install,
    cmd_installed,
    cmd_list,
    cmd_reset,
    cmd_setup,
    cmd_status,
    cmd_unblock,
    cmd_unhide,
    cmd_uninstall,
    main,
)

PKG = "steam_backlog_enforcer.main"


def _snap(
    app_id: int = 1,
    name: str = "G",
    total: int = 10,
    unlocked: int = 0,
    hours: float = -1,
) -> dict[str, Any]:
    return {
        "app_id": app_id,
        "name": name,
        "total_achievements": total,
        "unlocked_achievements": unlocked,
        "playtime_minutes": 60,
        "completionist_hours": hours,
    }


class TestCmdStatus:
    """Tests for cmd_status."""

    def test_with_game(self) -> None:
        state = State(current_app_id=440, current_game_name="TF2")
        with (
            patch(f"{PKG}.is_store_blocked", return_value=True),
            patch(f"{PKG}.get_installed_games", return_value=[(440, "TF2")]),
            patch(f"{PKG}._echo"),
        ):
            cmd_status(Config(), state)

    def test_no_game(self) -> None:
        with (
            patch(f"{PKG}.is_store_blocked", return_value=False),
            patch(f"{PKG}.get_installed_games", return_value=[]),
            patch(f"{PKG}._echo"),
        ):
            cmd_status(Config(), State())


class TestCmdList:
    """Tests for cmd_list."""

    def test_no_snapshot(self) -> None:
        with (
            patch(f"{PKG}.load_snapshot", return_value=None),
            patch(f"{PKG}._echo") as mock_echo,
        ):
            cmd_list(Config(), State())
            assert any("No snapshot" in str(c) for c in mock_echo.call_args_list)

    def test_with_games(self) -> None:
        snap = [
            _snap(1, "A", 10, 5, 20.0),
            _snap(2, "B", 10, 10, 10.0),
            _snap(3, "C", 10, 3, -1),
        ]
        state = State(current_app_id=1)
        with (
            patch(f"{PKG}.load_snapshot", return_value=snap),
            patch(f"{PKG}._echo"),
        ):
            cmd_list(Config(), state)

    def test_many_games(self) -> None:
        snap = [_snap(i, f"Game{i}") for i in range(60)]
        with (
            patch(f"{PKG}.load_snapshot", return_value=snap),
            patch(f"{PKG}._echo") as mock_echo,
        ):
            cmd_list(Config(), State())
            assert any("more" in str(c) for c in mock_echo.call_args_list)


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


class TestCmdInstalled:
    """Tests for cmd_installed."""

    def test_shows_games(self) -> None:
        with (
            patch(
                f"{PKG}.get_installed_games",
                return_value=[(440, "TF2"), (228980, "RT")],
            ),
            patch(f"{PKG}.is_protected_app", side_effect=lambda aid: aid == 228980),
            patch(f"{PKG}._echo"),
        ):
            cmd_installed(Config(), State(current_app_id=440))


class TestCmdUninstall:
    """Tests for cmd_uninstall."""

    def test_no_game(self) -> None:
        with patch(f"{PKG}._echo") as mock_echo:
            cmd_uninstall(Config(), State())
            assert any("No game" in str(c) for c in mock_echo.call_args_list)

    def test_nothing_to_remove(self) -> None:
        state = State(current_app_id=440)
        with (
            patch(f"{PKG}.get_installed_games", return_value=[(440, "TF2")]),
            patch(f"{PKG}._echo"),
        ):
            cmd_uninstall(Config(), state)

    def test_confirms_yes(self) -> None:
        state = State(current_app_id=440)
        with (
            patch(
                f"{PKG}.get_installed_games",
                return_value=[(440, "TF2"), (730, "CS")],
            ),
            patch(f"{PKG}.uninstall_other_games", return_value=1),
            patch("builtins.input", return_value="YES"),
            patch(f"{PKG}._echo"),
        ):
            cmd_uninstall(Config(), state)

    def test_aborts(self) -> None:
        state = State(current_app_id=440)
        with (
            patch(
                f"{PKG}.get_installed_games",
                return_value=[(440, "TF2"), (730, "CS")],
            ),
            patch("builtins.input", return_value="no"),
            patch(f"{PKG}._echo") as mock_echo,
        ):
            cmd_uninstall(Config(), state)
            assert any("Aborted" in str(c) for c in mock_echo.call_args_list)


class TestCmdSetup:
    """Tests for cmd_setup."""

    def test_calls_interactive(self) -> None:
        with patch(f"{PKG}.interactive_setup") as mock_setup:
            cmd_setup(Config(), State())
            mock_setup.assert_called_once()


class TestCmdInstall:
    """Tests for cmd_install."""

    def test_no_game(self) -> None:
        with patch(f"{PKG}._echo") as mock_echo:
            cmd_install(Config(), State())
            assert any("No game" in str(c) for c in mock_echo.call_args_list)

    def test_already_installed(self) -> None:
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{PKG}.is_game_installed", return_value=True),
            patch(f"{PKG}._echo"),
        ):
            cmd_install(Config(), state)

    def test_installs_ok(self) -> None:
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{PKG}.is_game_installed", return_value=False),
            patch(f"{PKG}.install_game", return_value=True),
            patch(f"{PKG}._echo"),
        ):
            cmd_install(Config(steam_id="i"), state)

    def test_install_fails(self) -> None:
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{PKG}.is_game_installed", return_value=False),
            patch(f"{PKG}.install_game", return_value=False),
            patch(f"{PKG}._echo"),
        ):
            cmd_install(Config(steam_id="i"), state)


class TestCmdHide:
    """Tests for cmd_hide."""

    def test_no_game(self) -> None:
        with patch(f"{PKG}._echo"):
            cmd_hide(Config(), State())

    def test_no_owned(self) -> None:
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{PKG}.get_all_owned_app_ids", return_value=[]),
            patch(f"{PKG}._echo"),
        ):
            cmd_hide(Config(), state)

    def test_hides(self) -> None:
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{PKG}.get_all_owned_app_ids", return_value=[1, 2]),
            patch(f"{PKG}.hide_other_games", return_value=1),
            patch(f"{PKG}._echo"),
        ):
            cmd_hide(Config(), state)

    def test_hides_zero(self) -> None:
        state = State(current_app_id=1, current_game_name="G")
        with (
            patch(f"{PKG}.get_all_owned_app_ids", return_value=[1]),
            patch(f"{PKG}.hide_other_games", return_value=0),
            patch(f"{PKG}._echo"),
        ):
            cmd_hide(Config(), state)


class TestCmdUnhide:
    """Tests for cmd_unhide."""

    def test_no_owned(self) -> None:
        with (
            patch(f"{PKG}.get_all_owned_app_ids", return_value=[]),
            patch(f"{PKG}._echo"),
        ):
            cmd_unhide(Config(), State())

    def test_unhides(self) -> None:
        with (
            patch(f"{PKG}.get_all_owned_app_ids", return_value=[1]),
            patch(f"{PKG}.unhide_all_games", return_value=1),
            patch(f"{PKG}._echo"),
        ):
            cmd_unhide(Config(), State())

    def test_unhides_zero(self) -> None:
        with (
            patch(f"{PKG}.get_all_owned_app_ids", return_value=[1]),
            patch(f"{PKG}.unhide_all_games", return_value=0),
            patch(f"{PKG}._echo"),
        ):
            cmd_unhide(Config(), State())


# ──────────────────────────────────────────────────────────────
# cmd_add_exception
# ──────────────────────────────────────────────────────────────

_VALID_REASON = "I need this game installed for a work presentation this week."


class TestCmdAddException:
    def test_no_args_prints_usage_and_exits(self) -> None:
        with (
            patch(f"{PKG}._echo"),
            pytest.raises(SystemExit, match="1"),
        ):
            cmd_add_exception([])

    def test_missing_reason_flag_exits(self) -> None:
        with (
            patch(f"{PKG}._echo"),
            pytest.raises(SystemExit, match="1"),
        ):
            cmd_add_exception(["440", "no", "flag"])

    def test_non_numeric_app_id_exits(self) -> None:
        with (
            patch(f"{PKG}._echo"),
            pytest.raises(SystemExit, match="1"),
        ):
            cmd_add_exception(["notanumber", "--reason", _VALID_REASON])

    def test_reason_flag_with_no_value_exits(self) -> None:
        with (
            patch(f"{PKG}._echo"),
            pytest.raises(SystemExit, match="1"),
        ):
            cmd_add_exception(["440", "--reason"])

    def test_reason_flag_last_position_with_no_value_exits(self) -> None:
        # 3 args passes the len/flag guard but --reason is last so reason_parts=[]
        with (
            patch(f"{PKG}._echo"),
            pytest.raises(SystemExit, match="1"),
        ):
            cmd_add_exception(["440", "extra", "--reason"])

    def test_invalid_reason_exits(self) -> None:
        with (
            patch(f"{PKG}._echo"),
            pytest.raises(SystemExit, match="1"),
        ):
            cmd_add_exception(["440", "--reason", "too short"])

    def test_add_pending_exception_raises_value_error(self) -> None:
        with (
            patch(f"{PKG}._echo"),
            patch(
                f"{PKG}.add_pending_exception",
                side_effect=ValueError("already approved"),
            ),
            pytest.raises(SystemExit, match="1"),
        ):
            cmd_add_exception(["440", "--reason", _VALID_REASON])

    def test_happy_path(self) -> None:
        with (
            patch(f"{PKG}._echo") as mock_echo,
            patch(
                f"{PKG}.add_pending_exception",
                return_value="Exception approved for AppID 440. Active immediately.",
            ),
        ):
            cmd_add_exception(["440", "--reason", _VALID_REASON])
        mock_echo.assert_called()


# ──────────────────────────────────────────────────────────────
# main() dispatch to add-exception
# ──────────────────────────────────────────────────────────────


class TestMainDispatchAddException:
    def test_dispatches_add_exception(self) -> None:
        argv = ["prog", "add-exception", "440", "--reason", _VALID_REASON]
        with (
            patch.object(sys, "argv", argv),
            patch(f"{PKG}.cmd_add_exception") as mock_cmd,
        ):
            main()
        mock_cmd.assert_called_once_with(["440", "--reason", _VALID_REASON])
