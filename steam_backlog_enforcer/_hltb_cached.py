"""Cached batch lookup of HowLongToBeat times.

Split out of :mod:`steam_backlog_enforcer.hltb` to keep both files
under the 250-line cap.
"""

from __future__ import annotations

import logging

from steam_backlog_enforcer._hltb_types import (
    ProgressCb,
    _HLTBExtras,
    load_hltb_cache,
    load_hltb_count_comp_cache,
    load_hltb_leisure_100h_cache,
    load_hltb_polls_cache,
    load_hltb_rush_cache,
    save_hltb_cache,
)
from steam_backlog_enforcer.hltb import fetch_hltb_times_timed, games_per_second

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# Confidence-only batch fetch (no leisure/DLC detail pages)
# ──────────────────────────────────────────────────────────────


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
    extras = _HLTBExtras(
        count_comp=load_hltb_count_comp_cache(),
        rush=load_hltb_rush_cache(),
        leisure_100h=load_hltb_leisure_100h_cache(),
    )
    uncached = [(app_id, name) for app_id, name in games if app_id not in cache]

    if uncached:
        logger.info(
            "Fetching HLTB data for %d uncached games (%d cached)...",
            len(uncached),
            len(games) - len(uncached),
        )
        elapsed = fetch_hltb_times_timed(uncached, cache, polls, progress_cb, extras)

        # Final save.
        save_hltb_cache(cache, polls, extras)

        found = sum(1 for aid, _ in uncached if cache.get(aid, -1) > 0)
        logger.info(
            "HLTB fetch done: %d/%d found in %.1fs (%.0f games/s)",
            found,
            len(uncached),
            elapsed,
            games_per_second(len(uncached), elapsed),
        )
    else:
        logger.info("All %d games found in HLTB cache.", len(games))

    return cache
