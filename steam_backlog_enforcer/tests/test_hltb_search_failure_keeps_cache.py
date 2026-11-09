"""A failed HLTB search must keep the cached entry; only a clean no-match is a miss.

Fake transport only: no request ever leaves the process.
"""

from __future__ import annotations

import asyncio
from typing import cast

import aiohttp
import pytest

from steam_backlog_enforcer._hltb_failures import (
    failure_summary_lines,
    reset_failures,
)
from steam_backlog_enforcer._hltb_search_one import _search_one, _SearchCtx
from steam_backlog_enforcer._hltb_types import _AuthInfo, _HLTBExtras
from steam_backlog_enforcer.tests._hltb_fake_transport import (
    MATCH,
    NO_MATCH,
    FakeResp,
    FakeSession,
)


def _ctx(session: FakeSession, total: int = 1) -> _SearchCtx:
    return _SearchCtx(
        session=cast("aiohttp.ClientSession", session),
        search_url="https://example.invalid/api/finder",
        headers={},
        cache={1: 50.0},
        polls={1: 120},
        extras=_HLTBExtras(count_comp={1: 900}),
        auth=_AuthInfo("t"),
        counter={"done": 0, "found": 0, "failed": 0},
        total=total,
    )


def _run(ctx: _SearchCtx, app_id: int, name: str) -> None:
    asyncio.run(_search_one(asyncio.Semaphore(1), ctx, app_id, name))


@pytest.fixture(autouse=True)
def _fresh_tally() -> None:
    reset_failures()


_FAILURES = {
    "429": FakeResp(429),
    "500": FakeResp(500),
    "403": FakeResp(403),
    "timeout": TimeoutError(),
    "client_error": aiohttp.ClientConnectionError("refused"),
    "bad_json": FakeResp(200, None),
}


@pytest.mark.parametrize("kind", sorted(_FAILURES))
def test_failed_search_keeps_prior_entry(kind: str) -> None:
    """Any non-clean answer leaves hours, polls and count_comp untouched."""
    ctx = _ctx(FakeSession({"*": _FAILURES[kind]}))
    _run(ctx, 1, "Celeste")
    assert ctx.cache[1] == 50.0
    assert ctx.polls[1] == 120
    assert ctx.extras.count_comp[1] == 900
    assert ctx.counter["failed"] == 1
    assert ctx.counter["found"] == 0


def test_failed_variant_blocks_a_miss() -> None:
    """One variant no-match + one variant 429 is a failure, not a miss."""
    routes = {"Vox Populi Poland 2023": FakeResp(200, NO_MATCH), "*": FakeResp(429)}
    ctx = _ctx(FakeSession(routes))
    _run(ctx, 1, "Vox Populi: Poland 2023")
    assert (ctx.cache[1], ctx.polls[1], ctx.extras.count_comp[1]) == (50.0, 120, 900)
    assert ctx.counter["failed"] == 1


def test_match_beats_failed_sibling_variant() -> None:
    """A real match replaces the entry even when another variant failed."""
    routes = {"Vox Populi Poland 2023": FakeResp(429), "*": FakeResp(200, MATCH)}
    ctx = _ctx(FakeSession(routes))
    _run(ctx, 1, "Vox Populi: Poland 2023")
    assert (ctx.cache[1], ctx.polls[1], ctx.extras.count_comp[1]) == (10.0, 42, 300)
    assert ctx.counter == {"done": 1, "found": 1, "failed": 0}


def test_clean_no_match_still_writes_a_miss() -> None:
    """Every variant answered 200 with nothing usable: that is a real miss."""
    ctx = _ctx(FakeSession({"*": FakeResp(200, NO_MATCH)}))
    _run(ctx, 1, "Vox Populi: Poland 2023")
    assert (ctx.cache[1], ctx.polls[1], ctx.extras.count_comp[1]) == (-1, 0, 0)
    assert ctx.counter["failed"] == 0


def test_failure_without_prior_entry_writes_nothing() -> None:
    """An uncached game that fails stays uncached so the next run retries it."""
    ctx = _ctx(FakeSession({"*": FakeResp(429)}))
    _run(ctx, 2, "Celeste")
    assert 2 not in ctx.cache
    assert 2 not in ctx.polls
    assert 2 not in ctx.extras.count_comp
    assert ctx.counter == {"done": 1, "found": 0, "failed": 1}


def test_summary_line_counts_reasons() -> None:
    """The end-of-run line names every failure reason with its count."""
    ctx = _ctx(FakeSession({"*": FakeResp(429)}), total=2)
    _run(ctx, 1, "Celeste")
    ctx.session = cast("aiohttp.ClientSession", FakeSession({"*": TimeoutError()}))
    _run(ctx, 1, "Celeste")
    assert failure_summary_lines()[0] == (
        "HLTB: 2 lookups failed (HTTP 429 x1, timeouts x1), cache kept for those games"
    )


def test_no_failures_no_summary() -> None:
    """A clean run prints no failure line."""
    ctx = _ctx(FakeSession({"*": FakeResp(200, MATCH)}))
    _run(ctx, 1, "Vox Populi")
    assert failure_summary_lines() == []
