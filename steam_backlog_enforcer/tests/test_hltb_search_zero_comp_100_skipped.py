"""Tests for HLTB search, batch-fetch, and page parsing — part 2."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Self
from unittest.mock import MagicMock, patch

from steam_backlog_enforcer._hltb_search import (
    _search_one,
    _SearchCtx,
)
from steam_backlog_enforcer._hltb_types import (
    _SAVE_INTERVAL,
)

if TYPE_CHECKING:
    from collections.abc import Callable


class _FakeResponse:
    """Async context manager mimicking aiohttp response."""

    def __init__(self, status: int, json_data: dict[str, Any] | None = None) -> None:
        """Test init."""
        self.status = status
        self._json_data = json_data or {}

    async def __aenter__(self) -> Self:
        """Test aenter."""
        return self

    async def __aexit__(self, *args: object) -> None:
        """Test aexit."""

    async def json(self) -> dict[str, Any]:
        """Test json."""
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


class TestSearchOneGroup2:
    """Tests for _search_one."""

    def test_zero_comp_100_skipped(self) -> None:
        """Test zero comp 100 skipped."""
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
        """Test alias match."""
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
        """Test full edition colon."""
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
        """Test full edition dash."""
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
        with patch("steam_backlog_enforcer._hltb_search.save_hltb_cache") as mock_save:
            asyncio.run(_search_one(asyncio.Semaphore(1), ctx, 440, "TF2"))
            mock_save.assert_called_once()

    def test_colon_strip_fallback_rejects_cross_franchise_match(self) -> None:
        """Colon-stripped fallback must not match a different franchise loosely.

        "Vox Populi: Poland 2023" stripped to "Vox Populi" should NOT match
        "Vox Populi Vox Dei 2" (different game, low-similarity entry).
        """
        empty_resp = _FakeResponse(200, {"data": []})
        loose_resp = _FakeResponse(
            200,
            {
                "data": [
                    {
                        "game_name": "Vox Populi Vox Dei 2",
                        "game_alias": "",
                        "game_type": "game",
                        "comp_100": 14400,
                        "comp_100_count": 9,
                        "count_comp": 57,
                        "game_id": 99999,
                    }
                ]
            },
        )
        session = MagicMock()
        session.post.side_effect = [empty_resp, loose_resp]
        ctx = _make_ctx(session)
        result = asyncio.run(
            _search_one(asyncio.Semaphore(1), ctx, 2590810, "Vox Populi: Poland 2023")
        )
        assert result is None

    def test_colon_strip_fallback_accepts_full_edition(self) -> None:
        """Colon-stripped fallback must still match when the HLTB entry is a
        full edition of the stripped name (name starts with stripped + ':').
        """
        empty_resp = _FakeResponse(200, {"data": []})
        full_edition_resp = _FakeResponse(
            200,
            {
                "data": [
                    {
                        "game_name": "Batman: Arkham Asylum",
                        "game_alias": "",
                        "game_type": "game",
                        "comp_100": 144000,
                        "comp_100_count": 300,
                        "count_comp": 5000,
                        "game_id": 11111,
                    }
                ]
            },
        )
        session = MagicMock()
        session.post.side_effect = [empty_resp, full_edition_resp]
        ctx = _make_ctx(session)
        result = asyncio.run(
            _search_one(asyncio.Semaphore(1), ctx, 35140, "Batman: Arkham Asylum")
        )
        assert result is not None
        assert result.game_name == "Batman: Arkham Asylum"
