"""Shared fake aiohttp response, search context and runners for HLTB search tests."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Self
from unittest.mock import AsyncMock, MagicMock, patch

from steam_backlog_enforcer._hltb_search import (
    _fetch_batch,
    _search_one,
    _SearchCtx,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from steam_backlog_enforcer._hltb_types import HLTBResult, _AuthInfo


_SEARCH = "steam_backlog_enforcer._hltb_search"


class FakeResponse:
    """Async context manager mimicking aiohttp response."""

    def __init__(self, status: int, json_data: dict[str, Any] | None = None) -> None:
        """Store the canned status and JSON body (``None`` = empty body)."""
        self.status = status
        self._json_data = json_data or {}

    async def __aenter__(self) -> Self:
        """Enter."""
        return self

    async def __aexit__(self, *args: object) -> None:
        """Exit."""

    async def json(self) -> dict[str, Any]:
        """Return the canned JSON body."""
        return self._json_data


def make_session(resp: FakeResponse) -> MagicMock:
    """Return a fake session whose every POST answers ``resp``."""
    session = MagicMock()
    session.post.return_value = resp
    return session


def make_ctx(
    session: MagicMock,
    *,
    cache: dict[int, float] | None = None,
    progress_cb: Callable[..., object] | None = None,
    counter: dict[str, int] | None = None,
) -> _SearchCtx:
    """Return a one-game search context over ``session``."""
    return _SearchCtx(
        session=session,
        search_url="https://example.com/search",
        headers={},
        cache=cache if cache is not None else {},
        counter=counter if counter is not None else {"done": 0, "found": 0},
        total=1,
        progress_cb=progress_cb,
    )


def hit(
    name: str, comp_100: int, game_id: int, *, alias: str = "", **extra: object
) -> dict[str, Any]:
    """Return a search body holding one HLTB entry."""
    entry = {
        "game_name": name,
        "game_alias": alias,
        "comp_100": comp_100,
        "game_id": game_id,
    }
    return {"data": [{**entry, **extra}]}


def run_search(
    ctx: _SearchCtx, app_id: int = 440, name: str = "TF2"
) -> HLTBResult | None:
    """Run ``_search_one`` for one game on ``ctx``."""
    return asyncio.run(_search_one(asyncio.Semaphore(1), ctx, app_id, name))


def search_tf2(body: dict[str, Any]) -> HLTBResult | None:
    """Answer a TF2 search with ``body`` (status 200) and return the result."""
    return run_search(make_ctx(make_session(FakeResponse(200, body))))


@contextmanager
def hltb_auth_patched(auth: _AuthInfo | None) -> Iterator[None]:
    """Stub the search-URL lookup and make the auth handshake return ``auth``."""
    with (
        patch(f"{_SEARCH}._get_hltb_search_url", return_value="https://example.com"),
        patch(f"{_SEARCH}._get_auth_info", new_callable=AsyncMock, return_value=auth),
    ):
        yield


def fetch_tf2_batch(
    auth: _AuthInfo, search_result: HLTBResult | None
) -> list[HLTBResult]:
    """Run ``_fetch_batch`` for TF2; every per-game search returns ``search_result``."""
    with (
        hltb_auth_patched(auth),
        patch(
            f"{_SEARCH}._search_one",
            new_callable=AsyncMock,
            return_value=search_result,
        ),
        patch(f"{_SEARCH}._fetch_leisure_times", new_callable=AsyncMock),
    ):
        return asyncio.run(_fetch_batch([(440, "TF2")], {}, {}, None))
