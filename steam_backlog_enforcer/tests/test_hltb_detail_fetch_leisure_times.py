"""Tests for HLTB internal helpers, detail fetching, and leisure times — part 3."""

from __future__ import annotations

import asyncio
from typing import Any, Self
from unittest.mock import AsyncMock, MagicMock, patch

from steam_backlog_enforcer._hltb_detail import _fetch_leisure_times
from steam_backlog_enforcer._hltb_types import (
    HLTBResult,
)


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


class TestFetchLeisureTimes:
    """Tests for _fetch_leisure_times."""

    def test_updates_cache(self) -> None:
        """Test updates cache."""
        results = [
            HLTBResult(
                app_id=440,
                game_name="TF2",
                completionist_hours=50.0,
                similarity=1.0,
                hltb_game_id=12345,
            ),
        ]
        game_data: dict[str, Any] = {
            "game": [{"comp_100_h": 21243}],
            "relationships": [],
        }
        cache: dict[int, float] = {}
        with patch(
            "steam_backlog_enforcer._hltb_detail._fetch_detail_one",
            new_callable=AsyncMock,
            return_value=game_data,
        ):
            asyncio.run(_fetch_leisure_times(results, cache, {}, None))
        assert cache[440] == round(21243 / 3600, 2)
        assert results[0].completionist_hours == round(21243 / 3600, 2)

    def test_no_valid_results(self) -> None:
        """Test no valid results."""
        results = [
            HLTBResult(
                app_id=440,
                game_name="TF2",
                completionist_hours=50.0,
                similarity=1.0,
                hltb_game_id=0,
            ),
        ]
        cache: dict[int, float] = {}
        asyncio.run(_fetch_leisure_times(results, cache, {}, None))
        assert not cache

    def test_empty_results(self) -> None:
        """Test empty results."""
        cache: dict[int, float] = {}
        asyncio.run(_fetch_leisure_times([], cache, {}, None))
        assert not cache

    def test_detail_returns_none(self) -> None:
        """Test detail returns none."""
        results = [
            HLTBResult(
                app_id=440,
                game_name="TF2",
                completionist_hours=50.0,
                similarity=1.0,
                hltb_game_id=12345,
            ),
        ]
        cache: dict[int, float] = {}
        with patch(
            "steam_backlog_enforcer._hltb_detail._fetch_detail_one",
            new_callable=AsyncMock,
            return_value=None,
        ):
            asyncio.run(_fetch_leisure_times(results, cache, {}, None))
        assert not cache
        assert results[0].completionist_hours == 50.0

    def test_negative_leisure(self) -> None:
        """Test negative leisure."""
        results = [
            HLTBResult(
                app_id=440,
                game_name="TF2",
                completionist_hours=50.0,
                similarity=1.0,
                hltb_game_id=12345,
            ),
        ]
        game_data: dict[str, Any] = {"game": [], "relationships": []}
        cache: dict[int, float] = {}
        with patch(
            "steam_backlog_enforcer._hltb_detail._fetch_detail_one",
            new_callable=AsyncMock,
            return_value=game_data,
        ):
            asyncio.run(_fetch_leisure_times(results, cache, {}, None))
        assert not cache
        assert results[0].completionist_hours == 50.0

    def test_with_progress_cb(self) -> None:
        """Test with progress cb."""
        results = [
            HLTBResult(
                app_id=440,
                game_name="TF2",
                completionist_hours=50.0,
                similarity=1.0,
                hltb_game_id=12345,
            ),
        ]
        game_data: dict[str, Any] = {
            "game": [{"comp_100_h": 3600}],
            "relationships": [],
        }
        cache: dict[int, float] = {}
        cb = MagicMock()
        with patch(
            "steam_backlog_enforcer._hltb_detail._fetch_detail_one",
            new_callable=AsyncMock,
            return_value=game_data,
        ):
            asyncio.run(_fetch_leisure_times(results, cache, {}, cb))
        cb.assert_called_once()
