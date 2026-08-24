"""Tests for library_hider's hide/unhide operations.

Split from test_library_hider_part2.py to keep both files under the 250-line cap.
"""

from __future__ import annotations

from unittest.mock import patch

from steam_backlog_enforcer._steam_errors import (
    SteamUnavailableError,
    SteamUpdateInProgressError,
)
from steam_backlog_enforcer._steam_launch import restart_steam
from steam_backlog_enforcer.library_hider import (
    hide_other_games,
    try_hide_other_games,
    unhide_all_games,
)

PKG = "steam_backlog_enforcer.library_hider"
STEAM_LAUNCH_PKG = "steam_backlog_enforcer._steam_launch"
LIBRARY_HIDER_PKG = "steam_backlog_enforcer.library_hider"


class TestRestartSteam:
    """Tests for restart_steam."""

    def test_cdp_ready(self) -> None:
        with (
            patch("steam_backlog_enforcer._steam_launch._shutdown_steam"),
            patch("steam_backlog_enforcer._steam_launch._launch_steam_with_debug"),
            patch(
                "steam_backlog_enforcer._steam_launch._wait_for_cdp_ready",
                return_value=True,
            ),
        ):
            restart_steam()

    def test_cdp_not_ready(self) -> None:
        with (
            patch("steam_backlog_enforcer._steam_launch._shutdown_steam"),
            patch("steam_backlog_enforcer._steam_launch._launch_steam_with_debug"),
            patch(
                "steam_backlog_enforcer._steam_launch._wait_for_cdp_ready",
                return_value=False,
            ),
        ):
            restart_steam()


class TestHideOtherGames:
    """Tests for hide_other_games."""

    def test_hides(self) -> None:
        with (
            patch("steam_backlog_enforcer.library_hider.ensure_steam_debug_port"),
            patch(
                "steam_backlog_enforcer.library_hider._evaluate_js",
                return_value={
                    "result": {"result": {"value": '{"totalHidden": 5}'}},
                },
            ),
            patch(
                "steam_backlog_enforcer.library_hider._cdp_result_value",
                return_value='{"totalHidden": 5}',
            ),
        ):
            count = hide_other_games([1, 2, 3], {1})
            assert count == 5

    def test_empty_list(self) -> None:
        with (
            patch("steam_backlog_enforcer.library_hider.ensure_steam_debug_port"),
            patch(
                "steam_backlog_enforcer.library_hider._evaluate_js",
                return_value={
                    "result": {"result": {"value": '{"totalHidden": 0}'}},
                },
            ),
            patch(
                "steam_backlog_enforcer.library_hider._cdp_result_value",
                return_value='{"totalHidden": 0}',
            ),
        ):
            count = hide_other_games([1], {1})
            assert count == 0

    def test_no_allowed(self) -> None:
        with (
            patch("steam_backlog_enforcer.library_hider.ensure_steam_debug_port"),
            patch(
                "steam_backlog_enforcer.library_hider._evaluate_js",
                return_value={
                    "result": {"result": {"value": '{"totalHidden": 2}'}},
                },
            ),
            patch(
                "steam_backlog_enforcer.library_hider._cdp_result_value",
                return_value='{"totalHidden": 2}',
            ),
        ):
            count = hide_other_games([1, 2], set())
            assert count == 2


class TestTryHideOtherGames:
    """Tests for the graceful wrapper around hide_other_games.

    Regression guard: an unreachable Steam (or a deferred restart while a game
    update is in flight) used to escape as a traceback out of every
    interactive command that reconciles the library.
    """

    def test_success_returns_count_and_no_reason(self) -> None:
        with patch(f"{PKG}.hide_other_games", return_value=7):
            assert try_hide_other_games([1, 2], {1}) == (7, None)

    def test_steam_unavailable_is_reported_not_raised(self) -> None:
        with patch(
            f"{PKG}.hide_other_games",
            side_effect=SteamUnavailableError("Steam is not installed"),
        ):
            hidden, reason = try_hide_other_games([1, 2], {1})
        assert hidden == 0
        assert reason == "Steam is not installed"

    def test_update_in_progress_is_reported_not_raised(self) -> None:
        with patch(
            f"{PKG}.hide_other_games",
            side_effect=SteamUpdateInProgressError("update in progress"),
        ):
            hidden, reason = try_hide_other_games([1, 2], {1})
        assert hidden == 0
        assert reason == "update in progress"


class TestUnhideAllGames:
    """Tests for unhide_all_games."""

    def test_unhides(self) -> None:
        with (
            patch("steam_backlog_enforcer.library_hider.ensure_steam_debug_port"),
            patch(
                "steam_backlog_enforcer.library_hider._evaluate_js",
                return_value={"result": {"result": {"value": '{"count": 10}'}}},
            ),
            patch(
                "steam_backlog_enforcer.library_hider._cdp_result_value",
                return_value='{"count": 10}',
            ),
        ):
            count = unhide_all_games([1, 2, 3])
            assert count == 10
