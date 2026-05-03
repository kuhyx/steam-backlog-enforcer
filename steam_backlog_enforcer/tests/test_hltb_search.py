"""Tests for HLTB search, batch-fetch, and page parsing — part 2."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
from typing_extensions import Self

from python_pkg.steam_backlog_enforcer._hltb_detail import (
    _extract_leisure_hours,
    _parse_game_page,
)
from python_pkg.steam_backlog_enforcer.hltb import (
    _SAVE_INTERVAL,
    HLTBResult,
    _AuthInfo,
    _fetch_batch,
    _pick_best_hltb_entry,
    _search_one,
    _SearchCtx,
)

if TYPE_CHECKING:
    from collections.abc import Callable


class _FakeResponse:
    """Async context manager mimicking aiohttp response."""

    def __init__(self, status: int, json_data: dict[str, Any] | None = None) -> None:
        self.status = status
        self._json_data = json_data or {}

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    async def json(self) -> dict[str, Any]:
        return self._json_data


def _make_session(resp: _FakeResponse) -> MagicMock:
    session = MagicMock()
    session.post.return_value = resp
    return session


def _make_ctx(
    session: MagicMock,
    *,
    cache: dict[int, float] | None = None,
    progress_cb: Callable[..., object] | None = None,
) -> _SearchCtx:
    return _SearchCtx(
        session=session,
        search_url="https://example.com/search",
        headers={},
        cache=cache if cache is not None else {},
        counter={"done": 0, "found": 0},
        total=1,
        progress_cb=progress_cb,
    )


class TestSearchOne:
    """Tests for _search_one."""

    def test_found(self) -> None:
        resp = _FakeResponse(
            200,
            {
                "data": [
                    {
                        "game_name": "TF2",
                        "game_alias": "",
                        "comp_100": 180000,
                        "game_id": 12345,
                    }
                ],
            },
        )
        ctx = _make_ctx(_make_session(resp))
        result = asyncio.run(_search_one(asyncio.Semaphore(1), ctx, 440, "TF2"))
        assert result is not None
        assert result.app_id == 440

    def test_not_found(self) -> None:
        resp = _FakeResponse(200, {"data": []})
        ctx = _make_ctx(_make_session(resp))
        result = asyncio.run(_search_one(asyncio.Semaphore(1), ctx, 440, "TF2"))
        assert result is None
        assert ctx.cache[440] == -1

    def test_error(self) -> None:
        session = MagicMock()
        session.post.side_effect = aiohttp.ClientError("fail")
        ctx = _make_ctx(session)
        result = asyncio.run(_search_one(asyncio.Semaphore(1), ctx, 440, "TF2"))
        assert result is None

    def test_non_200(self) -> None:
        resp = _FakeResponse(500)
        ctx = _make_ctx(_make_session(resp))
        result = asyncio.run(_search_one(asyncio.Semaphore(1), ctx, 440, "TF2"))
        assert result is None

    def test_fallback_name_without_year_suffix(self) -> None:
        session = MagicMock()
        session.post.side_effect = [
            _FakeResponse(200, {"data": []}),
            _FakeResponse(
                200,
                {
                    "data": [
                        {
                            "game_name": "Final Fantasy VII",
                            "game_alias": "",
                            "game_type": "game",
                            "comp_100": 141120,
                            "game_id": 435,
                            "comp_100_count": 746,
                            "count_comp": 10450,
                        }
                    ]
                },
            ),
        ]
        ctx = _make_ctx(session)
        result = asyncio.run(
            _search_one(asyncio.Semaphore(1), ctx, 39140, "Final Fantasy VII (2013)")
        )
        assert result is not None
        assert result.app_id == 39140
        assert result.comp_100_count == 746
        assert result.count_comp == 10450
        assert session.post.call_count == 2

    def test_with_progress_cb(self) -> None:
        resp = _FakeResponse(200, {"data": []})
        cb = MagicMock()
        ctx = _make_ctx(_make_session(resp), progress_cb=cb)
        asyncio.run(_search_one(asyncio.Semaphore(1), ctx, 440, "TF2"))
        cb.assert_called_once()

    def test_low_similarity_skipped(self) -> None:
        resp = _FakeResponse(
            200,
            {
                "data": [
                    {
                        "game_name": "Completely Different Name",
                        "game_alias": "",
                        "comp_100": 3600,
                        "game_id": 1,
                    }
                ],
            },
        )
        ctx = _make_ctx(_make_session(resp))
        result = asyncio.run(_search_one(asyncio.Semaphore(1), ctx, 440, "TF2"))
        assert result is None

    def test_zero_comp_100_skipped(self) -> None:
        resp = _FakeResponse(
            200,
            {
                "data": [
                    {
                        "game_name": "TF2",
                        "game_alias": "",
                        "comp_100": 0,
                        "game_id": 1,
                    }
                ],
            },
        )
        ctx = _make_ctx(_make_session(resp))
        result = asyncio.run(_search_one(asyncio.Semaphore(1), ctx, 440, "TF2"))
        assert result is None

    def test_alias_match(self) -> None:
        resp = _FakeResponse(
            200,
            {
                "data": [
                    {
                        "game_name": "Team Fortress 2",
                        "game_alias": "TF2",
                        "comp_100": 180000,
                        "game_id": 12345,
                    }
                ],
            },
        )
        ctx = _make_ctx(_make_session(resp))
        result = asyncio.run(_search_one(asyncio.Semaphore(1), ctx, 440, "TF2"))
        assert result is not None

    def test_full_edition_colon(self) -> None:
        resp = _FakeResponse(
            200,
            {
                "data": [
                    {
                        "game_name": "TF2: Complete",
                        "game_alias": "",
                        "comp_100": 180000,
                        "game_id": 99,
                    }
                ],
            },
        )
        ctx = _make_ctx(_make_session(resp))
        result = asyncio.run(_search_one(asyncio.Semaphore(1), ctx, 440, "TF2"))
        assert result is not None

    def test_full_edition_dash(self) -> None:
        resp = _FakeResponse(
            200,
            {
                "data": [
                    {
                        "game_name": "TF2 - Complete",
                        "game_alias": "",
                        "comp_100": 180000,
                        "game_id": 99,
                    }
                ],
            },
        )
        ctx = _make_ctx(_make_session(resp))
        result = asyncio.run(_search_one(asyncio.Semaphore(1), ctx, 440, "TF2"))
        assert result is not None

    def test_save_interval(self) -> None:
        """Trigger the _SAVE_INTERVAL branch."""
        resp = _FakeResponse(200, {"data": []})
        ctx = _make_ctx(_make_session(resp))
        # Set done to one less than _SAVE_INTERVAL so it triggers save

        ctx.counter["done"] = _SAVE_INTERVAL - 1
        with patch(
            "python_pkg.steam_backlog_enforcer.hltb.save_hltb_cache"
        ) as mock_save:
            asyncio.run(_search_one(asyncio.Semaphore(1), ctx, 440, "TF2"))
            mock_save.assert_called_once()


class TestFetchBatchHltb:
    """Tests for _fetch_batch (the hltb version)."""

    def test_no_auth(self) -> None:
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.hltb._get_hltb_search_url",
                return_value="https://example.com",
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.hltb._get_auth_info",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            results = asyncio.run(_fetch_batch([(440, "TF2")], {}, {}, None))
            assert results == []


class TestPickBestEntry:
    """Tests for exact-vs-extended entry choice logic."""

    def test_prefers_exact_over_low_confidence_modded_extended(self) -> None:
        exact = (
            {
                "game_name": "Celeste",
                "game_alias": "",
                "game_type": "game",
                "comp_100": 141105,
                "comp_100_count": 899,
                "count_comp": 14055,
            },
            1.0,
        )
        mod_extended = (
            {
                "game_name": "Celeste - Strawberry Jam",
                "game_alias": "",
                "game_type": "mod",
                "comp_100": 952080,
                "comp_100_count": 1,
                "count_comp": 6,
            },
            0.9,
        )

        best = _pick_best_hltb_entry("Celeste", [exact, mod_extended])
        assert best is not None
        assert best[0]["game_name"] == "Celeste"

    def test_prefers_extended_when_confident_and_longer(self) -> None:
        exact_demo = (
            {
                "game_name": "FAITH",
                "game_alias": "",
                "game_type": "game",
                "comp_100": 1800,
                "comp_100_count": 1,
                "count_comp": 1,
            },
            1.0,
        )
        full_extended = (
            {
                "game_name": "FAITH: The Unholy Trinity",
                "game_alias": "",
                "game_type": "game",
                "comp_100": 25200,
                "comp_100_count": 50,
                "count_comp": 500,
            },
            0.9,
        )

        best = _pick_best_hltb_entry("FAITH", [exact_demo, full_extended])
        assert best is not None
        assert best[0]["game_name"] == "FAITH: The Unholy Trinity"

    def test_with_auth(self) -> None:
        auth = _AuthInfo("token123", "ign_x", "ff")
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.hltb._get_hltb_search_url",
                return_value="https://example.com",
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.hltb._get_auth_info",
                new_callable=AsyncMock,
                return_value=auth,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.hltb._search_one",
                new_callable=AsyncMock,
                return_value=HLTBResult(
                    app_id=440,
                    game_name="TF2",
                    completionist_hours=50.0,
                    similarity=1.0,
                    hltb_game_id=12345,
                ),
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.hltb._fetch_leisure_times",
                new_callable=AsyncMock,
            ),
        ):
            results = asyncio.run(_fetch_batch([(440, "TF2")], {}, {}, None))
            assert len(results) == 1

    def test_with_auth_no_hp(self) -> None:
        auth = _AuthInfo("tok123")
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.hltb._get_hltb_search_url",
                return_value="https://example.com",
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.hltb._get_auth_info",
                new_callable=AsyncMock,
                return_value=auth,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.hltb._search_one",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.hltb._fetch_leisure_times",
                new_callable=AsyncMock,
            ),
        ):
            results = asyncio.run(_fetch_batch([(440, "TF2")], {}, {}, None))
            assert results == []

    def test_filters_none_results(self) -> None:
        auth = _AuthInfo("tok123")
        with (
            patch(
                "python_pkg.steam_backlog_enforcer.hltb._get_hltb_search_url",
                return_value="https://example.com",
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.hltb._get_auth_info",
                new_callable=AsyncMock,
                return_value=auth,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.hltb._search_one",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "python_pkg.steam_backlog_enforcer.hltb._fetch_leisure_times",
                new_callable=AsyncMock,
            ),
        ):
            results = asyncio.run(_fetch_batch([(440, "TF2")], {}, {}, None))
            assert results == []


class TestParseGamePage:
    """Tests for _parse_game_page."""

    def test_valid_html(self) -> None:
        game_data: dict[str, Any] = {
            "game": [{"comp_100_h": 21243, "comp_100": 6800}],
            "relationships": [],
        }
        next_data = {
            "props": {"pageProps": {"game": {"data": game_data}}},
        }
        html = (
            '<html><script id="__NEXT_DATA__" type="application/json">'
            + json.dumps(next_data)
            + "</script></html>"
        )
        assert _parse_game_page(html) == game_data

    def test_no_script_tag(self) -> None:
        assert _parse_game_page("<html></html>") is None

    def test_bad_json(self) -> None:
        html = '<script id="__NEXT_DATA__" type="application/json">{not json}</script>'
        assert _parse_game_page(html) is None

    def test_missing_keys(self) -> None:
        html = (
            '<script id="__NEXT_DATA__" type="application/json">{"props": {}}</script>'
        )
        assert _parse_game_page(html) is None


class TestExtractLeisureHours:
    """Tests for _extract_leisure_hours."""

    def test_leisure_time_only(self) -> None:
        data: dict[str, Any] = {
            "game": [{"comp_100_h": 21243, "comp_100": 6800}],
            "relationships": [],
        }
        assert _extract_leisure_hours(data) == round(21243 / 3600, 2)

    def test_leisure_with_dlc(self) -> None:
        data: dict[str, Any] = {
            "game": [{"comp_100_h": 21243, "comp_100": 6800}],
            "relationships": [
                {"game_type": "dlc", "comp_100": 12298},
                {"game_type": "dlc", "comp_100": 3600},
            ],
        }
        assert _extract_leisure_hours(data) == round((21243 + 12298 + 3600) / 3600, 2)

    def test_fallback_to_comp_100(self) -> None:
        data: dict[str, Any] = {
            "game": [{"comp_100": 7200}],
            "relationships": [],
        }
        assert _extract_leisure_hours(data) == round(7200 / 3600, 2)

    def test_no_game_data(self) -> None:
        assert _extract_leisure_hours({"game": [], "relationships": []}) == -1

    def test_zero_leisure(self) -> None:
        data: dict[str, Any] = {
            "game": [{"comp_100_h": 0, "comp_100": 0}],
            "relationships": [],
        }
        assert _extract_leisure_hours(data) == -1

    def test_no_game_key(self) -> None:
        assert _extract_leisure_hours({"relationships": []}) == -1

    def test_non_dlc_relationship_ignored(self) -> None:
        data: dict[str, Any] = {
            "game": [{"comp_100_h": 3600}],
            "relationships": [
                {"game_type": "game", "comp_100": 9999},
                {"game_type": "dlc", "comp_100": 1800},
            ],
        }
        assert _extract_leisure_hours(data) == round((3600 + 1800) / 3600, 2)

    def test_dlc_zero_comp_100_skipped(self) -> None:
        data: dict[str, Any] = {
            "game": [{"comp_100_h": 3600}],
            "relationships": [
                {"game_type": "dlc", "comp_100": 0},
            ],
        }
        assert _extract_leisure_hours(data) == round(3600 / 3600, 2)

    def test_negative_leisure(self) -> None:
        data: dict[str, Any] = {
            "game": [{"comp_100_h": -1, "comp_100": -1}],
            "relationships": [],
        }
        assert _extract_leisure_hours(data) == -1

    def test_string_numeric_fields(self) -> None:
        data: dict[str, Any] = {
            "game": [{"comp_100_h": "7200", "comp_100": "3600"}],
            "relationships": [{"game_type": "dlc", "game_id": "1", "comp_100": "1800"}],
        }
        assert _extract_leisure_hours(data) == round((7200 + 1800) / 3600, 2)

    def test_bad_string_falls_back_to_comp_100(self) -> None:
        data: dict[str, Any] = {
            "game": [{"comp_100_h": "bad", "comp_100": "3600"}],
            "relationships": [],
        }
        assert _extract_leisure_hours(data) == 1.0

    def test_relationships_not_list(self) -> None:
        data: dict[str, Any] = {
            "game": [{"comp_100_h": 3600}],
            "relationships": "not-a-list",
        }
        assert _extract_leisure_hours(data) == 1.0
