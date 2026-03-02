"""HowLongToBeat integration for estimating game completion times."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import logging

from howlongtobeatpy import HowLongToBeat

from python_pkg.steam_backlog_enforcer.config import CONFIG_DIR

logger = logging.getLogger(__name__)

HLTB_CACHE_FILE = CONFIG_DIR / "hltb_cache.json"
MAX_CONCURRENT = 30
MIN_SIMILARITY = 0.5


@dataclass
class HLTBResult:
    """Result from a HowLongToBeat lookup."""

    app_id: int
    game_name: str
    completionist_hours: float
    similarity: float


def load_hltb_cache() -> dict[int, float]:
    """Load the persistent HLTB cache from disk.

    Returns: dict mapping app_id -> completionist_hours.
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
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        HLTB_CACHE_FILE.write_text(
            json.dumps({str(k): v for k, v in cache.items()}, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError:
        logger.exception("Failed to save HLTB cache")


async def _search_one(
    sem: asyncio.Semaphore, app_id: int, name: str
) -> HLTBResult | None:
    """Search HLTB for a single game."""
    async with sem:
        try:
            results = await HowLongToBeat().async_search(name)
            if results:
                best = max(results, key=lambda r: r.similarity)
                if best.similarity >= MIN_SIMILARITY:
                    comp = best.completionist
                    if comp and comp > 0:
                        return HLTBResult(
                            app_id=app_id,
                            game_name=name,
                            completionist_hours=comp,
                            similarity=best.similarity,
                        )
        except (OSError, ValueError, TypeError, AttributeError) as e:
            logger.debug("HLTB search failed for '%s': %s", name, e)
        return None


async def _fetch_batch(
    games: list[tuple[int, str]],
) -> list[HLTBResult]:
    """Fetch HLTB data for a batch of games concurrently."""
    sem = asyncio.Semaphore(MAX_CONCURRENT)
    tasks = [_search_one(sem, app_id, name) for app_id, name in games]
    results = await asyncio.gather(*tasks)
    return [r for r in results if r is not None]


def fetch_hltb_times(games: list[tuple[int, str]]) -> list[HLTBResult]:
    """Synchronous wrapper: fetch HLTB times for games."""
    if not games:
        return []
    return asyncio.run(_fetch_batch(games))


def fetch_hltb_times_cached(
    games: list[tuple[int, str]],
) -> dict[int, float]:
    """Fetch HLTB times, using disk cache for already-known games.

    Returns: dict mapping app_id -> completionist_hours.
    """
    cache = load_hltb_cache()
    uncached = [(app_id, name) for app_id, name in games if app_id not in cache]

    if uncached:
        logger.info(
            "Fetching HLTB data for %d uncached games (out of %d total)...",
            len(uncached),
            len(games),
        )
        results = fetch_hltb_times(uncached)
        for r in results:
            cache[r.app_id] = r.completionist_hours
        # Also cache misses as -1 so we don't re-fetch them.
        found_ids = {r.app_id for r in results}
        for app_id, _ in uncached:
            if app_id not in found_ids:
                cache[app_id] = -1
        save_hltb_cache(cache)
    else:
        logger.info("All %d games found in HLTB cache.", len(games))

    return cache
