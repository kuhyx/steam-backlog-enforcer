"""Tests for the Steam lifecycle: is it running, has it a CDP port, restart it.

Split to keep every test file under the 250-line cap.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from steam_backlog_enforcer._steam_launch import (
    _is_steam_running,
    _steam_has_debug_port,
    _wait_for_cdp_ready,
    _wait_for_collections_ready,
)


class TestIsSteamRunning:
    """Tests for _is_steam_running."""

    def test_running(self) -> None:
        mock_result = MagicMock(returncode=0)
        with patch(
            "steam_backlog_enforcer._steam_launch.subprocess.run",
            return_value=mock_result,
        ):
            assert _is_steam_running() is True

    def test_not_running(self) -> None:
        mock_result = MagicMock(returncode=1)
        with patch(
            "steam_backlog_enforcer._steam_launch.subprocess.run",
            return_value=mock_result,
        ):
            assert _is_steam_running() is False


class TestSteamHasDebugPort:
    """Tests for _steam_has_debug_port."""

    def test_has_port(self) -> None:
        with patch(
            "steam_backlog_enforcer._steam_launch._get_shared_js_ws_url",
            return_value="ws://test",
        ):
            assert _steam_has_debug_port() is True

    def test_no_port(self) -> None:
        with patch(
            "steam_backlog_enforcer._steam_launch._get_shared_js_ws_url",
            return_value=None,
        ):
            assert _steam_has_debug_port() is False


class TestWaitForCdpReady:
    """Tests for _wait_for_cdp_ready."""

    def test_ready_immediately(self) -> None:
        with patch(
            "steam_backlog_enforcer._steam_launch._get_shared_js_ws_url",
            return_value="ws://test",
        ):
            assert _wait_for_cdp_ready() is True

    def test_timeout(self) -> None:
        with (
            patch(
                "steam_backlog_enforcer._steam_launch._get_shared_js_ws_url",
                return_value=None,
            ),
            patch(
                "steam_backlog_enforcer._steam_launch.time.sleep",
            ),
            patch(
                "steam_backlog_enforcer.library_hider._STEAM_STARTUP_WAIT",
                2,
            ),
        ):
            assert _wait_for_cdp_ready() is False


class TestWaitForCollectionsReady:
    """Tests for _wait_for_collections_ready."""

    def test_ready(self) -> None:
        with (
            patch(
                "steam_backlog_enforcer._steam_launch._evaluate_js",
                return_value={"result": {"result": {"value": "ok"}}},
            ),
            patch(
                "steam_backlog_enforcer._steam_launch._cdp_result_value",
                return_value="ok",
            ),
        ):
            assert _wait_for_collections_ready() is True

    def test_not_ready_then_ready(self) -> None:
        with (
            patch(
                "steam_backlog_enforcer._steam_launch._evaluate_js",
                return_value={"result": {"result": {"value": "not_ready"}}},
            ),
            patch(
                "steam_backlog_enforcer._steam_launch._cdp_result_value",
                side_effect=["not_ready", "ok"],
            ),
            patch(
                "steam_backlog_enforcer._steam_launch.time.sleep",
            ),
            patch(
                "steam_backlog_enforcer.library_hider._STEAM_STARTUP_WAIT",
                2,
            ),
        ):
            assert _wait_for_collections_ready() is True

    def test_timeout(self) -> None:
        with (
            patch(
                "steam_backlog_enforcer._steam_launch._evaluate_js",
                side_effect=RuntimeError,
            ),
            patch(
                "steam_backlog_enforcer._steam_launch.time.sleep",
            ),
            patch(
                "steam_backlog_enforcer.library_hider._STEAM_STARTUP_WAIT",
                2,
            ),
        ):
            assert _wait_for_collections_ready() is False
