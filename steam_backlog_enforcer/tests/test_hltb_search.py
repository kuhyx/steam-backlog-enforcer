"""Tests for HLTB search, batch-fetch, and page parsing — part 2."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
from typing_extensions import Self

from python_pkg.steam_backlog_enforcer._hltb_search import (
    _fetch_batch,
    _search_one,
    _SearchCtx,
)
from python_pkg.steam_backlog_enforcer._hltb_types import (
    _SAVE_INTERVAL,
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
            "python_pkg.steam_backlog_enforcer._hltb_search.save_hltb_cache"
        ) as mock_save:
            asyncio.run(_search_one(asyncio.Semaphore(1), ctx, 440, "TF2"))
            mock_save.assert_called_once()


class TestFetchBatchHltb:
    """Tests for _fetch_batch (the hltb version)."""

    def test_no_auth(self) -> None:
        with (
            patch(
                "python_pkg.steam_backlog_enforcer._hltb_search._get_hltb_search_url",
                return_value="https://example.com",
            ),
            patch(
                "python_pkg.steam_backlog_enforcer._hltb_search._get_auth_info",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            results = asyncio.run(_fetch_batch([(440, "TF2")], {}, {}, None))
            assert results == []


class TestPickBestEntry:
    """Tests for exact-vs-extended entry choice logic."""
