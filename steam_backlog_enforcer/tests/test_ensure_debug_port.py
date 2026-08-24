"""Tests for ensure_steam_debug_port: getting Steam drivable over CDP.

Split to keep every test file under the 250-line cap.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from steam_backlog_enforcer._steam_errors import SteamUnavailableError
from steam_backlog_enforcer._steam_launch import (
    ensure_steam_debug_port,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


class TestEnsureSteamDebugPort:
    """Tests for ensure_steam_debug_port."""

    @pytest.fixture(autouse=True)
    def _steam_present(self) -> Iterator[None]:
        """Pretend Steam is installed for every test in this class.

        Without it the function raises before reaching any launch logic,
        which on a test machine without Steam would make the cases below
        vacuous. The absent case has its own test.
        """
        with patch(
            "steam_backlog_enforcer._steam_launch.steam_is_installed",
            return_value=True,
        ):
            yield

    def test_raises_when_steam_absent(self) -> None:
        """An uninstalled Steam must fail fast, before any launch attempt.

        Regression guard: without this the caller spent ~45s waiting on a
        CDP port that no process was ever going to open.
        """
        with (
            patch(
                "steam_backlog_enforcer._steam_launch._steam_has_debug_port",
                return_value=False,
            ),
            patch(
                "steam_backlog_enforcer._steam_launch.steam_is_installed",
                return_value=False,
            ),
            patch(
                "steam_backlog_enforcer._steam_launch._launch_steam_with_debug",
            ) as mock_launch,
            pytest.raises(SteamUnavailableError, match="not installed"),
        ):
            ensure_steam_debug_port()

        mock_launch.assert_not_called()

    def test_already_available(self) -> None:
        with patch(
            "steam_backlog_enforcer._steam_launch._steam_has_debug_port",
            return_value=True,
        ):
            ensure_steam_debug_port()

    def test_starts_fresh(self) -> None:
        with (
            patch(
                "steam_backlog_enforcer._steam_launch._steam_has_debug_port",
                return_value=False,
            ),
            patch(
                "steam_backlog_enforcer._steam_launch._is_steam_running",
                return_value=False,
            ),
            patch(
                "steam_backlog_enforcer._steam_launch._launch_steam_with_debug",
            ),
            patch(
                "steam_backlog_enforcer._steam_launch._wait_for_cdp_ready",
                return_value=True,
            ),
            patch(
                "steam_backlog_enforcer._steam_launch._wait_for_collections_ready",
                return_value=True,
            ),
        ):
            ensure_steam_debug_port()

    def test_restarts_running_steam(self) -> None:
        with (
            patch(
                "steam_backlog_enforcer._steam_launch._steam_has_debug_port",
                return_value=False,
            ),
            patch(
                "steam_backlog_enforcer._steam_launch._is_steam_running",
                return_value=True,
            ),
            patch(
                "steam_backlog_enforcer._steam_launch._shutdown_steam",
            ),
            patch(
                "steam_backlog_enforcer._steam_launch._launch_steam_with_debug",
            ),
            patch(
                "steam_backlog_enforcer._steam_launch._wait_for_cdp_ready",
                return_value=True,
            ),
            patch(
                "steam_backlog_enforcer._steam_launch._wait_for_collections_ready",
                return_value=True,
            ),
        ):
            ensure_steam_debug_port()

    def test_cdp_timeout(self) -> None:
        with (
            patch(
                "steam_backlog_enforcer._steam_launch._steam_has_debug_port",
                return_value=False,
            ),
            patch(
                "steam_backlog_enforcer._steam_launch._is_steam_running",
                return_value=False,
            ),
            patch(
                "steam_backlog_enforcer._steam_launch._launch_steam_with_debug",
            ),
            patch(
                "steam_backlog_enforcer._steam_launch._wait_for_cdp_ready",
                return_value=False,
            ),
            pytest.raises(RuntimeError, match="Timed out waiting for Steam CDP"),
        ):
            ensure_steam_debug_port()

    def test_collections_timeout(self) -> None:
        with (
            patch(
                "steam_backlog_enforcer._steam_launch._steam_has_debug_port",
                return_value=False,
            ),
            patch(
                "steam_backlog_enforcer._steam_launch._is_steam_running",
                return_value=False,
            ),
            patch(
                "steam_backlog_enforcer._steam_launch._launch_steam_with_debug",
            ),
            patch(
                "steam_backlog_enforcer._steam_launch._wait_for_cdp_ready",
                return_value=True,
            ),
            patch(
                "steam_backlog_enforcer._steam_launch._wait_for_collections_ready",
                return_value=False,
            ),
            pytest.raises(
                RuntimeError, match="Timed out waiting for Steam collections"
            ),
        ):
            ensure_steam_debug_port()
