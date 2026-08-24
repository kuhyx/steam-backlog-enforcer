"""Tests for HLTB search, batch-fetch, and page parsing — part 2."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

from typing_extensions import Self

from steam_backlog_enforcer._hltb_search import (
    _fetch_batch,
    _SearchCtx,
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


class TestFetchBatchHltb:
    """Tests for _fetch_batch (the hltb version)."""

    def test_no_auth(self) -> None:
        """Test no auth."""
        with (
            patch(
                "steam_backlog_enforcer._hltb_search._get_hltb_search_url",
                return_value="https://example.com",
            ),
            patch(
                "steam_backlog_enforcer._hltb_search._get_auth_info",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            results = asyncio.run(_fetch_batch([(440, "TF2")], {}, {}, None))
            assert results == []


class TestPickBestEntry:
    """Tests for exact-vs-extended entry choice logic."""
