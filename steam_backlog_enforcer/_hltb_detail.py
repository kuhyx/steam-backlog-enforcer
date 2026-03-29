"""Detail page parsing and leisure time / DLC fetching for HLTB."""

from __future__ import annotations

import asyncio
from http import HTTPStatus
import json
import logging
import re
from typing import Any

import aiohttp

from python_pkg.steam_backlog_enforcer._hltb_types import (
    _SAVE_INTERVAL,
    HLTB_BASE_URL,
    MAX_CONCURRENT,
    HLTBResult,
    ProgressCb,
    save_hltb_cache,
)

logger = logging.getLogger(__name__)

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

            if not done % _SAVE_INTERVAL:
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
