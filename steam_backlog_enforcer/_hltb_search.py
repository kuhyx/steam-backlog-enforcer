"""Internal HLTB search helpers: URL discovery, auth, matching, and batch fetch."""

from __future__ import annotations

import asyncio
from http import HTTPStatus
import logging

import aiohttp

from steam_backlog_enforcer._hltb_auth_refresh import apply_auth
from steam_backlog_enforcer._hltb_detail import (
    _fetch_leisure_times,
)
from steam_backlog_enforcer._hltb_failures import (
    SKIPPED_AFTER_RATE_LIMIT,
    HLTBUnavailableError,
    record_breaker,
    record_failure,
    record_fatal,
    shared_breaker,
    status_reason,
)
from steam_backlog_enforcer._hltb_search_api import (
    _get_auth_info,
    _get_hltb_search_url,
    forget_hltb_search_url,
)
from steam_backlog_enforcer._hltb_search_one import _search_one, _SearchCtx
from steam_backlog_enforcer._hltb_types import (
    MAX_CONCURRENT,
    HLTBResult,
    ProgressCb,
    _HLTBExtras,
)

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# Async fetching with shared session & progress
# ──────────────────────────────────────────────────────────────


def _fail_batch(message: str) -> HLTBUnavailableError:
    """Log and remember a batch that refreshed nothing; return the error."""
    logger.warning("%s", message)
    record_fatal(message)
    return HLTBUnavailableError(message)


def _skip_rate_limited(games: list[tuple[int, str]]) -> HLTBUnavailableError:
    """Count a whole batch as not refreshed because the breaker already tripped."""
    for _game in games:
        record_failure(SKIPPED_AFTER_RATE_LIMIT)
    record_breaker(app_id for app_id, _name in games)
    msg = f"HLTB: rate-limited, skipped {len(games)} lookups"
    logger.warning("%s", msg)
    return HLTBUnavailableError(msg)


def _check_batch(ctx: _SearchCtx) -> None:
    """Report a batch's failures; raise when not a single lookup succeeded."""
    failed = ctx.counter["failed"]
    if not failed:
        return
    logger.warning(
        "HLTB: %d/%d lookups failed in this batch; cache kept for them",
        failed,
        ctx.total,
    )
    if ctx.breaker.tripped:
        record_breaker(ctx.failed_ids)
    if failed == ctx.total:
        msg = f"HLTB: all {failed} lookups failed, nothing refreshed"
        raise _fail_batch(msg)


async def _search_batch(
    games: list[tuple[int, str]],
    cache: dict[int, float],
    polls: dict[int, int],
    progress_cb: ProgressCb | None,
    extras: _HLTBExtras,
) -> list[HLTBResult]:
    """Run the search-level HLTB lookups for a batch through one session.

    Hours, poll counts and the extras come from the search results alone;
    :func:`_fetch_batch` layers the per-game detail pages on top of this.

    Raises:
        HLTBUnavailableError: auth init failed, or every lookup failed. The
            caches are untouched in both cases.
    """
    if not games:
        return []
    breaker = shared_breaker()
    if breaker.tripped:
        raise _skip_rate_limited(games)
    # 1. Discover the search URL (sync, one-time).
    search_url = _get_hltb_search_url()
    logger.info("HLTB search URL: %s", search_url)

    timeout = aiohttp.ClientTimeout(total=20, sock_read=15)

    # 2. Get auth info (separate session — avoids reuse issues).
    auth_failures: list[str] = []
    async with aiohttp.ClientSession(timeout=timeout) as init_session:
        auth = await _get_auth_info(search_url, init_session, auth_failures)
    if auth is None:
        forget_hltb_search_url()
        why = auth_failures[0] if auth_failures else "no token"
        if why == status_reason(HTTPStatus.TOO_MANY_REQUESTS):
            breaker.tripped = True
        msg = f"HLTB: rate-limited, nothing refreshed (auth init: {why})"
        raise _fail_batch(msg)
    logger.info("HLTB auth token acquired.")

    # 3. Build shared headers for all search requests.
    headers: dict[str, str] = {
        "content-type": "application/json",
        "accept": "*/*",
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64; rv:136.0) Gecko/20100101 Firefox/136.0"
        ),
        "referer": "https://howlongtobeat.com/",
    }
    apply_auth(headers, auth)

    # 4. Fire all searches through a single persistent session.
    sem = asyncio.Semaphore(MAX_CONCURRENT)
    connector = aiohttp.TCPConnector(
        limit=MAX_CONCURRENT,
        keepalive_timeout=30,
    )
    async with aiohttp.ClientSession(
        timeout=timeout,
        connector=connector,
    ) as session:
        ctx = _SearchCtx(
            session=session,
            search_url=search_url,
            headers=headers,
            cache=cache,
            polls=polls,
            extras=extras,
            auth=auth,
            counter={"done": 0, "found": 0, "failed": 0},
            total=len(games),
            progress_cb=progress_cb,
            breaker=breaker,
        )
        tasks = [_search_one(sem, ctx, app_id, name) for app_id, name in games]
        results = await asyncio.gather(*tasks)
    _check_batch(ctx)

    return [r for r in results if r is not None]


async def _fetch_batch(
    games: list[tuple[int, str]],
    cache: dict[int, float],
    polls: dict[int, int],
    progress_cb: ProgressCb | None,
    extras: _HLTBExtras | None = None,
) -> list[HLTBResult]:
    """Fetch HLTB data for a batch of games using one shared session."""
    if extras is None:
        extras = _HLTBExtras()
    search_results = await _search_batch(games, cache, polls, progress_cb, extras)

    # 5. Fetch leisure times + DLC from game detail pages.
    logger.info(
        "Fetching leisure times for %d games from detail pages...",
        len(search_results),
    )
    await _fetch_leisure_times(
        search_results,
        cache,
        polls,
        progress_cb=None,
        extras=extras,
    )

    return search_results
