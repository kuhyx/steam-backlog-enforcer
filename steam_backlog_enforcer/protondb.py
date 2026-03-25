"""ProtonDB integration for Linux compatibility ratings.

Fetches game compatibility tiers from ProtonDB's public API to filter out
games that don't work well on Linux.  Ratings are cached locally so repeated
lookups are free.

Tier hierarchy (best → worst): native, platinum, gold, silver, bronze, borked.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import logging
from typing import Any

import aiohttp

from python_pkg.steam_backlog_enforcer.config import CONFIG_DIR, _atomic_write

logger = logging.getLogger(__name__)

PROTONDB_CACHE_FILE = CONFIG_DIR / "protondb_cache.json"
_PROTONDB_API = "https://www.protondb.com/api/v1/reports/summaries/{app_id}.json"
MAX_CONCURRENT = 30  # parallel requests - be polite to the CDN

HTTP_NOT_FOUND = 404

# Tier ordering from best to worst.
TIER_ORDER: dict[str, int] = {
    "native": 0,
    "platinum": 1,
    "gold": 2,
    "silver": 3,
    "bronze": 4,
    "borked": 5,
    "pending": 6,
}

# Games at or below this tier are skipped.
MIN_PLAYABLE_TIER = "gold"


@dataclass
class ProtonDBRating:
    """ProtonDB compatibility rating for a game."""

    app_id: int
    tier: str = ""
    trending_tier: str = ""
    score: float = 0.0
    confidence: str = ""
    total_reports: int = 0

    @property
    def is_playable(self) -> bool:
        """True if the game has at least gold-tier compatibility.

        A game is considered unplayable when:
        - Its tier is silver, bronze, or borked.
        - Its tier is gold but trending to silver or worse.
        - No data exists (unknown compatibility).
        """
        if not self.tier or self.tier == "pending":
            return True  # No data / pending → don't block; user can skip manually.
        tier_rank = TIER_ORDER.get(self.tier, 99)
        min_rank = TIER_ORDER[MIN_PLAYABLE_TIER]

        if tier_rank > min_rank:
            # Silver, bronze, borked → skip.
            return False

        if tier_rank == min_rank and self.trending_tier:
            # Gold but trending silver/bronze/borked → skip.
            trend_rank = TIER_ORDER.get(self.trending_tier, 99)
            if trend_rank > min_rank:
                return False

        return True


def _load_cache() -> dict[str, Any]:
    """Load the on-disk ProtonDB cache."""
    if PROTONDB_CACHE_FILE.exists():
        data: dict[str, Any] = json.loads(
            PROTONDB_CACHE_FILE.read_text(encoding="utf-8"),
        )
        return data
    return {}


def _save_cache(cache: dict[str, Any]) -> None:
    """Persist the ProtonDB cache."""
    _atomic_write(
        PROTONDB_CACHE_FILE,
        json.dumps(cache, indent=2) + "\n",
    )


async def _fetch_one(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    app_id: int,
) -> ProtonDBRating:
    """Fetch a single game's ProtonDB rating."""
    url = _PROTONDB_API.format(app_id=app_id)
    async with sem:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status == HTTP_NOT_FOUND:
                    return ProtonDBRating(app_id=app_id)
                r.raise_for_status()
                data = await r.json(content_type=None)
                return ProtonDBRating(
                    app_id=app_id,
                    tier=data.get("tier", ""),
                    trending_tier=data.get("trendingTier", ""),
                    score=data.get("score", 0.0),
                    confidence=data.get("confidence", ""),
                    total_reports=data.get("total", 0),
                )
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
            logger.warning("ProtonDB fetch failed for AppID=%d", app_id)
            return ProtonDBRating(app_id=app_id)


async def _fetch_batch(app_ids: list[int]) -> list[ProtonDBRating]:
    """Fetch ProtonDB ratings for a batch of app IDs concurrently."""
    sem = asyncio.Semaphore(MAX_CONCURRENT)
    async with aiohttp.ClientSession() as session:
        tasks = [_fetch_one(session, sem, aid) for aid in app_ids]
        return await asyncio.gather(*tasks)


def _rating_to_dict(r: ProtonDBRating) -> dict[str, Any]:
    """Serialize a rating to a cache-friendly dict."""
    return {
        "tier": r.tier,
        "trending_tier": r.trending_tier,
        "score": r.score,
        "confidence": r.confidence,
        "total_reports": r.total_reports,
    }


def _rating_from_cache(app_id: int, data: dict[str, Any]) -> ProtonDBRating:
    """Deserialize a rating from cached data."""
    return ProtonDBRating(
        app_id=app_id,
        tier=data.get("tier", ""),
        trending_tier=data.get("trending_tier", ""),
        score=data.get("score", 0.0),
        confidence=data.get("confidence", ""),
        total_reports=data.get("total_reports", 0),
    )


def fetch_protondb_ratings(
    app_ids: list[int],
) -> dict[int, ProtonDBRating]:
    """Fetch ProtonDB ratings with local caching.

    Returns a dict mapping app_id → ProtonDBRating for every requested ID.
    Cached results are reused; only missing IDs are fetched from the network.
    """
    cache = _load_cache()

    # Separate cached vs. uncached.
    results: dict[int, ProtonDBRating] = {}
    to_fetch: list[int] = []
    for aid in app_ids:
        key = str(aid)
        if key in cache:
            results[aid] = _rating_from_cache(aid, cache[key])
        else:
            to_fetch.append(aid)

    if to_fetch:
        logger.info(
            "Fetching ProtonDB ratings for %d games (%d cached)...",
            len(to_fetch),
            len(results),
        )
        fetched = asyncio.run(_fetch_batch(to_fetch))
        for r in fetched:
            results[r.app_id] = r
            cache[str(r.app_id)] = _rating_to_dict(r)
        _save_cache(cache)
        logger.info("ProtonDB: fetched %d, total cached %d", len(fetched), len(cache))
    else:
        logger.info("All %d ProtonDB ratings found in cache.", len(results))

    return results
