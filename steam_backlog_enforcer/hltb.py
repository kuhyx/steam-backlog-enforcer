"""HowLongToBeat integration for estimating game completion times.

Fetches completionist hour estimates from howlongtobeat.com with:
- direct API calls (bypassing the slow howlongtobeatpy per-request setup)
- single shared aiohttp session for all requests
- concurrent requests with configurable concurrency
- live progress reporting via callback
- incremental disk-cache saves so crashes don't lose work
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from http import HTTPStatus
import json
import logging
import time
from typing import Any

import aiohttp
from howlongtobeatpy.HTMLRequests import HTMLRequests

from python_pkg.steam_backlog_enforcer.config import CONFIG_DIR, _atomic_write

logger = logging.getLogger(__name__)

HLTB_CACHE_FILE = CONFIG_DIR / "hltb_cache.json"
MAX_CONCURRENT = 60  # parallel requests to HLTB
_SAVE_INTERVAL = 50  # flush cache to disk every N results
MIN_SIMILARITY = 0.5

# Type for progress callbacks: (done, total, found, game_name)
ProgressCb = Callable[[int, int, int, str], None]


@dataclass
class HLTBResult:
    """Result from a HowLongToBeat lookup."""

    app_id: int
    game_name: str
    completionist_hours: float
    similarity: float
    hltb_game_id: int = 0


HLTB_BASE_URL = "https://howlongtobeat.com"


# ──────────────────────────────────────────────────────────────
# Cache I/O
# ──────────────────────────────────────────────────────────────


def load_hltb_cache() -> dict[int, float]:
    """Load the persistent HLTB cache from disk.

    Returns: dict mapping app_id -> completionist_hours (-1 = no data on HLTB).
    """
    if HLTB_CACHE_FILE.exists():
        try:
            data = json.loads(HLTB_CACHE_FILE.read_text(encoding="utf-8"))
            return {int(k): float(v) for k, v in data.items()}
        except (json.JSONDecodeError, ValueError, OSError):
            logger.warning("Corrupt HLTB cache, starting fresh.")
    return {}


def save_hltb_cache(cache: dict[int, float]) -> None:
    """Save the HLTB cache to disk."""
    try:
        _atomic_write(
            HLTB_CACHE_FILE,
            json.dumps({str(k): v for k, v in cache.items()}, indent=2) + "\n",
        )
    except OSError:
        logger.exception("Failed to save HLTB cache")


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


async def _get_auth_token(
    search_url: str,
    session: aiohttp.ClientSession,
) -> str | None:
    """Fetch the HLTB auth token (one GET request)."""
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
                return token
    except (aiohttp.ClientError, asyncio.TimeoutError):
        logger.warning("Failed to get HLTB auth token")
    return None


def _similarity(a: str, b: str) -> float:
    """Case-insensitive SequenceMatcher ratio between two strings."""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _build_search_payload(game_name: str) -> str:
    """Build the JSON POST body for an HLTB search."""
    return json.dumps(
        {
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
    )


def _pick_best_hltb_entry(
    search_name: str,
    candidates: list[tuple[dict[str, Any], float]],
) -> tuple[dict[str, Any], float] | None:
    """Pick the best HLTB entry, preferring full editions over demos/chapters.

    When a short name like "FAITH" matches both "FAITH" (demo) and
    "FAITH: The Unholy Trinity" (full game), prefer the full game
    since Steam often lists the full game under the shorter name.
    """
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    lower = search_name.lower()
    for entry, sim in candidates:
        entry_name = (entry.get("game_name") or "").lower()
        if entry_name.startswith((lower + ":", lower + " -")):
            return entry, sim

    # Fall back to highest similarity.
    return max(candidates, key=lambda x: x[1])


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
        payload = _build_search_payload(name)
        try:
            async with ctx.session.post(
                ctx.search_url,
                headers=ctx.headers,
                data=payload,
            ) as resp:
                if resp.status == HTTPStatus.OK:
                    data = await resp.json()
                    candidates: list[tuple[dict[str, Any], float]] = []
                    lower_name = name.lower()
                    for entry in data.get("data", []):
                        entry_name = entry.get("game_name", "")
                        entry_alias = entry.get("game_alias", "") or ""
                        sim = max(
                            _similarity(name, entry_name),
                            _similarity(name, entry_alias),
                        )
                        is_full_edition = entry_name.lower().startswith(
                            lower_name + ":"
                        ) or entry_name.lower().startswith(lower_name + " -")
                        if sim >= MIN_SIMILARITY or is_full_edition:
                            comp_100 = entry.get("comp_100", 0)
                            if comp_100 and comp_100 > 0:
                                candidates.append((entry, sim))
                    best = _pick_best_hltb_entry(name, candidates)
                    if best is not None:
                        entry, sim = best
                        hours = round(entry["comp_100"] / 3600, 2)
                        result = HLTBResult(
                            app_id=app_id,
                            game_name=name,
                            completionist_hours=hours,
                            similarity=sim,
                            hltb_game_id=entry.get("game_id", 0),
                        )
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            logger.debug("HLTB search failed for '%s': %s", name, exc)

        # Update cache immediately (miss = -1).
        if result is not None:
            ctx.cache[app_id] = result.completionist_hours
            ctx.counter["found"] += 1
        else:
            ctx.cache[app_id] = -1

        ctx.counter["done"] += 1
        done = ctx.counter["done"]

        # Incremental save every _SAVE_INTERVAL lookups.
        if done % _SAVE_INTERVAL == 0:
            save_hltb_cache(ctx.cache)

        # Report progress.
        if ctx.progress_cb is not None:
            ctx.progress_cb(done, ctx.total, ctx.counter["found"], name)

        return result


async def _fetch_batch(
    games: list[tuple[int, str]],
    cache: dict[int, float],
    progress_cb: ProgressCb | None,
) -> list[HLTBResult]:
    """Fetch HLTB data for a batch of games using one shared session."""
    # 1. Discover the search URL (sync, one-time).
    search_url = _get_hltb_search_url()
    logger.info("HLTB search URL: %s", search_url)

    timeout = aiohttp.ClientTimeout(total=20, sock_read=15)

    # 2. Get auth token (separate session — avoids reuse issues).
    async with aiohttp.ClientSession(timeout=timeout) as init_session:
        token = await _get_auth_token(search_url, init_session)
    if token is None:
        logger.warning("Could not get HLTB auth token, aborting fetch.")
        return []
    logger.info("HLTB auth token acquired.")

    # 3. Build shared headers for all search requests.
    headers = {
        "content-type": "application/json",
        "accept": "*/*",
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64; rv:136.0) Gecko/20100101 Firefox/136.0"
        ),
        "referer": "https://howlongtobeat.com/",
        "x-auth-token": token,
    }

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
    progress_cb: ProgressCb | None = None,
) -> list[HLTBResult]:
    """Synchronous wrapper: fetch HLTB times for games."""
    if not games:
        return []
    if cache is None:
        cache = {}
    return asyncio.run(_fetch_batch(games, cache, progress_cb))


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
    uncached = [(app_id, name) for app_id, name in games if app_id not in cache]

    if uncached:
        logger.info(
            "Fetching HLTB data for %d uncached games (%d cached)...",
            len(uncached),
            len(games) - len(uncached),
        )
        t0 = time.monotonic()
        fetch_hltb_times(uncached, cache=cache, progress_cb=progress_cb)
        elapsed = time.monotonic() - t0

        # Final save.
        save_hltb_cache(cache)

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
