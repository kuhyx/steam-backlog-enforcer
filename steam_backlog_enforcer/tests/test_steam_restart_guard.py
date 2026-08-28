"""Tests for refusing to bounce Steam when the bounce would destroy something.

The game case is the one that cost a real session: restarting the daemon on
2026-08-28 relaunched Steam for its CDP port and killed a live game with it.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from steam_backlog_enforcer._steam_errors import (
    GameInProgressError,
    SteamUpdateInProgressError,
)
from steam_backlog_enforcer._steam_restart_guard import (
    assert_safe_to_restart,
    game_is_running,
)

GUARD = "steam_backlog_enforcer._steam_restart_guard"


class TestGameIsRunning:
    def test_no_processes_means_no_game(self) -> None:
        with patch(f"{GUARD}.get_running_steam_game_pids", return_value={}):
            assert game_is_running() is False

    def test_the_steam_client_itself_does_not_count(self) -> None:
        with patch(f"{GUARD}.get_running_steam_game_pids", return_value={42: 0}):
            assert game_is_running() is False

    def test_a_real_app_id_counts(self) -> None:
        with patch(
            f"{GUARD}.get_running_steam_game_pids", return_value={42: 0, 43: 3164500}
        ):
            assert game_is_running() is True


class TestAssertSafeToRestart:
    def test_refuses_while_a_game_runs(self) -> None:
        with (
            patch(f"{GUARD}.get_running_steam_game_pids", return_value={7: 412830}),
            patch(f"{GUARD}.steam_update_in_progress", return_value=False),
            pytest.raises(GameInProgressError),
        ):
            assert_safe_to_restart()

    def test_a_running_game_outranks_an_update(self) -> None:
        with (
            patch(f"{GUARD}.get_running_steam_game_pids", return_value={7: 412830}),
            patch(f"{GUARD}.steam_update_in_progress", return_value=True),
            pytest.raises(GameInProgressError),
        ):
            assert_safe_to_restart()

    def test_refuses_during_an_update(self) -> None:
        with (
            patch(f"{GUARD}.get_running_steam_game_pids", return_value={}),
            patch(f"{GUARD}.steam_update_in_progress", return_value=True),
            pytest.raises(SteamUpdateInProgressError),
        ):
            assert_safe_to_restart()

    def test_allows_when_idle(self) -> None:
        with (
            patch(f"{GUARD}.get_running_steam_game_pids", return_value={}),
            patch(f"{GUARD}.steam_update_in_progress", return_value=False),
        ):
            assert_safe_to_restart()
