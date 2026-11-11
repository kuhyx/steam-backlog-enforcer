"""Tests for HLTB internal helpers, detail fetching, and leisure times — part 3."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

from steam_backlog_enforcer._hltb_detail import _fetch_leisure_times
from steam_backlog_enforcer.tests._hltb_leisure_runs import run_leisure, tf2_result


class TestFetchLeisureTimes:
    """Tests for _fetch_leisure_times."""

    def test_updates_cache(self) -> None:
        """Test updates cache."""
        results = [tf2_result()]
        game_data: dict[str, Any] = {
            "game": [{"comp_100_h": 21243}],
            "relationships": [],
        }
        cache = run_leisure(results, game_data)
        assert cache[440] == round(21243 / 3600, 2)
        assert results[0].completionist_hours == round(21243 / 3600, 2)

    def test_no_valid_results(self) -> None:
        """Test no valid results."""
        results = [tf2_result(hltb_game_id=0)]
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
        results = [tf2_result()]
        cache = run_leisure(results, None)
        assert not cache
        assert results[0].completionist_hours == 50.0

    def test_negative_leisure(self) -> None:
        """Test negative leisure."""
        results = [tf2_result()]
        game_data: dict[str, Any] = {"game": [], "relationships": []}
        cache = run_leisure(results, game_data)
        assert not cache
        assert results[0].completionist_hours == 50.0

    def test_with_progress_cb(self) -> None:
        """Test with progress cb."""
        game_data: dict[str, Any] = {
            "game": [{"comp_100_h": 3600}],
            "relationships": [],
        }
        cb = MagicMock()
        run_leisure([tf2_result()], game_data, progress_cb=cb)
        cb.assert_called_once()
