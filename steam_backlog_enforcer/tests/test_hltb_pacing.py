"""HLTB requests are paced: one at a time, 1.1 s gap after each request (~55/min).

HLTB rate-limits a burst after ~60 lookups; a full refresh is ~800 games.
Fake transport only: no request ever leaves the process.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast
from unittest.mock import patch

import pytest

from steam_backlog_enforcer import _hltb_pacing
from steam_backlog_enforcer._hltb_comp_extract import _fetch_detail_one
from steam_backlog_enforcer._hltb_failures import BREAKER_LIMIT, shared_breaker
from steam_backlog_enforcer._hltb_search_one import (
    _AuthSlot,
    _search_one,
    _SearchCtx,
)
from steam_backlog_enforcer._hltb_types import MAX_CONCURRENT, _AuthInfo
from steam_backlog_enforcer.tests._hltb_fake_transport import (
    MATCH,
    NO_MATCH,
    FakeResp,
    FakeSession,
)

if TYPE_CHECKING:
    import aiohttp

_INTERVAL = 1.1


class _DetailSession:
    """Fake session answering every detail GET with a 404."""

    def __init__(self) -> None:
        self.gets = 0

    def get(self, _url: str, *, headers: object) -> FakeResp:
        """Count the detail request and answer 404."""
        del headers
        self.gets += 1
        return FakeResp(404)


def _ctx(session: FakeSession) -> _SearchCtx:
    return _SearchCtx(
        session=cast("aiohttp.ClientSession", session),
        search_url="https://example.invalid/api/finder",
        headers={},
        cache={},
        auth=_AuthSlot(_AuthInfo("t")),
        counter={"done": 0, "found": 0, "failed": 0},
    )


def _record_sleeps(sem: asyncio.Semaphore) -> tuple[list[float], object]:
    """Fake ``asyncio.sleep`` that records each pause and that a slot is held."""
    pauses: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        assert sem.locked(), "the pause must hold the request slot"
        pauses.append(seconds)

    return pauses, fake_sleep


def test_one_request_in_flight() -> None:
    """HLTB sees one request in flight at a time."""
    assert MAX_CONCURRENT == 1


def test_default_interval_stays_under_the_limit() -> None:
    """1.1 s between requests keeps us at ~55/min, under the ~60/min limit."""
    assert _hltb_pacing.REQUEST_INTERVAL_S == _INTERVAL


@pytest.mark.parametrize("body", [MATCH, NO_MATCH])
def test_each_search_post_is_followed_by_a_pause(body: dict[str, object]) -> None:
    """Every search POST, match or not, waits the interval inside its slot."""
    session = FakeSession({"*": FakeResp(200, body)})
    ctx = _ctx(session)

    async def run() -> list[float]:
        sem = asyncio.Semaphore(1)
        pauses, fake_sleep = _record_sleeps(sem)
        with patch.object(_hltb_pacing, "_sleep", fake_sleep):
            await _search_one(sem, ctx, 1, "Vox Populi: Poland 2023")
        return pauses

    pauses = asyncio.run(run())
    assert len(session.posts) >= 1
    assert pauses == [_INTERVAL] * len(session.posts)


def test_skipped_lookup_after_breaker_does_not_pause() -> None:
    """Once the breaker has tripped nothing is sent, so nothing waits."""
    session = FakeSession({"*": FakeResp(200, MATCH)})
    ctx = _ctx(session)
    ctx.breaker = shared_breaker()
    for _ in range(BREAKER_LIMIT):
        ctx.breaker.note(429)

    async def run() -> list[float]:
        sem = asyncio.Semaphore(1)
        pauses, fake_sleep = _record_sleeps(sem)
        with patch.object(_hltb_pacing, "_sleep", fake_sleep):
            await _search_one(sem, ctx, 1, "Celeste")
        return pauses

    assert asyncio.run(run()) == []
    assert session.posts == []


def test_each_detail_get_is_followed_by_a_pause() -> None:
    """Detail-page GETs are paced the same way as search POSTs."""
    session = _DetailSession()

    async def run() -> list[float]:
        sem = asyncio.Semaphore(1)
        pauses, fake_sleep = _record_sleeps(sem)
        with patch.object(_hltb_pacing, "_sleep", fake_sleep):
            await _fetch_detail_one(sem, cast("aiohttp.ClientSession", session), 77)
        return pauses

    assert asyncio.run(run()) == [_INTERVAL]
    assert session.gets == 1
