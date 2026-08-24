"""Tests for HLTB internal helpers, detail fetching, and leisure times — part 3."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

from typing_extensions import Self

from steam_backlog_enforcer._hltb_detail import _fetch_leisure_times
from steam_backlog_enforcer._hltb_types import (
    _SAVE_INTERVAL,
    HLTBResult,
    _HLTBExtras,
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


class TestFetchLeisureTimesGroup2:
    """Tests for _fetch_leisure_times."""

    def test_save_interval(self) -> None:
        """Trigger the _SAVE_INTERVAL branch in leisure fetching."""
        results = [
            HLTBResult(
                app_id=i,
                game_name=f"Game{i}",
                completionist_hours=1.0,
                similarity=1.0,
                hltb_game_id=i + 1000,
            )
            for i in range(_SAVE_INTERVAL)
        ]
        game_data: dict[str, Any] = {
            "game": [{"comp_100_h": 3600}],
            "relationships": [],
        }
        cache: dict[int, float] = {}
        with (
            patch(
                "steam_backlog_enforcer._hltb_detail._fetch_detail_one",
                new_callable=AsyncMock,
                return_value=game_data,
            ),
            patch("steam_backlog_enforcer._hltb_detail.save_hltb_cache") as mock_save,
        ):
            asyncio.run(_fetch_leisure_times(results, cache, {}, None))
            mock_save.assert_called_once()

    def test_dlc_detail_overrides_relationship_fallback(self) -> None:
        """Test dlc detail overrides relationship fallback."""
        results = [
            HLTBResult(
                app_id=1289310,
                game_name="Helltaker",
                completionist_hours=1.0,
                similarity=1.0,
                hltb_game_id=78118,
            ),
        ]
        base_data: dict[str, Any] = {
            "game": [{"comp_100_h": 21243, "comp_100": 6846}],
            "relationships": [{"game_type": "dlc", "game_id": 92236, "comp_100": 4075}],
        }
        dlc_data: dict[str, Any] = {
            "game": [{"comp_100_h": 12298, "comp_100": 4075}],
            "relationships": [],
        }
        cache: dict[int, float] = {}
        with patch(
            "steam_backlog_enforcer._hltb_detail._fetch_detail_one",
            new_callable=AsyncMock,
            side_effect=[base_data, dlc_data],
        ):
            asyncio.run(_fetch_leisure_times(results, cache, {}, None))

        expected = round((21243 + 12298) / 3600, 2)
        assert cache[1289310] == expected
        assert results[0].completionist_hours == expected

    def test_missing_dlc_detail_keeps_relationship_fallback(self) -> None:
        """Test missing dlc detail keeps relationship fallback."""
        results = [
            HLTBResult(
                app_id=1289310,
                game_name="Helltaker",
                completionist_hours=1.0,
                similarity=1.0,
                hltb_game_id=78118,
            ),
        ]
        base_data: dict[str, Any] = {
            "game": [{"comp_100_h": 21243, "comp_100": 6846}],
            "relationships": [{"game_type": "dlc", "game_id": 92236, "comp_100": 4075}],
        }
        cache: dict[int, float] = {}
        with patch(
            "steam_backlog_enforcer._hltb_detail._fetch_detail_one",
            new_callable=AsyncMock,
            side_effect=[base_data, None],
        ):
            asyncio.run(_fetch_leisure_times(results, cache, {}, None))

        expected = round((21243 + 4075) / 3600, 2)
        assert cache[1289310] == expected
        assert results[0].completionist_hours == expected

    def test_extras_populated_with_rush_and_l100(self) -> None:
        """rush_h and l100 are stored in extras when game has comp_100 data."""
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
            "game": [{"comp_100_h": 10800, "comp_100": 7200}],
            "relationships": [],
        }
        cache: dict[int, float] = {}
        extras = _HLTBExtras(count_comp={440: 5})
        with patch(
            "steam_backlog_enforcer._hltb_detail._fetch_detail_one",
            new_callable=AsyncMock,
            return_value=game_data,
        ):
            asyncio.run(_fetch_leisure_times(results, cache, {}, None, extras=extras))
        assert extras.rush[440] == round(7200 / 3600, 2)
        assert extras.leisure_100h[440] == round(10800 / 3600, 2)

    def test_with_explicit_extras(self) -> None:
        """Pass a pre-populated _HLTBExtras to cover the non-None extras branch."""
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
        extras = _HLTBExtras(count_comp={440: 5})
        with patch(
            "steam_backlog_enforcer._hltb_detail._fetch_detail_one",
            new_callable=AsyncMock,
            return_value=game_data,
        ):
            asyncio.run(_fetch_leisure_times(results, cache, {}, None, extras=extras))
        assert cache[440] == 1.0

    def test_count_comp_from_detail_page_stored_in_extras(self) -> None:
        """Line 254: extras.count_comp updated when game detail has count_comp > 0."""
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
            "game": [{"comp_100_h": 3600, "count_comp": 99}],
            "relationships": [],
        }
        cache: dict[int, float] = {}
        extras = _HLTBExtras()
        with patch(
            "steam_backlog_enforcer._hltb_detail._fetch_detail_one",
            new_callable=AsyncMock,
            return_value=game_data,
        ):
            asyncio.run(_fetch_leisure_times(results, cache, {}, None, extras=extras))
        assert extras.count_comp[440] == 99
