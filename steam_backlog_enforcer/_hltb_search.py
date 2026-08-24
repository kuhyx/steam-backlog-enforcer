"""Internal HLTB search helpers: URL discovery, auth, matching, and batch fetch."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from http import HTTPStatus
import logging

import aiohttp

from steam_backlog_enforcer._hltb_detail import (
    _fetch_leisure_times,
)
from steam_backlog_enforcer._hltb_matching import (
    _build_result_from_best,
    _build_search_variants,
)
from steam_backlog_enforcer._hltb_search_api import (
    _build_search_payload,
    _collect_candidates,
    _get_auth_info,
    _get_hltb_search_url,
    _pick_best_hltb_entry,
)
from steam_backlog_enforcer._hltb_types import (
    _SAVE_INTERVAL,
    MAX_CONCURRENT,
    HLTBResult,
    ProgressCb,
    _AuthInfo,
    _HLTBExtras,
    save_hltb_cache,
)

logger = logging.getLogger(__name__)

# When extended entry has ≥ this many times more hours than the exact match,
# prefer it even if its confidence count is lower.
_EXTENDED_DOMINANCE_RATIO = 4.0
# Minimum combined confidence for the dominance path (avoids picking entries
# that have almost no data at all).
_EXTENDED_MIN_CONFIDENCE = 3


# ──────────────────────────────────────────────────────────────
# HLTB API setup (done once, not per-request like the library)
# ──────────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────
# Async fetching with shared session & progress
# ──────────────────────────────────────────────────────────────


@dataclass
class _SearchCtx:
    """Shared context for HLTB search requests."""

    session: aiohttp.ClientSession
    search_url: str
    headers: dict[str, str]
    cache: dict[int, float]
    polls: dict[int, int] = field(default_factory=dict)
    count_comp: dict[int, int] = field(default_factory=dict)
    auth: _AuthInfo | None = None
    counter: dict[str, int] = field(default_factory=dict)
    total: int = 0
    progress_cb: ProgressCb | None = None
    hltb_game_id: dict[int, int] = field(default_factory=dict)


async def _search_one(
    sem: asyncio.Semaphore,
    ctx: _SearchCtx,
    app_id: int,
    name: str,
) -> HLTBResult | None:
    """Search HLTB for one game via direct POST, update cache."""
    async with sem:
        result: HLTBResult | None = None
        for query_name in _build_search_variants(name):
            payload = _build_search_payload(query_name, ctx.auth)
            try:
                async with ctx.session.post(
                    ctx.search_url,
                    headers=ctx.headers,
                    data=payload,
                ) as resp:
                    if resp.status != HTTPStatus.OK:
                        continue
                    data = await resp.json()
                    candidates = _collect_candidates(query_name, data)
                    # When we stripped ": subtitle" from the original name to
                    # get query_name, only keep full-edition entries (those
                    # whose HLTB name starts with query_name + ":"/"-") or
                    # exact name/alias matches.  This prevents "Vox Populi"
                    # (stripped from "Vox Populi: Poland 2023") from falsely
                    # matching "Vox Populi Vox Dei 2".
                    if ":" in name and ":" not in query_name:
                        lower_q = query_name.lower()
                        candidates = [
                            (e, s)
                            for e, s in candidates
                            if (e.get("game_name") or "").lower() == lower_q
                            or (e.get("game_alias") or "").lower() == lower_q
                            or (e.get("game_name") or "")
                            .lower()
                            .startswith(lower_q + ":")
                            or (e.get("game_name") or "")
                            .lower()
                            .startswith(lower_q + " -")
                        ]
                    best = _pick_best_hltb_entry(query_name, candidates)
                    if best is None:
                        continue
                    result = _build_result_from_best(app_id, name, query_name, best)
                    break
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                logger.debug("HLTB search failed for '%s': %s", query_name, exc)

        # Update cache immediately (miss = -1).
        if result is not None:
            ctx.cache[app_id] = result.completionist_hours
            ctx.polls[app_id] = result.comp_100_count
            ctx.count_comp[app_id] = result.count_comp
            if result.hltb_game_id > 0:
                ctx.hltb_game_id[app_id] = result.hltb_game_id
            ctx.counter["found"] += 1
        else:
            ctx.cache[app_id] = -1
            ctx.polls[app_id] = 0
            ctx.count_comp[app_id] = 0

        ctx.counter["done"] += 1
        done = ctx.counter["done"]

        # Incremental save every _SAVE_INTERVAL lookups.
        if not done % _SAVE_INTERVAL:
            save_hltb_cache(
                ctx.cache,
                ctx.polls,
                _HLTBExtras(count_comp=ctx.count_comp, hltb_game_id=ctx.hltb_game_id),
            )

        # Report progress.
        if ctx.progress_cb is not None:
            ctx.progress_cb(done, ctx.total, ctx.counter["found"], name)

        return result


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
            count_comp=extras.count_comp,
            auth=auth,
            counter=counter,
            total=total,
            progress_cb=progress_cb,
            hltb_game_id=extras.hltb_game_id,
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

    search_results = [r for r in results if r is not None]

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
