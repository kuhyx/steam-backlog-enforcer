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
import importlib
import logging
from typing import Any, TypeAlias

import aiohttp

from steam_backlog_enforcer._hltb_search import (
    _fetch_batch,
    _get_auth_info,
    _get_hltb_search_url,
    _search_one,
    _SearchCtx,
)
from steam_backlog_enforcer._hltb_types import (
    MAX_CONCURRENT,
    HLTBResult,
    ProgressCb,
    _HLTBExtras,
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
    extras: _HLTBExtras | None = None,
) -> list[HLTBResult]:
    """Synchronous wrapper: fetch HLTB times for games."""
    if not games:
        return []
    if cache is None:
        cache = {}
    if polls is None:
        polls = {}
    return asyncio.run(
        _fetch_batch(
            games,
            cache,
            polls,
            progress_cb,
            extras=extras,
        )
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


_REEXPORTED = {
    "HLTB_BASE_URL": "steam_backlog_enforcer._hltb_types",
    "MAX_CONCURRENT": "steam_backlog_enforcer._hltb_types",
    "HLTBResult": "steam_backlog_enforcer._hltb_types",
    "ProgressCb": "steam_backlog_enforcer._hltb_types",
    "_HLTBExtras": "steam_backlog_enforcer._hltb_types",
    "load_hltb_cache": "steam_backlog_enforcer._hltb_types",
    "load_hltb_count_comp_cache": "steam_backlog_enforcer._hltb_types",
    "load_hltb_game_id_cache": "steam_backlog_enforcer._hltb_types",
    "load_hltb_leisure_100h_cache": "steam_backlog_enforcer._hltb_types",
    "load_hltb_polls_cache": "steam_backlog_enforcer._hltb_types",
    "load_hltb_rush_cache": "steam_backlog_enforcer._hltb_types",
    "save_hltb_cache": "steam_backlog_enforcer._hltb_types",
    "fetch_hltb_times_cached": "steam_backlog_enforcer._hltb_cached",
    "fetch_hltb_confidence_cached": "steam_backlog_enforcer._hltb_confidence",
    "fetch_hltb_detail_missing": "steam_backlog_enforcer._hltb_confidence",
    "get_hltb_submit_url": "steam_backlog_enforcer._hltb_confidence",
}


# Whatever the re-exported name turns out to be -- a function, a class or
# a constant. Aliased so the annotation is a name rather than a bare Any.
_Reexport: TypeAlias = Any


def __getattr__(name: str) -> _Reexport:
    """Serve names that moved out of this module when it was split.

    Deferred via importlib rather than imported at the top: the modules below
    import back from here, so a module-level import would be circular.
    """
    home = _REEXPORTED.get(name)
    if home is not None:
        return getattr(importlib.import_module(home), name)
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
