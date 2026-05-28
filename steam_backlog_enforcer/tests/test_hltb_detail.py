"""Tests for HLTB internal helpers, detail fetching, and leisure times — part 3."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
from typing_extensions import Self

from python_pkg.steam_backlog_enforcer._hltb_detail import (
    _apply_dlc_leisure_overrides,
    _as_positive_int,
    _collect_dlc_relationships,
    _extract_base_leisure_hours,
    _extract_comp_100_avg_and_high,
    _extract_dlc_relationships,
    _fetch_detail_one,
    _fetch_dlc_leisure_hours,
    _fetch_leisure_times,
    _process_game_detail,
)
from python_pkg.steam_backlog_enforcer._hltb_types import (
    _SAVE_INTERVAL,
    HLTBResult,
    _HLTBExtras,
)


class TestInternalHelpers:
    """Tests for internal helper coverage."""

    def test_as_positive_int_float(self) -> None:
        assert _as_positive_int(1.9) == 1

    def test_as_positive_int_invalid_type(self) -> None:
        assert not _as_positive_int(object())

    def test_extract_base_leisure_non_dict_game(self) -> None:
        data: dict[str, Any] = {"game": [123]}
        assert _extract_base_leisure_hours(data) == -1

    def test_extract_base_leisure_platform_data_comp_high_is_max(self) -> None:
        data: dict[str, Any] = {
            "game": [{"comp_100_h": 16063}],
            "platformData": [{"platform": "PC", "comp_high": 23760}],
        }
        assert _extract_base_leisure_hours(data) == round(23760 / 3600, 2)

    def test_extract_base_leisure_h_field_exceeds_platform_comp_high(self) -> None:
        data: dict[str, Any] = {
            "game": [{"comp_100_h": 25000}],
            "platformData": [{"platform": "PC", "comp_high": 23760}],
        }
        assert _extract_base_leisure_hours(data) == round(25000 / 3600, 2)

    def test_extract_base_leisure_max_of_multiple_platforms(self) -> None:
        data: dict[str, Any] = {
            "game": [{}],
            "platformData": [
                {"platform": "PC", "comp_high": 23760},
                {"platform": "Switch", "comp_high": 18000},
            ],
        }
        assert _extract_base_leisure_hours(data) == round(23760 / 3600, 2)

    def test_extract_base_leisure_platform_data_not_list(self) -> None:
        data: dict[str, Any] = {
            "game": [{"comp_100_h": 16063}],
            "platformData": "not_a_list",
        }
        assert _extract_base_leisure_hours(data) == round(16063 / 3600, 2)

    def test_extract_base_leisure_platform_non_dict_entry_skipped(self) -> None:
        data: dict[str, Any] = {
            "game": [{"comp_100_h": 16063}],
            "platformData": ["bad", {"platform": "PC", "comp_high": 23760}],
        }
        assert _extract_base_leisure_hours(data) == round(23760 / 3600, 2)

    def test_extract_base_leisure_platform_comp_high_zero_skipped(self) -> None:
        data: dict[str, Any] = {
            "game": [{"comp_100_h": 16063}],
            "platformData": [{"platform": "PC", "comp_high": 0}],
        }
        assert _extract_base_leisure_hours(data) == round(16063 / 3600, 2)

    def test_extract_base_leisure_max_of_h_fields(self) -> None:
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
        data: dict[str, Any] = {
            "game": [{"comp_main": 10800, "comp_plus": 0, "comp_100": 0}],
        }
        assert _extract_base_leisure_hours(data) == round(10800 / 3600, 2)

    def test_extract_dlc_relationships_skips_non_dict(self) -> None:
        data: dict[str, Any] = {
            "relationships": [
                "bad",
                {"game_type": "dlc", "game_id": 7, "comp_100": 3600},
            ],
        }
        assert _extract_dlc_relationships(data) == [(7, 1.0)]

    def test_collect_dlc_relationships_ignores_non_positive_id(self) -> None:
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
        adjusted = _apply_dlc_leisure_overrides(
            base_hours=6.0,
            dlc_rels=[(10, 1.0), (11, 2.0)],
            dlc_hours_by_id={10: 3.0},
        )
        assert adjusted == 8.0

    def test_fetch_dlc_leisure_hours_empty(self) -> None:
        async def _run() -> dict[int, float]:
            async with aiohttp.ClientSession() as session:
                return await _fetch_dlc_leisure_hours(asyncio.Semaphore(1), session, [])

        assert asyncio.run(_run()) == {}

    def test_fetch_dlc_leisure_hours_skips_none_data(self) -> None:
        async def _run() -> dict[int, float]:
            async with aiohttp.ClientSession() as session:
                with patch(
                    "python_pkg.steam_backlog_enforcer._hltb_detail._fetch_detail_one",
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
        bad_dlc_data: dict[str, Any] = {
            "game": [{"comp_100_h": 0, "comp_100": 0}],
            "relationships": [],
        }

        async def _run() -> dict[int, float]:
            async with aiohttp.ClientSession() as session:
                with patch(
                    "python_pkg.steam_backlog_enforcer._hltb_detail._fetch_detail_one",
                    new_callable=AsyncMock,
                    return_value=bad_dlc_data,
                ):
                    return await _fetch_dlc_leisure_hours(
                        asyncio.Semaphore(1),
                        session,
                        [1],
                    )

        assert asyncio.run(_run()) == {}


class TestExtractComp100AvgAndHigh:
    """Tests for _extract_comp_100_avg_and_high."""

    def test_returns_minus_one_for_empty_game_list(self) -> None:
        assert _extract_comp_100_avg_and_high({"game": []}) == (-1, -1)

    def test_returns_minus_one_for_non_list_game(self) -> None:
        assert _extract_comp_100_avg_and_high({"game": "bad"}) == (-1, -1)

    def test_returns_minus_one_when_game0_not_dict(self) -> None:
        assert _extract_comp_100_avg_and_high({"game": [42]}) == (-1, -1)

    def test_returns_avg_and_high(self) -> None:
        data: dict[str, Any] = {"game": [{"comp_100": 7200, "comp_100_h": 10800}]}
        avg_h, high_h = _extract_comp_100_avg_and_high(data)
        assert avg_h == round(7200 / 3600, 2)
        assert high_h == round(10800 / 3600, 2)

    def test_high_falls_back_to_avg_when_zero(self) -> None:
        data: dict[str, Any] = {"game": [{"comp_100": 7200, "comp_100_h": 0}]}
        avg_h, high_h = _extract_comp_100_avg_and_high(data)
        assert avg_h == round(7200 / 3600, 2)
        assert high_h == avg_h

    def test_avg_zero_returns_minus_one_avg(self) -> None:
        data: dict[str, Any] = {"game": [{"comp_100": 0, "comp_100_h": 0}]}
        avg_h, high_h = _extract_comp_100_avg_and_high(data)
        assert avg_h == -1
        assert high_h == -1


class TestProcessGameDetail:
    """Tests for _process_game_detail."""

    def test_returns_leisure_rush_and_l100(self) -> None:
        data: dict[str, Any] = {
            "game": [{"comp_100_h": 10800, "comp_100": 7200}],
            "relationships": [],
        }
        leisure, rush_h, l100 = _process_game_detail(data, [], {})
        assert leisure == round(10800 / 3600, 2)
        assert rush_h == round(7200 / 3600, 2)
        assert l100 == round(10800 / 3600, 2)

    def test_negative_leisure_when_no_data(self) -> None:
        leisure, rush_h, l100 = _process_game_detail({"game": []}, [], {})
        assert leisure == -1
        assert rush_h == -1.0
        assert l100 == -1.0

    def test_rush_includes_dlc_fallback(self) -> None:
        data: dict[str, Any] = {
            "game": [{"comp_100": 7200, "comp_100_h": 0}],
            "relationships": [],
        }
        dlc_rels = [(99, 1.5)]
        _leisure, rush_h, _l100 = _process_game_detail(data, dlc_rels, {})
        assert rush_h == round(7200 / 3600 + 1.5, 2)

    def test_l100_uses_dlc_override(self) -> None:
        data: dict[str, Any] = {
            "game": [{"comp_100_h": 10800, "comp_100": 7200}],
            "relationships": [],
        }
        dlc_rels = [(77, 2.0)]
        dlc_hours_by_id = {77: 3.0}
        _leisure, _rush_h, l100 = _process_game_detail(data, dlc_rels, dlc_hours_by_id)
        assert l100 == round(10800 / 3600 + (3.0 - 2.0), 2)


class _FakeTextResponse:
    """Async context manager mimicking aiohttp response for text."""

    def __init__(self, status: int, text: str = "") -> None:
        self.status = status
        self._text = text

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    async def text(self) -> str:
        return self._text


class TestFetchDetailOne:
    """Tests for _fetch_detail_one."""

    def test_success(self) -> None:
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
        resp = _FakeTextResponse(404)
        session = MagicMock()
        session.get = MagicMock(return_value=resp)
        result = asyncio.run(_fetch_detail_one(asyncio.Semaphore(1), session, 12345))
        assert result is None

    def test_client_error(self) -> None:
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(side_effect=aiohttp.ClientError)
        ctx.__aexit__ = AsyncMock(return_value=False)
        session = MagicMock()
        session.get = MagicMock(return_value=ctx)
        result = asyncio.run(_fetch_detail_one(asyncio.Semaphore(1), session, 12345))
        assert result is None

    def test_parse_failure(self) -> None:
        resp = _FakeTextResponse(200, "<html>no script</html>")
        session = MagicMock()
        session.get = MagicMock(return_value=resp)
        result = asyncio.run(_fetch_detail_one(asyncio.Semaphore(1), session, 12345))
        assert result is None


class TestFetchLeisureTimes:
    """Tests for _fetch_leisure_times."""

    def test_updates_cache(self) -> None:
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
            "python_pkg.steam_backlog_enforcer._hltb_detail._fetch_detail_one",
            new_callable=AsyncMock,
            return_value=game_data,
        ):
            asyncio.run(_fetch_leisure_times(results, cache, {}, None))
        assert cache[440] == round(21243 / 3600, 2)
        assert results[0].completionist_hours == round(21243 / 3600, 2)

    def test_no_valid_results(self) -> None:
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
        cache: dict[int, float] = {}
        asyncio.run(_fetch_leisure_times([], cache, {}, None))
        assert not cache

    def test_detail_returns_none(self) -> None:
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
            "python_pkg.steam_backlog_enforcer._hltb_detail._fetch_detail_one",
            new_callable=AsyncMock,
            return_value=None,
        ):
            asyncio.run(_fetch_leisure_times(results, cache, {}, None))
        assert not cache
        assert results[0].completionist_hours == 50.0

    def test_negative_leisure(self) -> None:
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
            "python_pkg.steam_backlog_enforcer._hltb_detail._fetch_detail_one",
            new_callable=AsyncMock,
            return_value=game_data,
        ):
            asyncio.run(_fetch_leisure_times(results, cache, {}, None))
        assert not cache
        assert results[0].completionist_hours == 50.0

    def test_with_progress_cb(self) -> None:
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
            "python_pkg.steam_backlog_enforcer._hltb_detail._fetch_detail_one",
            new_callable=AsyncMock,
            return_value=game_data,
        ):
            asyncio.run(_fetch_leisure_times(results, cache, {}, cb))
        cb.assert_called_once()

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
                "python_pkg.steam_backlog_enforcer._hltb_detail._fetch_detail_one",
                new_callable=AsyncMock,
                return_value=game_data,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer._hltb_detail.save_hltb_cache"
            ) as mock_save,
        ):
            asyncio.run(_fetch_leisure_times(results, cache, {}, None))
            mock_save.assert_called_once()

    def test_dlc_detail_overrides_relationship_fallback(self) -> None:
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
            "python_pkg.steam_backlog_enforcer._hltb_detail._fetch_detail_one",
            new_callable=AsyncMock,
            side_effect=[base_data, dlc_data],
        ):
            asyncio.run(_fetch_leisure_times(results, cache, {}, None))

        expected = round((21243 + 12298) / 3600, 2)
        assert cache[1289310] == expected
        assert results[0].completionist_hours == expected

    def test_missing_dlc_detail_keeps_relationship_fallback(self) -> None:
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
            "python_pkg.steam_backlog_enforcer._hltb_detail._fetch_detail_one",
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
            "python_pkg.steam_backlog_enforcer._hltb_detail._fetch_detail_one",
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
            "python_pkg.steam_backlog_enforcer._hltb_detail._fetch_detail_one",
            new_callable=AsyncMock,
            return_value=game_data,
        ):
            asyncio.run(_fetch_leisure_times(results, cache, {}, None, extras=extras))
        assert cache[440] == 1.0
