"""Tests for HLTB internal helpers, detail fetching, and leisure times — part 3."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import aiohttp
from typing_extensions import Self

from steam_backlog_enforcer._hltb_comp_extract import _fetch_detail_one
from steam_backlog_enforcer._hltb_detail import _process_game_detail


class _FakeTextResponse:
    """Async context manager mimicking aiohttp response for text."""

    def __init__(self, status: int, text: str = "") -> None:
        """Test init."""
        self.status = status
        self._text = text

    async def __aenter__(self) -> Self:
        """Test aenter."""
        return self

    async def __aexit__(self, *args: object) -> None:
        """Test aexit."""

    async def text(self) -> str:
        """Test text."""
        return self._text


class TestProcessGameDetail:
    """Tests for _process_game_detail."""

    def test_returns_leisure_rush_and_l100(self) -> None:
        """Test returns leisure rush and l100."""
        data: dict[str, Any] = {
            "game": [{"comp_100_h": 10800, "comp_100": 7200}],
            "relationships": [],
        }
        leisure, rush_h, l100 = _process_game_detail(data, [], {})
        assert leisure == round(10800 / 3600, 2)
        assert rush_h == round(7200 / 3600, 2)
        assert l100 == round(10800 / 3600, 2)

    def test_negative_leisure_when_no_data(self) -> None:
        """Test negative leisure when no data."""
        leisure, rush_h, l100 = _process_game_detail({"game": []}, [], {})
        assert leisure == -1
        assert rush_h == -1.0
        assert l100 == -1.0

    def test_rush_includes_dlc_fallback(self) -> None:
        """Test rush includes dlc fallback."""
        data: dict[str, Any] = {
            "game": [{"comp_100": 7200, "comp_100_h": 0}],
            "relationships": [],
        }
        dlc_rels = [(99, 1.5)]
        _leisure, rush_h, _l100 = _process_game_detail(data, dlc_rels, {})
        assert rush_h == round(7200 / 3600 + 1.5, 2)

    def test_l100_uses_dlc_override(self) -> None:
        """Test l100 uses dlc override."""
        data: dict[str, Any] = {
            "game": [{"comp_100_h": 10800, "comp_100": 7200}],
            "relationships": [],
        }
        dlc_rels = [(77, 2.0)]
        dlc_hours_by_id = {77: 3.0}
        _leisure, _rush_h, l100 = _process_game_detail(data, dlc_rels, dlc_hours_by_id)
        assert l100 == round(10800 / 3600 + (3.0 - 2.0), 2)


class TestFetchDetailOne:
    """Tests for _fetch_detail_one."""

    def test_success(self) -> None:
        """Test success."""
        game_data: dict[str, Any] = {
            "game": [{"comp_100_h": 21243}],
            "relationships": [],
        }
        next_data = {"props": {"pageProps": {"game": {"data": game_data}}}}
        html = (
            '<script id="__NEXT_DATA__" type="application/json">'
            + json.dumps(next_data)
            + "</script>"
        )
        resp = _FakeTextResponse(200, html)
        session = MagicMock()
        session.get = MagicMock(return_value=resp)
        result = asyncio.run(_fetch_detail_one(asyncio.Semaphore(1), session, 12345))
        assert result == game_data

    def test_non_200(self) -> None:
        """Test non 200."""
        resp = _FakeTextResponse(404)
        session = MagicMock()
        session.get = MagicMock(return_value=resp)
        result = asyncio.run(_fetch_detail_one(asyncio.Semaphore(1), session, 12345))
        assert result is None

    def test_client_error(self) -> None:
        """Test client error."""
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(side_effect=aiohttp.ClientError)
        ctx.__aexit__ = AsyncMock(return_value=False)
        session = MagicMock()
        session.get = MagicMock(return_value=ctx)
        result = asyncio.run(_fetch_detail_one(asyncio.Semaphore(1), session, 12345))
        assert result is None

    def test_parse_failure(self) -> None:
        """Test parse failure."""
        resp = _FakeTextResponse(200, "<html>no script</html>")
        session = MagicMock()
        session.get = MagicMock(return_value=resp)
        result = asyncio.run(_fetch_detail_one(asyncio.Semaphore(1), session, 12345))
        assert result is None
