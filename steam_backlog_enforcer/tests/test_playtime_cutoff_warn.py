"""Tests for the playtime warnings and the desktop notification route."""

import logging
from typing import TYPE_CHECKING
from unittest.mock import patch

from steam_backlog_enforcer._playtime_cutoff import _warn
from steam_backlog_enforcer._playtime_notify import notify_desktop_user
from steam_backlog_enforcer._playtime_state import (
    PlaytimeRules,
    PlaytimeState,
    rules_for,
)
from steam_backlog_enforcer.config import Config

if TYPE_CHECKING:
    import pytest


def _rules() -> PlaytimeRules:
    return rules_for(Config(), demo=False)


class TestWarn:
    """Warnings fire once per threshold and are recorded."""

    def test_records_the_threshold(self) -> None:
        """A due threshold notifies and is added to warned_seconds."""
        state = PlaytimeState(seconds=8 * 3600 - 300, warned_seconds=[3600, 1800, 600])
        with patch(
            "steam_backlog_enforcer._playtime_cutoff.notify_desktop_user"
        ) as mock_notify:
            out = _warn(state, _rules())
        assert out.warned_seconds == [3600, 1800, 600, 300]
        assert mock_notify.call_args.args == ("⏳🎮", "5m")

    def test_a_fired_warning_is_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        """A fired warning is also logged."""
        state = PlaytimeState(seconds=8 * 3600 - 300, warned_seconds=[3600, 1800, 600])
        with (
            caplog.at_level(logging.INFO),
            patch("steam_backlog_enforcer._playtime_cutoff.notify_desktop_user"),
        ):
            _warn(state, _rules())
        assert "5 minutes" in caplog.text

    def test_no_op_when_nothing_is_due(self) -> None:
        """With no threshold due nothing is sent and the state is returned as is."""
        state = PlaytimeState(seconds=0.0)
        with patch(
            "steam_backlog_enforcer._playtime_cutoff.notify_desktop_user"
        ) as mock_notify:
            out = _warn(state, _rules())
        mock_notify.assert_not_called()
        assert out is state


class TestNotifyDesktopUser:
    """Desktop notifications go to the desktop user and never raise."""

    def test_routes_through_the_desktop_session(self) -> None:
        """notify-send as root with no DBUS address never reaches the user."""
        with (
            patch(
                "steam_backlog_enforcer._playtime_notify._resolve_desktop_user",
                return_value="kuhy",
            ),
            patch("steam_backlog_enforcer._playtime_notify._run_as_user") as mock_run,
        ):
            notify_desktop_user("T", "B")
        cmd, user = mock_run.call_args.args
        assert cmd[0] == "notify-send"
        assert user == "kuhy"

    def test_swallows_errors(self) -> None:
        """A failure to reach the session is swallowed."""
        with (
            patch(
                "steam_backlog_enforcer._playtime_notify._resolve_desktop_user",
                return_value="kuhy",
            ),
            patch(
                "steam_backlog_enforcer._playtime_notify._run_as_user",
                side_effect=OSError("no session"),
            ),
        ):
            notify_desktop_user("T", "B")
