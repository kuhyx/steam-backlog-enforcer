"""Tests for library_hider module."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from python_pkg.steam_backlog_enforcer.library_hider import (
    _cdp_result_value,
    _evaluate_js,
    _evaluate_js_async,
    _get_shared_js_ws_url,
    _is_steam_running,
    _launch_steam_with_debug,
    _shutdown_steam,
    _steam_has_debug_port,
    _wait_for_cdp_ready,
    _wait_for_collections_ready,
    ensure_steam_debug_port,
    hide_other_games,
    unhide_all_games,
)


class TestGetSharedJsWsUrl:
    """Tests for _get_shared_js_ws_url."""

    def test_finds_url(self) -> None:
        targets = [
            {
                "title": "SharedJSContext",
                "webSocketDebuggerUrl": "ws://127.0.0.1:8080/x",
            },
            {"title": "Other", "webSocketDebuggerUrl": "ws://other"},
        ]
        mock_resp = MagicMock()
        mock_resp.json.return_value = targets
        with patch(
            "python_pkg.steam_backlog_enforcer.library_hider.requests.get",
            return_value=mock_resp,
        ):
            result = _get_shared_js_ws_url()
            assert result == "ws://127.0.0.1:8080/x"

    def test_no_shared_context(self) -> None:
        targets = [{"title": "Other", "webSocketDebuggerUrl": "ws://other"}]
        mock_resp = MagicMock()
        mock_resp.json.return_value = targets
        with patch(
            "python_pkg.steam_backlog_enforcer.library_hider.requests.get",
            return_value=mock_resp,
        ):
            assert _get_shared_js_ws_url() is None

    def test_connection_error(self) -> None:
        with patch(
            "python_pkg.steam_backlog_enforcer.library_hider.requests.get",
            side_effect=OSError,
        ):
            assert _get_shared_js_ws_url() is None


class TestEvaluateJsAsync:
    """Tests for _evaluate_js_async."""

    def test_success(self) -> None:
        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        mock_ws.recv = AsyncMock(
            return_value=json.dumps({"result": {"result": {"value": "ok"}}})
        )
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "python_pkg.steam_backlog_enforcer.library_hider.websockets.connect",
            return_value=mock_ws,
        ):
            result = asyncio.run(_evaluate_js_async("ws://test", "1+1"))
            assert result["result"]["result"]["value"] == "ok"


class TestEvaluateJs:
    """Tests for _evaluate_js."""

    def test_success(self) -> None:
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider._get_shared_js_ws_url",
                return_value="ws://test",
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider.asyncio.run",
                return_value={"result": {"result": {"value": "ok"}}},
            ),
        ):
            result = _evaluate_js("1+1")
            assert result["result"]["result"]["value"] == "ok"

    def test_no_ws_url(self) -> None:
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider._get_shared_js_ws_url",
                return_value=None,
            ),
            pytest.raises(RuntimeError, match="SharedJSContext not found"),
        ):
            _evaluate_js("1+1")


class TestCdpResultValue:
    """Tests for _cdp_result_value."""

    def test_extracts_value(self) -> None:
        result = {"result": {"result": {"value": "hello"}}}
        assert _cdp_result_value(result) == "hello"

    def test_exception(self) -> None:
        result = {
            "result": {
                "result": {"description": "Error!"},
                "exceptionDetails": {},
            }
        }
        with pytest.raises(RuntimeError, match="JS evaluation error"):
            _cdp_result_value(result)

    def test_empty(self) -> None:
        assert _cdp_result_value({}) == ""


class TestIsSteamRunning:
    """Tests for _is_steam_running."""

    def test_running(self) -> None:
        mock_result = MagicMock(returncode=0)
        with patch(
            "python_pkg.steam_backlog_enforcer.library_hider.subprocess.run",
            return_value=mock_result,
        ):
            assert _is_steam_running() is True

    def test_not_running(self) -> None:
        mock_result = MagicMock(returncode=1)
        with patch(
            "python_pkg.steam_backlog_enforcer.library_hider.subprocess.run",
            return_value=mock_result,
        ):
            assert _is_steam_running() is False


class TestSteamHasDebugPort:
    """Tests for _steam_has_debug_port."""

    def test_has_port(self) -> None:
        with patch(
            "python_pkg.steam_backlog_enforcer.library_hider._get_shared_js_ws_url",
            return_value="ws://test",
        ):
            assert _steam_has_debug_port() is True

    def test_no_port(self) -> None:
        with patch(
            "python_pkg.steam_backlog_enforcer.library_hider._get_shared_js_ws_url",
            return_value=None,
        ):
            assert _steam_has_debug_port() is False


class TestWaitForCdpReady:
    """Tests for _wait_for_cdp_ready."""

    def test_ready_immediately(self) -> None:
        with patch(
            "python_pkg.steam_backlog_enforcer.library_hider._get_shared_js_ws_url",
            return_value="ws://test",
        ):
            assert _wait_for_cdp_ready() is True

    def test_timeout(self) -> None:
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider._get_shared_js_ws_url",
                return_value=None,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider.time.sleep",
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider._STEAM_STARTUP_WAIT",
                2,
            ),
        ):
            assert _wait_for_cdp_ready() is False


class TestWaitForCollectionsReady:
    """Tests for _wait_for_collections_ready."""

    def test_ready(self) -> None:
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider._evaluate_js",
                return_value={"result": {"result": {"value": "ok"}}},
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider._cdp_result_value",
                return_value="ok",
            ),
        ):
            assert _wait_for_collections_ready() is True

    def test_not_ready_then_ready(self) -> None:
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider._evaluate_js",
                return_value={"result": {"result": {"value": "not_ready"}}},
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider._cdp_result_value",
                side_effect=["not_ready", "ok"],
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider.time.sleep",
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider._STEAM_STARTUP_WAIT",
                2,
            ),
        ):
            assert _wait_for_collections_ready() is True

    def test_timeout(self) -> None:
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider._evaluate_js",
                side_effect=RuntimeError,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider.time.sleep",
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider._STEAM_STARTUP_WAIT",
                2,
            ),
        ):
            assert _wait_for_collections_ready() is False


class TestShutdownSteam:
    """Tests for _shutdown_steam."""

    def test_exits_immediately(self) -> None:
        mock_result = MagicMock(returncode=1)  # Not running
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider._run_as_user",
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider.subprocess.run",
                return_value=mock_result,
            ),
        ):
            _shutdown_steam()

    def test_waits_for_exit(self) -> None:
        results = [MagicMock(returncode=0), MagicMock(returncode=1)]
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider._run_as_user",
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider.subprocess.run",
                side_effect=results,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider.time.sleep",
            ),
        ):
            _shutdown_steam()

    def test_file_not_found(self) -> None:
        with patch(
            "python_pkg.steam_backlog_enforcer.library_hider._run_as_user",
            side_effect=FileNotFoundError,
        ):
            _shutdown_steam()  # Should not raise

    def test_timeout(self) -> None:
        mock_result = MagicMock(returncode=0)  # Still running
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider._run_as_user",
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider.subprocess.run",
                return_value=mock_result,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider.time.sleep",
            ),
        ):
            _shutdown_steam()  # Should complete loop without raising


class TestLaunchSteamWithDebug:
    """Tests for _launch_steam_with_debug."""

    def test_launches(self) -> None:
        with patch(
            "python_pkg.steam_backlog_enforcer.library_hider._run_as_user",
        ) as mock_run:
            _launch_steam_with_debug()
            mock_run.assert_called_once()


class TestEnsureSteamDebugPort:
    """Tests for ensure_steam_debug_port."""

    def test_already_available(self) -> None:
        with patch(
            "python_pkg.steam_backlog_enforcer.library_hider._steam_has_debug_port",
            return_value=True,
        ):
            ensure_steam_debug_port()

    def test_starts_fresh(self) -> None:
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider._steam_has_debug_port",
                return_value=False,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider._is_steam_running",
                return_value=False,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider._launch_steam_with_debug",
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider._wait_for_cdp_ready",
                return_value=True,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider._wait_for_collections_ready",
                return_value=True,
            ),
        ):
            ensure_steam_debug_port()

    def test_restarts_running_steam(self) -> None:
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider._steam_has_debug_port",
                return_value=False,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider._is_steam_running",
                return_value=True,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider._shutdown_steam",
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider._launch_steam_with_debug",
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider._wait_for_cdp_ready",
                return_value=True,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider._wait_for_collections_ready",
                return_value=True,
            ),
        ):
            ensure_steam_debug_port()

    def test_cdp_timeout(self) -> None:
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider._steam_has_debug_port",
                return_value=False,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider._is_steam_running",
                return_value=False,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider._launch_steam_with_debug",
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider._wait_for_cdp_ready",
                return_value=False,
            ),
            pytest.raises(RuntimeError, match="Timed out waiting for Steam CDP"),
        ):
            ensure_steam_debug_port()

    def test_collections_timeout(self) -> None:
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider._steam_has_debug_port",
                return_value=False,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider._is_steam_running",
                return_value=False,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider._launch_steam_with_debug",
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider._wait_for_cdp_ready",
                return_value=True,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider._wait_for_collections_ready",
                return_value=False,
            ),
            pytest.raises(
                RuntimeError, match="Timed out waiting for Steam collections"
            ),
        ):
            ensure_steam_debug_port()


class TestHideOtherGames:
    """Tests for hide_other_games."""

    def test_hides(self) -> None:
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider.ensure_steam_debug_port",
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider._evaluate_js",
                return_value={"result": {"result": {"value": '{"newlyHidden": 5}'}}},
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider._cdp_result_value",
                return_value='{"newlyHidden": 5}',
            ),
        ):
            count = hide_other_games([1, 2, 3], 1)
            assert count == 5

    def test_empty_list(self) -> None:
        with patch(
            "python_pkg.steam_backlog_enforcer.library_hider.ensure_steam_debug_port",
        ):
            count = hide_other_games([1], 1)
            assert count == 0

    def test_no_allowed(self) -> None:
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider.ensure_steam_debug_port",
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider._evaluate_js",
                return_value={"result": {"result": {"value": '{"newlyHidden": 2}'}}},
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider._cdp_result_value",
                return_value='{"newlyHidden": 2}',
            ),
        ):
            count = hide_other_games([1, 2], None)
            assert count == 2


class TestUnhideAllGames:
    """Tests for unhide_all_games."""

    def test_unhides(self) -> None:
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider.ensure_steam_debug_port",
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider._evaluate_js",
                return_value={"result": {"result": {"value": '{"count": 10}'}}},
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.library_hider._cdp_result_value",
                return_value='{"count": 10}',
            ),
        ):
            count = unhide_all_games([1, 2, 3])
            assert count == 10
