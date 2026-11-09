"""Batch-level HLTB failure handling: auth init, total failure, circuit breaker."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import aiohttp
import pytest

from steam_backlog_enforcer import _hltb_search
from steam_backlog_enforcer._hltb_failures import (
    HLTBUnavailableError,
    failure_summary_lines,
    reset_failures,
)
from steam_backlog_enforcer._hltb_search import _search_batch
from steam_backlog_enforcer._hltb_types import _HLTBExtras
from steam_backlog_enforcer.tests._hltb_fake_transport import (
    MATCH,
    FakeInitSession,
    FakeResp,
)


@pytest.fixture(autouse=True)
def _fresh_tally() -> None:
    reset_failures()


def _batch(
    status: int,
    routes: dict[str, object],
    games: list[tuple[int, str]],
    fake: FakeInitSession | None = None,
) -> FakeInitSession:
    fake = fake or FakeInitSession(status, routes)
    with (
        patch.object(
            _hltb_search, "_get_hltb_search_url", return_value="https://x.invalid/f"
        ),
        patch.object(_hltb_search.aiohttp, "ClientSession", lambda **_k: fake),
        patch.object(_hltb_search.aiohttp, "TCPConnector", lambda **_k: None),
    ):
        asyncio.run(_search_batch(games, {}, {}, None, _HLTBExtras()))
    return fake


@pytest.mark.parametrize(
    "init", [429, aiohttp.ClientConnectionError("no network")], ids=["429", "offline"]
)
def test_auth_init_failure_fails_the_batch_up_front(
    init: int | BaseException,
) -> None:
    """A failed /init means nothing can refresh: raise instead of returning []."""
    with pytest.raises(HLTBUnavailableError, match="rate-limited, nothing refreshed"):
        _batch(init, {"*": FakeResp(200, MATCH)}, [(1, "Vox Populi")])
    assert any("nothing refreshed" in ln for ln in failure_summary_lines())


def test_empty_batch_is_not_a_failure() -> None:
    """No games: no request, no error."""
    fake = _batch(429, {}, [])
    assert fake.search.posts == []
    assert failure_summary_lines() == []


def test_breaker_trips_after_five_consecutive_429s() -> None:
    """After 5 straight 429s the rest of the batch sends no request at all."""
    fake = FakeInitSession(200, {"*": FakeResp(429)})
    games = [(aid, "Celeste") for aid in range(10, 18)]
    with (
        patch.object(
            _hltb_search, "_get_hltb_search_url", return_value="https://x.invalid/f"
        ),
        patch.object(_hltb_search.aiohttp, "ClientSession", lambda **_k: fake),
        patch.object(_hltb_search.aiohttp, "TCPConnector", lambda **_k: None),
        pytest.raises(HLTBUnavailableError, match="all 8 lookups failed"),
    ):
        asyncio.run(_search_batch(games, {}, {}, None, _HLTBExtras()))
    assert len(fake.search.posts) == 5
    lines = failure_summary_lines()
    assert lines[0] == (
        "HLTB: 8 lookups failed (HTTP 429 x5, skipped after rate-limit x3),"
        " cache kept for those games"
    )
    assert "HLTB: rate-limited, 8 games not refreshed" in lines


def test_batch_where_every_lookup_failed_raises() -> None:
    """Every lookup failing is a total failure."""
    with pytest.raises(HLTBUnavailableError, match="all 2 lookups failed"):
        _batch(200, {"*": FakeResp(500)}, [(1, "Celeste"), (2, "Celeste")])


def test_batch_with_one_success_does_not_raise() -> None:
    """At least one success: the batch completes and failures are only reported."""
    _batch(
        200,
        {"Vox Populi": FakeResp(200, MATCH), "*": FakeResp(500)},
        [(1, "Vox Populi"), (2, "Celeste")],
    )
    assert failure_summary_lines()[0].startswith("HLTB: 1 lookups failed (HTTP 500 x1)")


def test_tripped_breaker_skips_later_batches_of_the_same_command() -> None:
    """Once HLTB rate-limits us, later batches send no request (not even /init)."""
    with pytest.raises(HLTBUnavailableError):
        _batch(200, {"*": FakeResp(429)}, [(aid, "Celeste") for aid in range(5)])
    fake = FakeInitSession(200, {"*": FakeResp(200, MATCH)})
    with pytest.raises(HLTBUnavailableError, match="rate-limited"):
        _batch(200, {}, [(1, "Vox"), (2, "Vox")], fake)
    assert (fake.gets, fake.search.posts) == (0, [])
    # Games 1 and 2 were in both batches: count games, not lookups.
    assert "HLTB: rate-limited, 5 games not refreshed" in failure_summary_lines()


def test_reset_clears_a_tripped_breaker() -> None:
    """A new command starts with HLTB assumed reachable again."""
    with pytest.raises(HLTBUnavailableError):
        _batch(200, {"*": FakeResp(429)}, [(aid, "Celeste") for aid in range(5)])
    reset_failures()
    fake = _batch(200, {"*": FakeResp(200, MATCH)}, [(1, "Vox Populi")])
    assert len(fake.search.posts) == 1
