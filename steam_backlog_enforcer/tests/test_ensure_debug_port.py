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
from steam_backlog_enforcer.tests._desktop_launch_patches import (
    fresh_launch_patches,
    launch_patches,
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
            launch_patches(
                "_launch_steam_with_debug",
                _steam_has_debug_port=False,
                steam_is_installed=False,
            ) as mocks,
            pytest.raises(SteamUnavailableError, match="not installed"),
        ):
            ensure_steam_debug_port()

        mocks["_launch_steam_with_debug"].assert_not_called()

    def test_already_available(self) -> None:
        """An open debug port needs no launch and does not raise."""
        with patch(
            "steam_backlog_enforcer._steam_launch._steam_has_debug_port",
            return_value=True,
        ):
            ensure_steam_debug_port()

    def test_starts_fresh(self) -> None:
        """A stopped Steam is launched with the debug port and waited on."""
        with fresh_launch_patches(_is_steam_running=False):
            ensure_steam_debug_port()

    def test_restarts_running_steam(self) -> None:
        """A running Steam without the port is shut down and relaunched."""
        with fresh_launch_patches("_shutdown_steam", _is_steam_running=True):
            ensure_steam_debug_port()

    def test_cdp_timeout(self) -> None:
        """A CDP port that never opens raises a timeout."""
        with (
            fresh_launch_patches(
                cdp_ready=False, collections_ready=None, _is_steam_running=False
            ),
            pytest.raises(RuntimeError, match="Timed out waiting for Steam CDP"),
        ):
            ensure_steam_debug_port()

    def test_collections_timeout(self) -> None:
        """Collections that never load raise a timeout."""
        with (
            fresh_launch_patches(collections_ready=False, _is_steam_running=False),
            pytest.raises(
                RuntimeError, match="Timed out waiting for Steam collections"
            ),
        ):
            ensure_steam_debug_port()
