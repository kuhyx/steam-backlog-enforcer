"""Tests for how ``status`` shows two concurrent manual picks.

Split out of test_main_abandon.py to keep every test file under 250 lines.
"""

from __future__ import annotations

from unittest.mock import patch

from steam_backlog_enforcer.config import Config
from steam_backlog_enforcer.main import cmd_status
from steam_backlog_enforcer.tests._main_helpers import OLD_PICK, two_pick_state


class TestStatusWithTwoPicks:
    def test_status_lists_both_picks(self) -> None:
        with (
            patch(
                "steam_backlog_enforcer.main.status.is_store_blocked",
                return_value=False,
            ),
            patch(
                "steam_backlog_enforcer.main.status.get_installed_games",
                return_value=[],
            ),
            patch(
                "steam_backlog_enforcer.main.status.report_completion",
                return_value=[],
            ),
            patch("steam_backlog_enforcer.main.status._echo") as mock_echo,
        ):
            cmd_status(Config(), two_pick_state())
        output = " ".join(str(c) for c in mock_echo.call_args_list)
        assert "Manual picks (2)" in output
        assert "picked" in output
        assert "day(s) ago" in output

    def test_status_shows_age_for_old_picks(self) -> None:
        state = two_pick_state()
        state.manual_picks[0]["started_at"] = OLD_PICK
        state.manual_picks[1]["started_at"] = OLD_PICK
        with (
            patch(
                "steam_backlog_enforcer.main.status.is_store_blocked",
                return_value=False,
            ),
            patch(
                "steam_backlog_enforcer.main.status.get_installed_games",
                return_value=[],
            ),
            patch(
                "steam_backlog_enforcer.main.status.report_completion",
                return_value=[],
            ),
            patch("steam_backlog_enforcer.main.status._echo") as mock_echo,
        ):
            cmd_status(Config(), state)
        assert "picked 8.0 day(s) ago" in " ".join(
            str(c) for c in mock_echo.call_args_list
        )
