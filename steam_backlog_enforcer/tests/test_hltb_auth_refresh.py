"""A long paced batch renews the HLTB token before it expires.

Seen 2026-11-08: at ~55 requests/min every search ~3 min after /init came
back 403 while a fresh token got 200 for the same game. Fake transport and a
fake clock only: no request leaves the process and nothing sleeps.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Self, cast
from unittest.mock import patch

from steam_backlog_enforcer import _hltb_auth_refresh
from steam_backlog_enforcer._hltb_failures import (
    BREAKER_LIMIT,
    SKIPPED_AFTER_RATE_LIMIT,
    Breaker,
    failure_summary_lines,
)
from steam_backlog_enforcer._hltb_search_one import (
    _AuthSlot,
    _search_one,
    _SearchCtx,
)
from steam_backlog_enforcer._hltb_types import _AuthInfo
from steam_backlog_enforcer.tests._hltb_fake_transport import MATCH, FakeResp

if TYPE_CHECKING:
    import aiohttp

_AGE = _hltb_auth_refresh.AUTH_MAX_AGE_S


class _RotatingSession:
    """Fake session: each /init GET hands out a new token; POSTs record auth."""

    def __init__(self, init_status: int = 200, post_status: int = 200) -> None:
        self.init_status = init_status
        self.post_status = post_status
        self.gets = 0
        # (x-auth-token header, honeypot value in the body) per POST.
        self.posts: list[tuple[str | None, str | None]] = []

    def get(self, *_a: object, **_k: object) -> FakeResp:
        """Hand out a fresh token and honeypot pair for each /init call."""
        self.gets += 1
        n = self.gets
        return FakeResp(
            self.init_status, {"token": f"tok{n}", "hpKey": "hp", "hpVal": f"v{n}"}
        )

    def post(self, _url: str, *, headers: dict[str, str], data: str) -> FakeResp:
        """Record the auth header and honeypot sent, answer with post_status."""
        self.posts.append((headers.get("x-auth-token"), json.loads(data).get("hp")))
        body = MATCH if self.post_status == 200 else None
        return FakeResp(self.post_status, body)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass


class _ListBodySession(_RotatingSession):
    """Fake session whose searches answer 200 with a JSON list, not an object."""

    def post(self, _url: str, *, headers: dict[str, str], data: str) -> FakeResp:
        del headers, data
        return FakeResp(200, cast("dict[str, object]", []))


class _Clock:
    """Fake monotonic clock advanced by the test."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def _ctx(session: _RotatingSession, clock: _Clock) -> _SearchCtx:
    return _SearchCtx(
        session=cast("aiohttp.ClientSession", session),
        search_url="https://example.invalid/api/finder",
        headers={"x-auth-token": "tok0", "x-hp-key": "hp", "x-hp-val": "v0"},
        cache={},
        auth=_AuthSlot(_AuthInfo("tok0", "hp", "v0"), issued_at=clock.t),
        counter={"done": 0, "found": 0, "failed": 0},
        breaker=Breaker(),
    )


def _lookups(ctx: _SearchCtx, clock: _Clock, steps: list[float]) -> None:
    """Run one lookup per step, advancing the clock by that many seconds first."""

    async def run() -> None:
        sem = asyncio.Semaphore(1)
        for i, step in enumerate(steps):
            clock.t += step
            await _search_one(sem, ctx, i + 1, "Vox Populi")

    with patch.object(_hltb_auth_refresh, "_now", clock):
        asyncio.run(run())


def test_young_token_is_not_refreshed() -> None:
    """Within the max age no extra /init request is made."""
    session, clock = _RotatingSession(), _Clock()
    _lookups(_ctx(session, clock), clock, [0, _AGE / 2])
    assert session.gets == 0
    assert session.posts == [("tok0", "v0"), ("tok0", "v0")]


def test_aged_token_is_refreshed_into_headers_and_body() -> None:
    """Past the max age the next POST carries the new token and honeypot."""
    session, clock = _RotatingSession(), _Clock()
    ctx = _ctx(session, clock)
    _lookups(ctx, clock, [0, _AGE + 1])
    assert session.gets == 1
    assert session.posts == [("tok0", "v0"), ("tok1", "v1")]
    assert ctx.auth.info == _AuthInfo("tok1", "hp", "v1")


def test_one_refresh_per_elapsed_interval() -> None:
    """Many lookups inside one interval share a single refresh."""
    session, clock = _RotatingSession(), _Clock()
    _lookups(_ctx(session, clock), clock, [_AGE + 1, 1, 1, 1, _AGE + 1, 1])
    assert session.gets == 2
    assert [tok for tok, _hp in session.posts] == [
        "tok1",
        "tok1",
        "tok1",
        "tok1",
        "tok2",
        "tok2",
    ]


def test_failed_refresh_stops_sending_and_trips_the_breaker() -> None:
    """A refresh that gets 429 never falls back to the stale token."""
    session, clock = _RotatingSession(init_status=429), _Clock()
    ctx = _ctx(session, clock)
    _lookups(ctx, clock, [_AGE + 1, 1, 1])
    assert session.gets == 1
    assert session.posts == []
    assert ctx.breaker.tripped
    assert ctx.counter["failed"] == 3
    summary = failure_summary_lines()[0]
    assert "auth refresh HTTP 429 x1" in summary
    assert f"{SKIPPED_AFTER_RATE_LIMIT} x2" in summary


def test_consecutive_403s_trip_the_breaker() -> None:
    """A rejected token cannot turn into hundreds of doomed requests."""
    session, clock = _RotatingSession(post_status=403), _Clock()
    ctx = _ctx(session, clock)
    _lookups(ctx, clock, [0] * (BREAKER_LIMIT + 3))
    assert len(session.posts) == BREAKER_LIMIT
    assert ctx.breaker.tripped
    assert ctx.counter["failed"] == BREAKER_LIMIT + 3


def test_concurrent_lookups_share_one_refresh() -> None:
    """A lookup that waited on the lock reuses the token renewed meanwhile."""
    session, clock = _RotatingSession(), _Clock()
    ctx = _ctx(session, clock)
    clock.t += _AGE + 1

    async def yielding_pause(_seconds: float) -> None:
        await asyncio.sleep(0)  # let the other lookup reach the lock

    async def run() -> list[str | None]:
        return list(
            await asyncio.gather(
                _hltb_auth_refresh.ensure_fresh_auth(ctx),
                _hltb_auth_refresh.ensure_fresh_auth(ctx),
            )
        )

    with (
        patch.object(_hltb_auth_refresh, "_now", clock),
        patch("steam_backlog_enforcer._hltb_pacing._sleep", yielding_pause),
    ):
        assert asyncio.run(run()) == [None, None]
    assert session.gets == 1


def test_non_object_json_is_a_failure() -> None:
    """A 200 whose body is not a JSON object is "bad JSON", never a miss."""
    session, clock = _ListBodySession(), _Clock()
    ctx = _ctx(session, clock)
    ctx.cache[1] = 50.0
    _lookups(ctx, clock, [0])
    assert ctx.cache[1] == 50.0
    assert "bad JSON x1" in failure_summary_lines()[0]
