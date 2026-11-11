"""Tests for how ``status`` shows two concurrent manual picks.

Split out of test_main_abandon.py to keep every test file under 250 lines.
"""

from __future__ import annotations

from steam_backlog_enforcer.config import Config
from steam_backlog_enforcer.main import cmd_status
from steam_backlog_enforcer.tests._main_dispatch_world import status_stubs
from steam_backlog_enforcer.tests._main_helpers import OLD_PICK, two_pick_state


class TestStatusWithTwoPicks:
    """status shows every concurrent manual pick with its age."""

    def test_status_lists_both_picks(self) -> None:
        """Two manual picks are both listed with how long ago they were picked."""
        with status_stubs(stub_completion=True) as mock_echo:
            cmd_status(Config(), two_pick_state())
        output = " ".join(str(c) for c in mock_echo.call_args_list)
        assert "Manual picks (2)" in output
        assert "picked" in output
        assert "day(s) ago" in output

    def test_status_shows_age_for_old_picks(self) -> None:
        """Old picks show their age in days."""
        state = two_pick_state()
        state.manual_picks[0]["started_at"] = OLD_PICK
        state.manual_picks[1]["started_at"] = OLD_PICK
        with status_stubs(stub_completion=True) as mock_echo:
            cmd_status(Config(), state)
        assert "picked 8.0 day(s) ago" in " ".join(
            str(c) for c in mock_echo.call_args_list
        )
