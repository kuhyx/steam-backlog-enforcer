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
from collections.abc import Callable
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


@dataclass
class _AuthInfo:
    """HLTB API authentication details."""

    token: str
    hp_key: str = ""
    hp_val: str = ""


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

    # Prefer base games over DLC entries when both are present.
    non_dlc = [c for c in candidates if str(c[0].get("game_type", "")).lower() != "dlc"]
    usable = non_dlc or candidates
    if len(usable) == 1:
        return usable[0]

    lower = search_name.lower()
    for entry, sim in usable:
        entry_name = (entry.get("game_name") or "").lower()
        if entry_name.startswith((lower + ":", lower + " -")):
            return entry, sim

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
        payload = _build_search_payload(name, ctx.auth)
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
                        is_dlc = str(entry.get("game_type", "")).lower() == "dlc"
                        sim = max(
                            _similarity(name, entry_name),
                            _similarity(name, entry_alias),
                        )
                        is_full_edition = (
                            (not is_dlc)
                            and entry_name.lower().startswith(lower_name + ":")
                        ) or (
                            (not is_dlc)
                            and entry_name.lower().startswith(lower_name + " -")
                        )
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


# ──────────────────────────────────────────────────────────────
# Leisure time + DLC fetching from game detail pages
# ──────────────────────────────────────────────────────────────

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
)


def _parse_game_page(html: str) -> dict[str, Any] | None:
    """Extract game data dict from a HLTB game page's __NEXT_DATA__."""
    match = _NEXT_DATA_RE.search(html)
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
        result: dict[str, Any] = data["props"]["pageProps"]["game"]["data"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
    else:
        return result


def _as_positive_int(value: object) -> int:
    """Convert HLTB numeric JSON values to a positive int, or 0 when invalid."""
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float):
        int_value = int(value)
        return max(0, int_value)
    if isinstance(value, str):
        try:
            int_value = int(value)
            return max(0, int_value)
        except ValueError:
            return 0
    return 0


def _extract_base_leisure_hours(game_data: dict[str, Any]) -> float:
    """Extract base-game leisure hours from game detail data."""
    games = game_data.get("game", [])
    if not isinstance(games, list) or not games:
        return -1
    if not isinstance(games[0], dict):
        return -1

    base = games[0]
    leisure_s = _as_positive_int(base.get("comp_100_h", 0))
    if leisure_s <= 0:
        leisure_s = _as_positive_int(base.get("comp_100", 0))
    if leisure_s <= 0:
        return -1

    return round(leisure_s / 3600, 2)


def _extract_dlc_relationships(game_data: dict[str, Any]) -> list[tuple[int, float]]:
    """Extract DLC relationship IDs and fallback hours from detail data."""
    relationships = game_data.get("relationships", [])
    if not isinstance(relationships, list):
        return []

    dlcs: list[tuple[int, float]] = []
    for rel in relationships:
        if not isinstance(rel, dict):
            continue
        if str(rel.get("game_type", "")).lower() != "dlc":
            continue
        dlc_id = _as_positive_int(rel.get("game_id", 0))
        fallback_comp_100 = _as_positive_int(rel.get("comp_100", 0))
        if fallback_comp_100 > 0:
            fallback_hours = round(fallback_comp_100 / 3600, 2)
        else:
            fallback_hours = 0.0
        dlcs.append((dlc_id, fallback_hours))

    return dlcs


def _extract_leisure_hours(game_data: dict[str, Any]) -> float:
    """Compute total leisure hours: base game + all DLCs.

    Uses ``comp_100_h`` (leisure completionist) from the game detail page.
    Falls back to ``comp_100`` (average completionist) if leisure unavailable.
    Also sums leisure time from any DLC listed in ``relationships``.
    """
    base_hours = _extract_base_leisure_hours(game_data)
    if base_hours <= 0:
        return -1

    total_hours = base_hours

    # Add DLC leisure times from relationships.
    for _dlc_id, fallback_hours in _extract_dlc_relationships(game_data):
        total_hours += fallback_hours

    return round(total_hours, 2)


async def _fetch_detail_one(
    sem: asyncio.Semaphore,
    session: aiohttp.ClientSession,
    hltb_game_id: int,
) -> dict[str, Any] | None:
    """Fetch a single HLTB game detail page and parse its data."""
    async with sem:
        url = f"{HLTB_BASE_URL}/game/{hltb_game_id}"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64; rv:136.0) Gecko/20100101 Firefox/136.0"
            ),
            "accept": "text/html",
            "referer": "https://howlongtobeat.com/",
        }
        try:
            async with session.get(url, headers=headers) as resp:
                if resp.status == HTTPStatus.OK:
                    html = await resp.text()
                    return _parse_game_page(html)
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            logger.debug(
                "HLTB detail fetch failed for game_id=%d: %s",
                hltb_game_id,
                exc,
            )
    return None


async def _fetch_leisure_times(
    search_results: list[HLTBResult],
    cache: dict[int, float],
    progress_cb: ProgressCb | None,
) -> None:
    """Fetch leisure times from game detail pages for all search results.

    Updates ``cache`` in-place with leisure hours (including DLC time).
    """
    valid = [r for r in search_results if r.hltb_game_id > 0]
    if not valid:
        return

    timeout = aiohttp.ClientTimeout(total=30, sock_read=20)
    sem = asyncio.Semaphore(MAX_CONCURRENT)
    connector = aiohttp.TCPConnector(
        limit=MAX_CONCURRENT,
        keepalive_timeout=30,
    )

    total = len(valid)
    done = 0
    found = 0

    async with aiohttp.ClientSession(
        timeout=timeout,
        connector=connector,
    ) as session:
        coros = [_fetch_detail_one(sem, session, r.hltb_game_id) for r in valid]
        details = await asyncio.gather(*coros)

        dlc_relationships_by_app, dlc_ids = _collect_dlc_relationships(valid, details)
        dlc_hours_by_id = await _fetch_dlc_leisure_hours(sem, session, dlc_ids)

        for r, game_data in zip(valid, details, strict=False):
            done += 1
            if game_data is not None:
                leisure = _extract_leisure_hours(game_data)
                if leisure > 0:
                    leisure = _apply_dlc_leisure_overrides(
                        leisure,
                        dlc_relationships_by_app.get(r.app_id, []),
                        dlc_hours_by_id,
                    )
                    r.completionist_hours = leisure
                    cache[r.app_id] = leisure
                    found += 1

            if progress_cb is not None:
                progress_cb(done, total, found, r.game_name)

            if done % _SAVE_INTERVAL == 0:
                save_hltb_cache(cache)


def _collect_dlc_relationships(
    valid: list[HLTBResult],
    details: list[dict[str, Any] | None],
) -> tuple[dict[int, list[tuple[int, float]]], list[int]]:
    """Collect DLC relationship IDs for all base-game detail responses."""
    by_app: dict[int, list[tuple[int, float]]] = {}
    unique_dlc_ids: set[int] = set()

    for result, game_data in zip(valid, details, strict=False):
        if game_data is None:
            continue
        dlc_rels = _extract_dlc_relationships(game_data)
        by_app[result.app_id] = dlc_rels
        for dlc_id, _fallback_hours in dlc_rels:
            if dlc_id > 0:
                unique_dlc_ids.add(dlc_id)

    return by_app, sorted(unique_dlc_ids)


async def _fetch_dlc_leisure_hours(
    sem: asyncio.Semaphore,
    session: aiohttp.ClientSession,
    dlc_ids: list[int],
) -> dict[int, float]:
    """Fetch leisure hours for each DLC game id."""
    if not dlc_ids:
        return {}

    coros = [_fetch_detail_one(sem, session, dlc_id) for dlc_id in dlc_ids]
    dlc_details = await asyncio.gather(*coros)

    dlc_hours_by_id: dict[int, float] = {}
    for dlc_id, dlc_data in zip(dlc_ids, dlc_details, strict=False):
        if dlc_data is None:
            continue
        dlc_leisure = _extract_base_leisure_hours(dlc_data)
        if dlc_leisure > 0:
            dlc_hours_by_id[dlc_id] = dlc_leisure
    return dlc_hours_by_id


def _apply_dlc_leisure_overrides(
    base_hours: float,
    dlc_rels: list[tuple[int, float]],
    dlc_hours_by_id: dict[int, float],
) -> float:
    """Replace fallback DLC hours with detailed leisure hours when available."""
    adjusted = base_hours
    for dlc_id, fallback_hours in dlc_rels:
        dlc_leisure = dlc_hours_by_id.get(dlc_id, -1.0)
        if dlc_leisure > 0:
            adjusted += dlc_leisure - fallback_hours
    return round(adjusted, 2)


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
    await _fetch_leisure_times(search_results, cache, progress_cb=None)

    return search_results


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
