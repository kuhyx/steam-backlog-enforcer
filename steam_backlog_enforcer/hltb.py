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
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from http import HTTPStatus
import json
import logging
import re
import time
from typing import Any

import aiohttp
from howlongtobeatpy.HTMLRequests import HTMLRequests

from python_pkg.steam_backlog_enforcer._hltb_detail import (
    _fetch_leisure_times,
)
from python_pkg.steam_backlog_enforcer._hltb_types import (
    _SAVE_INTERVAL,
    _SUBSET_SUFFIXES,
    HLTB_BASE_URL,
    MAX_CONCURRENT,
    MIN_SIMILARITY,
    HLTBResult,
    ProgressCb,
    _AuthInfo,
    load_hltb_cache,
    load_hltb_count_comp_cache,
    load_hltb_polls_cache,
    save_hltb_cache,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# HLTB API setup (done once, not per-request like the library)
# ──────────────────────────────────────────────────────────────


def _get_hltb_search_url() -> str:
    """Discover the current HLTB search API endpoint.

    Scrapes the homepage for JS bundles containing the fetch URL.
    Falls back to ``/api/finder`` if extraction fails.
    """
    try:
        search_info = HTMLRequests.send_website_request_getcode(
            parse_all_scripts=False,
        )
        if search_info is None:
            search_info = HTMLRequests.send_website_request_getcode(
                parse_all_scripts=True,
            )
        if search_info and search_info.search_url:
            url: str = HTMLRequests.BASE_URL + search_info.search_url
            return url
    except (OSError, RuntimeError, ValueError, TypeError):
        logger.debug("Failed to discover HLTB search URL, using default")
    return "https://howlongtobeat.com/api/finder"


async def _get_auth_info(
    search_url: str,
    session: aiohttp.ClientSession,
) -> _AuthInfo | None:
    """Fetch the HLTB auth token and honeypot key/val (one GET request)."""
    init_url = search_url + "/init"
    ts = int(time.time() * 1000)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64; rv:136.0) Gecko/20100101 Firefox/136.0"
        ),
        "referer": "https://howlongtobeat.com/",
    }
    try:
        async with session.get(
            init_url,
            params={"t": ts},
            headers=headers,
        ) as resp:
            if resp.status == HTTPStatus.OK:
                data = await resp.json()
                token: str | None = data.get("token")
                if token is None:
                    return None
                return _AuthInfo(
                    token=token,
                    hp_key=data.get("hpKey", ""),
                    hp_val=data.get("hpVal", ""),
                )
    except (aiohttp.ClientError, asyncio.TimeoutError):
        logger.warning("Failed to get HLTB auth token")
    return None


def _similarity(a: str, b: str) -> float:
    """Case-insensitive SequenceMatcher ratio between two strings."""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _build_search_payload(game_name: str, auth: _AuthInfo | None = None) -> str:
    """Build the JSON POST body for an HLTB search."""
    payload: dict[str, Any] = {
        "searchType": "games",
        "searchTerms": game_name.split(),
        "searchPage": 1,
        "size": 20,
        "searchOptions": {
            "games": {
                "userId": 0,
                "platform": "",
                "sortCategory": "popular",
                "rangeCategory": "main",
                "rangeTime": {"min": 0, "max": 0},
                "gameplay": {
                    "perspective": "",
                    "flow": "",
                    "genre": "",
                    "difficulty": "",
                },
                "rangeYear": {"max": "", "min": ""},
                "modifier": "",
            },
            "users": {"sortCategory": "postcount"},
            "lists": {"sortCategory": "follows"},
            "filter": "",
            "sort": 0,
            "randomizer": 0,
        },
        "useCache": True,
    }
    if auth and auth.hp_key:
        payload[auth.hp_key] = auth.hp_val
    return json.dumps(payload)


def _build_search_variants(game_name: str) -> list[str]:
    """Return fallback search terms for one Steam game title."""
    base = game_name.strip()
    variants = [base]
    no_year = re.sub(r"\s*\(\d{4}\)$", "", base).strip()
    if no_year and no_year != base:
        variants.append(no_year)
    return variants


def _collect_candidates(
    query_name: str,
    data: dict[str, Any],
) -> list[tuple[dict[str, Any], float]]:
    """Build candidate list from one HLTB response payload."""
    candidates: list[tuple[dict[str, Any], float]] = []
    lower_name = query_name.lower()
    for entry in data.get("data", []):
        entry_name = entry.get("game_name", "")
        entry_alias = entry.get("game_alias", "") or ""
        is_dlc = str(entry.get("game_type", "")).lower() == "dlc"
        sim = max(
            _similarity(query_name, entry_name),
            _similarity(query_name, entry_alias),
        )
        is_full_edition = (
            (not is_dlc) and entry_name.lower().startswith(lower_name + ":")
        ) or ((not is_dlc) and entry_name.lower().startswith(lower_name + " -"))
        if sim >= MIN_SIMILARITY or is_full_edition:
            comp_100 = entry.get("comp_100", 0)
            if comp_100 and comp_100 > 0:
                candidates.append((entry, sim))
    return candidates


def _build_result_from_best(
    app_id: int,
    original_name: str,
    query_name: str,
    best: tuple[dict[str, Any], float],
) -> HLTBResult:
    """Convert selected HLTB entry into HLTBResult."""
    entry, sim = best
    hours = round(entry["comp_100"] / 3600, 2)
    logger.debug(
        ("HLTB match for '%s' via '%s': '%s' (id=%s, comp_100=%s, sim=%.3f)"),
        original_name,
        query_name,
        entry.get("game_name"),
        entry.get("game_id"),
        entry.get("comp_100"),
        sim,
    )
    return HLTBResult(
        app_id=app_id,
        game_name=original_name,
        completionist_hours=hours,
        similarity=sim,
        hltb_game_id=entry.get("game_id", 0),
        comp_100_count=int(entry.get("comp_100_count", 0) or 0),
        count_comp=int(entry.get("count_comp", 0) or 0),
    )


def _pick_best_hltb_entry(
    search_name: str,
    candidates: list[tuple[dict[str, Any], float]],
) -> tuple[dict[str, Any], float] | None:
    """Pick the best HLTB entry, preferring full editions over demos/chapters.

    When a short name like "FAITH" matches both "FAITH" (demo) and
    "FAITH: The Unholy Trinity" (full game), prefer the full game
    since Steam often lists the full game under the shorter name.

    When an exact match like "Timberman" (26 h) competes against an
    unrelated subtitle entry like "Timberman: The Big Adventure" (2 h),
    the exact match wins because it has more hours.
    """
    if not candidates:
        return None

    # Prefer base games over DLC entries when both are present.
    non_dlc = [c for c in candidates if str(c[0].get("game_type", "")).lower() != "dlc"]
    usable = non_dlc or candidates
    if len(usable) == 1:
        return usable[0]

    lower = search_name.lower()
    best_exact = _find_exact_match(usable, lower)
    best_extended = _find_best_extended(usable, lower)
    return _resolve_exact_vs_extended(best_exact, best_extended, usable)


def _find_exact_match(
    usable: list[tuple[dict[str, Any], float]],
    lower: str,
) -> tuple[dict[str, Any], float] | None:
    """Find best exact name/alias match (highest comp_100)."""
    return next(
        (
            (e, s)
            for e, s in sorted(
                usable,
                key=lambda x: x[0].get("comp_100", 0),
                reverse=True,
            )
            if (e.get("game_name") or "").lower() == lower
            or (e.get("game_alias") or "").lower() == lower
        ),
        None,
    )


def _find_best_extended(
    usable: list[tuple[dict[str, Any], float]],
    lower: str,
) -> tuple[dict[str, Any], float] | None:
    """Find best extended entry ("Name: Subtitle" / "Name - Subtitle").

    Skips subset entries (prologue, demo, etc.).
    """
    best: tuple[dict[str, Any], float] | None = None
    for entry, sim in usable:
        game_type = str(entry.get("game_type", "")).lower()
        if game_type not in ("", "game"):
            continue
        entry_name = (entry.get("game_name") or "").lower()
        if entry_name.startswith((lower + ":", lower + " -")):
            suffix = entry_name[len(lower) :].lstrip(" :-")
            if not any(suffix.startswith(kw) for kw in _SUBSET_SUFFIXES) and (
                best is None or entry.get("comp_100", 0) > best[0].get("comp_100", 0)
            ):
                best = (entry, sim)
    return best


def _resolve_exact_vs_extended(
    best_exact: tuple[dict[str, Any], float] | None,
    best_extended: tuple[dict[str, Any], float] | None,
    usable: list[tuple[dict[str, Any], float]],
) -> tuple[dict[str, Any], float]:
    """Decide between exact match, extended entry, or highest similarity."""
    if best_exact is not None and best_extended is not None:
        exact_hours = best_exact[0].get("comp_100", 0)
        extended_hours = best_extended[0].get("comp_100", 0)
        exact_confidence = int(best_exact[0].get("comp_100_count", 0) or 0) + int(
            best_exact[0].get("count_comp", 0) or 0
        )
        extended_confidence = int(best_extended[0].get("comp_100_count", 0) or 0) + int(
            best_extended[0].get("count_comp", 0) or 0
        )
        # Prefer the extended entry only when it has strictly more hours
        # than the exact match AND at least as much confidence.
        # This lets "FAITH: The Unholy Trinity" (full game) beat
        # a low-confidence exact demo while preventing low-confidence
        # mods like "Celeste - Strawberry Jam" from beating
        # the exact base game.
        if extended_hours > exact_hours and extended_confidence >= exact_confidence:
            return best_extended
        return best_exact
    if best_exact is not None:
        return best_exact
    if best_extended is not None:
        return best_extended

    # Fall back to highest similarity.
    return max(usable, key=lambda x: x[1])


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
            ctx.counter["found"] += 1
        else:
            ctx.cache[app_id] = -1
            ctx.polls[app_id] = 0
            ctx.count_comp[app_id] = 0

        ctx.counter["done"] += 1
        done = ctx.counter["done"]

        # Incremental save every _SAVE_INTERVAL lookups.
        if not done % _SAVE_INTERVAL:
            save_hltb_cache(ctx.cache, ctx.polls, ctx.count_comp)

        # Report progress.
        if ctx.progress_cb is not None:
            ctx.progress_cb(done, ctx.total, ctx.counter["found"], name)

        return result


async def _fetch_batch(
    games: list[tuple[int, str]],
    cache: dict[int, float],
    polls: dict[int, int],
    progress_cb: ProgressCb | None,
    count_comp: dict[int, int] | None = None,
) -> list[HLTBResult]:
    """Fetch HLTB data for a batch of games using one shared session."""
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
        count_comp=count_comp,
    )

    return search_results


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
