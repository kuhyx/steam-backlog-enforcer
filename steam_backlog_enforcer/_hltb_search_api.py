"""Building and issuing the HowLongToBeat search request.

Leaf helpers: they call nothing else in the module, so extracting
them introduces no cycle. Split to keep both files under the 250-line cap.
"""

from __future__ import annotations

import asyncio
from http import HTTPStatus
import json
import logging
import time
from typing import Any

import aiohttp
from howlongtobeatpy.HTMLRequests import HTMLRequests

from steam_backlog_enforcer._hltb_matching import (
    _find_best_extended,
    _find_exact_match,
    _resolve_exact_vs_extended,
    _sanitize_search_name,
    _similarity,
)
from steam_backlog_enforcer._hltb_types import (
    MIN_SIMILARITY,
    _AuthInfo,
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


def _build_search_payload(game_name: str, auth: _AuthInfo | None = None) -> str:
    """Build the JSON POST body for an HLTB search."""
    payload: dict[str, Any] = {
        "searchType": "games",
        "searchTerms": _sanitize_search_name(game_name).split(),
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
