"""Extracting completionist and DLC data from a HowLongToBeat page.

Leaf helpers: they call nothing else in the module, so extracting
them introduces no cycle. Split to keep both files under the 250-line cap.
"""

from __future__ import annotations

from http import HTTPStatus
import logging
import re
from typing import TYPE_CHECKING, Any

import aiohttp

from steam_backlog_enforcer._hltb_page_parse import (
    _as_positive_int,
    _parse_game_page,
)
from steam_backlog_enforcer._hltb_types import (
    HLTB_BASE_URL,
)

if TYPE_CHECKING:
    import asyncio

logger = logging.getLogger(__name__)

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
)


def _platform_comp_high_candidates(game_data: dict[str, Any]) -> list[int]:
    """Collect positive ``comp_high`` values from ``platformData`` entries."""
    platform_data = game_data.get("platformData", [])
    if not isinstance(platform_data, list):
        return []
    candidates = []
    for entry in platform_data:
        if isinstance(entry, dict):
            v = _as_positive_int(entry.get("comp_high", 0))
            if v > 0:
                candidates.append(v)
    return candidates


def _extract_comp_100_avg_and_high(game_data: dict[str, Any]) -> tuple[float, float]:
    """Extract (average comp_100, high comp_100) from game detail data.

    Returns hours as floats: (avg_hours, high_hours).  Returns (-1, -1) when
    insufficient data is present.  The average is ``comp_100`` (seconds) from
    ``game[0]``; the high is ``comp_100_h``.
    """
    games = game_data.get("game", [])
    if not isinstance(games, list) or not games:
        return -1, -1
    if not isinstance(games[0], dict):
        return -1, -1

    base = games[0]
    avg_s = _as_positive_int(base.get("comp_100", 0))
    high_s = _as_positive_int(base.get("comp_100_h", 0))

    avg_h = round(avg_s / 3600, 2) if avg_s > 0 else -1
    high_h = round(high_s / 3600, 2) if high_s > 0 else avg_h
    return avg_h, high_h


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
        except (TimeoutError, aiohttp.ClientError) as exc:
            logger.debug(
                "HLTB detail fetch failed for game_id=%d: %s",
                hltb_game_id,
                exc,
            )
    return None
