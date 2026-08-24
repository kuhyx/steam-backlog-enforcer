"""Tests for shutting Steam down and relaunching it with the debug port.

Split to keep every test file under the 250-line cap.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from steam_backlog_enforcer._steam_launch import (
    _launch_steam_with_debug,
    _shutdown_steam,
)


class TestShutdownSteam:
    """Tests for _shutdown_steam."""

    def test_exits_immediately(self) -> None:
        mock_result = MagicMock(returncode=1)  # Not running
        with (
            patch(
                "steam_backlog_enforcer._steam_launch._run_as_user",
            ),
            patch(
                "steam_backlog_enforcer._steam_launch.subprocess.run",
                return_value=mock_result,
            ),
        ):
            _shutdown_steam()

    def test_waits_for_exit(self) -> None:
        results = [MagicMock(returncode=0), MagicMock(returncode=1)]
        with (
            patch(
                "steam_backlog_enforcer._steam_launch._run_as_user",
            ),
            patch(
                "steam_backlog_enforcer._steam_launch.subprocess.run",
                side_effect=results,
            ),
            patch(
                "steam_backlog_enforcer._steam_launch.time.sleep",
            ),
        ):
            _shutdown_steam()

    def test_file_not_found(self) -> None:
        with patch(
            "steam_backlog_enforcer._steam_launch._run_as_user",
            side_effect=FileNotFoundError,
        ):
            _shutdown_steam()  # Should not raise

    def test_timeout(self) -> None:
        mock_result = MagicMock(returncode=0)  # Still running
        with (
            patch(
                "steam_backlog_enforcer._steam_launch._run_as_user",
            ),
            patch(
                "steam_backlog_enforcer._steam_launch.subprocess.run",
                return_value=mock_result,
            ),
            patch(
                "steam_backlog_enforcer._steam_launch.time.sleep",
            ),
        ):
            _shutdown_steam()  # Should complete loop without raising


class TestLaunchSteamWithDebug:
    """Tests for _launch_steam_with_debug."""

    def test_launches(self) -> None:
        with patch(
            "steam_backlog_enforcer._steam_launch._run_as_user",
        ) as mock_run:
            _launch_steam_with_debug()
            mock_run.assert_called_once()
