"""Tests for library_hider module."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from steam_backlog_enforcer._cdp import (
    _cdp_result_value,
    _evaluate_js,
    _evaluate_js_async,
    _get_shared_js_ws_url,
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
            "steam_backlog_enforcer._cdp.requests.get",
            return_value=mock_resp,
        ):
            result = _get_shared_js_ws_url()
            assert result == "ws://127.0.0.1:8080/x"

    def test_no_shared_context(self) -> None:
        targets = [{"title": "Other", "webSocketDebuggerUrl": "ws://other"}]
        mock_resp = MagicMock()
        mock_resp.json.return_value = targets
        with patch(
            "steam_backlog_enforcer._cdp.requests.get",
            return_value=mock_resp,
        ):
            assert _get_shared_js_ws_url() is None

    def test_connection_error(self) -> None:
        with patch(
            "steam_backlog_enforcer._cdp.requests.get",
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
            "steam_backlog_enforcer._cdp.websockets.connect",
            return_value=mock_ws,
        ):
            result = asyncio.run(_evaluate_js_async("ws://test", "1+1"))
            assert result["result"]["result"]["value"] == "ok"


class TestEvaluateJs:
    """Tests for _evaluate_js."""

    def test_success(self) -> None:
        with (
            patch(
                "steam_backlog_enforcer._cdp._get_shared_js_ws_url",
                return_value="ws://test",
            ),
            patch(
                "steam_backlog_enforcer._cdp.asyncio.run",
                return_value={"result": {"result": {"value": "ok"}}},
            ),
        ):
            result = _evaluate_js("1+1")
            assert result["result"]["result"]["value"] == "ok"

    def test_no_ws_url(self) -> None:
        with (
            patch(
                "steam_backlog_enforcer._cdp._get_shared_js_ws_url",
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
