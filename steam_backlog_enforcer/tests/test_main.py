"""Tests for main CLI module."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from python_pkg.steam_backlog_enforcer.config import Config, State
from python_pkg.steam_backlog_enforcer.main import (
    _try_reassign_shorter_game,
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
)
from python_pkg.steam_backlog_enforcer.steam_api import GameInfo

PKG = "python_pkg.steam_backlog_enforcer.main"


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
            patch(f"{PKG}.PROTECTED_APP_IDS", {228980}),
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


class TestTryReassignShorterGame:
    """Tests for _try_reassign_shorter_game."""

    def test_no_snapshot(self) -> None:
        with patch(f"{PKG}.load_snapshot", return_value=None):
            assert not _try_reassign_shorter_game({}, 1, 10.0, State(), Config())

    def test_no_shorter_candidate(self) -> None:
        snap = [_snap(1, "G", 10, 5, 10.0), _snap(2, "H", 10, 5, -1)]
        with (
            patch(f"{PKG}.load_snapshot", return_value=snap),
            patch(f"{PKG}._echo"),
        ):
            result = _try_reassign_shorter_game(
                {1: 10.0},
                1,
                10.0,
                State(),
                Config(),
            )
            assert not result

    def test_reassigns(self) -> None:
        snap = [
            _snap(1, "Long", 10, 5, 100.0),
            _snap(2, "Short", 10, 5, 5.0),
        ]
        state = State(current_app_id=1, current_game_name="Long")
        short_game = GameInfo(
            app_id=2,
            name="Short",
            total_achievements=10,
            unlocked_achievements=5,
            playtime_minutes=60,
            completionist_hours=5.0,
        )
        with (
            patch(f"{PKG}.load_snapshot", return_value=snap),
            patch(f"{PKG}._echo"),
            patch(
                f"{PKG}._pick_playable_candidate",
                return_value=short_game,
            ),
            patch(f"{PKG}.pick_next_game"),
        ):
            result = _try_reassign_shorter_game(
                {1: 100.0, 2: 5.0},
                1,
                100.0,
                state,
                Config(),
            )
            assert result

    def test_playable_none(self) -> None:
        snap = [
            _snap(1, "Long", 10, 5, 100.0),
            _snap(2, "Short", 10, 5, 5.0),
        ]
        with (
            patch(f"{PKG}.load_snapshot", return_value=snap),
            patch(f"{PKG}._pick_playable_candidate", return_value=None),
            patch(f"{PKG}._echo"),
        ):
            result = _try_reassign_shorter_game(
                {1: 100.0, 2: 5.0},
                1,
                100.0,
                State(),
                Config(),
            )
            assert not result

    def test_playable_longer(self) -> None:
        """Playable candidate is longer than current — no reassign."""
        snap = [
            _snap(1, "Short", 10, 5, 10.0),
            _snap(2, "Long", 10, 5, 200.0),
        ]
        long_game = GameInfo(
            app_id=2,
            name="Long",
            total_achievements=10,
            unlocked_achievements=5,
            playtime_minutes=60,
            completionist_hours=200.0,
        )
        with (
            patch(f"{PKG}.load_snapshot", return_value=snap),
            patch(f"{PKG}._pick_playable_candidate", return_value=long_game),
            patch(f"{PKG}._echo"),
        ):
            result = _try_reassign_shorter_game(
                {1: 10.0, 2: 200.0},
                1,
                10.0,
                State(),
                Config(),
            )
            assert not result

    def test_refreshes_stale_shorter_snapshot_entry(self) -> None:
        """Uncached shorter snapshot candidates are refreshed before reassigning."""
        snap = [
            _snap(1, "Current", 10, 5, 20.1),
            _snap(2, "Lacuna", 10, 0, 0.9),
        ]
        state = State(current_app_id=1, current_game_name="Current")
        refreshed_short = GameInfo(
            app_id=2,
            name="Lacuna",
            total_achievements=10,
            unlocked_achievements=0,
            playtime_minutes=60,
            completionist_hours=18.8,
        )
        with (
            patch(f"{PKG}.load_snapshot", return_value=snap),
            patch(
                f"{PKG}.fetch_hltb_times_cached",
                return_value={2: 18.8},
            ) as mock_fetch_hltb,
            patch(
                f"{PKG}._pick_playable_candidate",
                return_value=refreshed_short,
            ) as mock_pick_playable,
            patch(f"{PKG}.pick_next_game"),
            patch(f"{PKG}._echo"),
        ):
            result = _try_reassign_shorter_game(
                {1: 20.1},
                1,
                20.1,
                state,
                Config(),
            )

        assert result
        mock_fetch_hltb.assert_called_once_with([(2, "Lacuna")])
        mock_pick_playable.assert_called_once()
