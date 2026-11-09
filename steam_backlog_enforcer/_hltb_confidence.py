"""Cached HowLongToBeat confidence lookups.

Split out of :mod:`steam_backlog_enforcer.hltb` to keep both files
under the 250-line cap.
"""

from __future__ import annotations

import logging
import time

from steam_backlog_enforcer._hltb_cached import reporting_progress_cb
from steam_backlog_enforcer._hltb_failures import HLTBUnavailableError
from steam_backlog_enforcer._hltb_types import (
    HLTB_BASE_URL,
    ProgressCb,
    _HLTBExtras,
    load_hltb_cache,
    load_hltb_count_comp_cache,
    load_hltb_game_id_cache,
    load_hltb_leisure_100h_cache,
    load_hltb_polls_cache,
    load_hltb_rush_cache,
    restore_prior_hours,
    save_hltb_cache,
)
from steam_backlog_enforcer.hltb import (
    fetch_hltb_confidence,
    fetch_hltb_times,
    fetch_hltb_times_timed,
    games_per_second,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# Confidence-only batch fetch (no leisure/DLC detail pages)
# ──────────────────────────────────────────────────────────────


def refresh_confidence(
    games: list[tuple[int, str]],
) -> tuple[dict[int, float], dict[int, int], dict[int, int]]:
    """Re-search ``games`` (cached or not) and save hours, polls and count_comp.

    Nothing is dropped from the cache first: a failed lookup writes nothing,
    so the old entry survives. Prior hours beat a clean miss, since a prior
    leisure/DLC estimate is trusted over "not found". When HLTB is unavailable
    the cache is returned unchanged and nothing is saved.

    Returns:
        The (hours, polls, count_comp) caches after the refresh.
    """
    cache = load_hltb_cache()
    polls = load_hltb_polls_cache()
    count_comp = load_hltb_count_comp_cache()
    prior_hours = {aid: cache[aid] for aid, _ in games if aid in cache}
    try:
        fetch_hltb_confidence(games, cache=cache, polls=polls, count_comp=count_comp)
    except HLTBUnavailableError:
        # Already logged and tallied by the batch; the cache is untouched.
        return cache, polls, count_comp
    restore_prior_hours(cache, prior_hours)
    save_hltb_cache(cache, polls, _HLTBExtras(count_comp=count_comp))
    return cache, polls, count_comp


def refetch_poll_counts(missing: list[tuple[int, str]]) -> dict[int, int]:
    """Re-search ``missing`` for poll counts and return the refreshed polls cache."""
    return refresh_confidence(missing)[1]


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
        try:
            fetch_hltb_confidence(
                uncached,
                cache=cache,
                polls=polls,
                progress_cb=reporting_progress_cb(
                    "Fetching HLTB poll counts", len(uncached), progress_cb
                ),
                count_comp=count_comp,
            )
        except HLTBUnavailableError:
            # Already logged and tallied by the batch; the cache is untouched.
            return cache
        elapsed = time.monotonic() - t0

        save_hltb_cache(cache, polls, _HLTBExtras(count_comp=count_comp))

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


def fetch_hltb_detail_missing(
    games: list[tuple[int, str]],
    progress_cb: ProgressCb | None = None,
) -> int:
    """Fetch HLTB detail (rush + leisure) for games that are missing it.

    Also backfills ``hltb_game_id`` for any game that already has rush/leisure
    data but whose HLTB game ID was never stored (e.g. from an old cache).
    Games with both rush data and a game_id are skipped entirely.  For the
    rest, ``fetch_hltb_times`` re-searches them and visits their detail pages
    (it never skips cached games).  Prior hours win over a clean miss; a failed
    lookup writes nothing, so its old entry survives untouched.

    Args:
        games: list of (app_id, name) tuples to check.
        progress_cb: optional progress callback.

    Returns:
        Number of games that now have rush-hour data after the fetch.
    """
    rush = load_hltb_rush_cache()
    game_id_cache = load_hltb_game_id_cache()
    missing_rush = [
        (app_id, name) for app_id, name in games if rush.get(app_id, -1) <= 0
    ]
    # Also re-search games that have rush data but no HLTB game ID yet so the
    # direct URL can be shown in stats output.
    missing_id_only = [
        (app_id, name)
        for app_id, name in games
        if rush.get(app_id, -1) > 0 and game_id_cache.get(app_id, 0) == 0
    ]
    missing = missing_rush + missing_id_only
    if not missing:
        return 0

    cache = load_hltb_cache()
    polls = load_hltb_polls_cache()
    extras = _HLTBExtras(
        count_comp=load_hltb_count_comp_cache(),
        rush=rush,
        leisure_100h=load_hltb_leisure_100h_cache(),
        hltb_game_id=game_id_cache,
    )

    prior_hours = {aid: cache[aid] for aid, _ in missing if aid in cache}

    n_rush = len(missing_rush)
    n_id = len(missing_id_only)
    if n_rush and n_id:
        logger.info(
            "Fetching HLTB detail for %d games missing rush/leisure data"
            " + %d games missing game ID...",
            n_rush,
            n_id,
        )
    elif n_rush:
        logger.info(
            "Fetching HLTB detail for %d games missing rush/leisure data...", n_rush
        )
    else:
        logger.info("Backfilling HLTB game ID for %d game(s)...", n_id)
    report = reporting_progress_cb("Fetching HLTB details", len(missing), progress_cb)
    try:
        elapsed = fetch_hltb_times_timed(missing, cache, polls, report, extras)
    except HLTBUnavailableError:
        # Already logged and tallied by the batch; the cache is untouched.
        return 0

    restore_prior_hours(cache, prior_hours)

    save_hltb_cache(cache, polls, extras)

    fetched = sum(1 for app_id, _ in missing_rush if extras.rush.get(app_id, -1) > 0)
    logger.info(
        "HLTB detail fetch done: %d/%d got rush data in %.1fs (%.0f games/s)",
        fetched,
        len(missing_rush),
        elapsed,
        games_per_second(len(missing), elapsed),
    )
    return fetched


def get_hltb_submit_url(game_name: str) -> str | None:
    """Look up a game on HLTB and return its submit page URL.

    Args:
        game_name: Name of the game to search for.

    Returns:
        URL like ``https://howlongtobeat.com/submit/game/12345``,
        or ``None`` if the game wasn't found.
    """
    try:
        results = fetch_hltb_times([(0, game_name)])
    except HLTBUnavailableError:
        # Already logged and tallied by the batch; the cache is untouched.
        return None
    if results and results[0].hltb_game_id:
        return f"{HLTB_BASE_URL}/submit/game/{results[0].hltb_game_id}"
    return None
