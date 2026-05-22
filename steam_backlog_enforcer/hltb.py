"""HowLongToBeat integration for estimating game completion times.

Fetches leisure completionist hour estimates from howlongtobeat.com with:
- direct API calls (bypassing the slow howlongtobeatpy per-request setup)
- single shared aiohttp session for all requests
- concurrent requests with configurable concurrency
- live progress reporting via callback
- incremental disk-cache saves so crashes don't lose work
- leisure time (upper-bound play time) from individual game pages
- DLC time aggregation (base game + all DLC leisure times combined)
"""

from __future__ import annotations

import asyncio
import logging
import time

import aiohttp

from python_pkg.steam_backlog_enforcer._hltb_search import (
    _fetch_batch,
    _get_auth_info,
    _get_hltb_search_url,
    _search_one,
    _SearchCtx,
)
from python_pkg.steam_backlog_enforcer._hltb_types import (
    HLTB_BASE_URL,
    MAX_CONCURRENT,
    HLTBResult,
    ProgressCb,
    load_hltb_cache,
    load_hltb_count_comp_cache,
    load_hltb_polls_cache,
    save_hltb_cache,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# Confidence-only batch fetch (no leisure/DLC detail pages)
# ──────────────────────────────────────────────────────────────
async def _fetch_batch_confidence_only(
    games: list[tuple[int, str]],
    cache: dict[int, float],
    polls: dict[int, int],
    progress_cb: ProgressCb | None,
    count_comp: dict[int, int] | None = None,
) -> list[HLTBResult]:
    """Fetch only search-level HLTB data (hours + confidence), no detail pages."""
    # 1. Discover the search URL (sync, one-time).
    search_url = _get_hltb_search_url()
    logger.info("HLTB search URL: %s", search_url)

    timeout = aiohttp.ClientTimeout(total=20, sock_read=15)

    # 2. Get auth info (separate session — avoids reuse issues).
    async with aiohttp.ClientSession(timeout=timeout) as init_session:
        auth = await _get_auth_info(search_url, init_session)
    if auth is None:
        logger.warning("Could not get HLTB auth info, aborting fetch.")
        return []
    logger.info("HLTB auth token acquired.")

    # 3. Build shared headers for all search requests.
    headers: dict[str, str] = {
        "content-type": "application/json",
        "accept": "*/*",
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64; rv:136.0) Gecko/20100101 Firefox/136.0"
        ),
        "referer": "https://howlongtobeat.com/",
        "x-auth-token": auth.token,
    }
    if auth.hp_key:
        headers["x-hp-key"] = auth.hp_key
        headers["x-hp-val"] = auth.hp_val

    # 4. Fire all searches through a single persistent session.
    sem = asyncio.Semaphore(MAX_CONCURRENT)
    counter = {"done": 0, "found": 0}
    total = len(games)

    if count_comp is None:
        count_comp = {}

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
            count_comp=count_comp,
            auth=auth,
            counter=counter,
            total=total,
            progress_cb=progress_cb,
        )
        tasks = [
            _search_one(
                sem,
                ctx,
                app_id,
                name,
            )
            for app_id, name in games
        ]
        results = await asyncio.gather(*tasks)

    return [r for r in results if r is not None]


def fetch_hltb_times(
    games: list[tuple[int, str]],
    cache: dict[int, float] | None = None,
    polls: dict[int, int] | None = None,
    progress_cb: ProgressCb | None = None,
    count_comp: dict[int, int] | None = None,
) -> list[HLTBResult]:
    """Synchronous wrapper: fetch HLTB times for games."""
    if not games:
        return []
    if cache is None:
        cache = {}
    if polls is None:
        polls = {}
    if count_comp is None:
        count_comp = {}
    return asyncio.run(
        _fetch_batch(games, cache, polls, progress_cb, count_comp=count_comp)
    )


def fetch_hltb_confidence(
    games: list[tuple[int, str]],
    cache: dict[int, float] | None = None,
    polls: dict[int, int] | None = None,
    progress_cb: ProgressCb | None = None,
    count_comp: dict[int, int] | None = None,
) -> list[HLTBResult]:
    """Fetch only HLTB search-level data (hours + confidence metrics)."""
    if not games:
        return []
    if cache is None:
        cache = {}
    if polls is None:
        polls = {}
    if count_comp is None:
        count_comp = {}
    return asyncio.run(
        _fetch_batch_confidence_only(
            games,
            cache,
            polls,
            progress_cb,
            count_comp=count_comp,
        )
    )


def fetch_hltb_times_cached(
    games: list[tuple[int, str]],
    progress_cb: ProgressCb | None = None,
) -> dict[int, float]:
    """Fetch HLTB times, using disk cache for already-known games.

    Args:
        games: list of (app_id, name) tuples to look up.
        progress_cb: optional callback(done, total, found, game_name).

    Returns: dict mapping app_id -> completionist_hours.
    """
    cache = load_hltb_cache()
    polls = load_hltb_polls_cache()
    count_comp = load_hltb_count_comp_cache()
    uncached = [(app_id, name) for app_id, name in games if app_id not in cache]

    if uncached:
        logger.info(
            "Fetching HLTB data for %d uncached games (%d cached)...",
            len(uncached),
            len(games) - len(uncached),
        )
        t0 = time.monotonic()
        fetch_hltb_times(
            uncached,
            cache=cache,
            polls=polls,
            progress_cb=progress_cb,
            count_comp=count_comp,
        )
        elapsed = time.monotonic() - t0

        # Final save.
        save_hltb_cache(cache, polls, count_comp)

        found = sum(1 for aid, _ in uncached if cache.get(aid, -1) > 0)
        rate = len(uncached) / elapsed if elapsed > 0 else 0
        logger.info(
            "HLTB fetch done: %d/%d found in %.1fs (%.0f games/s)",
            found,
            len(uncached),
            elapsed,
            rate,
        )
    else:
        logger.info("All %d games found in HLTB cache.", len(games))

    return cache


def fetch_hltb_confidence_cached(
    games: list[tuple[int, str]],
    progress_cb: ProgressCb | None = None,
) -> dict[int, float]:
    """Fetch HLTB search-level confidence data, using disk cache for known IDs."""
    cache = load_hltb_cache()
    polls = load_hltb_polls_cache()
    count_comp = load_hltb_count_comp_cache()
    uncached = [(app_id, name) for app_id, name in games if app_id not in cache]

    if uncached:
        logger.info(
            "Fetching HLTB confidence for %d uncached games (%d cached)...",
            len(uncached),
            len(games) - len(uncached),
        )
        t0 = time.monotonic()
        fetch_hltb_confidence(
            uncached,
            cache=cache,
            polls=polls,
            progress_cb=progress_cb,
            count_comp=count_comp,
        )
        elapsed = time.monotonic() - t0

        save_hltb_cache(cache, polls, count_comp)

        found = sum(1 for aid, _ in uncached if cache.get(aid, -1) > 0)
        rate = len(uncached) / elapsed if elapsed > 0 else 0
        logger.info(
            "HLTB confidence fetch done: %d/%d found in %.1fs (%.0f games/s)",
            found,
            len(uncached),
            elapsed,
            rate,
        )
    else:
        logger.info("All %d games found in HLTB cache.", len(games))

    return cache


def get_hltb_submit_url(game_name: str) -> str | None:
    """Look up a game on HLTB and return its submit page URL.

    Args:
        game_name: Name of the game to search for.

    Returns:
        URL like ``https://howlongtobeat.com/submit/game/12345``,
        or ``None`` if the game wasn't found.
    """
    results = fetch_hltb_times([(0, game_name)])
    if results and results[0].hltb_game_id:
        return f"{HLTB_BASE_URL}/submit/game/{results[0].hltb_game_id}"
    return None
