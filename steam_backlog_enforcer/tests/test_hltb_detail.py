"""Tests for HLTB internal helpers, detail fetching, and leisure times — part 3."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import aiohttp
from typing_extensions import Self

from steam_backlog_enforcer._hltb_detail import (
    _apply_dlc_leisure_overrides,
    _as_positive_int,
    _collect_dlc_relationships,
    _extract_base_leisure_hours,
    _extract_dlc_relationships,
    _fetch_dlc_leisure_hours,
)
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


class TestInternalHelpers:
    """Tests for internal helper coverage."""

    def test_as_positive_int_float(self) -> None:
        """Test as positive int float."""
        assert _as_positive_int(1.9) == 1

    def test_as_positive_int_invalid_type(self) -> None:
        """Test as positive int invalid type."""
        assert not _as_positive_int(object())

    def test_extract_base_leisure_non_dict_game(self) -> None:
        """Test extract base leisure non dict game."""
        data: dict[str, Any] = {"game": [123]}
        assert _extract_base_leisure_hours(data) == -1

    def test_extract_base_leisure_platform_data_comp_high_is_max(self) -> None:
        """Test extract base leisure platform data comp high is max."""
        data: dict[str, Any] = {
            "game": [{"comp_100_h": 16063}],
            "platformData": [{"platform": "PC", "comp_high": 23760}],
        }
        assert _extract_base_leisure_hours(data) == round(23760 / 3600, 2)

    def test_extract_base_leisure_h_field_exceeds_platform_comp_high(self) -> None:
        """Test extract base leisure h field exceeds platform comp high."""
        data: dict[str, Any] = {
            "game": [{"comp_100_h": 25000}],
            "platformData": [{"platform": "PC", "comp_high": 23760}],
        }
        assert _extract_base_leisure_hours(data) == round(25000 / 3600, 2)

    def test_extract_base_leisure_max_of_multiple_platforms(self) -> None:
        """Test extract base leisure max of multiple platforms."""
        data: dict[str, Any] = {
            "game": [{}],
            "platformData": [
                {"platform": "PC", "comp_high": 23760},
                {"platform": "Switch", "comp_high": 18000},
            ],
        }
        assert _extract_base_leisure_hours(data) == round(23760 / 3600, 2)

    def test_extract_base_leisure_platform_data_not_list(self) -> None:
        """Test extract base leisure platform data not list."""
        data: dict[str, Any] = {
            "game": [{"comp_100_h": 16063}],
            "platformData": "not_a_list",
        }
        assert _extract_base_leisure_hours(data) == round(16063 / 3600, 2)

    def test_extract_base_leisure_platform_non_dict_entry_skipped(self) -> None:
        """Test extract base leisure platform non dict entry skipped."""
        data: dict[str, Any] = {
            "game": [{"comp_100_h": 16063}],
            "platformData": ["bad", {"platform": "PC", "comp_high": 23760}],
        }
        assert _extract_base_leisure_hours(data) == round(23760 / 3600, 2)

    def test_extract_base_leisure_platform_comp_high_zero_skipped(self) -> None:
        """Test extract base leisure platform comp high zero skipped."""
        data: dict[str, Any] = {
            "game": [{"comp_100_h": 16063}],
            "platformData": [{"platform": "PC", "comp_high": 0}],
        }
        assert _extract_base_leisure_hours(data) == round(16063 / 3600, 2)

    def test_extract_base_leisure_max_of_h_fields(self) -> None:
        """Test extract base leisure max of h fields."""
        data: dict[str, Any] = {
            "game": [
                {
                    "comp_main_h": 14951,
                    "comp_plus_h": 17957,
                    "comp_100_h": 16063,
                    "comp_all_h": 17959,
                }
            ],
        }
        assert _extract_base_leisure_hours(data) == round(17959 / 3600, 2)

    def test_extract_base_leisure_fallback_to_avg_comp_main(self) -> None:
        """Test extract base leisure fallback to avg comp main."""
        data: dict[str, Any] = {
            "game": [{"comp_main": 10800, "comp_plus": 0, "comp_100": 0}],
        }
        assert _extract_base_leisure_hours(data) == round(10800 / 3600, 2)

    def test_extract_dlc_relationships_skips_non_dict(self) -> None:
        """Test extract dlc relationships skips non dict."""
        data: dict[str, Any] = {
            "relationships": [
                "bad",
                {"game_type": "dlc", "game_id": 7, "comp_100": 3600},
            ],
        }
        assert _extract_dlc_relationships(data) == [(7, 1.0)]

    def test_collect_dlc_relationships_ignores_non_positive_id(self) -> None:
        """Test collect dlc relationships ignores non positive id."""
        valid = [
            HLTBResult(
                app_id=1,
                game_name="Game",
                completionist_hours=1.0,
                similarity=1.0,
                hltb_game_id=123,
            )
        ]
        details: list[dict[str, Any] | None] = [
            {
                "relationships": [
                    {"game_type": "dlc", "game_id": 0, "comp_100": 3600},
                ]
            }
        ]
        by_app, ids = _collect_dlc_relationships(valid, details)
        assert by_app[1] == [(0, 1.0)]
        assert ids == []

    def test_apply_dlc_leisure_overrides(self) -> None:
        """Test apply dlc leisure overrides."""
        adjusted = _apply_dlc_leisure_overrides(
            base_hours=6.0,
            dlc_rels=[(10, 1.0), (11, 2.0)],
            dlc_hours_by_id={10: 3.0},
        )
        assert adjusted == 8.0

    def test_fetch_dlc_leisure_hours_empty(self) -> None:
        """Test fetch dlc leisure hours empty."""

        async def _run() -> dict[int, float]:
            """Test run."""
            async with aiohttp.ClientSession() as session:
                return await _fetch_dlc_leisure_hours(asyncio.Semaphore(1), session, [])

        assert asyncio.run(_run()) == {}

    def test_fetch_dlc_leisure_hours_skips_none_data(self) -> None:
        """Test fetch dlc leisure hours skips none data."""

        async def _run() -> dict[int, float]:
            """Test run."""
            async with aiohttp.ClientSession() as session:
                with patch(
                    "steam_backlog_enforcer._hltb_detail._fetch_detail_one",
                    new_callable=AsyncMock,
                    return_value=None,
                ):
                    return await _fetch_dlc_leisure_hours(
                        asyncio.Semaphore(1),
                        session,
                        [1],
                    )

        assert asyncio.run(_run()) == {}

    def test_fetch_dlc_leisure_hours_skips_non_positive_leisure(self) -> None:
        """Test fetch dlc leisure hours skips non positive leisure."""
        bad_dlc_data: dict[str, Any] = {
            "game": [{"comp_100_h": 0, "comp_100": 0}],
            "relationships": [],
        }

        async def _run() -> dict[int, float]:
            """Test run."""
            async with aiohttp.ClientSession() as session:
                with patch(
                    "steam_backlog_enforcer._hltb_detail._fetch_detail_one",
                    new_callable=AsyncMock,
                    return_value=bad_dlc_data,
                ):
                    return await _fetch_dlc_leisure_hours(
                        asyncio.Semaphore(1),
                        session,
                        [1],
                    )

        assert asyncio.run(_run()) == {}
